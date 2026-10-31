"""ndi_gui_component_ProgressBarWindow — Multi-bar progress window.

Mirrors MATLAB: ndi.gui.component.ndi_gui_component_ProgressBarWindow

Creates and manages a PySide6 window that can display one or more
progress bars.  Bars can be added, updated, and removed dynamically.
Each bar shows a label, a coloured progress bar, a percentage, an
estimated-time-remaining label, and a close button.

SILENT (HEADLESS) MODE
Mirrors MATLAB's silent mode. Building a Qt window needs PySide6 and a usable
display; without a display Qt typically aborts the whole process, which no
try/except can catch. So, as in MATLAB, the window runs silently whenever it
detects a headless context: no widgets are created and every graphics
touchpoint is skipped, while the bookkeeping (addBar, updateBar, removeBar,
getBarNum, getState, timeouts) behaves exactly as it does with a window. The
decision is made once per construction by resolveSilentMode, in this order:
the ``Silent`` argument, the process-wide silentModeDefault, then isHeadless.

CROSS-LANGUAGE NAMING
Methods mirroring MATLAB keep MATLAB's exact name and also carry a
snake_case alias bound to the same function -- one method under two names,
so neither a ported MATLAB script nor idiomatic Python has to remember which
spelling a given method happens to have.
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
import warnings

from ndi.gui._qt_helpers import _QT_AVAILABLE, get_or_create_app, require_qt

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    pass

# Module-level registry of existing windows (mirrors MATLAB findall)
_ACTIVE_WINDOWS: dict[str, ndi_gui_component_ProgressBarWindow] = {}

# Process-wide silent-mode override (mirrors MATLAB's persistent variable in
# silentModeDefault). None means "decide by detection".
_SILENT_OVERRIDE: bool | None = None

# Sentinel distinguishing "no argument" from None in silentModeDefault.
_NOT_GIVEN = object()


class _BarRecord:
    """Internal bookkeeping for one progress bar row."""

    __slots__ = (
        "Tag",
        "Progress",
        "State",
        "Auto",
        "label_widget",
        "timer_widget",
        "bar_widget",
        "pct_widget",
        "btn_widget",
        "color",
        "clock_start",
        "clock_last",
        # Per-bar timeout in seconds (MATLAB addBar's Timeout). None inherits
        # the window's Timeout; math.inf never times out.
        "Timeout",
        # The row's container widget, so removeBar can take the whole row
        # out. It is in __slots__ because addBar assigns it: without it,
        # every addBar raised AttributeError and no bar could be drawn.
        "_frame",
    )

    def __init__(
        self,
        tag: str,
        auto: bool,
        color: tuple[float, float, float],
        timeout: float | None = None,
    ):
        self.Tag = tag
        self.Timeout = timeout
        self.Progress: float = 0.0
        self.State: str = "Open"
        self.Auto = auto
        self.color = color
        self.clock_start: float = time.monotonic()
        self.clock_last: float = self.clock_start

        # Widget handles (set later)
        self.label_widget: QtWidgets.QLabel | None = None
        self.timer_widget: QtWidgets.QLabel | None = None
        self.bar_widget: QtWidgets.QProgressBar | None = None
        self.pct_widget: QtWidgets.QLabel | None = None
        self.btn_widget: QtWidgets.QPushButton | None = None
        self._frame: QtWidgets.QFrame | None = None


class ndi_gui_component_ProgressBarWindow:
    """Multi-bar progress window using PySide6.

    Parameters
    ----------
    title : str
        Window title.
    Overwrite : bool
        If ``True``, close any existing window with the same *title*.
    AutoDelete : bool
        If ``True``, auto-close the window when all bars are closed.
    Silent : bool | None
        Forces silent (headless) mode on or off for this window, bypassing
        detection. ``None`` (the default) decides automatically -- see
        :meth:`resolveSilentMode`. In silent mode no Qt widgets are created
        (PySide6 is not even required) and the bars exist as bookkeeping only.
    """

    def __init__(
        self,
        title: str = "",
        *,
        Overwrite: bool = False,
        AutoDelete: bool = True,
        Silent: bool | None = None,
    ) -> None:
        # Decide once, here, whether to run headless; every method below asks
        # the object rather than re-detecting.
        self.Silent: bool = self.resolveSilentMode(Silent)

        if self.Silent:
            # No window to find or reuse (MATLAB: openFigs is empty when
            # silent), so a silent window is always a fresh object.
            self.ScreenFrac = 0.025
            self.Timeout = 60.0  # seconds
            self.AutoDelete = AutoDelete
            self._title = title
            self._bars = []
            self._app = None
            self._window = None
            self._layout = None
            return

        require_qt()
        self._app = get_or_create_app()

        # Singleton / reuse logic (mirrors MATLAB findall + guidata)
        if title in _ACTIVE_WINDOWS:
            existing = _ACTIVE_WINDOWS[title]
            if Overwrite:
                existing._window.close()
                del _ACTIVE_WINDOWS[title]
            else:
                # Re-use existing window — copy its state into self
                self.__dict__ = existing.__dict__
                self._window.raise_()
                self._window.activateWindow()
                return

        self.ScreenFrac: float = 0.025
        self.Timeout: float = 60.0  # seconds
        self.AutoDelete: bool = AutoDelete
        self._title = title
        self._bars: list[_BarRecord] = []

        self._window = QtWidgets.QWidget()
        self._window.setWindowTitle(title)
        self._window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._layout = QtWidgets.QVBoxLayout(self._window)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self._window.resize(500, 60)
        self._window.show()

        _ACTIVE_WINDOWS[title] = self

    # -- Public API -------------------------------------------------------

    def addBar(
        self,
        *,
        Label: str = "",
        Tag: str = "",
        Color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        Auto: bool = False,
        Timeout: float | None = None,
    ) -> None:
        """Add a new progress bar row.

        Parameters
        ----------
        Label : str
            Text label displayed above the bar.
        Tag : str
            Unique identifier. Defaults to *Label*.
        Color : tuple[float, float, float]
            RGB colour for the bar.
        Auto : bool
            Auto-remove bar on completion or timeout.
        Timeout : float | None
            Per-bar timeout in seconds, overriding the window's ``Timeout``
            for this bar only. ``None`` (the default) inherits the window's
            value; ``math.inf`` opts the bar out of timing out -- appropriate
            for a bar that ticks less often than the window timeout.
        """
        if not Tag:
            Tag = Label

        # Check for duplicate tag
        idx = self._find_bar(Tag)
        if idx is not None:
            rec = self._bars[idx]
            if rec.State == "Closed":
                self._bars.pop(idx)
            else:
                warnings.warn(
                    f'BarID "{Tag}" already used. Resetting progress bar.',
                    stacklevel=2,
                )
                self.updateBar(Tag, 0.0)
                rec.clock_start = time.monotonic()
                rec.clock_last = rec.clock_start
                return

        # Generate a visible colour if white
        if all(c >= 0.99 for c in Color):
            while True:
                Color = (random.random(), random.random(), random.random())
                s = sum(Color)
                if 1.5 <= s <= 2.8:
                    break

        rec = _BarRecord(Tag, Auto, Color, Timeout)

        if self.Silent:
            # Bookkeeping only; no widgets.
            self._bars.append(rec)
            return

        # Build widgets
        row_frame = QtWidgets.QFrame()
        row_layout = QtWidgets.QVBoxLayout(row_frame)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(2)

        # Top row: label + timer
        top = QtWidgets.QHBoxLayout()
        rec.label_widget = QtWidgets.QLabel(Label)
        rec.label_widget.setStyleSheet("font-size: 12px;")
        top.addWidget(rec.label_widget)

        rec.timer_widget = QtWidgets.QLabel("Estimated time: calculating")
        rec.timer_widget.setStyleSheet("font-size: 12px; color: #b0b0b0;")
        rec.timer_widget.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        top.addWidget(rec.timer_widget)
        row_layout.addLayout(top)

        # Bottom row: bar + pct + close button
        bot = QtWidgets.QHBoxLayout()
        rec.bar_widget = QtWidgets.QProgressBar()
        rec.bar_widget.setRange(0, 1000)
        rec.bar_widget.setValue(0)
        rec.bar_widget.setTextVisible(False)
        r, g, b = (int(c * 255) for c in Color)
        rec.bar_widget.setStyleSheet(
            f"QProgressBar {{ background-color: #e0e0e0; border: none; "
            f"border-radius: 4px; min-height: 18px; }}"
            f"QProgressBar::chunk {{ background-color: rgb({r},{g},{b}); "
            f"border-radius: 4px; }}"
        )
        bot.addWidget(rec.bar_widget, stretch=10)

        rec.pct_widget = QtWidgets.QLabel("0%")
        rec.pct_widget.setFixedWidth(40)
        bot.addWidget(rec.pct_widget)

        rec.btn_widget = QtWidgets.QPushButton("\u2715")  # × symbol
        rec.btn_widget.setFixedSize(24, 24)
        rec.btn_widget.setToolTip("Close")
        rec.btn_widget.clicked.connect(lambda _checked, t=Tag: self._on_button(t))
        bot.addWidget(rec.btn_widget)

        row_layout.addLayout(bot)

        # Store frame reference on record for later removal
        rec._frame = row_frame
        self._layout.addWidget(row_frame)
        self._bars.append(rec)

        self._resize_window()
        self._window.raise_()

    #: Snake-case alias for MATLAB's name; one method under two names.
    add_bar = addBar

    def updateBar(self, barID: int | str, progress: float) -> None:
        """Update the progress of a bar.

        Parameters
        ----------
        barID : int | str
            Numeric index (0-based internal) or Tag string.
        progress : float
            New progress value, 0–1.
        """
        idx, status = self.getBarNum(barID)
        if idx is None:
            warnings.warn(
                f"Could not find barID {barID}",
                stacklevel=2,
            )
            return
        if status["identifier"]:
            warnings.warn(status["message"], stacklevel=2)
            if idx is None:
                return

        rec = self._bars[idx]
        try:
            rec.Progress = progress
            if rec.bar_widget is not None:
                rec.bar_widget.setValue(int(progress * 1000))
            if rec.pct_widget is not None:
                rec.pct_widget.setText(f"{progress * 100:.0f}%")
            rec.clock_last = time.monotonic()

            if 0 < progress < 1 and rec.timer_widget is not None:
                elapsed = rec.clock_last - rec.clock_start
                remaining = elapsed * (1.0 - progress) / progress
                rec.timer_widget.setText(f"Estimated time: {self._fmt_time(remaining)}")

            self._check_timeout()
            self._check_complete()

            # Auto-close bars that completed or timed out
            to_remove: list[str] = []
            for r in self._bars:
                if r.State in ("Timeout", "Complete") and r.Auto:
                    to_remove.append(r.Tag)
            for tag in to_remove:
                self.removeBar(tag)

        except RuntimeError:
            warnings.warn(f"Execution of task {rec.Tag} terminated.", stacklevel=2)

    #: Snake-case alias for MATLAB's name; one method under two names.
    update_bar = updateBar

    def removeBar(self, barID: int | str) -> None:
        """Remove a progress bar row."""
        idx, status = self.getBarNum(barID)
        if status["identifier"]:
            warnings.warn(status["message"], stacklevel=2)
            return
        if idx is None:
            return

        rec = self._bars[idx]
        prev_state = rec.State
        rec.State = "Closed"

        frame = getattr(rec, "_frame", None)
        if frame is not None:
            self._layout.removeWidget(frame)
            frame.deleteLater()

        if rec.Progress < 1.0:
            if prev_state == "Button":
                warnings.warn(
                    f"Execution of task {rec.Tag} terminated by user.",
                    stacklevel=2,
                )
            elif prev_state == "Timeout":
                warnings.warn(
                    f"Task {rec.Tag} has timed out.",
                    stacklevel=2,
                )

        self._bars.pop(idx)
        self._resize_window()

        if self.AutoDelete:
            self._deleteIfNoOpenBars()

    #: Snake-case alias for MATLAB's name; one method under two names.
    remove_bar = removeBar

    def getBarNum(self, barID: int | str) -> tuple[int | None, dict[str, str]]:
        """Find bar index by numeric index or Tag.

        Returns
        -------
        tuple[int | None, dict]
            (index, status) where status has keys ``identifier`` and
            ``message`` (both empty strings if OK).
        """
        status: dict[str, str] = {"identifier": "", "message": ""}
        if not self._bars:
            status["identifier"] = "ndi_gui_component_ProgressBarWindow:NoBarsExist"
            status["message"] = "No progress bars have been added yet."
            return None, status

        if isinstance(barID, int):
            if 0 <= barID < len(self._bars):
                return barID, status
            status["identifier"] = "ndi_gui_component_ProgressBarWindow:InvalidBarIndex"
            status["message"] = f"Numeric BarID {barID} is out of bounds (0-{len(self._bars) - 1})."
            return None, status

        # String tag lookup
        for i, rec in enumerate(self._bars):
            if rec.Tag.lower() == str(barID).lower():
                return i, status
        status["identifier"] = "ndi_gui_component_ProgressBarWindow:InvalidBarTag"
        status["message"] = f'BarID Tag "{barID}" not found.'
        return None, status

    #: Snake-case alias for MATLAB's name; one method under two names.
    get_bar_num = getBarNum

    def getState(self, barID: int | str) -> str:
        """Return the state of a specific bar."""
        idx, status = self.getBarNum(barID)
        if status["identifier"]:
            warnings.warn(status["message"], stacklevel=2)
            return ""
        if idx is None:
            return ""
        return self._bars[idx].State

    #: Snake-case alias for MATLAB's name; one method under two names.
    get_state = getState

    def setTimeout(self, newTimeout: float) -> None:
        """Set the timeout duration in seconds."""
        self.Timeout = newTimeout

    #: Snake-case alias for MATLAB's name; one method under two names.
    set_timeout = setTimeout

    def checkTimeout(self) -> list[int]:
        """Flag bars that have timed out."""
        return self._check_timeout()

    #: Snake-case alias for MATLAB's name; one method under two names.
    check_timeout = checkTimeout

    def checkComplete(self) -> list[int]:
        """Flag bars that have reached 100%."""
        return self._check_complete()

    #: Snake-case alias for MATLAB's name; one method under two names.
    check_complete = checkComplete

    # -- Private helpers --------------------------------------------------

    def _find_bar(self, tag: str) -> int | None:
        for i, rec in enumerate(self._bars):
            if rec.Tag.lower() == tag.lower():
                return i
        return None

    def _check_timeout(self) -> list[int]:
        timed_out: list[int] = []
        now = time.monotonic()
        for i, rec in enumerate(self._bars):
            if rec.State in ("Closed", "Complete"):
                continue
            if rec.Progress >= 1.0:
                continue
            timeout = self.Timeout if rec.Timeout is None else rec.Timeout
            if math.isinf(timeout):
                continue
            if now - rec.clock_last >= timeout:
                rec.State = "Timeout"
                if rec.btn_widget is not None:
                    rec.btn_widget.setText("\u26a0")  # ⚠
                timed_out.append(i)
        return timed_out

    def _check_complete(self) -> list[int]:
        completed: list[int] = []
        for i, rec in enumerate(self._bars):
            if rec.State == "Closed":
                continue
            if rec.Progress >= 1.0:
                rec.State = "Complete"
                if rec.timer_widget is not None:
                    rec.timer_widget.setText("Complete")
                if rec.btn_widget is not None:
                    rec.btn_widget.setText("\u2713")  # ✓
                completed.append(i)
        return completed

    def _on_button(self, tag: str) -> None:
        idx = self._find_bar(tag)
        if idx is not None:
            self._bars[idx].State = "Button"
            self.removeBar(tag)

    def _resize_window(self) -> None:
        if self._window is None:
            return
        n = max(len(self._bars), 1)
        self._window.resize(500, 60 * n + 20)

    def _deleteIfNoOpenBars(self) -> None:
        if not self._bars:
            if self._window is None:
                return
            self._window.close()
            if self._title in _ACTIVE_WINDOWS:
                del _ACTIVE_WINDOWS[self._title]

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f} seconds"
        if seconds < 7200:
            return f"{seconds / 60:.0f} minutes"
        return f"{seconds / 3600:.0f} hours"

    # -- Silent (headless) mode ------------------------------------------

    @staticmethod
    def isHeadless() -> bool:
        """Is there no usable display for a Qt window?

        Mirrors MATLAB ``isHeadless``. MATLAB asks whether it was started
        with ``-batch`` or, on Linux, has an empty ``DISPLAY``. Python has no
        ``-batch``; the Python-specific signals are:

        * PySide6 is not installed -- there is nothing to draw with;
        * on Linux, neither ``DISPLAY`` nor ``WAYLAND_DISPLAY`` is set, unless
          ``QT_QPA_PLATFORM`` names a platform that needs no display
          (``offscreen`` or ``minimal``), in which case Qt can still build
          widgets safely.
        """
        if not _QT_AVAILABLE:
            return True
        if sys.platform.startswith("linux"):
            platform = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
            if platform in ("offscreen", "minimal"):
                return False
            return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        return False

    #: Snake-case alias for MATLAB's name; one method under two names.
    is_headless = isHeadless

    @staticmethod
    def silentModeDefault(newValue: object = _NOT_GIVEN) -> bool | None:
        """Get or set the process-wide silent-mode override.

        Mirrors MATLAB ``silentModeDefault``. Called with no argument, it
        returns the current override (``None`` means "decide by detection").
        Called with ``True``/``False`` it forces silent mode on/off for every
        window constructed afterwards; called with ``None`` it clears the
        override.
        """
        global _SILENT_OVERRIDE
        if newValue is not _NOT_GIVEN:
            _SILENT_OVERRIDE = None if newValue is None else bool(newValue)
        return _SILENT_OVERRIDE

    #: Snake-case alias for MATLAB's name; one method under two names.
    silent_mode_default = silentModeDefault

    @classmethod
    def resolveSilentMode(cls, explicitValue: bool | None = None) -> bool:
        """Decide whether a new window runs silently.

        Mirrors MATLAB ``resolveSilentMode``: the explicit value when given,
        else the process-wide :meth:`silentModeDefault`, else
        :meth:`isHeadless`.
        """
        if explicitValue is not None:
            return bool(explicitValue)
        override = cls.silentModeDefault()
        if override is not None:
            return bool(override)
        return cls.isHeadless()

    #: Snake-case alias for MATLAB's name; one method under two names.
    resolve_silent_mode = resolveSilentMode
