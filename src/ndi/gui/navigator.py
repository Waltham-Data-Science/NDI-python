"""ndi.gui.navigator - a small, resizable NDI navigator window.

MATLAB counterpart: ``src/ndi/+ndi/+gui/navigator.m``

A compact window built from a vertical stack of panes. Resizable, but never
smaller than its content requires and never narrower than
:data:`~ndi.gui.nav.layout.MIN_WIDTH`.

The pane stack is object-oriented: every pane is an
:class:`~ndi.gui.nav.pane.NavPane` subclass. A new pane is added by writing a
subclass -- choosing collapsible or not, resizable or not, a minimum engaged
height and a title -- and appending it in :meth:`Navigator.build_panes`.

WHAT THIS CLASS IS, AND IS NOT
All the layout arithmetic lives in :mod:`ndi.gui.nav.layout`, which has no
Qt in it and is tested exactly. This class owns the window, the widgets and
the mouse handling, and calls into that module for every number. Keeping the
split sharp is the only way this part of the port is checkable at all: a
window that leaves a gap at the bottom, or a pane that will not drag down to
its minimum, is a wrong number rather than a raised error.

THE PANE STACK
NDI, NDI Cloud, Datasets, Progress -- MATLAB's stack, complete. Datasets is
the elastic pane, so content changes are absorbed by resizing it rather than
by resizing the window; the panes below it keep hugging the bottom edge.
"""

from __future__ import annotations

from typing import Any

from .cloud_colors import cloud_colors, rgb_to_hex
from .nav import layout as nav_layout
from .nav.cloud_pane import CloudPane
from .nav.datasets_pane import DatasetsPane
from .nav.ndi_pane import NdiPane
from .nav.progress_pane import ProgressPane

__all__ = ["Navigator", "DEFAULT_POSITION"]

#: Default window geometry, ``(x, y, width, height)``, as MATLAB has it.
DEFAULT_POSITION = (100, 100, 300, 500)

#: Object name on the window, so an open navigator can be found again --
#: how a progress-bar window discovers a navigator to dock into.
WINDOW_TAG = "ndiNavigator"


