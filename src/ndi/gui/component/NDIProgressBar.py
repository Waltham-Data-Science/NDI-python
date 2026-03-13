"""NDIProgressBar — A styled progress bar widget.

Mirrors MATLAB: ndi.gui.component.NDIProgressBar

Provides a single progress bar with NDI styling (blue colour scheme),
a text label, and optional time-remaining display.  Uses PySide6.
"""

from __future__ import annotations

from typing import Any

from ndi.gui._qt_helpers import require_qt
from ndi.gui.component.abstract.ProgressMonitor import ProgressMonitor

# Guard the Qt import so the module can still be *imported* without
# PySide6 installed (the error fires only on construction).
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    pass

# NDI colour constants (matching MATLAB NDIProgressBar)
_BG_COLOR = "#4472C4"  # background blue
_FG_COLOR = "#2F5597"  # foreground dark-blue


class NDIProgressBar(ProgressMonitor):
    """A single progress bar widget with NDI styling.

    Parameters
    ----------
    **kwargs
        Property overrides accepted by :class:`ProgressMonitor` plus:

        * ``Value`` (float, 0–1) — initial progress fraction.
        * ``Message`` (str) — initial status text.
        * ``Size`` (tuple[int, int]) — ``(width, height)`` in pixels.
        * ``Location`` (tuple[int, int]) — ``(x, y)`` position.
        * ``parent`` — optional parent QWidget.
    """

    def __init__(self, **kwargs: Any) -> None:
        require_qt()
        super().__init__(**kwargs)

        self.Value: float = kwargs.get("Value", 0.0)
        self._message_text: str = kwargs.get("Message", "")
        self.Size: tuple[int, int] = kwargs.get("Size", (400, 40))
        self.Location: tuple[int, int] = kwargs.get("Location", (100, 100))

        parent = kwargs.get("parent", None)

        # Build the widget hierarchy
        self._frame = QtWidgets.QFrame(parent)
        self._frame.setFixedSize(self.Size[0], self.Size[1])
        self._frame.move(self.Location[0], self.Location[1])

        layout = QtWidgets.QVBoxLayout(self._frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._label = QtWidgets.QLabel(self._message_text)
        self._label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._label)

        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setValue(int(self.Value * 1000))
        self._bar.setTextVisible(True)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background-color: {_BG_COLOR}; border: none; "
            f"border-radius: 4px; text-align: center; color: white; }}"
            f"QProgressBar::chunk {{ background-color: {_FG_COLOR}; "
            f"border-radius: 4px; }}"
        )
        layout.addWidget(self._bar)

    # -- Widget access ----------------------------------------------------

    @property
    def widget(self) -> QtWidgets.QFrame:
        """The root QFrame containing the progress bar."""
        return self._frame

    # -- ProgressMonitor overrides ----------------------------------------

    def updateProgressDisplay(self) -> None:
        """Update the visual bar to reflect current progress."""
        self.Value = self.getProgressValue()
        self._bar.setValue(int(self.Value * 1000))
        pct = self.Value * 100
        self._bar.setFormat(f"{pct:.0f}%")

    def updateMessage(self, message: str) -> None:
        """Update the label text."""
        self._message_text = message
        self._label.setText(self.formatMessage(message))

    def finish(self) -> None:
        """Set bar to 100 % and show completion text."""
        self.Value = 1.0
        self._bar.setValue(1000)
        self._bar.setFormat("100%")
        self._label.setText("Complete")
