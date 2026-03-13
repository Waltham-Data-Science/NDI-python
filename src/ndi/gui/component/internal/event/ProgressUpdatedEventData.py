"""ProgressUpdatedEventData — Event data for progress update notifications.

Mirrors MATLAB: ndi.gui.component.internal.event.ProgressUpdatedEventData
"""

from __future__ import annotations


class ProgressUpdatedEventData:
    """Event data carrying the current percentage complete.

    Parameters
    ----------
    PercentageComplete : float
        Current completion percentage (0–100).
    """

    def __init__(self, PercentageComplete: float) -> None:
        self.PercentageComplete: float = PercentageComplete
