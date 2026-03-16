"""ndi_gui_component_internal_event_ProgressUpdatedEventData — Event data for progress update notifications.

Mirrors MATLAB: ndi.gui.component.internal.event.ndi_gui_component_internal_event_ProgressUpdatedEventData
"""

from __future__ import annotations


class ndi_gui_component_internal_event_ProgressUpdatedEventData:
    """Event data carrying the current percentage complete.

    Parameters
    ----------
    PercentageComplete : float
        Current completion percentage (0–100).
    """

    def __init__(self, PercentageComplete: float) -> None:
        self.PercentageComplete: float = PercentageComplete
