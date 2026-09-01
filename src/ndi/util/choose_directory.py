"""Folder pickers that only return an NDI directory of the wanted kind.

MATLAB counterparts: ``src/ndi/+ndi/+util/chooseDatasetOrSession.m``,
``chooseSession.m``, ``chooseDataset.m``

:func:`choose_dataset_or_session` opens a folder dialog and keeps asking
until the user either cancels or picks a directory of an accepted kind. The
caller therefore never has to re-check what it was handed: a returned path is
an NDI directory of a kind it asked for, full stop.

WHY THE RULES ARE SEPARATE FROM THE DIALOG
Everything that decides -- whether a kind is accepted, what the dialog is
called, and what to say when the choice was wrong -- is a plain function here
with no Qt in it. Only the loop touches a dialog. A wrong message in this
code does not raise; it just tells someone their folder is the wrong sort of
thing for the wrong reason, which is the kind of bug that survives a long
time. Keeping the wording testable is the point.

``"unknown"`` IS NOT ACCEPTED BY DEFAULT WHERE A KIND MATTERS
:data:`ACCEPT_ALL` includes it, but :func:`choose_session` and
:func:`choose_dataset` do not: an NDI folder created before object-type
markers existed cannot be confirmed to be a session rather than a dataset,
and guessing would hand the caller the wrong object. The message says how to
resolve it -- open the folder once so its type is recorded -- rather than
just refusing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "ACCEPT_ALL",
    "is_accepted",
    "accepted_kinds_phrase",
    "default_title",
    "mismatch_message",
    "choose_dataset_or_session",
    "choose_session",
    "choose_dataset",
]

#: Every directory kind a picker may accept, as MATLAB's default.
ACCEPT_ALL: tuple[str, ...] = ("session", "dataset", "unknown")


def is_accepted(dirtype: str, accept: Sequence[str]) -> bool:
    """Whether a directory type is one the caller asked for."""
    return str(dirtype) in tuple(accept)


def accepted_kinds_phrase(accept: Sequence[str]) -> str:
    """A human phrase for the kinds a picker will take."""
    wants_session = "session" in tuple(accept)
    wants_dataset = "dataset" in tuple(accept)
    if wants_session and not wants_dataset:
        return "an NDI session"
    if wants_dataset and not wants_session:
        return "an NDI dataset"
    return "an NDI session or dataset"


def default_title(accept: Sequence[str]) -> str:
    """The dialog title describing the accepted kinds."""
    wants_session = "session" in tuple(accept)
    wants_dataset = "dataset" in tuple(accept)
    if wants_session and not wants_dataset:
        return "Select an NDI session directory"
    if wants_dataset and not wants_session:
        return "Select an NDI dataset directory"
    return "Select an NDI session or dataset directory"


def mismatch_message(dirtype: str, accept: Sequence[str]) -> str:
    """Why a chosen folder was not accepted.

    Three different situations, deliberately worded differently, because the
    user's next move differs in each:

        ``"none"``     -- not an NDI folder at all; pick another.
        ``"unknown"``  -- an NDI folder whose type predates the markers. It
                          might be the right kind; opening it once records
                          which, so the message says to do that rather than
                          implying the folder is unusable.
        otherwise      -- a valid NDI folder of the OTHER kind, which is a
                          near miss worth naming precisely.
    """
    wanted = accepted_kinds_phrase(accept)
    dirtype = str(dirtype)
    if dirtype == "none":
        return "That folder is not an NDI session or dataset directory. " f"Please choose {wanted}."
    if dirtype == "unknown":
        return (
            "That NDI folder predates object-type markers, so its type cannot "
            "be confirmed. Open it once with ndi.session.dir or "
            "ndi.dataset.dir to record whether it is a session or a dataset, "
            f"then choose it again. (Expected {wanted}.)"
        )
    return f"That folder is an NDI {dirtype}, but {wanted} is required. " f"Please choose {wanted}."


def choose_dataset_or_session(
    *,
    start_path: str = "",
    title: str = "",
    accept: Sequence[str] = ACCEPT_ALL,
    parent: Any = None,
    _pick: Any = None,
    _explain: Any = None,
) -> tuple[str, str]:
    """Ask for a folder until it is an NDI directory of an accepted kind.

    Returns ``(pathname, dirtype)``, or ``("", "")`` if the user cancels.

    On a wrong choice the reason is shown and the dialog reopens AT THE
    FOLDER THE USER JUST PICKED, not back at the start: someone who lands one
    level away from the right directory should not have to navigate there
    again.

    ``_pick`` and ``_explain`` exist so the loop itself can be tested without
    a display -- they default to a Qt folder dialog and a Qt message box.
    They are not part of the MATLAB interface.
    """
    accept = tuple(accept)
    title = title or default_title(accept)
    pick = _pick if _pick is not None else _qt_pick_directory
    explain = _explain if _explain is not None else _qt_explain

    start = start_path
    while True:
        selection = pick(start, title, parent)
        if not selection:
            return "", ""  # cancelled

        dirtype = _directory_type(selection)
        if is_accepted(dirtype, accept):
            return selection, dirtype

        explain(mismatch_message(dirtype, accept), title, parent)
        start = selection


def choose_session(
    *, start_path: str = "", title: str = "", parent: Any = None, **kwargs: Any
) -> tuple[str, str]:
    """Ask for a folder until it is an NDI SESSION directory."""
    return choose_dataset_or_session(
        start_path=start_path, title=title, accept=("session",), parent=parent, **kwargs
    )


def choose_dataset(
    *, start_path: str = "", title: str = "", parent: Any = None, **kwargs: Any
) -> tuple[str, str]:
    """Ask for a folder until it is an NDI DATASET directory."""
    return choose_dataset_or_session(
        start_path=start_path, title=title, accept=("dataset",), parent=parent, **kwargs
    )


def _directory_type(path: str) -> str:
    from ..session.dir import ndi_session_dir

    return ndi_session_dir.directorytype(path)


def _qt_pick_directory(start: str, title: str, parent: Any) -> str:
    from PySide6 import QtWidgets

    return QtWidgets.QFileDialog.getExistingDirectory(parent, title, start or "")


def _qt_explain(message: str, title: str, parent: Any) -> None:
    from PySide6 import QtWidgets

    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.exec()
