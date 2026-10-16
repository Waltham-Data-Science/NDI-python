"""Start NDI's command-line viewers safely when MATLAB is the parent process.

The ``napariViewGEF`` and ``napariViewLightsheet`` console scripts point HERE
rather than at their ``cli.main`` functions, and that is the whole reason this
module exists outside the ``ndi`` package. Importing anything under ``ndi``
runs ``ndi/__init__.py``, which loads numpy, pydantic_core, DID and roughly a
thousand other modules -- so by the time a ``main()`` inside ``ndi`` runs, the
dynamic loader has already resolved their shared libraries against whatever
LD_LIBRARY_PATH the process inherited. Cleaning the environment there would be
too late for those libraries. This module imports only the standard library,
so the console script can clean up and re-exec before any of that happens.
(The two ``main()`` functions call :func:`escapeMatlabEnvironment` too, which
covers ``python -m ndi napari`` and is a no-op after the re-exec.)

WHY. MATLAB exports library search paths of its own, and a process it starts
with ``system()`` inherits them. MEASURED, not assumed (these notes came from
the shell wrappers this module replaced, tools/napariViewGEF and
scripts/napariViewLightsheet):

  Linux  -- MATLAB prepends nine of its own directories to LD_LIBRARY_PATH,
            among them sys/os/glnxa64 (its libstdc++) and
            sys/opengl/lib/glnxa64 (OpenGL, which napari needs through vispy).
            numpy and PyQt5 imported fine anyway under R2026a on Ubuntu 24.04,
            so this is insurance rather than a fix for a known break, except
            for OpenGL, which can only be tested on a machine with a GPU.
  macOS  -- MATLAB sets no MW_* except MW_DESKTOP_IGNORE_STDIN and leaves LD_*
            and DYLD_* empty. Nothing to protect against today; the DYLD_*
            variables are cleared anyway, at no cost.
  Windows -- UNMEASURED. See :func:`cleanedEnvironment`.

MW_ORIG_LD_LIBRARY_PATH was unset on both measured platforms, so it can
neither detect MATLAB nor restore the caller's original value. Detection is
therefore the NDI_FROM_MATLAB variable the MATLAB-side launcher sets (one call
site, no dependence on MATLAB internals), plus a fallback for callers that
forget it: a library path naming one of MATLAB's architecture directories.

WHY RE-EXEC. On Linux and macOS the dynamic loader reads LD_LIBRARY_PATH and
DYLD_* once, when the process starts; changing ``os.environ`` afterwards does
not change where later ``dlopen`` calls look. So the cleaned environment has to
be handed to a NEW process image: ``os.execve`` of the same interpreter with
the same command line. A marker variable stops the new image from doing it
again.

Python-only; no MATLAB counterpart. The MATLAB side solves the mirror-image
problem for curl with ``ndi.common.systemCurlEnvPrefix`` (recorded
``matlab_only`` in src/ndi/common/ndi_matlab_python_bridge.yaml). Standard
library only, deliberately -- which is also why it does not use the
``@pydantic.validate_call`` that NDI's public API carries: importing pydantic
loads a compiled extension, which is exactly what must not happen first.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "LIBRARY_VARS",
    "MARKER_VAR",
    "cleanedEnvironment",
    "escapeMatlabEnvironment",
    "isFromMatlab",
    "napariViewGEF",
    "napariViewLightsheet",
]

# Removed from the environment of a viewer started from MATLAB, POSIX only.
# Each one is something a Python GUI process must not inherit from MATLAB:
LIBRARY_VARS = (
    # Linux: MATLAB prepends its own lib dirs (libstdc++, OpenGL, ...) and the
    # loader searches them BEFORE a wheel's own RUNPATH, so numpy, Qt or
    # napari's OpenGL could bind MATLAB's copies. Measured; see above.
    "LD_LIBRARY_PATH",
    # Linux: forces a library into every process. Nothing in a viewer should
    # inherit one from MATLAB. (This also drops a VirtualGL `vglrun` preload,
    # should MATLAB itself have been started that way; run the viewer under
    # vglrun directly in that case.)
    "LD_PRELOAD",
    # macOS: the dyld counterparts of the two above, with the same failure
    # modes -- a library or framework from MATLAB's tree bound in place of the
    # one a wheel ships, or injected outright. Measured empty under MATLAB
    # today; cleared so that staying true does not depend on MATLAB.
    "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    # Both platforms: PYTHONHOME replaces the interpreter's prefix outright, so
    # the venv's standard library and site-packages would not be the ones
    # used. PYTHONPATH puts directories AHEAD of the venv's site-packages, so
    # a numpy or Qt built for another Python could shadow the installed one.
    # The viewers are installed as self-contained tools and need neither.
    "PYTHONHOME",
    "PYTHONPATH",
)

# Set in the cleaned environment. Its presence means "already done": the
# re-exec'd process must not re-exec again, whatever else it finds. Its value
# says how it was done: "reexec", or "in-place" (Windows, or no faithful
# restart possible).
MARKER_VAR = "NDI_MATLAB_ENV_CLEANED"

# Set by MATLAB's launcher (any non-empty value).
FROM_MATLAB_VAR = "NDI_FROM_MATLAB"

# Hidden: when non-empty, the final process prints one JSON line describing
# its environment to stderr. Used by CI to prove the re-exec happened.
DEBUG_VAR = "NDI_LAUNCH_DEBUG"

# MathWorks' own architecture names. No other software names a directory
# this way, so a library path holding one is MATLAB's.
_MATLAB_ARCH_DIRS = frozenset({"glnxa64", "maci64", "maca64"})

# The variables whose contents can betray MATLAB without NDI_FROM_MATLAB.
_DETECTION_VARS = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
)

# MATLAB's binary directories on Windows, relative to matlabroot.
_WINDOWS_MATLAB_TAILS = (
    ("bin", "win64"),
    ("runtime", "win64"),
    ("sys", "os", "win64"),
    ("extern", "bin", "win64"),
)


def _parts(path: str) -> list[str]:
    """Split a path on both separators, dropping empties; lower-cased."""
    return [p for p in path.replace("\\", "/").lower().split("/") if p]


def _isMatlabLibraryEntry(entry: str) -> bool:
    return any(p in _MATLAB_ARCH_DIRS for p in _parts(entry))


def _isMatlabWindowsPathEntry(entry: str) -> bool:
    parts = _parts(entry)
    return any(len(parts) > len(t) and tuple(parts[-len(t) :]) == t for t in _WINDOWS_MATLAB_TAILS)


def isFromMatlab(environ: Mapping[str, str]) -> bool:
    """True when ``environ`` looks like that of a process MATLAB started.

    Either MATLAB's launcher said so (NDI_FROM_MATLAB is non-empty), or a
    dynamic-loader variable names one of MATLAB's architecture directories
    (``glnxa64``, ``maci64``, ``maca64``), which nothing but MATLAB uses.
    """
    if environ.get(FROM_MATLAB_VAR, ""):
        return True
    return any(
        _isMatlabLibraryEntry(entry)
        for var in _DETECTION_VARS
        for entry in environ.get(var, "").split(":")
        if entry
    )


def cleanedEnvironment(environ: Mapping[str, str], platform: str) -> dict[str, str] | None:
    """Return the environment a viewer started from MATLAB should run in.

    ``None`` means "leave it alone": the environment was already cleaned (the
    marker is set), it does not come from MATLAB, or there is nothing in it to
    remove. Otherwise a new dict: the input minus :data:`LIBRARY_VARS` (minus
    MATLAB's directories on PATH, on Windows), plus the marker.

    WINDOWS IS UNMEASURED. Nobody has recorded what MATLAB exports to a child
    there, so this does the minimum that is certainly right: drop MATLAB's
    own binary directories (``<matlabroot>\\bin\\win64`` and kin) from PATH,
    and PYTHONHOME / PYTHONPATH. Since Python 3.8 extension modules load
    their DLLs without consulting PATH, so this matters mainly for programs
    the viewer starts. On Windows only NDI_FROM_MATLAB triggers it.
    """
    if environ.get(MARKER_VAR, ""):
        return None
    windows = platform.startswith("win")
    if windows:
        if not environ.get(FROM_MATLAB_VAR, ""):
            return None
    elif not isFromMatlab(environ):
        return None

    env = dict(environ)
    changed = False
    removable = ("PYTHONHOME", "PYTHONPATH") if windows else LIBRARY_VARS
    for var in removable:
        if var in env:
            del env[var]
            changed = True
    if windows:
        # Windows variable names are case-insensitive; find PATH however spelled.
        for key in [k for k in env if k.upper() == "PATH"]:
            entries = env[key].split(";")
            kept = [e for e in entries if not _isMatlabWindowsPathEntry(e)]
            if len(kept) != len(entries):
                env[key] = ";".join(kept)
                changed = True
    if not changed:
        return None
    env[MARKER_VAR] = "in-place" if windows else "reexec"
    return env


def _isStandaloneInterpreter() -> bool:
    """True when this process is a Python interpreter running a program.

    False when Python is embedded in a host -- MATLAB's in-process ``pyenv``,
    say -- where exec would replace the HOST, whatever ``sys.orig_argv``
    holds. Two signs: an embedded interpreter has no ``__main__`` file, and
    (Linux) the running binary is not a Python.
    """
    main = sys.modules.get("__main__")
    if not getattr(main, "__file__", None):
        return False
    try:
        exe = os.path.basename(os.path.realpath("/proc/self/exe"))
    except OSError:
        return True
    return not os.path.exists("/proc/self/exe") or exe.lower().startswith("python")


_reported = False


def _debugReport(environ: Mapping[str, str]) -> None:
    # Once per process: the console script and main() both call in.
    global _reported
    if _reported or not environ.get(DEBUG_VAR, ""):
        return
    _reported = True
    report = {
        "cleaned": environ.get(MARKER_VAR) or None,
        "fromMatlab": bool(environ.get(FROM_MATLAB_VAR, "")),
        "env": {var: environ.get(var) for var in LIBRARY_VARS},
    }
    print("ndi-launch: " + json.dumps(report, sort_keys=True), file=sys.stderr, flush=True)


def escapeMatlabEnvironment(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    executable: str | None = None,
    orig_argv: Sequence[str] | None = None,
    execve: Callable[..., object] | None = None,
    standalone: bool | None = None,
) -> bool:
    """Leave MATLAB's library paths behind before NDI's viewers load anything.

    Call it FIRST in a viewer's entry point. When :func:`cleanedEnvironment`
    finds something to remove, on Linux and macOS this replaces the current
    process with a fresh copy of itself -- same interpreter, same command
    line (``sys.orig_argv``), cleaned environment -- and does not return. On
    Windows it cleans ``os.environ`` in place and returns True. Otherwise it
    returns False and changes nothing.

    It never re-execs a process it cannot faithfully restart: one with no
    interpreter path or no recorded command line, or one where Python is
    embedded in another program (MATLAB's in-process ``pyenv`` among them),
    where an exec would replace the HOST. Those fall back to cleaning
    ``os.environ`` in place, which protects child processes but not this one.

    The keyword arguments exist for tests; each defaults to the real thing
    (``os.environ``, ``sys.platform``, ``sys.executable``, ``sys.orig_argv``,
    ``os.execve``, :func:`_isStandaloneInterpreter`).
    """
    live = environ is None
    if live:
        environ = os.environ
    platform = sys.platform if platform is None else platform
    executable = sys.executable if executable is None else executable
    if orig_argv is None:
        orig_argv = getattr(sys, "orig_argv", [])
    execve = os.execve if execve is None else execve

    env = cleanedEnvironment(environ, platform)
    if env is None:
        _debugReport(environ)
        return False

    restartable = (
        not platform.startswith("win")
        and bool(executable)
        and len(orig_argv) >= 2
        and not getattr(sys, "frozen", False)
        and (_isStandaloneInterpreter() if standalone is None else standalone)
    )
    if restartable:
        argv = [executable, *orig_argv[1:]]
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            execve(executable, argv, env)
            # A real execve does not return; an injected one does.
            return True
        except OSError as err:
            print(
                f"ndi: could not restart without MATLAB's library paths ({err}); "
                "continuing with them removed for child processes only.",
                file=sys.stderr,
            )

    # Windows, or no faithful restart possible: clean in place.
    env[MARKER_VAR] = "in-place"
    if live:
        for var in [k for k in environ if k not in env]:
            del environ[var]
        environ.update(env)
    _debugReport(env)
    return True


# --- console-script entry points (pyproject.toml [project.scripts]) --------


def napariViewGEF() -> int:
    """Console script ``napariViewGEF``: escape, then run the real CLI."""
    escapeMatlabEnvironment()
    from ndi.gui.app.genepyramid.cli import main

    return main()


def napariViewLightsheet() -> int:
    """Console script ``napariViewLightsheet``: escape, then run the real CLI."""
    escapeMatlabEnvironment()
    from ndi.gui.app.lightsheetZarr.cli import main

    return main()
