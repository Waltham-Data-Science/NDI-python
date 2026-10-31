"""ndi.gui.nav.ndi_pane - the top, uncollapsible "NDI" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/ndiPane.m``

A single-row pane with an "NDI" title and, on the right, a broom button that
clears NDI's in-memory caches, an "Update" button that checks for newer
versions of NDI-python and its dependencies and offers to install them (in
:mod:`ndi.gui.nav.update_dialog`'s package table), and a "Prefs" button that
opens the preferences editor. Always the first pane in the navigator, and it
cannot be collapsed.
"""

from __future__ import annotations

import os
from typing import Any

from .pane import NavPane

__all__ = [
    "NdiPane",
    "BROOM",
    "BROOM_WIDTH",
    "UPDATE_WIDTH",
    "PREFS_WIDTH",
    "BUTTON_SPACING",
    "updated_message",
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


UPDATE_TOOLTIP = "Check for a newer version of NDI-python and its dependencies"
UPDATE_TITLE = "NDI Update"


def updated_message(result: dict[str, Any], packages: list[str]) -> str:
    """What the Update button says after installing PACKAGES for a check RESULT."""
    from ...update import packageStatus

    rows, _ = packageStatus(result)
    names = [r["Name"] for r in rows if r["Name"] in packages]
    if result.get("InstallType") == "installer" and os.name == "nt":
        return "The NDI installer has opened in a new window. Close NDI to let it finish."
    return f"Updated: {', '.join(names)}.\n\nRestart NDI to make sure the new versions are used."


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
        """Check for, and offer to install, NDI updates (the Update button).

        Runs ``ndi.update.check`` and lists every package in
        :class:`ndi.gui.nav.update_dialog.UpdateDialog` -- NDI-python and its
        dependency clones -- each with its status, notes and a tick box. If
        the user presses Update, runs ``ndi.update.install`` for the ticked
        packages only, without its terminal prompts (the dialog has already
        shown what updating will do). Returns the check result (None if the
        check itself failed).
        """
        from ... import update

        try:
            with _busy_cursor():
                result = update.check(Verbose=False)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self._alert(str(exc), UPDATE_TITLE, success=False)
            return None

        go, packages = self._ask(result)
        if not go or not packages:
            return result

        try:
            with _busy_cursor():
                update.install(Confirm=False, AllowModified=True, Packages=packages)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self._alert(str(exc), UPDATE_TITLE, success=False)
            return result
        self._alert(updated_message(result, packages), UPDATE_TITLE, success=True)
        return result

    def _ask(self, result: dict[str, Any]) -> tuple[bool, list[str]]:
        """Show the package table; blocking, as MATLAB's uiwait is."""
        if self.navigator is None or getattr(self.navigator, "figure", None) is None:
            return False, []
        from .update_dialog import ask

        return ask(result, self.navigator.figure)

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
