"""ndi.util.keep_awake: holds by key, the platform helpers, and the job runner.

MATLAB counterpart: ``+ndi/+util/KeepAwake.m`` (and the keep-awake hold in
``+ndi/+job/Job.m``). Nothing here really keeps the computer awake: the
helper is a fake (the Launcher test hook, or a patched subprocess.Popen /
SetThreadExecutionState), so the tests run on any CI machine.
"""

from __future__ import annotations

import base64
import os
import threading

import pytest

from ndi.job import ndi_job_Job
from ndi.util import keep_awake as ka
from ndi.util.keep_awake import ndi_util_KeepAwake


class FakeProcess:
    def __init__(self, args):
        self.args = list(args)
        self.alive = True
        self.destroyed = 0

    def isAlive(self):
        return self.alive

    def destroy(self):
        self.destroyed += 1
        self.alive = False


class FakeLauncher:
    def __init__(self):
        self.started: list[FakeProcess] = []

    def __call__(self, args):
        p = FakeProcess(args)
        self.started.append(p)
        return p

    @property
    def running(self) -> int:
        return sum(p.alive for p in self.started)


@pytest.fixture
def keep_awake(monkeypatch):
    """A fresh KeepAwake singleton whose helper is a fake."""
    k = ndi_util_KeepAwake()
    k.Launcher = FakeLauncher()
    monkeypatch.setattr(ndi_util_KeepAwake, "_the", k)
    yield k
    k.delete()


class TestHolds:
    def test_singleton(self, keep_awake):
        assert ndi_util_KeepAwake.instance() is keep_awake
        assert ndi_util_KeepAwake.instance() is ndi_util_KeepAwake.instance()

    def test_one_helper_while_anything_holds_it(self, keep_awake):
        launcher = keep_awake.Launcher
        assert keep_awake.isOn() is False
        keep_awake.hold("job:a", "job a")
        keep_awake.hold("job:b", "job b")
        assert keep_awake.isOn() is True
        assert len(launcher.started) == 1
        assert keep_awake.keys == ["job:a", "job:b"]
        assert keep_awake.labels == ["job a", "job b"]
        keep_awake.release("job:a")
        assert keep_awake.isOn() is True
        keep_awake.release("job:b")
        assert keep_awake.isOn() is False
        assert launcher.started[0].destroyed == 1

    def test_holds_are_by_key_not_counted(self, keep_awake):
        keep_awake.hold("k")
        keep_awake.hold("k", "again")
        assert keep_awake.keys == ["k"]
        assert keep_awake.labels == ["k"]  # the first label stays, as in MATLAB
        keep_awake.release("k")
        assert keep_awake.keys == []
        assert keep_awake.isOn() is False

    def test_release_of_an_unknown_key_is_ignored(self, keep_awake):
        keep_awake.release("nobody")
        assert keep_awake.keys == []
        keep_awake.hold("k")
        keep_awake.release("nobody")
        assert keep_awake.isHeldBy("k")
        assert keep_awake.isOn() is True

    def test_a_dead_helper_is_restarted_by_the_next_hold(self, keep_awake):
        keep_awake.hold("a")
        keep_awake.Launcher.started[0].alive = False
        assert keep_awake.isOn() is False
        assert "stopped" in keep_awake.describe()
        keep_awake.hold("b")
        assert keep_awake.isOn() is True
        assert len(keep_awake.Launcher.started) == 2

    def test_a_helper_that_cannot_start_never_raises(self, keep_awake):
        def refuse(args):
            raise OSError("no such program")

        keep_awake.Launcher = refuse
        keep_awake.hold("a")
        assert keep_awake.isOn() is False
        assert "could not be started (no such program)" in keep_awake.lastError
        assert keep_awake.describe().startswith("Could not keep this computer awake")

    def test_toggle_manual(self, keep_awake):
        keep_awake.toggleManual()
        assert keep_awake.manualOn()
        assert keep_awake.isHeldBy(ndi_util_KeepAwake.ManualKey)
        assert "stop keeping it awake yourself" in keep_awake.describe()
        keep_awake.hold("job:x", 'job "x" is running')
        assert keep_awake.describe().endswith("It stays awake while the rest need it.")
        keep_awake.toggleManual()
        assert not keep_awake.manualOn()
        assert keep_awake.isOn() is True
        assert "also keep it awake after that" in keep_awake.describe()

    def test_describe_when_idle(self, keep_awake):
        assert keep_awake.describe().startswith("Let this computer sleep as usual.")

    def test_listeners_hear_every_change(self, keep_awake):
        heard = []
        remove = keep_awake.addListener(lambda: heard.append(keep_awake.isOn()))
        keep_awake.hold("a")
        keep_awake.release("a")
        assert heard == [True, False]
        remove()
        keep_awake.hold("a")
        assert heard == [True, False]

    def test_a_failing_listener_does_not_stop_a_hold(self, keep_awake):
        def boom():
            raise RuntimeError("listener broke")

        keep_awake.addListener(boom)
        keep_awake.hold("a")
        assert keep_awake.isOn() is True


