"""ndi.fun.probe.channel_count - how many channels a probe's epochprobemap assigns it.

MATLAB counterpart: ``+ndi/+fun/+probe/channelCount.m``

The count comes from the probe's channel list, read through
``getchanneldevinfo``, and so costs no sample reads: it is the number an
exported binary will have interleaved, which is what a channel map has to
agree with (see :mod:`ndi.fun.probe.geometry`).

WHY THE RETURN SHAPE IS TOLERATED RATHER THAN ASSUMED
MATLAB has one ``getchanneldevinfo`` signature, whose fifth output is the
channel list. Python has two: :class:`ndi.probe.timeseries_mfdaq` returns
``(device, device_epoch, channeltype, channellist)`` and the base
:class:`ndi.probe.ndi_probe` returns a dict. Rather than pick one and be
wrong for the other, both shapes are read, and anything else yields ``None``
-- MATLAB's ``[]`` -- which every caller here already has to handle, because
a probe with no epochs cannot answer either.
"""

from __future__ import annotations

from typing import Any

__all__ = ["channelCount", "channel_count"]

#: Dict keys that have held the channel list, most specific first.
_CHANNEL_LIST_KEYS = ("channellist", "channel_list", "channels")


def channelCount(probe: Any, epoch: Any = None) -> int | None:  # noqa: N802 (MATLAB mirror)
    """Number of channels the epochprobemap assigns to *probe*.

    *epoch* is an epoch number or epoch_id; by default the probe's first
    epoch is used, the channel count being normally the same across a
    probe's epochs.

    Returns ``None`` (MATLAB's ``[]``) when it cannot be determined -- the
    probe has no epochs, does not expose ``getchanneldevinfo``, or answers
    with something no channel list can be read out of.

    MATLAB equivalent: ``ndi.fun.probe.channelCount``.
    """
    try:
        candidates = [epoch] if epoch is not None else _first_epoch_candidates(probe)
    except Exception:  # noqa: BLE001 - MATLAB's catch: an unanswerable probe is []
        return None

    for candidate in candidates:
        # Each candidate names the same epoch a different way, so one being
        # refused says nothing about the next: the try is per candidate, not
        # around the loop.
        try:
            channels = _channel_list(probe.getchanneldevinfo(candidate))
        except Exception:  # noqa: BLE001 - see above
            continue
        if channels is not None:
            return len(channels)
    return None


def _first_epoch_candidates(probe: Any) -> list[Any]:
    """How to name the probe's first epoch, in the order to try.

    MATLAB asks by ``epoch_id``. The base Python probe wants an epoch
    NUMBER and raises on a string, so the 1-based number is tried after it;
    both name the same epoch, so whichever the probe understands is right.
    """
    et, _ = probe.epochtable()
    if not et:
        return []
    epoch_id = et[0].get("epoch_id")
    return [c for c in (epoch_id, 1) if c is not None]


def _channel_list(info: Any) -> list[Any] | None:
    """The channel list inside a ``getchanneldevinfo`` answer, or None."""
    if info is None:
        return None
    if isinstance(info, dict):
        for key in _CHANNEL_LIST_KEYS:
            value = info.get(key)
            if value is not None:
                return list(value)
        return None
    if isinstance(info, (tuple, list)):
        # MATLAB's fifth output; Python's mfdaq probe returns it last too.
        return list(info[-1]) if info and info[-1] is not None else None
    return None


#: snake_case spelling, the house style for new code.
channel_count = channelCount
