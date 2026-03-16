"""ndi_gui_Lab — Experiment view with draggable icons and connection wires.

Mirrors MATLAB: ndi.gui.ndi_gui_Lab

Provides a graphical canvas (QGraphicsScene) where subjects, probes,
and DAQ devices are displayed as draggable icons.  Connections between
them are rendered as wire paths.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ndi.gui._qt_helpers import require_qt
from ndi.gui.icon import ndi_gui_Icon

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    pass

_UNIT = ndi_gui_Icon._UNIT


class ndi_gui_Lab:
    """Experiment / lab view widget.

    Manages a :class:`QGraphicsScene` containing subject, probe, and DAQ
    icons with draggable positioning and inter-icon connection wires.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        require_qt()

        self.editable: bool = False
        self.subjects: list[ndi_gui_Icon] = []
        self.probes: list[ndi_gui_Icon] = []
        self.DAQs: list[ndi_gui_Icon] = []
        self.drag: ndi_gui_Icon | None = None
        self.dragPt: tuple[float, float] | None = None
        self.moved: bool = False
        self.connects: np.ndarray = np.zeros((0, 0), dtype=int)
        self.transmitting: bool = True
        self._row: int | None = None
        self._wires: list[Any] = []

        # Scene + view
        self.scene = QtWidgets.QGraphicsScene()
        self.window = QtWidgets.QGraphicsView(self.scene, parent)
        self.window.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.window.setSceneRect(0, 0, 24 * _UNIT, 16 * _UNIT)
        self.window.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)

        # Background
        self.scene.setBackgroundBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.white))

        # Detail panel
        self.panel = QtWidgets.QFrame(parent)
        self.panel.setStyleSheet("background-color: white;")
        panel_layout = QtWidgets.QVBoxLayout(self.panel)
        self._panel_name = QtWidgets.QLabel()
        self._panel_name.setStyleSheet("font-weight: bold;")
        panel_layout.addWidget(self._panel_name)
        self._panel_info = QtWidgets.QTextEdit()
        self._panel_info.setReadOnly(True)
        panel_layout.addWidget(self._panel_info)
        self._upload_btn = QtWidgets.QPushButton("Upload Image")
        panel_layout.addWidget(self._upload_btn)
        self.info: list[Any] = []

        # Edit toggle
        self._edit_btn = QtWidgets.QPushButton("EDIT")
        self._edit_btn.setCheckable(True)
        self._edit_btn.clicked.connect(self.editCallback)

        # Zoom buttons
        self._zoom_in_btn = QtWidgets.QPushButton("+")
        self._zoom_in_btn.setFixedSize(28, 28)
        self._zoom_in_btn.clicked.connect(lambda: self.setZoom(2.0 / 3.0))
        self._zoom_out_btn = QtWidgets.QPushButton("-")
        self._zoom_out_btn.setFixedSize(28, 28)
        self._zoom_out_btn.clicked.connect(lambda: self.setZoom(3.0 / 2.0))

    # -- Public API -------------------------------------------------------

    def addSubject(self, subj: list[Any]) -> None:
        """Add subject icons (blue) to the view."""
        for s in subj:
            icon = ndi_gui_Icon(self, len(self.subjects), s, 1, 1, 4, 3, (0.2, 0.4, 1.0))
            self.subjects.append(icon)
        self._rebuild_connects()

    def addProbe(self, prob: list[Any]) -> None:
        """Add probe icons (green) to the view."""
        for p in prob:
            icon = ndi_gui_Icon(self, len(self.probes), p, 6, 6, 2, 3, (0.0, 0.6, 0.0))
            self.probes.append(icon)
        self._rebuild_connects()

    def addDAQ(self, daq: list[Any]) -> None:
        """Add DAQ icons (orange) to the view."""
        for d in daq:
            icon = ndi_gui_Icon(self, len(self.DAQs), d, 9, 12, 4, 2, (1.0, 0.6, 0.0))
            self.DAQs.append(icon)
        self._rebuild_connects()

    def editCallback(self) -> None:
        """Toggle edit mode."""
        self.editable = not self.editable
        self.grid()

    def grid(self) -> None:
        """Show or hide the background grid."""
        # Grid is implicit in the scene — this is a visual toggle
        if self.editable:
            pen = QtGui.QPen(QtGui.QColor(200, 200, 200), 0.5)
            for x in range(0, 25 * _UNIT, _UNIT):
                self.scene.addLine(x, 0, x, 16 * _UNIT, pen).setZValue(-1)
            for y in range(0, 17 * _UNIT, _UNIT):
                self.scene.addLine(0, y, 24 * _UNIT, y, pen).setZValue(-1)

    def details(self, src: ndi_gui_Icon) -> None:
        """Show detail panel for the given icon."""
        c = src.c
        elem = src.elem
        if c == (0.2, 0.4, 1.0):
            # ndi_subject
            if isinstance(elem, list) and len(elem) > 0:
                elem = elem[0]
            dp = getattr(elem, "document_properties", {})
            dp_dict = dp if isinstance(dp, dict) else getattr(dp, "__dict__", {})
            subj = dp_dict.get("subject", {})
            name = (
                subj.get("local_identifier", "Not Found") if isinstance(subj, dict) else "Not Found"
            )
            desc = subj.get("description", "") if isinstance(subj, dict) else ""
            kind = "ndi_subject"
            ident = name
        elif c == (0.0, 0.6, 0.0):
            # ndi_probe
            name = getattr(elem, "name", "")
            kind = getattr(elem, "type", "ndi_probe")
            ident = getattr(elem, "identifier", "")
            desc = ""
        else:
            # DAQ
            name = getattr(elem, "name", "")
            kind = "DAQ"
            ident = getattr(elem, "identifier", "")
            desc = ""

        self._panel_name.setText(f"Name: {name}")
        self._panel_info.setPlainText(f"Type: {kind}\nID: {ident}\nDescription: {desc}")

        # Reconnect upload button
        try:
            self._upload_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._upload_btn.clicked.connect(src.upload)

    def setZoom(self, z: float) -> None:
        """Zoom the view by factor *z*."""
        self.window.scale(1.0 / z, 1.0 / z)

    def move(self, scene_x: float, scene_y: float) -> None:
        """Handle mouse-move for drag operations.

        Parameters
        ----------
        scene_x, scene_y : float
            Mouse position in scene coordinates.
        """
        if not self.editable or self.drag is None:
            return

        new_x = scene_x / _UNIT
        new_y = scene_y / _UNIT

        if self.dragPt is not None:
            dx = new_x - self.dragPt[0]
            dy = new_y - self.dragPt[1]
            if abs(dx) > 0.1 or abs(dy) > 0.1:
                self.moved = True
                self.drag.setPos(self.drag.x + dx, self.drag.y + dy)
                self.dragPt = (new_x, new_y)
                self.updateConnections()

    def connect(self, src: ndi_gui_Icon | None = None) -> None:
        """Create/complete a connection using a two-click pattern."""
        if src is None:
            return
        all_icons = self.subjects + self.probes + self.DAQs
        try:
            ind = all_icons.index(src)
        except ValueError:
            return

        if self.transmitting:
            self._row = ind
        elif self._row is not None and self._row != ind:
            self.connects[self._row, ind] += 1
            self.updateConnections()
        self.transmitting = not self.transmitting

    def updateConnections(self) -> None:
        """Redraw all connection wires from the adjacency matrix."""
        # Remove existing wires
        for item in self._wires:
            self.scene.removeItem(item)
        self._wires.clear()

        elems = self.subjects + self.probes + self.DAQs
        n = len(elems)
        if n == 0:
            return

        pen = QtGui.QPen(QtGui.QColor(255, 0, 0), 2)
        for r in range(n):
            for c in range(n):
                count = int(self.connects[r, c])
                if count <= 0:
                    continue
                out_icon = elems[r]
                in_icon = elems[c]
                for _k in range(count):
                    # Simple straight-line connection
                    x1 = (out_icon.x + out_icon.w / 2) * _UNIT
                    y1 = (out_icon.y + out_icon.h) * _UNIT
                    x2 = (in_icon.x + in_icon.w / 2) * _UNIT
                    y2 = in_icon.y * _UNIT
                    mid_y = (y1 + y2) / 2

                    line1 = self.scene.addLine(x1, y1, x1, mid_y, pen)
                    line2 = self.scene.addLine(x1, mid_y, x2, mid_y, pen)
                    line3 = self.scene.addLine(x2, mid_y, x2, y2, pen)
                    self._wires.extend([line1, line2, line3])

    def cut(self, src: Any) -> None:
        """Remove a connection wire (edit mode only)."""
        if not self.editable:
            return
        # Parse the wire tag to find the connection to remove
        tag = getattr(src, "tag", "")
        if "_" in tag:
            parts = tag.split("_")
            try:
                out_idx = int(parts[0])
                in_idx = int(parts[1])
                self.connects[out_idx, in_idx] = max(0, self.connects[out_idx, in_idx] - 1)
                self.updateConnections()
            except (ValueError, IndexError):
                pass

    def buttons(self) -> None:
        """Update terminal button visibility and colour based on active state."""
        for icon in self.subjects + self.probes + self.DAQs:
            if icon.active == 0:
                icon.term.setVisible(False)
            else:
                icon.term.setVisible(True)

    # -- Private ----------------------------------------------------------

    def _rebuild_connects(self) -> None:
        n = len(self.subjects) + len(self.probes) + len(self.DAQs)
        old = self.connects
        self.connects = np.zeros((n, n), dtype=int)
        m = min(old.shape[0], n)
        self.connects[:m, :m] = old[:m, :m]
