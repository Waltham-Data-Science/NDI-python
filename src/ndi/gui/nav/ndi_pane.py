"""ndi.gui.nav.ndi_pane - the top, uncollapsible "NDI" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/ndiPane.m``

A single-row pane with an "NDI" title and, on the right, a broom button that
clears NDI's in-memory caches followed by a "Prefs" button that opens the
preferences editor. Always the first pane in the navigator, and it cannot be
collapsed.
"""

from __future__ import annotations

from typing import Any

from .pane import NavPane

__all__ = ["NdiPane", "BROOM", "BROOM_WIDTH", "PREFS_WIDTH", "BUTTON_SPACING"]

#: U+1F9F9 BROOM. MATLAB has to write this as a UTF-16 surrogate pair
#: (char([55358 56825])) because it is above the BMP and a bare char(129529)
#: would overflow. Python strings are code points, so the literal is the
#: character itself -- the same glyph, without the workaround.
BROOM = "\U0001f9f9"

BROOM_WIDTH = 28
PREFS_WIDTH = 60
BUTTON_SPACING = 4

CACHE_TOOLTIP = (
    "Clear NDI in-memory caches (memoized functions, probe-type map, "
    "calculator list, document definitions, database hierarchy)"
)


class NdiPane(NavPane):
    """The top "NDI" pane: a broom and a Prefs button."""

    def __init__(self, navigator: Any = None):
        super().__init__(navigator, title="NDI", collapsible=False)
        self.broom_button: Any = None
        self.prefs_button: Any = None

    def right_width(self) -> float:
        """broom (28) + spacing (4) + Prefs (60)."""
        return BROOM_WIDTH + BUTTON_SPACING + PREFS_WIDTH

    def build_header_right(self, layout: Any) -> None:
        from PySide6 import QtWidgets

        self.broom_button = QtWidgets.QPushButton(BROOM)
        self.broom_button.setFixedWidth(BROOM_WIDTH)
        self.broom_button.setToolTip(CACHE_TOOLTIP)
        self.broom_button.clicked.connect(self.clear_caches)
        self.accent_button(self.broom_button)
        layout.addWidget(self.broom_button)

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

    def _alert(self, message: str, title: str, *, success: bool) -> None:
        """Show a message on the navigator figure, if there is one."""
        if self.navigator is None:
            return
        alert = getattr(self.navigator, "alert", None)
        if callable(alert):
            alert(message, title, success=success)
