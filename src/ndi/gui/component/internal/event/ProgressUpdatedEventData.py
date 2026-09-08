"""ndi_gui_component_internal_event_ProgressUpdatedEventData — Event data for progress update notifications.

Mirrors MATLAB: ndi.gui.component.internal.event.ProgressUpdatedEventData

MATLAB's class carries THREE properties -- ``ProgressPercentage``,
``CurrentStep`` and ``TotalSteps`` -- and both of ProgressTracker's notify
sites pass all three. This port carried only the percentage, under a
different name (``PercentageComplete``), so a listener written against the
MATLAB API got ``AttributeError`` for two of the three and missed the third
by spelling. A payload class whose whole job is to be that payload is the
one place the field list has to match.
"""

from __future__ import annotations


class ndi_gui_component_internal_event_ProgressUpdatedEventData:
    """Event data carrying a snapshot of progress at notify time.

    Parameters
    ----------
    ProgressPercentage : float
        Completion percentage (0-100) when the event was raised.
    CurrentStep : int | None
        Step reached when the event was raised.
    TotalSteps : int | None
        Total steps expected when the event was raised.

    Notes
    -----
    The values are a SNAPSHOT. A listener can also read the tracker it is
    handed, but that reports the tracker's state when the listener looks,
    which is not the same thing once a notification is deferred.
    """

    def __init__(
        self,
        ProgressPercentage: float,
        CurrentStep: int | None = None,
        TotalSteps: int | None = None,
    ) -> None:
        self.ProgressPercentage: float = ProgressPercentage
        self.CurrentStep: int | None = CurrentStep
        self.TotalSteps: int | None = TotalSteps

    @property
    def PercentageComplete(self) -> float:
        """The name this port used before it carried MATLAB's three fields.

        Kept so existing callers keep working; ``ProgressPercentage`` is the
        MATLAB name and the one to write against.
        """
        return self.ProgressPercentage
