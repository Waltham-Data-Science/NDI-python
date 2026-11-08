"""
ndi.fun.doc_lightsheet.view

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/view.m

Launch the napari viewer (``napariViewLightsheet``) on a lightsheet pyramid,
or list a session's pyramids.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import warnings
from typing import Any, Literal

import pydantic

from .viewCommand import _viewFlags, viewCommand

__all__ = ["view"]


def _launcherArgv(launcher: str) -> list[str]:
    """The argv prefix that runs the viewer's command line.

    An explicit launcher wins; otherwise the ``napariViewLightsheet`` console
    script on PATH, and failing that this interpreter running the CLI module.
    """
    launcher = launcher.strip()
    if launcher:
        return [launcher]
    found = shutil.which("napariViewLightsheet")
    if found:
        return [found]
    return [sys.executable, "-m", "ndi.gui.app.lightsheetZarr.cli"]


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def view(
    session: Any,
    pyramidID: str = "",
    *,
    launcher: str = "",
    sessionPath: str = "",
    reduction: Literal["", "mean", "max"] = "",
    channel: int = -1,
    level: int = -1,
    controls: bool = True,
    name: str = "",
    wait: bool = False,
    verbose: bool = True,
    debug: bool = True,
    logFile: str = "",
) -> subprocess.Popen | int:
    """Open a lightsheetZarrPyramid in napari, or list the session's pyramids.

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.view(session, pyramidID,
    ...)``

    Runs ``napariViewLightsheet`` (:mod:`ndi.gui.app.lightsheetZarr.cli`) as
    a child process with the flags :func:`viewCommand` builds, so napari's
    event loop does not take over the caller's. With no *pyramidID* the
    viewer runs in ``--list`` mode and prints every pyramid's id; that mode
    always waits, so the ids are printed before this returns.

    Args:
        session: the ndi session; its ``path`` is the viewer's session
            argument unless *sessionPath* is given.
        pyramidID: the lightsheetZarrPyramid to open; ``''`` lists them.
        launcher: path of ``napariViewLightsheet``. Default: the console
            script on PATH, else ``python -m ndi.gui.app.lightsheetZarr.cli``.
        sessionPath: override the session directory.
        reduction, channel, level, controls, name: as :func:`viewCommand`
            (channel 1-based, level 0-based).
        wait: block until the viewer exits (default False).
        verbose: print the command before running it.
        debug: run the viewer with ``NDI_LIGHTSHEET_DEBUG=1``.
        logFile: append the viewer's stdout/stderr to this file. Default
            ``''``: the output goes to this process's own stdout/stderr
            (MATLAB writes a timestamped log in its temp folder, because a
            viewer started from MATLAB has no terminal).

    Returns:
        The child's exit status when it was waited for, else the running
        :class:`subprocess.Popen`.

    Raises:
        ValueError: no session directory could be found.
    """
    if not sessionPath:
        path = getattr(session, "path", None)
        try:
            sessionPath = str(path() if callable(path) else path or "")
        except Exception:  # noqa: BLE001 - reported as below
            sessionPath = ""
        if not sessionPath:
            raise ValueError(
                "Could not read a directory from the session; pass 'sessionPath' explicitly."
            )

    prefix = _launcherArgv(launcher)
    env = dict(os.environ)
    listMode = not pyramidID
    if listMode:
        argv = prefix + [sessionPath, "--list"]
        wait = True
    else:
        # viewCommand validates the arguments exactly as MATLAB does.
        viewCommand(
            prefix[0],
            sessionPath,
            pyramidID,
            channel=channel,
            reduction=reduction,
            controls=controls,
            name=name,
            level=level,
        )
        argv = prefix + [sessionPath, "--pyramid", pyramidID]
        argv += _viewFlags(reduction, channel, level, controls, name)
        if debug:
            env["NDI_LIGHTSHEET_DEBUG"] = "1"

    if verbose:
        print(shlex.join(argv))

    log = open(logFile, "a") if logFile else None  # noqa: SIM115 - child owns it
    try:
        proc = subprocess.Popen(
            argv, env=env, stdout=log, stderr=subprocess.STDOUT if log else None
        )
    finally:
        if log is not None:
            log.close()  # the child holds its own descriptor
    if verbose and logFile:
        print(f"Viewer output: {logFile}")
    if not wait:
        return proc
    status = proc.wait()
    if status != 0:
        where = f"; see {logFile}" if logFile else ""
        warnings.warn(f"Launcher returned status {status}{where}.", stacklevel=2)
    return status
