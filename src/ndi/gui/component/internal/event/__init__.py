"""ndi.gui.component.internal.event — Event data classes for progress tracking."""

from ndi.gui.component.internal.event.MessageUpdatedEventData import (
    MessageUpdatedEventData,
)
from ndi.gui.component.internal.event.ProgressUpdatedEventData import (
    ProgressUpdatedEventData,
)

__all__ = [
    "ProgressUpdatedEventData",
    "MessageUpdatedEventData",
]
