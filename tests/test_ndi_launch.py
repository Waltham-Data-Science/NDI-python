"""Tests for _ndi_launch: leaving MATLAB's library paths behind.

Nothing here really execs: every test injects the environment, platform,
interpreter, command line and execve, and inspects what would have run.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

import _ndi_launch as L

# What MATLAB R2026a on Linux leaves in LD_LIBRARY_PATH (abridged; measured).
MATLAB_LD = (
    "/usr/local/MATLAB/R2026a/sys/opengl/lib/glnxa64:"
    "/usr/local/MATLAB/R2026a/bin/glnxa64:"
    "/usr/local/MATLAB/R2026a/sys/os/glnxa64"
)


class FakeExec:
    def __init__(self, raise_with: OSError | None = None):
        self.calls = []
        self.raise_with = raise_with

    def __call__(self, path, argv, env):
        self.calls.append((path, list(argv), dict(env)))
        if self.raise_with:
            raise self.raise_with


@pytest.fixture(autouse=True)
def _fresh_report_flag(monkeypatch):
    monkeypatch.setattr(L, "_reported", False)


def run(
    environ,
    platform="linux",
    orig_argv=("/venv/bin/python", "/bin/napariViewGEF", "x"),
    standalone=True,
):
    fake = FakeExec()
    result = L.escapeMatlabEnvironment(
        environ=environ,
        platform=platform,
        executable="/venv/bin/python",
        orig_argv=list(orig_argv),
        execve=fake,
        standalone=standalone,
    )
    return result, fake.calls


# --- detection --------------------------------------------------------------


class TestDetection:
    def test_the_flag_is_enough(self):
        assert L.isFromMatlab({"NDI_FROM_MATLAB": "1"})

    def test_an_empty_flag_is_not(self):
        assert not L.isFromMatlab({"NDI_FROM_MATLAB": ""})

    def test_matlab_library_dirs_are_recognised_without_the_flag(self):
        assert L.isFromMatlab({"LD_LIBRARY_PATH": MATLAB_LD})
        assert L.isFromMatlab({"DYLD_LIBRARY_PATH": "/Applications/MATLAB_R2026a.app/bin/maca64"})
        assert L.isFromMatlab({"DYLD_FALLBACK_LIBRARY_PATH": "/x/sys/os/maci64:/usr/lib"})

    @pytest.mark.parametrize(
        "value",
        [
            "/usr/local/cuda/lib64:/opt/intel/lib",
            "/home/me/glnxa64stuff/lib",  # a component must BE the arch name
            "",
        ],
    )
    def test_ordinary_library_paths_are_left_alone(self, value):
        assert not L.isFromMatlab({"LD_LIBRARY_PATH": value})


# --- the cleaned environment ------------------------------------------------


class TestCleanedEnvironment:
    def test_every_library_variable_goes_and_the_rest_stays(self):
        environ = dict.fromkeys(L.LIBRARY_VARS, "/something")
        environ.update(NDI_FROM_MATLAB="1", HOME="/home/me", PATH="/usr/bin", DISPLAY=":0")
        env = L.cleanedEnvironment(environ, "linux")
        assert env is not None
        for var in L.LIBRARY_VARS:
            assert var not in env
        assert env["HOME"] == "/home/me"
        assert env["PATH"] == "/usr/bin"
        assert env["DISPLAY"] == ":0"
        assert env["NDI_FROM_MATLAB"] == "1"
        assert env[L.MARKER_VAR] == "reexec"

    def test_the_input_is_not_modified(self):
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD}
        L.cleanedEnvironment(environ, "linux")
        assert environ == {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD}

    def test_already_cleaned_means_leave_it(self):
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD, L.MARKER_VAR: "1"}
        assert L.cleanedEnvironment(environ, "linux") is None

    def test_not_from_matlab_means_leave_it(self):
        assert L.cleanedEnvironment({"LD_LIBRARY_PATH": "/usr/local/cuda/lib64"}, "linux") is None

    def test_from_matlab_with_nothing_to_remove_means_leave_it(self):
        # macOS today: MATLAB sets no LD/DYLD at all, so no restart is needed.
        assert L.cleanedEnvironment({"NDI_FROM_MATLAB": "1", "HOME": "/h"}, "darwin") is None

    def test_detection_without_the_flag_cleans_too(self):
        env = L.cleanedEnvironment({"LD_LIBRARY_PATH": MATLAB_LD}, "linux")
        assert env == {L.MARKER_VAR: "reexec"}


class TestWindows:
    PATH = (
        r"C:\Program Files\MATLAB\R2026a\bin\win64;"
        r"C:\Program Files\MATLAB\R2026a\runtime\win64;"
        r"C:\Windows\system32;"
        r"C:\Program Files\MATLAB\R2026a\bin;"
        r"C:\Users\me\.ndi\bin"
    )

    def test_matlab_binary_dirs_leave_path_and_the_rest_stays(self):
        env = L.cleanedEnvironment(
            {"NDI_FROM_MATLAB": "1", "Path": self.PATH, "PYTHONPATH": r"C:\x"}, "win32"
        )
        assert env["Path"] == (
            r"C:\Windows\system32;C:\Program Files\MATLAB\R2026a\bin;C:\Users\me\.ndi\bin"
        )
        assert "PYTHONPATH" not in env
        assert env[L.MARKER_VAR] == "in-place"

    def test_only_the_flag_triggers_it(self):
        # Unmeasured platform: no guessing from PATH alone.
        assert L.cleanedEnvironment({"Path": self.PATH}, "win32") is None

    def test_posix_loader_variables_are_not_touched(self):
        env = L.cleanedEnvironment(
            {"NDI_FROM_MATLAB": "1", "PYTHONHOME": "x", "LD_LIBRARY_PATH": "y"}, "win32"
        )
        assert env["LD_LIBRARY_PATH"] == "y"

    def test_windows_never_execs(self):
        environ = {"NDI_FROM_MATLAB": "1", "PATH": self.PATH}
        result, calls = run(environ, platform="win32")
        assert result is True
        assert calls == []


# --- the restart ------------------------------------------------------------


class TestRestart:
    def test_execs_the_same_command_line_with_the_cleaned_environment(self):
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD, "HOME": "/h"}
        result, calls = run(environ, orig_argv=["python3", "/b/napariViewGEF", "/s", "--list"])
        assert result is True
        path, argv, env = calls[0]
        assert path == "/venv/bin/python"
        assert argv == ["/venv/bin/python", "/b/napariViewGEF", "/s", "--list"]
        assert "LD_LIBRARY_PATH" not in env
        assert env[L.MARKER_VAR] == "reexec"
        assert env["HOME"] == "/h"

    def test_python_dash_m_is_restarted_as_python_dash_m(self):
        environ = {"NDI_FROM_MATLAB": "1", "PYTHONPATH": "/x"}
        _, calls = run(environ, orig_argv=["python", "-I", "-m", "ndi", "napari", "/s"])
        assert calls[0][1] == ["/venv/bin/python", "-I", "-m", "ndi", "napari", "/s"]

    def test_a_cleaned_process_does_not_exec_again(self):
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": "/junk", L.MARKER_VAR: "1"}
        result, calls = run(environ)
        assert result is False
        assert calls == []

    def test_an_ordinary_launch_does_not_exec(self):
        result, calls = run({"HOME": "/h", "LD_LIBRARY_PATH": "/usr/local/cuda/lib64"})
        assert result is False
        assert calls == []

    @pytest.mark.parametrize("orig_argv", [[], [""]])
    def test_an_embedded_interpreter_is_never_replaced(self, orig_argv):
        # No recorded command line: Python is embedded in a host (MATLAB's
        # in-process pyenv, say). exec would replace the HOST.
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD}
        result, calls = run(environ, orig_argv=orig_argv)
        assert result is True
        assert calls == []
        # Injected environ: reported, never written back.
        assert environ == {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD}

    def test_a_host_with_a_command_line_of_its_own_is_never_replaced(self):
        # Embedded, but the host passed its own argv through: still no exec.
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD}
        result, calls = run(environ, orig_argv=["matlab", "-nodesktop"], standalone=False)
        assert result is True
        assert calls == []

    def test_pytest_itself_counts_as_standalone(self):
        assert L._isStandaloneInterpreter()

    def test_a_failed_exec_falls_back_to_cleaning_in_place(self, monkeypatch):
        environ = {"NDI_FROM_MATLAB": "1", "LD_LIBRARY_PATH": MATLAB_LD}
        monkeypatch.setattr(L.os, "environ", environ)
        fake = FakeExec(raise_with=OSError("nope"))
        result = L.escapeMatlabEnvironment(
            platform="linux", executable="/p", orig_argv=["p", "s"], execve=fake, standalone=True
        )
        assert result is True
        assert len(fake.calls) == 1
        assert "LD_LIBRARY_PATH" not in environ
        assert environ[L.MARKER_VAR] == "in-place"


class TestDebugReport:
    def test_reports_once_and_only_when_asked(self, monkeypatch):
        err = io.StringIO()
        monkeypatch.setattr(L.sys, "stderr", err)
        environ = {L.MARKER_VAR: "reexec", "NDI_FROM_MATLAB": "1", L.DEBUG_VAR: "1"}
        run(environ)
        run(environ)
        lines = err.getvalue().splitlines()
        assert len(lines) == 1
        report = json.loads(lines[0].removeprefix("ndi-launch: "))
        assert report["cleaned"] == "reexec"
        assert report["fromMatlab"] is True
        assert set(report["env"]) == set(L.LIBRARY_VARS)
        assert all(v is None for v in report["env"].values())

    def test_silent_by_default(self, monkeypatch):
        err = io.StringIO()
        monkeypatch.setattr(L.sys, "stderr", err)
        run({"HOME": "/h"})
        assert err.getvalue() == ""


# --- wiring -----------------------------------------------------------------


def test_the_console_scripts_go_through_the_launcher():
    from importlib.metadata import entry_points

    scripts = {ep.name: ep.value for ep in entry_points(group="console_scripts")}
    assert scripts["napariViewGEF"] == "_ndi_launch:napariViewGEF"
    assert scripts["napariViewLightsheet"] == "_ndi_launch:napariViewLightsheet"


def test_the_launcher_imports_nothing_heavy():
    # The point of the module: importing it must not import ndi or numpy.
    code = (
        "import sys, _ndi_launch; "
        "bad = [m for m in ('ndi', 'numpy', 'pydantic', 'PySide6') if m in sys.modules]; "
        "sys.exit(f'imported {bad}' if bad else 0)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


CHILD = (
    "import _ndi_launch, os, sys; _ndi_launch.escapeMatlabEnvironment(); "
    "print(os.environ.get('LD_LIBRARY_PATH'), os.environ.get('NDI_MATLAB_ENV_CLEANED'))"
)
CHILD_ENV = {
    "PATH": "/usr/bin:/bin",
    "NDI_FROM_MATLAB": "1",
    "LD_LIBRARY_PATH": "/junk/R2026a/sys/os/glnxa64",
}


@pytest.mark.skipif(sys.platform.startswith("win"), reason="no exec on Windows")
def test_a_real_restart_drops_the_variables(tmp_path):
    # One true exec, end to end, in a child process so pytest is not replaced.
    script = tmp_path / "viewer.py"
    script.write_text(CHILD)
    out = subprocess.run(
        [sys.executable, str(script)], env=CHILD_ENV, capture_output=True, text=True, check=True
    )
    assert out.stdout.split() == ["None", "reexec"]


@pytest.mark.skipif(sys.platform.startswith("win"), reason="no exec on Windows")
def test_no_main_file_means_no_exec():
    # `python -c` has no __main__ file, like an embedded interpreter: cleaned
    # in place rather than restarted.
    out = subprocess.run(
        [sys.executable, "-c", CHILD], env=CHILD_ENV, capture_output=True, text=True, check=True
    )
    assert out.stdout.split() == ["None", "in-place"]