class TestCommands:
    def test_mac(self):
        assert ndi_util_KeepAwake.commandFor("mac", 123) == ["caffeinate", "-ims", "-w", "123"]

    def test_linux(self):
        args = ndi_util_KeepAwake.commandFor("linux", 42)
        assert args[0] == "systemd-inhibit"
        assert "--what=idle:sleep" in args
        assert args[-4:] == ["tail", "--pid=42", "-f", "/dev/null"]

    def test_windows_matches_matlab(self):
        args = ndi_util_KeepAwake.commandFor("windows", 7)
        assert args[:6] == [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-EncodedCommand",
        ]
        script = base64.b64decode(args[6]).decode("utf-16-le")
        assert "SetThreadExecutionState([uint32]2147483649)" in script
        assert script.endswith("Wait-Process -Id 7")

    def test_unknown_platform(self):
        with pytest.raises(ValueError):
            ndi_util_KeepAwake.commandFor("amiga", 1)

    def test_platform(self):
        assert ndi_util_KeepAwake.platform() in ("mac", "linux", "windows")


class TestPlatformMechanisms:
    def test_posix_helper_is_popen_tied_to_this_process(self, monkeypatch, tmp_path):
        started = []

        class FakePopen:
            def __init__(self, args, **kwargs):
                started.append((args, kwargs))
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr(ka.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(ka.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(ndi_util_KeepAwake, "platform", staticmethod(lambda: "linux"))
        k = ndi_util_KeepAwake()
        k.hold("a")
        assert k.isOn() is True
        args, kwargs = started[0]
        assert args[0] == "systemd-inhibit"
        assert f"--pid={os.getpid()}" in args
        if os.name == "posix":
            assert kwargs.get("start_new_session") is True
        proc = k._process._popen
        k.release("a")
        assert proc.terminated is True
        assert k.isOn() is False

    def test_windows_holds_on_a_dedicated_thread(self, monkeypatch):
        calls = []
        set_event = threading.Event()

        def fake_set(flags):
            calls.append((flags, threading.current_thread().name))
            set_event.set()
            return 0x80000000  # the previous state: nonzero is success

        monkeypatch.setattr(ndi_util_KeepAwake, "platform", staticmethod(lambda: "windows"))
        real = ka._WindowsThreadHelper
        monkeypatch.setattr(ka, "_WindowsThreadHelper", lambda: real(fake_set))
        k = ndi_util_KeepAwake()
        k.hold("a")
        assert k.isOn() is True
        assert calls == [(ka.ES_CONTINUOUS | ka.ES_SYSTEM_REQUIRED, "ndi-keep-awake")]
        thread = k._process._thread
        k.release("a")
        assert not thread.is_alive()
        # Cleared on the same thread that set it.
        assert calls[1] == (ka.ES_CONTINUOUS, "ndi-keep-awake")
        assert k.isOn() is False

    def test_windows_refusal_is_reported(self, monkeypatch):
        monkeypatch.setattr(ndi_util_KeepAwake, "platform", staticmethod(lambda: "windows"))
        real = ka._WindowsThreadHelper
        monkeypatch.setattr(ka, "_WindowsThreadHelper", lambda: real(lambda flags: 0))
        k = ndi_util_KeepAwake()
        k.hold("a")
        assert k.isOn() is False
        assert "SetThreadExecutionState refused" in k.lastError


# ----------------------------------------------------------------------
# The job runner
# ----------------------------------------------------------------------
@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NDI_JOBS_DIR", str(tmp_path / "jobs"))
    return tmp_path / "jobs"


class WatchingJob(ndi_job_Job):
    """Records whether the computer was held awake while it worked."""

    Kind = "test.keepAwake"
    outcome = "succeed"

    def work(self) -> None:
        k = ndi_util_KeepAwake.instance()
        self.seen = (k.isHeldBy(f"job:{self.id}"), k.isOn(), list(k.labels))
        if self.outcome == "fail":
            raise ValueError("failed on purpose")
        if self.outcome == "interrupt":
            raise KeyboardInterrupt
        if self.outcome == "pause":
            self.requestPause()
            self.beat(0.5)


def make_job(outcome: str) -> WatchingJob:
    ndi_job_Job.register(WatchingJob.Kind, WatchingJob)
    job = WatchingJob()
    job.outcome = outcome
    job.initialize(f"watch {outcome}", {})
    return job


@pytest.fixture
def prefer(monkeypatch):
    from ndi import preferences

    values: dict[str, object] = {}
    real = preferences.get

    def fake_get(path):
        if path in values:
            return values[path]
        return real(path)

    monkeypatch.setattr(preferences, "get", fake_get)
    return values


class TestJobRunner:
    def test_preference_is_registered_with_matlabs_default(self):
        from ndi.preferences import ndi_preferences

        p = ndi_preferences.__new__(ndi_preferences)
        p._items = []
        p._register_defaults()
        item = next(i for i in p._items if (i.category, i.name) == ("Jobs", "KeepComputerAwake"))
        assert item.default_value is True
        assert item.subcategory == ""

    @pytest.mark.parametrize("outcome,state", [("succeed", "done"), ("fail", "failed")])
    def test_held_while_running_and_released_after(
        self, keep_awake, jobs_dir, prefer, outcome, state
    ):
        prefer["Jobs.KeepComputerAwake"] = True
        job = make_job(outcome)
        job.run()
        assert job.state == state
        held, on, labels = job.seen
        assert held and on
        assert labels == [f'job "watch {outcome}" is running']
        assert keep_awake.keys == []
        assert keep_awake.isOn() is False

    def test_released_when_paused(self, keep_awake, jobs_dir, prefer):
        prefer["Jobs.KeepComputerAwake"] = True
        job = make_job("pause")
        job.run()
        assert job.state == "paused"
        assert job.seen[0] is True
        assert keep_awake.keys == []

    def test_released_on_keyboard_interrupt(self, keep_awake, jobs_dir, prefer):
        prefer["Jobs.KeepComputerAwake"] = True
        job = make_job("interrupt")
        with pytest.raises(KeyboardInterrupt):
            job.run()
        assert job.state == "interrupted"
        assert job.seen[0] is True
        assert keep_awake.keys == []
        assert keep_awake.isOn() is False

    def test_no_hold_when_the_preference_is_off(self, keep_awake, jobs_dir, prefer):
        prefer["Jobs.KeepComputerAwake"] = False
        job = make_job("succeed")
        job.run()
        assert job.state == "done"
        assert job.seen == (False, False, [])
        assert keep_awake.Launcher.started == []

    def test_another_holder_is_left_alone(self, keep_awake, jobs_dir, prefer):
        prefer["Jobs.KeepComputerAwake"] = True
        keep_awake.toggleManual()
        make_job("succeed").run()
        assert keep_awake.keys == [ndi_util_KeepAwake.ManualKey]
        assert keep_awake.isOn() is True

    def test_unreadable_preference_means_keep_awake(self, monkeypatch):
        from ndi import preferences

        def broken(path):
            raise KeyError(path)

        monkeypatch.setattr(preferences, "get", broken)
        assert ndi_job_Job._keepAwakeWanted() is True
