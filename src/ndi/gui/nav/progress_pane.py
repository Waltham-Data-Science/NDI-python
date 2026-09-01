"""ndi.gui.nav.progress_pane - the collapsible "Progress" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/progressPane.m``

A collapsible pane that hosts progress bars. Idle it shows a thin empty
body; when a progress-bar window docks into it the bars are drawn here and
the pane grows to fit them, cascading concurrent tasks. The body scrolls, so
a tall cascade never exceeds the pane's maximum height.

THE DOCKING HANDSHAKE
    * the docking app calls :meth:`ProgressPane.adopt_bar_grid` to obtain the
      container it renders bars into, and registers itself as the active app;
    * as bars come and go it calls :meth:`ProgressPane.fit_to_bars` to resize;
    * when the last bar is gone it calls :meth:`ProgressPane.release_bars` to
      return the pane to its idle placeholder.

WHY THE GROWTH IS "QUIET"
``fit_to_bars`` engages the pane through ``set_engaged_quietly`` and asks the
navigator to re-lay out, rather than resizing the window. A background task
starting must not move a window the user did not ask to move; the elastic
panes absorb the change instead. That distinction is the reason the base
class has two engage paths at all, and it is pinned by the tests.
"""

from __future__ import annotations

from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex
from .pane import HEADER_HEIGHT, NavPane

__all__ = ["ProgressPane", "BODY_HEIGHT", "ROW_UNIT_PX", "MAX_BODY_PX"]

#: Pixels of body content when idle.
BODY_HEIGHT = 50

#: Pixels per grid "x" unit. Tall enough that label descenders (p, g, y) are
#: not clipped -- MATLAB's comment, and the reason this is not simply 1.
ROW_UNIT_PX = 32

#: Cap on body pixels. Taller cascades scroll rather than crowding out the
#: other panes.
MAX_BODY_PX = 240


class ProgressPane(NavPane):
    """The "Progress" pane: idle placeholder, or a scrollable cascade of bars."""

    def __init__(self, navigator: Any = None):
        h = HEADER_HEIGHT + BODY_HEIGHT
        super().__init__(
            navigator,
            title="Progress",
            collapsible=True,
            engaged=True,
            min_height=h,
            height=h,
        )
        self.desired_body_px: float = BODY_HEIGHT
        self.active_app: Any = None
        self.bar_grid: Any = None
        self._placeholder: Any = None

    def has_body(self) -> bool:
        return True

    def current_height(self) -> float:
        """Header alone when collapsed, else header plus the wanted body.

        Overrides the base class because this pane's height is CONTENT-driven
        rather than fixed: ``desired_body_px`` follows the docked bars, capped
        so a tall cascade scrolls instead of making the pane unbounded.
        """
        if self.collapsible and not self.engaged:
            return float(HEADER_HEIGHT)
        return float(HEADER_HEIGHT + self.desired_body_px)

    # ------------------------------------------------------------------
    # the docking handshake
    # ------------------------------------------------------------------
    def register_app(self, app: Any) -> None:
        """Record the docked app so later tasks can reuse it."""
        self.active_app = app

    def fit_to_bars(self, total_row_height: float) -> float:
        """Grow the pane to fit TOTAL_ROW_HEIGHT grid "x" units.

        Converts the sum of the bar grid's "x" row heights into pixels, sizes
        the scrollable body to that, and caps the requested pane body at
        :data:`MAX_BODY_PX`.

        Returns the requested body height in pixels, which is what makes the
        arithmetic testable without a display.
        """
        if total_row_height < 0:
            raise ValueError(f"total_row_height must be non-negative; got {total_row_height}.")

        body_px = max(total_row_height * ROW_UNIT_PX, BODY_HEIGHT)

        if self.bar_grid is not None and self.body_container is not None:
            # A fixed-pixel body makes the content scroll once it exceeds the
            # capped visible area, rather than compressing the bars.
            self.body_container.setMinimumHeight(int(body_px))

        # Content-driven: request a capped body height and let the navigator
        # shrink the elastic panes to make room. This never grows the window,
        # so a background task cannot resize it.
        self.desired_body_px = min(body_px, MAX_BODY_PX)
        self.set_engaged_quietly(True)
        if self.navigator is not None:
            self.navigator.layout()
        return self.desired_body_px

    def release_bars(self) -> None:
        """Return the pane to its idle placeholder state.

        Drops the docked app, clears the bar grid, restores the placeholder
        and shrinks back to the idle height. It never deletes the navigator:
        the elastic panes reclaim the space the bars had taken, and the
        window size is unchanged.
        """
        self.active_app = None
        self._clear_body()
        self._show_placeholder()
        self.desired_body_px = BODY_HEIGHT
        if self.navigator is not None:
            self.navigator.layout()

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def adopt_bar_grid(self) -> Any:
        """Prepare and return the container docked bars render into."""
        from PySide6 import QtWidgets

        self._clear_body()

        holder = QtWidgets.QWidget()
        grid = QtWidgets.QVBoxLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self.body_container.layout().addWidget(scroll)
        self.bar_grid = holder
        return holder

    def build_body(self, container: Any) -> None:
        """Idle body: a thin empty placeholder.

        Real content appears only when a progress-bar window docks.
        """
        self._show_placeholder()

    def _clear_body(self) -> None:
        """Delete every child of the pane body container."""
        if self.body_container is None:
            return
        layout = self.body_container.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
        self.bar_grid = None
        self._placeholder = None

    def _show_placeholder(self) -> None:
        """Ensure the idle empty-space label is present."""
        if self.body_container is None:
            return
        if self._placeholder is not None:
            return
        from PySide6 import QtWidgets

        c = cloud_colors()
        self._placeholder = QtWidgets.QLabel("")
        self._placeholder.setStyleSheet(f"background-color: {rgb_to_hex(c.white)};")
        layout = self.body_container.layout()
        if layout is not None:
            layout.addWidget(self._placeholder)