class Navigator:
    """The NDI navigator window."""

    def __init__(
        self,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        visible: bool = True,
        build: bool = True,
    ):
        x, y, w, h = position
        self.position = (
            x,
            y,
            max(w, nav_layout.MIN_WIDTH),
            max(h, nav_layout.MIN_HEIGHT),
        )
        self.panes: list[Any] = []
        self.figure: Any = None
        self.root_layout: Any = None

        #: Guards against a resize triggered from inside a layout re-entering
        #: it. Without it, setting the window height inside layout() calls
        #: the resize handler, which calls layout() again.
        self._busy = False
        self._dragging = False
        self._drag_last_y = 0.0
        #: Alert boxes currently on screen. A shown QMessageBox with no
        #: reference is collected and disappears, so they are held here and
        #: dropped again when dismissed.
        self._alert_boxes: list[Any] = []

        #: The preferences editor opened from the Prefs button, held so the
        #: window is not garbage collected while the user is looking at it.
        self._preferences_editor: Any = None

        if build:
            self.build()

    # ------------------------------------------------------------------
    # geometry, in terms of the pure layout module
    # ------------------------------------------------------------------
    @property
    def figure_height(self) -> float:
        """The window height, from the widget when built, else the request."""
        if self.figure is not None:
            return float(self.figure.height())
        return float(self.position[3])

    def min_figure_height(self) -> float:
        """The smallest height that fits the current pane stack."""
        return nav_layout.min_figure_height(self.panes)

    def layout(self) -> list[float]:
        """Distribute the window height across the pane rows.

        Returns the row heights, which is what makes the result checkable
        without a display. Re-entrant calls are dropped: resizing the window
        from in here would otherwise call the resize handler, which calls
        this again.
        """
        if self._busy or not self.panes:
            return []

        heights, new_height = nav_layout.distribute(self.panes, self.figure_height)

        if new_height is not None:
            self._set_figure_height(new_height)

        for pane, h in zip(self.panes, heights):
            pane.set_rendered_height(h)
            # `panel` is read with getattr because a pane is duck-typed here
            # the same way it is in the layout module: everything needed to
            # compute a height, and a widget only if one has been built.
            panel = getattr(pane, "panel", None)
            if panel is not None:
                panel.setFixedHeight(int(round(h)))
        return heights

    def pane_toggled(self, pane: Any) -> None:
        """Resize the window after a user collapse or expand.

        This is the STRUCTURAL path: the window grows by the body just added
        or shrinks by the body just removed. Content-driven changes go
        through ``set_engaged_quietly`` and :meth:`layout` instead, and must
        not reach here -- a window that jumps because a background task
        started is a window the user did not ask to move.
        """
        self._resize_figure_by(nav_layout.toggle_delta(pane))
        self.layout()

    def refresh(self) -> None:
        """Ask every pane to re-read its model state."""
        for pane in self.panes:
            pane.refresh()

    # ------------------------------------------------------------------
    # pane lookup
    # ------------------------------------------------------------------
    def progress_pane_handle(self) -> Any | None:
        """The progress pane in this stack, or None."""
        return self._pane_of_type(ProgressPane)

    def datasets_pane_handle(self) -> Any | None:
        """The datasets pane in this stack, or None.

        Returns None until the datasets pane is ported -- there is simply no
        such pane in the stack yet. Callers must handle that: the cloud
        pane's bulk status check, for one, has to say "no datasets pane is
        available" rather than raising. Written as a lookup over the stack
        rather than a hardcoded None so it starts working the moment the
        pane is appended in build_panes.
        """
        for pane in self.panes:
            if type(pane).__name__ == "DatasetsPane":
                return pane
        return None

    def _pane_of_type(self, cls: type) -> Any | None:
        for pane in self.panes:
            if isinstance(pane, cls):
                return pane
        return None

    # ------------------------------------------------------------------
    # actions the panes call back into
    # ------------------------------------------------------------------
    def open_preferences(self) -> Any | None:
        """Open the NDI preferences editor (MATLAB's ``ndi.gui.preferencesEditor``).

        Returns the editor, or None when Qt is missing -- which is reported
        on the window rather than raised, because this runs off a button
        click and an exception there would go nowhere the user can see.

        An editor already up is raised rather than duplicated, and the
        handle is HELD: a Qt window with no Python reference is garbage
        collected and vanishes, where MATLAB's figure stays up on its own.
        """
        editor = self._preferences_editor
        if editor is not None and editor.is_open():
            editor.show()
            return editor

        from .preferences_editor import PreferencesEditor

        try:
            editor = PreferencesEditor()
        except ImportError as exc:  # PySide6 missing
            self.alert(str(exc), "Preferences", success=False)
            return None
        self._preferences_editor = editor
        editor.show()
        return editor

    def alert(self, message: str, title: str, *, success: bool = True) -> Any:
        """Show a message on the navigator window, WITHOUT blocking.

        MATLAB's ``uialert`` displays the dialog and returns immediately --
        it is modal to the figure, not to the caller. So this uses ``show()``
        rather than ``exec()``: with ``exec()`` an action that reports its
        outcome would stop dead until someone clicked OK, and a caller that
        alerts and then carries on (the cloud pane's bulk check, the datasets
        pane's ingest) would behave differently in the two languages. It also
        deadlocks anything running without a user, tests included.

        The box is kept on ``self._alert_boxes`` because a shown, unreferenced
        QMessageBox is garbage-collected and vanishes off the screen.

        Returns the box, so a caller (or a test) can inspect or close it.
        """
        if self.figure is None:
            return None
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(
            QtWidgets.QMessageBox.Icon.Information
            if success
            else QtWidgets.QMessageBox.Icon.Warning
        )
        box.setAttribute(QtCore_WA_DeleteOnClose(), True)
        box.finished.connect(lambda _=0, b=box: self._forget_alert(b))
        self._alert_boxes.append(box)
        box.show()
        return box

    def _forget_alert(self, box: Any) -> None:
        """Drop a dismissed alert so the list does not grow without bound."""
        if box in self._alert_boxes:
            self._alert_boxes.remove(box)

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Create the window and its pane stack."""
        from ._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        x, y, w, h = self.position

        self.figure = _NavigatorWidget(self)
        self.figure.setWindowTitle("NDI Navigator")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {rgb_to_hex(c.dark_blue)};")
        self.figure.setMinimumWidth(nav_layout.MIN_WIDTH)
        # Mouse-tracking so hover events fire without a button held; this is
        # how the grip cursor changes when the pointer crosses the edge.
        self.figure.setMouseTracking(True)
        # Back-reference on the widget, mirroring MATLAB's guidata(fig, obj),
        # so find_open() can recover the navigator from a widget handle.
        self.figure.setProperty("_ndi_navigator", self)

        self.root_layout = QtWidgets.QVBoxLayout(self.figure)
        self.root_layout.setContentsMargins(
            nav_layout.PAD, nav_layout.PAD, nav_layout.PAD, nav_layout.PAD
        )
        self.root_layout.setSpacing(nav_layout.SPACING)

        self.build_panes()
        self.layout()
        return self.figure

    def build_panes(self) -> None:
        """Instantiate the pane stack, top to bottom.

        NDI, NDI Cloud, Datasets, Progress -- MATLAB's order, now complete.
        Progress stays last so it goes on hugging the bottom edge, and
        Datasets is the elastic pane that absorbs the leftover height.
        """
        self.panes = [
            NdiPane(self),
            CloudPane(self),
            DatasetsPane(self),
            ProgressPane(self),
        ]
        for row, pane in enumerate(self.panes):
            pane.build(self.root_layout, row)

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    # ------------------------------------------------------------------
    # window sizing
    # ------------------------------------------------------------------
    def _resize_figure_by(self, delta: float) -> float:
        """Change the window height by DELTA, never below the minimum."""
        new_height = max(self.figure_height + delta, self.min_figure_height())
        self._set_figure_height(new_height)
        return new_height

    def _set_figure_height(self, new_height: float) -> None:
        """Set the window height, keeping the TOP edge fixed.

        Top-anchored because a window that grows downward stays where the
        user put it; growing upward would walk the title bar off the screen
        over repeated expansions.
        """
        new_height = max(new_height, self.min_figure_height())
        x, y, w, h = self.position
        top = y + h
        self.position = (x, top - new_height, w, new_height)

        if self.figure is None:
            return
        self._busy = True
        try:
            self.figure.setGeometry(
                int(self.position[0]),
                int(self.position[1]),
                int(self.position[2]),
                int(new_height),
            )
        finally:
            self._busy = False

    def enforce_min_size(self) -> tuple[float, float]:
        """Clamp the window to the minimum size, keeping the top-left fixed.

        Returns the (width, height) in force afterwards.
        """
        x, y, w, h = self.position
        new_w = max(w, nav_layout.MIN_WIDTH)
        new_h = max(h, self.min_figure_height())
        if new_w != w or new_h != h:
            top = y + h
            self.position = (x, top - new_h, new_w, new_h)
            if self.figure is not None:
                self._busy = True
                try:
                    self.figure.setGeometry(int(x), int(top - new_h), int(new_w), int(new_h))
                finally:
                    self._busy = False
        return new_w, new_h

    def on_figure_resized(self) -> None:
        """Handle a user resize of the window."""
        if self._busy:
            return
        if self.figure is not None:
            geo = self.figure.geometry()
            self.position = (geo.x(), geo.y(), geo.width(), geo.height())
        self.enforce_min_size()
        self.layout()

    # ------------------------------------------------------------------
    # the resize grip on the elastic pane's lower edge
    # ------------------------------------------------------------------
    def grip_edge_y(self) -> float | None:
        """Y of the draggable edge, from the window bottom, or None."""
        index = nav_layout.first_elastic_index(self.panes)
        if index is None:
            return None
        return nav_layout.pane_bottom_edge(self.panes, index, self.figure_height)

    def is_on_grip(self, y_from_bottom: float) -> bool:
        """Whether a pointer Y (from the window bottom) is on the grip."""
        edge = self.grip_edge_y()
        if edge is None:
            return False
        return abs(y_from_bottom - edge) <= nav_layout.GRIP_PIXELS

    def begin_drag(self, pointer_y: float) -> bool:
        """Start a grip drag if the pointer is on the edge."""
        if self._dragging or not self.is_on_grip(pointer_y):
            return False
        self._dragging = True
        self._drag_last_y = pointer_y
        return True

    def drag_to(self, pointer_y: float) -> float | None:
        """Continue a drag. Returns the new window height, or None.

        Screen coordinates have Y increasing upward, so dragging the grip
        DOWN is a negative delta and must GROW the window -- the elastic
        pane absorbs the change while the bottom pane keeps hugging the
        bottom. Getting that sign backwards makes the window shrink when the
        user pulls down, which is the kind of thing that reads as "the drag
        is broken" rather than as an inverted constant.
        """
        if not self._dragging:
            return None
        dy = pointer_y - self._drag_last_y
        self._drag_last_y = pointer_y
        if dy == 0:
            return None
        height = self._resize_figure_by(-dy)
        self.layout()
        return height

    def end_drag(self) -> None:
        self._dragging = False

    # ------------------------------------------------------------------
    # Qt event dispatch (called by _NavigatorWidget)
    # ------------------------------------------------------------------
    def _on_button_down(self, y_from_bottom: float) -> None:
        """Begin a grip drag if the click is on the edge."""
        self.begin_drag(y_from_bottom)

    def _on_mouse_motion(self, y_from_bottom: float) -> None:
        """Drive a drag in progress, or update the edge cursor on hover.

        When a drag is in progress the drag delta is applied; otherwise the
        widget cursor becomes a hand when the pointer is on the grip and an
        arrow otherwise -- MATLAB does the same, and without it the drag
        region is invisible to the user.
        """
        if self._dragging:
            self.drag_to(y_from_bottom)
            return
        if self.figure is None:
            return
        from PySide6 import QtCore

        cursor_shape = (
            QtCore.Qt.CursorShape.SizeVerCursor
            if self.is_on_grip(y_from_bottom)
            else QtCore.Qt.CursorShape.ArrowCursor
        )
        self.figure.setCursor(cursor_shape)

    def _on_button_up(self) -> None:
        """End a grip drag, restoring the arrow cursor."""
        if self._dragging:
            self.end_drag()
            if self.figure is not None:
                from PySide6 import QtCore

                self.figure.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------
    # discovery of open navigators
    # ------------------------------------------------------------------
    @staticmethod
    def find_open() -> list[Navigator]:
        """Return open Navigator instances, newest last.

        Mirrors MATLAB's ``ndi.gui.navigator.findOpen``. Searches the running
        Qt application's top-level widgets for those tagged with the
        navigator ``WINDOW_TAG`` and returns their attached Navigator
        objects. Returns an empty list when no Qt application exists yet or
        when no navigator is open, so callers can use it in a ``for`` loop
        without an existence check.

        This is how :class:`ndi.gui.component.ProgressBarWindow` discovers a
        navigator to dock progress bars into, without a caller passing one
        in.
        """
        try:
            from PySide6 import QtWidgets
        except ImportError:
            return []

        app = QtWidgets.QApplication.instance()
        if app is None:
            return []

        found: list[Navigator] = []
        for widget in app.topLevelWidgets():
            if widget.objectName() != WINDOW_TAG:
                continue
            nav = widget.property("_ndi_navigator")
            if isinstance(nav, Navigator):
                found.append(nav)
        return found

    def __repr__(self) -> str:
        return f"Navigator(panes={len(self.panes)}, height={self.figure_height:g})"


def _NavigatorWidget(navigator: Navigator) -> Any:
    """Build a QWidget subclass whose events dispatch to NAVIGATOR.

    Defined as a factory rather than at module scope so this module keeps
    importing without PySide6 installed -- every Qt symbol here is the same
    lazy pattern used everywhere else in this file.

    Y is converted from Qt's top-anchored coordinate to the bottom-anchored
    coordinate the grip API expects, because MATLAB's figure coordinates are
    bottom-anchored and the layout math is written in those terms.
    """
    from PySide6 import QtWidgets

    class _Widget(QtWidgets.QWidget):
        def __init__(self, nav: Navigator):
            super().__init__()
            self._nav = nav

        def resizeEvent(self, event):  # noqa: N802 - Qt override name
            super().resizeEvent(event)
            self._nav.on_figure_resized()

        def mousePressEvent(self, event):  # noqa: N802
            y_from_bottom = float(self.height() - event.position().y())
            self._nav._on_button_down(y_from_bottom)
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):  # noqa: N802
            y_from_bottom = float(self.height() - event.position().y())
            self._nav._on_mouse_motion(y_from_bottom)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):  # noqa: N802
            self._nav._on_button_up()
            super().mouseReleaseEvent(event)

    return _Widget(navigator)


def QtCore_WA_DeleteOnClose() -> Any:
    """Qt.WidgetAttribute.WA_DeleteOnClose, imported lazily.

    Named as a function so this module still imports without Qt installed --
    the same reason every other Qt import here is inside a method.
    """
    from PySide6 import QtCore

    return QtCore.Qt.WidgetAttribute.WA_DeleteOnClose
