"""ProgressMonitor — Abstract base class for progress display.

Mirrors MATLAB: ndi.gui.component.abstract.ProgressMonitor

Provides timing, event-listener wiring, and time-remaining estimation.
Subclasses must implement :meth:`updateProgressDisplay`,
:meth:`updateMessage`, and :meth:`finish`.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from ndi.gui.component.internal.ProgressTracker import ProgressTracker


class ProgressMonitor(ABC):
    """Abstract monitor that listens to a :class:`ProgressTracker`.

    Parameters
    ----------
    **kwargs
        Arbitrary property overrides (``Title``, ``UpdateInterval``,
        ``DisplayElapsedTime``, ``DisplayRemainingTime``,
        ``ProgressTracker``).
    """

    def __init__(self, **kwargs: Any) -> None:
        self.Title: str = kwargs.get("Title", "In progress...")
        self.UpdateInterval: float = kwargs.get("UpdateInterval", 0.5)
        self.DisplayElapsedTime: bool = kwargs.get("DisplayElapsedTime", False)
        self.DisplayRemainingTime: bool = kwargs.get("DisplayRemainingTime", True)

        self.ProgressTracker: ProgressTracker | None = kwargs.get("ProgressTracker", None)

        self._start_time: float | None = None
        self._last_update_time: float = 0.0
        self._is_initialized: bool = False
        self._listener_handles: list[Any] = []

        if self.ProgressTracker is not None:
            self._attach_listeners(self.ProgressTracker)

    # -- Public API -------------------------------------------------------

    def reset(self) -> None:
        """Clear all timing data and state."""
        self._start_time = None
        self._last_update_time = 0.0
        self._is_initialized = False

    def markComplete(self) -> None:
        """Signal that the task is complete."""
        if self.ProgressTracker is not None:
            self.ProgressTracker.setCompleted()
        self.finish()

    def setProgressTracker(self, tracker: ProgressTracker) -> None:
        """Attach a new :class:`ProgressTracker` and wire up listeners."""
        self._detach_listeners()
        self.ProgressTracker = tracker
        self._attach_listeners(tracker)

    # -- Abstract methods (subclasses MUST implement) ---------------------

    @abstractmethod
    def updateProgressDisplay(self) -> None:
        """Update the visual progress display."""

    @abstractmethod
    def updateMessage(self, message: str) -> None:
        """Update the displayed message."""

    @abstractmethod
    def finish(self) -> None:
        """Display the completion state."""

    # -- Protected helpers ------------------------------------------------

    def getProgressValue(self) -> float:
        """Return current progress as a fraction 0–1."""
        if self.ProgressTracker is None:
            return 0.0
        return self.ProgressTracker.PercentageComplete / 100.0

    def getProgressTitle(self) -> str:
        """Return the tracker's rendered message, or *Title*."""
        if self.ProgressTracker is not None and self.ProgressTracker.Message:
            return self.ProgressTracker.Message
        return self.Title

    def formatMessage(self, message: str) -> str:
        """Append estimated remaining time to *message* if enabled."""
        if not self.DisplayRemainingTime:
            return message
        remaining = self._estimateRemainingTime()
        if remaining is None:
            return message
        return f"{message} ({self._formatDuration(remaining)} remaining)"

    # -- Time estimation --------------------------------------------------

    def _estimateRemainingTime(self) -> float | None:
        """Estimate seconds remaining based on elapsed time and progress."""
        progress = self.getProgressValue()
        if self._start_time is None or progress <= 0.0 or progress >= 1.0:
            return None
        elapsed = time.monotonic() - self._start_time
        return elapsed * (1.0 - progress) / progress

    @staticmethod
    def _formatDuration(seconds: float) -> str:
        """Human-readable duration string."""
        if seconds < 60:
            return f"{seconds:.0f} seconds"
        if seconds < 7200:
            return f"{seconds / 60:.0f} minutes"
        return f"{seconds / 3600:.0f} hours"

    # -- Listener wiring --------------------------------------------------

    def _attach_listeners(self, tracker: ProgressTracker) -> None:
        tracker.on_progress_updated.append(self._on_progress)
        tracker.on_message_updated.append(self._on_message)
        tracker.on_task_completed.append(self._on_complete)

    def _detach_listeners(self) -> None:
        if self.ProgressTracker is None:
            return
        t = self.ProgressTracker
        for lst, cb in [
            (t.on_progress_updated, self._on_progress),
            (t.on_message_updated, self._on_message),
            (t.on_task_completed, self._on_complete),
        ]:
            try:
                lst.remove(cb)
            except ValueError:
                pass

    def _on_progress(self, _src: Any, _evt: Any) -> None:
        if not self._is_initialized:
            self._start_time = time.monotonic()
            self._is_initialized = True
        now = time.monotonic()
        if now - self._last_update_time >= self.UpdateInterval:
            self._last_update_time = now
            self.updateProgressDisplay()

    def _on_message(self, _src: Any, evt: Any) -> None:
        self.updateMessage(evt.Message)

    def _on_complete(self, _src: Any) -> None:
        self.finish()
