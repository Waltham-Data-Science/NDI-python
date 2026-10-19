"""ndi.gui.nav.ndi_pane - the top, uncollapsible "NDI" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/ndiPane.m``

A single-row pane with an "NDI" title and, on the right, a broom button that
clears NDI's in-memory caches, an "Update" button that checks for a newer
NDI-python and offers to install it, and a "Prefs" button that opens the
preferences editor. Always the first pane in the navigator, and it cannot be
collapsed.

What the Update button says is decided by :func:`update_dialog`, which is
pure (a check result in, a dialog description out) so it is testable without
Qt, the split ndi.gui.nav makes elsewhere.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .pane import NavPane

__all__ = [
    "NdiPane",
    "BROOM",
    "BROOM_WIDTH",
    "UPDATE_WIDTH",
    "PREFS_WIDTH",
    "BUTTON_SPACING",
    "update_dialog",
]

#: U+1F9F9 BROOM. MATLAB has to write this as a UTF-16 surrogate pair
#: (char([55358 56825])) because it is above the BMP and a bare char(129529)
#: would overflow. Python strings are code points, so the literal is the
#: character itself -- the same glyph, without the workaround.
BROOM = "\U0001f9f9"

BROOM_WIDTH = 28
UPDATE_WIDTH = 60
PREFS_WIDTH = 60
BUTTON_SPACING = 4

CACHE_TOOLTIP = (
    "Clear NDI in-memory caches (memoized functions, probe-type map, "
    "calculator list, document definitions, database hierarchy)"
)


UPDATE_TOOLTIP = "Check for a newer version of NDI-python"
UPDATE_TITLE = "NDI Update"


def update_dialog(result: dict[str, Any]) -> dict[str, Any]:
    """What the Update button shows for an ``ndi.update.check`` RESULT.

    Mirrors the decisions in MATLAB's ``ndiPane.checkForUpdates``. Returns a
    dict with ``kind`` -- ``"alert"`` (just tell the user) or ``"confirm"``
    (ask, then install) -- and ``message``, ``success`` (alert icon),
    ``accept`` (the confirm button's label) and ``default_cancel`` (Cancel is
    the default button, as it is whenever the user's own code is touched).
    """
    message = result.get("Message", "")
    if not result.get("UpdateAvailable"):
        return {
            "kind": "alert",
            "message": message,
            "success": result.get("Status") != "unknown",
        }
    if not result.get("CanInstall"):
        return {"kind": "alert", "message": message, "success": False}
    if result.get("InstallType") == "git" and result.get("Branch") != "main":
        # ndi.update.install refuses this case; say why up front.
        return {"kind": "alert", "message": message, "success": False}

    # The message ends with command-line hints; the dialog replaces them.
    message = re.sub(r"\n?Run ndi\.update\.install\(\)[^\n]*", "", message)
    message = re.sub(r"\n?Note: you have changed code[^\n]*", "", message)
    if result.get("HasModifications"):
        from ...update import modificationSummary

        summary = modificationSummary(result)
        if any(m.get("BlockingFiles") for m in result.get("Modifications", [])):
            # Untracked files sit where the update adds files; git will not
            # overwrite them, so updating cannot work until they move.
            return {
                "kind": "alert",
                "message": f"{message}\n\n{summary}\n\nMove or rename the files marked "
                '"in the way", then press Update again.',
                "success": False,
            }
        return {
            "kind": "confirm",
            "message": f"{message}\n\n{summary}\n\nUpdate anyway?",
            "accept": "Update anyway",
            "default_cancel": True,
        }
    if result.get("InstallType") == "installer" and os.name == "nt":
        message += (
            "\n\nThe NDI installer will open in its own window and finish " "after you close NDI."
        )
    return {
        "kind": "confirm",
        "message": f"{message}\n\nUpdate now?",
        "accept": "Update",
        "default_cancel": False,
    }


class NdiPane(NavPane):
    """The top "NDI" pane: a broom, an Update and a Prefs button."""

    def __init__(self, navigator: Any = None):
        super().__init__(navigator, title="NDI", collapsible=False)
        self.broom_button: Any = None
        self.update_button: Any = None
        self.prefs_button: Any = None

    def right_width(self) -> float:
        """broom (28) + spacing (4) + Update (60) + spacing (4) + Prefs (60)."""
        return BROOM_WIDTH + BUTTON_SPACING + UPDATE_WIDTH + BUTTON_SPACING + PREFS_WIDTH

    def build_header_right(self, layout: Any) -> None:
        from PySide6 import QtWidgets

        self.broom_button = QtWidgets.QPushButton(BROOM)
        self.broom_button.setFixedWidth(BROOM_WIDTH)
        self.broom_button.setToolTip(CACHE_TOOLTIP)
        self.broom_button.clicked.connect(self.clear_caches)
        self.accent_button(self.broom_button)
        layout.addWidget(self.broom_button)

        self.update_button = QtWidgets.QPushButton("Update")
        self.update_button.setFixedWidth(UPDATE_WIDTH)
        self.update_button.setToolTip(UPDATE_TOOLTIP)
        self.update_button.clicked.connect(self.check_for_updates)
        self.accent_button(self.update_button)
        layout.addWidget(self.update_button)

        self.prefs_button = QtWidgets.QPushButton("Prefs")
        self.prefs_button.setFixedWidth(PREFS_WIDTH)
        self.prefs_button.setToolTip("Open the NDI preferences editor")
        self.prefs_button.clicked.connect(self._open_preferences)
        self.accent_button(self.prefs_button)
        layout.addWidget(self.prefs_button)

    def _open_preferences(self) -> None:
        if self.navigator is not None:
            self.navigator.open_preferences()

    def clear_caches(self) -> list[str]:
        """Clear NDI's in-memory caches (the broom button).

        Returns the names of the caches cleared, and reports on the navigator
        figure the way MATLAB's does. The return value is what makes this
        testable without a display, and it is worth having anyway: a caller
        can see which caches a "clear all" actually covered.
        """
        from ...fun.cache import clear_all_caches

        try:
            cleared = clear_all_caches()
        except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
            self._alert(str(exc), "Clear Caches", success=False)
            return []
        self._alert("NDI in-memory caches were cleared.", "Clear Caches", success=True)
        return cleared

    def check_for_updates(self) -> dict[str, Any] | None:
        """Check for, and offer to install, an NDI-python update (the Update button).

        Runs ``ndi.update.check`` and reports the result. If an update can be
        installed, asks the user to confirm and then runs
        ``ndi.update.install`` without its terminal prompt. Returns the check
        result (None if the check itself failed).
        """
        from ... import update

        try:
            with _busy_cursor():
                result = update.check(Verbose=False)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self._alert(str(exc), UPDATE_TITLE, success=False)
            return None

        plan = update_dialog(result)
        if plan["kind"] == "alert":
            self._alert(plan["message"], UPDATE_TITLE, success=plan["success"])
            return result
        if not self._confirm(plan["message"], plan["accept"], plan["default_cancel"]):
            return result

        try:
            with _busy_cursor():
                update.install(Confirm=False, AllowModified=True)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self._alert(str(exc), UPDATE_TITLE, success=False)
            return result
        if result["InstallType"] == "installer" and os.name == "nt":
            done = "The NDI installer has opened in a new window. Close NDI to let it finish."
        else:
            done = "NDI-python was updated. Restart NDI to make sure the new version is used."
        self._alert(done, UPDATE_TITLE, success=True)
        return result

    def _confirm(self, message: str, accept: str, default_cancel: bool) -> bool:
        """Ask before updating; blocking, as MATLAB's uiconfirm is."""
        if self.navigator is None or getattr(self.navigator, "figure", None) is None:
            return False
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.navigator.figure)
        box.setWindowTitle(UPDATE_TITLE)
        box.setText(message)
        box.setIcon(
            QtWidgets.QMessageBox.Icon.Warning
            if default_cancel
            else QtWidgets.QMessageBox.Icon.Question
        )
        go = box.addButton(accept, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel if default_cancel else go)
        box.exec()
        return box.clickedButton() is go

    def _alert(self, message: str, title: str, *, success: bool) -> None:
        """Show a message on the navigator figure, if there is one."""
        if self.navigator is None:
            return
        alert = getattr(self.navigator, "alert", None)
        if callable(alert):
            alert(message, title, success=success)


class _busy_cursor:
    """A wait cursor while the check or the install runs, if Qt is up."""

    def __enter__(self) -> None:
        self._app = None
        try:
            from PySide6 import QtCore, QtGui, QtWidgets

            self._app = QtWidgets.QApplication.instance()
            if self._app is not None:
                self._app.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
        except ImportError:
            self._app = None

    def __exit__(self, *exc: object) -> None:
        if self._app is not None:
            self._app.restoreOverrideCursor()
