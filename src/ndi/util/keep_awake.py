"""ndi.util.keep_awake - keep this computer from sleeping while NDI works.

MATLAB counterpart: ``src/ndi/+ndi/+util/KeepAwake.m``

    k = ndi_util_KeepAwake.instance()   # the one for this Python process
    k.hold(key, label)    # keep the computer awake for KEY ("job:x", ...)
    k.release(key)        # KEY no longer needs it
    k.toggleManual()      # the navigator's coffee-cup button
    k.isOn()              # is the computer being kept awake now?

While anything holds it, the operating system is kept from going to sleep on
its own; when the last holder lets go, that stops and the computer sleeps as
it normally would:

    macOS    caffeinate -ims -w <python pid>
    Linux    systemd-inhibit --what=idle:sleep ... tail --pid=<python pid>
    Windows  SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED),
             called through ctypes on a dedicated thread of this process

The macOS and Linux helpers end by themselves when this Python exits (or
crashes), and the Windows request ends with the thread (and so with the
process), so the computer is never left unable to sleep. The display may
still sleep, and closing a laptop's lid still sleeps it.

:class:`ndi.job.job.ndi_job_Job` holds it while a job runs (unless the
preference ``Jobs.KeepComputerAwake`` is false). The navigator's NDI pane
shows it as a coffee cup: steaming while the computer is kept awake.

Nothing here ever stops NDI's work: if the helper cannot be started (Linux
without systemd, say), :meth:`isOn` is false and ``lastError`` says why.
"""

from __future__ import annotations

import atexit
import base64
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Sequence
from typing import Any, ClassVar

__all__ = ["ndi_util_KeepAwake"]

#: SetThreadExecutionState flags (winbase.h).
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class _PopenHelper:
    """A started helper program, with MATLAB's process-like API."""

    def __init__(self, args: Sequence[str], log: str):
        kwargs: dict[str, Any] = {}
        if os.name == "posix":
            # Its own session, so a Ctrl+C at the terminal (meant for a job)
            # does not also kill the helper; it still ends with this process.
            kwargs["start_new_session"] = True
        with open(log, "ab") as out:
            self._popen = subprocess.Popen(
                list(args),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                **kwargs,
            )

    def isAlive(self) -> bool:
        return self._popen.poll() is None

    def destroy(self) -> None:
        if self._popen.poll() is None:
            self._popen.terminate()
            try:
                self._popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._popen.kill()


