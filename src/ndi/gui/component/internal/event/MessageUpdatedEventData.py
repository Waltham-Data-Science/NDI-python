"""ndi_gui_component_internal_event_MessageUpdatedEventData — Event data for message update notifications.

Mirrors MATLAB: ndi.gui.component.internal.event.ndi_gui_component_internal_event_MessageUpdatedEventData
"""

from __future__ import annotations


class ndi_gui_component_internal_event_MessageUpdatedEventData:
    """Event data carrying an updated status message.

    Parameters
    ----------
    Message : str
        The updated message string.
    """

    def __init__(self, Message: str) -> None:
        self.Message: str = Message
