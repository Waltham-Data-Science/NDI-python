"""centerFigure — Center a window on screen or relative to another widget.

Mirrors MATLAB: ndi.gui.utility.centerFigure
"""

from __future__ import annotations

from ndi.gui._qt_helpers import require_qt

try:
    from PySide6 import QtWidgets
except ImportError:
    pass


def centerFigure(
    figureHandle: QtWidgets.QWidget,
    referencePosition: tuple[int, int, int, int] | QtWidgets.QWidget | None = None,
    offset: tuple[int, int] = (0, 0),
) -> None:
    """Center *figureHandle* on screen or relative to a reference.

    Parameters
    ----------
    figureHandle : QWidget
        The widget / window to reposition.
    referencePosition : tuple | QWidget | None
        ``(x, y, width, height)`` rectangle, another QWidget to centre
        within, or ``None`` to centre on the primary screen.
    offset : tuple[int, int]
        ``(dx, dy)`` pixel offset applied after centring.
    """
    require_qt()

    # Determine reference rectangle
    if referencePosition is None:
        screen = QtWidgets.QApplication.primaryScreen()
        geom = screen.availableGeometry()
        ref_x, ref_y = geom.x(), geom.y()
        ref_w, ref_h = geom.width(), geom.height()
    elif isinstance(referencePosition, QtWidgets.QWidget):
        g = referencePosition.geometry()
        ref_x, ref_y = g.x(), g.y()
        ref_w, ref_h = g.width(), g.height()
    else:
        ref_x, ref_y, ref_w, ref_h = referencePosition

    fig_w = figureHandle.width()
    fig_h = figureHandle.height()

    new_x = ref_x + (ref_w - fig_w) // 2 + offset[0]
    new_y = ref_y + (ref_h - fig_h) // 2 + offset[1]

    figureHandle.move(new_x, new_y)
