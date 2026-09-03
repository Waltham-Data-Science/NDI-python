"""ndi.gui.app.pyraview.mappings - channel reordering for the viewer.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/mappings.m``
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["mappings", "MAPPING_NAMES"]

#: The mappings the viewer offers, in menu order.
MAPPING_NAMES = ("raw", "PlexonSV")


def mappings(channels: Sequence[int], mapping_name: str) -> list[int]:
    """Reorder CHANNELS according to MAPPING_NAME.

    ``raw`` leaves the order alone. ``PlexonSV`` is the fixed permutation of a
    32-channel Plexon headstage, and requires exactly channels 1..32 -- as in
    MATLAB, a different set is an error rather than a silent partial mapping,
    because a wrong electrode order is invisible in the trace it draws.

    CHANNELS are 1-based channel numbers, as they are in MATLAB and as a user
    reads them: this is a user-facing count, not an index into a list.
    """
    channel_list = [int(c) for c in channels]
    if mapping_name not in MAPPING_NAMES:
        raise ValueError(f"mapping_name must be one of {MAPPING_NAMES}; got {mapping_name!r}.")

    if mapping_name == "raw":
        return channel_list

    if channel_list != list(range(1, 33)):
        raise ValueError("PlexonSV mapping requires exactly channels 1:32.")
    return [*range(25, 33), *range(16, 0, -1), *range(17, 25)]
