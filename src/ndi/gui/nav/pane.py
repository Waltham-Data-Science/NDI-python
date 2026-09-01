"""ndi.gui.nav.pane - base class for a pane in ndi.gui.navigator.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/pane.m``

Every pane owns one horizontal region of the navigator window. See the
package docstring for why the state machine and the geometry live here as
plain Python while only :meth:`NavPane.build` touches Qt.
"""

from __future__ import annotations

from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex

__all__ = ["NavPane", "HEADER_HEIGHT", "TRIANGLE_RIGHT", "TRIANGLE_DOWN"]

#: Header row height, in pixels. MATLAB's ndi.gui.nav.pane.HeaderHeight.
HEADER_HEIGHT = 28

#: Disclosure glyphs. U+25B6 collapsed, U+25BC expanded -- the same code
#: points MATLAB writes as char(9654) / char(9660).
TRIANGLE_RIGHT = "▶"
TRIANGLE_DOWN = "▼"

#: Width of the left disclosure column when a pane is collapsible.
DISCLOSURE_WIDTH = 22


class NavPane:
    """A single horizontal region of the navigator window.

    Not used directly; concrete panes subclass it and override the small set
    of hooks below.

    Args:
        navigator: The owning navigator.
        title: Text shown in the header.
        collapsible: If true a disclosure triangle is drawn and the pane can
            be collapsed to its header row only.
        engaged: Initial expanded state. Forced true for a non-collapsible
            pane -- a pane with no triangle cannot be collapsed, so a false
            here would be a state the user could never undo.
        min_height: Minimum total pane height while engaged. Raised to
            HEADER_HEIGHT if smaller: a pane shorter than its own header
            cannot render.
        height: Initial total pane height while engaged. Clamped UP to
            min_height. None means min_height.

    Overridable hooks:
        ``has_body``          - whether the pane renders a body row.
        ``build_body``        - populate the body (only called when has_body).
        ``build_header_right``- add the right-hand header control.
        ``right_width``       - pixel width of the right control column.
        ``refresh``           - re-read model state into the widgets.
    """

    def __init__(
        self,
        navigator: Any = None,
        *,
        title: str = "",
        collapsible: bool = False,
        engaged: bool = True,
        min_height: float = HEADER_HEIGHT,
        height: float | None = None,
    ):
        self.navigator = navigator
        self.title = str(title)
        self.collapsible = bool(collapsible)
        # A non-collapsible pane is always engaged, whatever was asked for.
        self.engaged = bool(engaged) or not self.collapsible
        self.min_height = max(float(min_height), float(HEADER_HEIGHT))
        self.height = self.min_height if height is None else max(float(height), self.min_height)
        #: Pixel height last assigned by the navigator layout; NaN until then.
        self.rendered_height = float("nan")

        # Qt objects, created by build().
        self.panel: Any = None
        self.grid: Any = None
        self.header_grid: Any = None
        self.disclosure_button: Any = None
        self.title_label: Any = None
        self.body_container: Any = None

    # ------------------------------------------------------------------
    # state and geometry -- no Qt below this line until build()
    # ------------------------------------------------------------------
    def has_body(self) -> bool:
        """True if the pane renders a body below the header. Default False."""
        return False

    def current_height(self) -> float:
        """The pixel height this pane requests in the navigator.

        Header-only when collapsed; otherwise its engaged height, never below
        ``min_height``. The lower clamp is applied here as well as in the
        constructor because ``height`` is a public attribute a caller may set
        directly, and a pane shorter than its header renders as a clipped
        title rather than failing.
        """
        if self.collapsible and not self.engaged:
            return float(HEADER_HEIGHT)
        return max(self.height, self.min_height)

    def disclosure_glyph(self) -> str:
        """The triangle for the current engaged state."""
        return TRIANGLE_DOWN if self.engaged else TRIANGLE_RIGHT

    def disclosure_tooltip(self) -> str:
        """Hover text for the disclosure triangle.

        Names the ACTION (the opposite of the current state) and the section,
        so a user reads what the click will do rather than where they are.
        """
        what = f"the {self.title} section" if self.title else "this section"
        return f"Collapse {what}" if self.engaged else f"Expand {what}"

    def toggle(self) -> None:
        """Flip a collapsible pane between engaged and collapsed.

        The user-driven path (the disclosure triangle). It is a STRUCTURAL
        action, so the navigator resizes the window to match: collapsing
        shrinks it, expanding grows it.
        """
        if not self.collapsible:
            return
        self.engaged = not self.engaged
        self._update_disclosure()
        self._apply_engaged_state()
        if self.navigator is not None:
            self.navigator.pane_toggled(self)

    def set_engaged(self, tf: bool) -> None:
        """Force the engaged state, structurally (the window resizes).

        Use :meth:`set_engaged_quietly` for content-driven engages that
        should not resize the window.
        """
        if not self.collapsible or bool(tf) == self.engaged:
            return
        self.toggle()

    def set_engaged_quietly(self, tf: bool) -> None:
        """Engage or collapse WITHOUT resizing the window.

        Used when content needs the pane open -- an arriving progress bar,
        say. The elastic panes absorb the change instead of the window
        growing, which is the difference that matters: a window that jumps
        because a background task started is a window the user did not ask to
        move.
        """
        if not self.collapsible or bool(tf) == self.engaged:
            return
        self.engaged = bool(tf)
        self._update_disclosure()
        self._apply_engaged_state()
        if self.navigator is not None:
            self.navigator.layout()

    def set_rendered_height(self, h: float) -> None:
        """Record the pixel height the navigator assigned to this pane."""
        self.rendered_height = float(h)

    def refresh(self) -> None:
        """Re-read model state into the pane widgets. Default no-op."""

    # ------------------------------------------------------------------
    # Qt construction
    # ------------------------------------------------------------------
    def build(self, parent_layout: Any, row: int) -> Any:
        """Create the pane's panel and contents in a layout row.

        Everything Qt-specific about a pane is here and in the hooks it
        calls; the state above is deliberately reachable without a display.
        """
        from .._qt_helpers import require_qt

        require_qt()
        from PySide6 import QtWidgets

        c = cloud_colors()

        self.panel = QtWidgets.QFrame()
        self.panel.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.panel.setStyleSheet(f"background-color: {rgb_to_hex(c.white)};")

        self.grid = QtWidgets.QVBoxLayout(self.panel)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)

        self._build_header()

        if self.has_body():
            self.body_container = QtWidgets.QWidget()
            body_layout = QtWidgets.QVBoxLayout(self.body_container)
            body_layout.setContentsMargins(0, 0, 0, 0)
            self.body_container.setStyleSheet(f"background-color: {rgb_to_hex(c.white)};")
            self.grid.addWidget(self.body_container, 1)
            self.build_body(self.body_container)
            self._apply_engaged_state()

        parent_layout.insertWidget(row, self.panel)
        return self.panel

    def _build_header(self) -> None:
        """Lay out the always-visible header row: a navy bar with white text."""
        from PySide6 import QtCore, QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)

        header = QtWidgets.QWidget()
        header.setFixedHeight(HEADER_HEIGHT)
        header.setStyleSheet(f"background-color: {navy};")
        hl = QtWidgets.QHBoxLayout(header)
        # 5px sides, 3px top/bottom insets the controls so the buttons do not
        # fill the header edge to edge.
        hl.setContentsMargins(5, 3, 5, 3)
        hl.setSpacing(4)

        if self.collapsible:
            self.disclosure_button = QtWidgets.QPushButton(self.disclosure_glyph())
            self.disclosure_button.setFixedWidth(DISCLOSURE_WIDTH)
            self.disclosure_button.setToolTip(self.disclosure_tooltip())
            self.disclosure_button.setStyleSheet(
                f"background-color: {navy}; color: {rgb_to_hex(c.white)}; "
                "border: none; font-size: 10px;"
            )
            self.disclosure_button.clicked.connect(self.toggle)
            hl.addWidget(self.disclosure_button)
        else:
            # Keeps the title in the same column as a collapsible pane's, so
            # titles line up down the window whether or not a pane collapses.
            spacer = QtWidgets.QWidget()
            spacer.setFixedWidth(0)
            hl.addWidget(spacer)

        self.title_label = QtWidgets.QLabel(self.title)
        self.title_label.setStyleSheet(
            f"color: {rgb_to_hex(c.white)}; font-size: 12px; font-weight: bold;"
        )
        self.title_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        hl.addWidget(self.title_label, 1)

        self.build_header_right(hl)

        self.header_grid = header
        self.grid.addWidget(header, 0)

    def accent_button(self, btn: Any) -> None:
        """Style a header button in the NDI Cloud accent.

        Light-blue fill with bold navy text, so the header buttons read as
        one family against the navy bar.
        """
        if btn is None:
            return
        c = cloud_colors()
        btn.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; "
            f"color: {rgb_to_hex(c.dark_blue)}; font-weight: bold;"
        )

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def build_header_right(self, layout: Any) -> None:
        """Add the right-hand header control. Default none."""

    def build_body(self, container: Any) -> None:
        """Populate the pane body. Default none."""

    def right_width(self) -> float:
        """Pixel width of the right header column. Default 0."""
        return 0

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _update_disclosure(self) -> None:
        """Refresh the disclosure glyph and tooltip after a state change."""
        if self.disclosure_button is not None:
            self.disclosure_button.setText(self.disclosure_glyph())
            self.disclosure_button.setToolTip(self.disclosure_tooltip())

    def _apply_engaged_state(self) -> None:
        """Show or hide the body to match ``engaged``."""
        if self.body_container is None:
            return
        self.body_container.setVisible(not (self.collapsible and not self.engaged))

    def __repr__(self) -> str:
        state = "engaged" if self.engaged else "collapsed"
        return f"{type(self).__name__}(title={self.title!r}, {state})"