class _WindowsThreadHelper:
    """SetThreadExecutionState held by a dedicated thread (Windows).

    The execution state SetThreadExecutionState sets belongs to the CALLING
    thread: it lasts while that thread lives and until that thread calls it
    again. Calling it from whichever thread happens to run hold() would tie
    the hold to that thread (a job's worker thread, say), and release() from
    another thread could not clear it. So one thread of our own makes the
    request, waits, and clears it when told to stop (or ends with the
    process, which clears it too).
    """

    def __init__(self, setter: Callable[[int], int] | None = None):
        if setter is None:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
            kernel32.SetThreadExecutionState.restype = ctypes.c_uint32
            setter = kernel32.SetThreadExecutionState
        self._set = setter
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._ok = False
        self._error = ""
        self._thread = threading.Thread(target=self._run, name="ndi-keep-awake", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        if not self._ok:
            self._stop.set()
            raise OSError(self._error or "SetThreadExecutionState did not answer")

    def _run(self) -> None:
        try:
            # 0 means the call failed.
            self._ok = bool(self._set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
            if not self._ok:
                self._error = "SetThreadExecutionState refused"
        except Exception as exc:  # noqa: BLE001 - reported through lastError
            self._error = str(exc)
        self._ready.set()
        if not self._ok:
            return
        self._stop.wait()
        try:
            self._set(ES_CONTINUOUS)
        except Exception:  # noqa: BLE001 - the thread ending clears it anyway
            pass

    def isAlive(self) -> bool:
        return self._ok and self._thread.is_alive() and not self._stop.is_set()

    def destroy(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


class ndi_util_KeepAwake:
    """Keep this computer from sleeping while anything holds it (a singleton).

    Get it with :meth:`instance`. Callbacks registered with
    :meth:`addListener` run after every change (MATLAB's ``Changed`` event):
    a holder came or went, or the helper started or stopped.
    """

    #: The key of the navigator's coffee-cup (manual) hold.
    ManualKey: ClassVar[str] = "manual"

    _the: ClassVar[ndi_util_KeepAwake | None] = None
    _the_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        #: Who holds it.
        self.keys: list[str] = []
        #: And, for people, what each is.
        self.labels: list[str] = []
        self.lastError: str = ""
        #: Test hook: a callable(args) returning a process-like object with
        #: isAlive() and destroy(). None: the platform's own mechanism.
        self.Launcher: Callable[[list[str]], Any] | None = None
        self._process: Any = None
        self._listeners: list[Callable[[], None]] = []
        self._lock = threading.RLock()

    # -- static ------------------------------------------------------------

    @classmethod
    def instance(cls) -> ndi_util_KeepAwake:
        """The KeepAwake of this Python process."""
        with cls._the_lock:
            if cls._the is None:
                cls._the = cls()
                atexit.register(cls._the.delete)
            return cls._the

    @staticmethod
    def commandFor(platform: str, pid: int) -> list[str]:
        """The helper program for PLATFORM ('mac', 'linux', 'windows'), tied to PID.

        On Windows, Python does not start this PowerShell helper (it calls
        SetThreadExecutionState itself, see :class:`_WindowsThreadHelper`);
        it is returned for parity with MATLAB and for a test Launcher.
        """
        p = str(int(round(pid)))
        platform = str(platform)
        if platform == "mac":
            # idle sleep, disk sleep, system sleep (on AC power)
            return ["caffeinate", "-ims", "-w", p]
        if platform == "linux":
            return [
                "systemd-inhibit",
                "--what=idle:sleep",
                "--who=NDI",
                "--why=NDI is working",
                "--mode=block",
                "tail",
                f"--pid={p}",
                "-f",
                "/dev/null",
            ]
        if platform == "windows":
            # 2147483649 = ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (1).
            script = (
                "$t = Add-Type -MemberDefinition "
                '\'[DllImport("kernel32.dll")] public static extern uint '
                "SetThreadExecutionState(uint f);' "
                "-Name Power -Namespace NdiKeepAwake -PassThru; "
                "[void]$t::SetThreadExecutionState([uint32]2147483649); "
                f"Wait-Process -Id {p}"
            )
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            return [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-EncodedCommand",
                encoded,
            ]
        raise ValueError(f"Unknown platform '{platform}'.")

    @staticmethod
    def platform() -> str:
        """'mac', 'windows' or 'linux'."""
        if sys.platform == "darwin":
            return "mac"
        if sys.platform.startswith("win"):
            return "windows"
        return "linux"

    # -- holders -----------------------------------------------------------

    def hold(self, key: str, label: str | None = None) -> None:
        """Keep the computer awake on behalf of KEY (LABEL is for people).

        Holding a key that already holds it changes nothing: holds are by
        key, not counted.
        """
        key = str(key)
        with self._lock:
            if key not in self.keys:
                self.keys.append(key)
                self.labels.append(str(key if label is None else label))
            self._update()
        self._notify()

    def release(self, key: str) -> None:
        """KEY no longer needs the computer awake (an unknown KEY is ignored)."""
        key = str(key)
        with self._lock:
            if key in self.keys:
                i = self.keys.index(key)
                del self.keys[i]
                del self.labels[i]
            self._update()
        self._notify()

    def toggleManual(self) -> None:
        """Turn the manual hold (the coffee cup) on or off."""
        if self.manualOn():
            self.release(self.ManualKey)
        else:
            self.hold(self.ManualKey, "you asked for it")

    def manualOn(self) -> bool:
        return self.ManualKey in self.keys

    def isHeldBy(self, key: str) -> bool:
        return str(key) in self.keys

    def isOn(self) -> bool:
        """Is the helper running, so the computer cannot idle-sleep?"""
        process = self._process
        if process is None:
            return False
        try:
            return bool(process.isAlive())
        except Exception:  # noqa: BLE001
            return False

    def describe(self) -> str:
        """One sentence for a tooltip."""
        if self.isOn():
            action = (
                "stop keeping it awake yourself"
                if self.manualOn()
                else "also keep it awake after that"
            )
            t = f"Keeping this computer awake ({'; '.join(self.labels)}). Click to {action}."
            if self.manualOn() and len(self.keys) > 1:
                t += " It stays awake while the rest need it."
            return t
        if self.keys:
            return f"Could not keep this computer awake: {self.lastError}"
        return (
            "Let this computer sleep as usual. Click to keep it "
            "awake (jobs do this themselves while they run)."
        )

    def delete(self) -> None:
        """Stop the helper (MATLAB's destructor); at exit, too."""
        with self._lock:
            self._stop()

    # -- the Changed event -------------------------------------------------

    def addListener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call CALLBACK after every change; returns a function that removes it.

        Callbacks run on the thread that made the change.
        """
        with self._lock:
            self._listeners.append(callback)

        def remove() -> None:
            self.removeListener(callback)

        return remove

    def removeListener(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb()
            except Exception:  # noqa: BLE001 - a listener must not stop a hold
                pass

    # -- private -----------------------------------------------------------

    def _update(self) -> None:
        if self.keys and not self.isOn():
            self._start()
        elif not self.keys and self._process is not None:
            self._stop()

    def _start(self) -> None:
        self._stop()
        helper = "the keep-awake helper"
        log = os.path.join(tempfile.gettempdir(), "ndi-keep-awake.log")
        try:
            platform = ndi_util_KeepAwake.platform()
            args = ndi_util_KeepAwake.commandFor(platform, os.getpid())
            if self.Launcher is not None:
                helper = args[0]
                self.lastError = f"{helper} stopped; its messages are in {log}."
                self._process = self.Launcher(args)
            elif platform == "windows":
                helper = "SetThreadExecutionState"
                self.lastError = f"{helper} was cleared."
                self._process = _WindowsThreadHelper()
            else:
                helper = args[0]
                # Said if it stops by itself (refused, or missing): see isOn.
                self.lastError = f"{helper} stopped; its messages are in {log}."
                self._process = _PopenHelper(args, log)
        except Exception as exc:  # noqa: BLE001 - never stops NDI's work
            self._process = None
            self.lastError = f"{helper} could not be started ({exc})."

    def _stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            try:
                process.destroy()
            except Exception:  # noqa: BLE001
                pass
