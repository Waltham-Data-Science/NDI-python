"""ndi_gui_component_internal_AsynchProgressTracker — File-backed asynchronous progress tracker.

Mirrors MATLAB: ndi.gui.component.internal.ndi_gui_component_internal_AsynchProgressTracker

Extends :class:`ndi_gui_component_internal_ProgressTracker` with the ability to serialise progress
state to a JSON file, enabling cross-process monitoring.
"""

from __future__ import annotations

import json
import time

from ndi.gui.component.internal.ndi_gui_component_internal_ProgressTracker import ndi_gui_component_internal_ProgressTracker


class ndi_gui_component_internal_AsynchProgressTracker(ndi_gui_component_internal_ProgressTracker):
    """Progress tracker that dumps state to a file for async monitoring.

    Inherits all behaviour from :class:`ndi_gui_component_internal_ProgressTracker` and adds
    throttled file-based serialisation via :meth:`updateProgress`.
    """

    def __init__(self, TotalSteps: int = 0) -> None:
        super().__init__(TotalSteps)
        self._last_dump_time: float = 0.0

    def updateProgress(self, currentStep: int | None = None) -> None:  # noqa: N802
        """Advance progress and optionally dump to file.

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
            self.IsFinished = True
            self.CurrentStep = self.TotalSteps
            self._dumpToFile()
            self._fire_progress_updated()
            self._fire_task_completed()
            return

        now = time.monotonic()
        if now - self._last_dump_time >= self.UpdateInterval:
            self._last_dump_time = now
            self._dumpToFile()
            self._fire_progress_updated()

    def _dumpToFile(self) -> None:
        """Serialise current state to :attr:`DumpFilePath` as JSON."""
        if self.DumpFilePath is None:
            return
        payload = {
            "CurrentStep": self.CurrentStep,
            "TotalSteps": self.TotalSteps,
            "TemplateMessage": self.TemplateMessage,
        }
        with open(self.DumpFilePath, "w") as fh:
            json.dump(payload, fh)

    @staticmethod
    def getAsynchTaskProgress(filepath: str) -> dict:
        """Read progress state from a dump file.

        Parameters
        ----------
        filepath : str
            Path written by :meth:`_dumpToFile`.

        Returns
        -------
        dict
            Keys ``CurrentStep``, ``TotalSteps``, ``TemplateMessage``.
        """
        with open(filepath) as fh:
            return json.load(fh)
