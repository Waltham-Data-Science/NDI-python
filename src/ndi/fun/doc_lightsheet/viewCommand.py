"""
ndi.fun.doc_lightsheet.viewCommand

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/viewCommand.m

The command line that opens a lightsheetZarrPyramid in the napari viewer.
"""

from __future__ import annotations

import os
from typing import Literal

import pydantic

__all__ = ["viewCommand"]


def _shellQuote(s: str) -> str:
    """Quote for cmd.exe on Windows, for a POSIX shell elsewhere (as MATLAB)."""
    if os.name == "nt":
        return '"' + s.replace('"', '""') + '"'
    return "'" + s.replace("'", "'\\''") + "'"


def _viewFlags(reduction: str, channel: int, level: int, controls: bool, name: str) -> list[str]:
    """The optional napariViewLightsheet flags, unquoted, in viewCommand's order."""
    flags: list[str] = []
    if reduction:
        flags += ["--reduction", reduction]
    if channel >= 1:
        flags += ["--channel", str(channel)]
    if level >= 0:
        flags += ["--level", str(level)]
    if not controls:
        flags.append("--no-controls")
    if name.strip():
        flags += ["--name", name.strip()]
    return flags


@pydantic.validate_call
def viewCommand(
    launcher: str,
    sessionPath: str,
    pyramidID: str,
    *,
    channel: int = -1,
    reduction: Literal["", "mean", "max"] = "",
    controls: bool = True,
    name: str = "",
    level: int = -1,
) -> str:
    """The shell command that hands a lightsheetZarrPyramid to napari.

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.viewCommand(launcher,
    sessionPath, pyramidID, 'channel', ..., 'reduction', ..., 'controls',
    ..., 'name', ..., 'level', ...)``

    PURE: nothing is launched and the filesystem is not touched. The flags
    are those of ``napariViewLightsheet``
    (:mod:`ndi.gui.app.lightsheetZarr.cli`). Arguments are single-quoted for
    a POSIX shell, double-quoted on Windows.

    Args:
        launcher: path of the ``napariViewLightsheet`` console script.
        sessionPath: the ndi.session.dir directory.
        pyramidID: the lightsheetZarrPyramid id (required: the viewer will
            not guess on a session holding more than one).
        channel: 1-based channel index (the viewer's ``--channel`` is
            1-based too); -1 opens every channel.
        reduction: ``''``, ``'mean'`` or ``'max'``.
        controls: dock the reduction / channel / level panels.
        name: image layer name; empty uses the pyramid's own label.
        level: 0-based initial level; -1 lets the viewer pick.

    Returns:
        The command line as one string.

    Raises:
        ValueError: an empty launcher, session path or pyramid id (MATLAB:
            ``NDI:lightsheet:viewCommand:noLauncher`` / ``noSessionPath`` /
            ``noPyramidID``).
    """
    if not launcher.strip():
        raise ValueError(
            "No viewer launcher is set. Pass the path of NDI-python's "
            "napariViewLightsheet (shutil.which('napariViewLightsheet')); if it "
            "is not installed, install NDI-python."
        )
    if not sessionPath.strip():
        raise ValueError(
            "This session has no directory on disk, so there is nothing for the "
            "viewer to open. The napari viewer reads an ndi.session.dir."
        )
    if not pyramidID.strip():
        raise ValueError(
            "viewCommand refuses to build a command without a "
            "lightsheetZarrPyramid id; the viewer will not guess which pyramid "
            "to open when a session holds more than one."
        )

    parts = [_shellQuote(launcher.strip()), _shellQuote(sessionPath), "--pyramid"]
    parts.append(_shellQuote(pyramidID))
    quoted = {"--reduction", "--name"}
    flags = _viewFlags(reduction, channel, level, controls, name)
    for i, f in enumerate(flags):
        parts.append(_shellQuote(f) if i > 0 and flags[i - 1] in quoted else f)
    return " ".join(parts)
