"""Icon — Draggable visual icon for the Lab view.

Mirrors MATLAB: ndi.gui.Icon

Represents a subject, probe, or DAQ device as a coloured rectangle with
an image and a connection terminal in the QGraphicsScene.
"""

from __future__ import annotations

from typing import Any

from ndi.gui._qt_helpers import require_qt

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    pass


class Icon:
    """Graphical icon shown in the :class:`Lab` view.

    Parameters
    ----------
    src : Lab
        The parent Lab instance.
    length : int
        Sequence index (used for initial positioning).
    elem : Any
        The NDI element (subject doc, probe, or DAQ) this icon represents.
    hShift : float
        Horizontal offset.
    vShift : float
        Vertical offset.
    w : float
        Width in scene units.
    h : float
        Height in scene units.
    color : tuple[float, float, float]
        RGB colour.
    """

    # Scale factor from scene units to pixels
    _UNIT = 40

    def __init__(
        self,
        src: Any,  # Lab
        length: int,
        elem: Any,
        hShift: float,
        vShift: float,
        w: float,
        h: float,
        color: tuple[float, float, float],
    ) -> None:
        require_qt()

        self.elem = elem
        self.src = src
        self.w = w
        self.h = h
        self.x = 8 * length + hShift
        self.y = vShift
        self.c = color
        self.active: int = 1
        self.tag: str = str(
            len(getattr(src, "subjects", []))
            + len(getattr(src, "probes", []))
            + len(getattr(src, "DAQs", []))
            + 1
        )

        u = self._UNIT
        r, g, b = (int(c * 255) for c in color)
        pen = QtGui.QPen(QtGui.QColor(r, g, b), 2)

        # Rectangle border
        self.rect = src.scene.addRect(
            self.x * u,
            self.y * u,
            w * u,
            h * u,
            pen,
            QtGui.QBrush(QtCore.Qt.GlobalColor.white),
        )
        self.rect.setZValue(1)

        # Placeholder image (filled rectangle)
        self.img = src.scene.addRect(
            self.x * u + 2,
            self.y * u + 2,
            w * u - 4,
            h * u - 4,
            QtGui.QPen(QtCore.Qt.PenStyle.NoPen),
            QtGui.QBrush(QtGui.QColor(220, 220, 220)),
        )
        self.img.setZValue(2)

        # Connection terminal (small circle at top-right)
        term_r = 6
        self.term = src.scene.addEllipse(
            (self.x + w) * u - term_r,
            (self.y + h) * u - term_r,
            term_r * 2,
            term_r * 2,
            pen,
            QtGui.QBrush(QtCore.Qt.GlobalColor.white),
        )
        self.term.setZValue(3)

        # DAQs (orange) start inactive
        if color == (1, 0.6, 0):
            self.active = 0
            self.term.setVisible(False)

    def upload(self) -> None:
        """Open a file dialog to select a new image for this icon."""
        require_qt()
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg)",
        )
        if filepath:
            pixmap = QtGui.QPixmap(filepath)
            if not pixmap.isNull():
                # Replace the placeholder rect with the actual image
                u = self._UNIT
                self.src.scene.removeItem(self.img)
                self.img = self.src.scene.addPixmap(
                    pixmap.scaled(
                        int(self.w * u - 4),
                        int(self.h * u - 4),
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    )
                )
                self.img.setPos(self.x * u + 2, self.y * u + 2)
                self.img.setZValue(2)

    def setPos(self, x: float, y: float) -> None:
        """Move icon to new scene-unit position."""
        u = self._UNIT
        dx = (x - self.x) * u
        dy = (y - self.y) * u
        self.x = x
        self.y = y
        self.rect.moveBy(dx, dy)
        self.img.moveBy(dx, dy)
        self.term.moveBy(dx, dy)
