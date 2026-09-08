"""ndi_gui_component_internal_ProgressTracker — Tracks progress of a multi-step task.

Mirrors MATLAB: ndi.gui.component.internal.ndi_gui_component_internal_ProgressTracker

Provides step counting, percentage calculation, template-based messages,
and event callbacks for progress updates, message changes, and completion.

CROSS-LANGUAGE NAMING
Methods mirroring MATLAB keep MATLAB's exact name and also carry a
snake_case alias bound to the same function -- one method under two names,
so neither a ported MATLAB script nor idiomatic Python has to remember which
spelling a given method happens to have.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any


class ndi_gui_component_internal_ProgressTracker:
    """Track progress of a task with *TotalSteps* discrete steps.

    Parameters
    ----------
    TotalSteps : int
        Total number of steps expected.  ``0`` means indeterminate.

    Attributes
    ----------
    CurrentStep : int
    TotalSteps : int
    IsFinished : bool
    UpdateInterval : float
        Minimum seconds between event notifications (throttle).
    TemplateMessage : str
        Template with ``{{PropertyName}}`` placeholders.
    CompletedMessage : str
    DumpFilePath : str | None
        Path for async file-based progress dumps.

    Events (callbacks)
    ------------------
    on_progress_updated : list[Callable]
    on_message_updated : list[Callable]
    on_task_completed : list[Callable]
    """

    def __init__(self, TotalSteps: int = 0) -> None:
        self.CurrentStep: int = 0
        self.TotalSteps: int = TotalSteps
        self.IsFinished: bool = False
        self.UpdateInterval: float = 0.0
        self.TemplateMessage: str = ""
        self.CompletedMessage: str = ""
        self.DumpFilePath: str | None = None

        # Event callback lists (Python equivalent of MATLAB events)
        self.on_progress_updated: list[Callable[..., Any]] = []
        self.on_message_updated: list[Callable[..., Any]] = []
        self.on_task_completed: list[Callable[..., Any]] = []

        self._last_notify_time: float = 0.0

    # -- Dependent properties (mirror MATLAB dependent props) -------------

    @property
    def PercentageComplete(self) -> float:
        """Current completion as a percentage (0–100)."""
        if self.TotalSteps <= 0:
            return 0.0
        return (self.CurrentStep / self.TotalSteps) * 100.0

    #: Snake-case alias for MATLAB's name; one method under two names.
    percentage_complete = PercentageComplete

    @property
    def Message(self) -> str:
        """Rendered message from *TemplateMessage* with ``{{…}}`` substitution."""
        return self._render_template(self.TemplateMessage)

    # -- Public methods ---------------------------------------------------

    def updateProgress(self, currentStep: int | None = None) -> None:
        """Advance progress by one step, or set to *currentStep*.

        Parameters
        ----------
        currentStep : int | None
            If ``None``, increments ``CurrentStep`` by 1.
        """
        if self.IsFinished:
            return

        if currentStep is None:
            self.CurrentStep += 1
        else:
            self.CurrentStep = currentStep

        if self.CurrentStep >= self.TotalSteps > 0:
            self.setCompleted()
            return

        now = time.monotonic()
        if now - self._last_notify_time >= self.UpdateInterval:
            self._last_notify_time = now
            self._fire_progress_updated()

    #: Snake-case alias for MATLAB's name; one method under two names.
    update_progress = updateProgress

    def updateMessage(self, newMessage: str) -> None:
        """Raise MessageUpdated carrying *newMessage*.

        MATLAB counterpart: ``ProgressTracker.updateMessage``, which is the
        ONLY place MATLAB notifies MessageUpdated. It was not ported, which
        left the whole message channel dead on this side: ProgressMonitor
        registers ``_on_message`` on :attr:`on_message_updated` and
        MessageUpdatedEventData exists, but nothing could ever fire them --
        ``_fire_message_updated`` had no caller anywhere in the tree.

        Like MATLAB's, this notifies without storing: the tracker's own
        :attr:`Message` stays the rendered TemplateMessage.
        """
        self._fire_message_updated(newMessage)

    #: Snake-case alias for MATLAB's name; one method under two names.
    update_message = updateMessage

    def setCompleted(self) -> None:
        """Mark the task as finished and notify listeners."""
        self.IsFinished = True
        self.CurrentStep = self.TotalSteps
        self._fire_progress_updated()
        self._fire_task_completed()

    #: Snake-case alias for MATLAB's name; one method under two names.
    set_completed = setCompleted

    def reset(self) -> None:
        """Re-initialise the tracker to step 0."""
        self.CurrentStep = 0
        self.IsFinished = False
        self._last_notify_time = 0.0

    # -- Event helpers ----------------------------------------------------

    def _fire_progress_updated(self) -> None:
        from ndi.gui.component.internal.event import (
            ndi_gui_component_internal_event_ProgressUpdatedEventData,
        )

        # All three, as MATLAB's two notify sites pass them. The event is a
        # snapshot: a listener reading the tracker instead sees its state when
        # it looks, which differs once a notification is deferred.
        evt = ndi_gui_component_internal_event_ProgressUpdatedEventData(
            self.PercentageComplete, self.CurrentStep, self.TotalSteps
        )
        for cb in self.on_progress_updated:
            cb(self, evt)

    def _fire_message_updated(self, message: str | None = None) -> None:
        from ndi.gui.component.internal.event import (
            ndi_gui_component_internal_event_MessageUpdatedEventData,
        )

        evt = ndi_gui_component_internal_event_MessageUpdatedEventData(
            self.Message if message is None else message
        )
        for cb in self.on_message_updated:
            cb(self, evt)

    def _fire_task_completed(self) -> None:
        # MATLAB raises TaskCompleted with the SAME ProgressUpdatedEventData
        # it raises ProgressUpdated with, so a completion listener sees the
        # final step counts rather than having to go back to the tracker.
        from ndi.gui.component.internal.event import (
            ndi_gui_component_internal_event_ProgressUpdatedEventData,
        )

        evt = ndi_gui_component_internal_event_ProgressUpdatedEventData(
            self.PercentageComplete, self.CurrentStep, self.TotalSteps
        )
        for cb in self.on_task_completed:
            cb(self, evt)

    # -- Template rendering -----------------------------------------------

    def _render_template(self, template: str) -> str:
        """Replace ``{{PropertyName}}`` tokens in *template*."""
        if not template:
            return ""

        def _replace(match: re.Match[str]) -> str:
            prop = match.group(1)
            val = getattr(self, prop, None)
            return str(val) if val is not None else match.group(0)

        return re.sub(r"\{\{(\w+)\}\}", _replace, template)
