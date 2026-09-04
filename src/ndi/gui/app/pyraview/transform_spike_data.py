"""ndi.gui.app.pyraview.transform_spike_data - spike ticks over the traces.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/transformSpikeData.m``
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

__all__ = ["transform_spike_data", "transformSpikeData", "BOX_HALF_WIDTH"]

#: Half-width of the per-spike box, in seconds: the box is 2 ms wide, centred
#: on the spike.
BOX_HALF_WIDTH = 0.001


def transform_spike_data(
    spiking_info: Sequence[Mapping[str, Any]],
    selected: Sequence[int],
    t0: float,
    t1: float,
    spacing: float,
    show_box: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Ticks for the selected units' spikes between T0 and T1.

    Each spike becomes a short vertical tick on its unit's best channel,
    between 0.4 and 0.6 of the channel spacing, so it reads as a mark ON the
    trace rather than a line across it. With SHOW_BOX, each spike also gets a
    2 ms box spanning the unit's significant channels, which is how a user
    sees that one unit appears on several channels at once.

    Only spikes inside the view are emitted, as in MATLAB: the number of
    segments then tracks what is on screen rather than the length of the
    epoch, which is what keeps panning cheap on a long recording.

    SELECTED holds indices into SPIKING_INFO; out-of-range entries are
    skipped, as MATLAB skips them.
    """
    if not len(spiking_info) or not len(selected):
        return np.array([]), np.array([])

    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []

    for index in selected:
        if index >= len(spiking_info) or index < 0:
            continue
        info = spiking_info[index]

        times = np.asarray(info.get("spike_times") or [], dtype=float).ravel()
        if times.size == 0:
            continue

        channel = info.get("best_channel")
        if channel is None:
            centre = info.get("center_of_mass")
            channel = round(float(centre)) if centre is not None else 1
        channel = int(channel)

        visible = times[(times >= t0) & (times <= t1)]
        if visible.size == 0:
            continue

        base = (channel - 1) * spacing
        y_low = base + 0.4 * spacing
        y_high = base + 0.6 * spacing

        count = visible.size
        tick_x = np.full((3, count), np.nan)
        tick_x[0] = visible
        tick_x[1] = visible
        tick_y = np.full((3, count), np.nan)
        tick_y[0] = y_low
        tick_y[1] = y_high
        xs.append(tick_x.ravel(order="F"))
        ys.append(tick_y.ravel(order="F"))

        if show_box:
            low = _channel_or(info, "low_channel", channel)
            high = _channel_or(info, "high_channel", channel)
            box_low = (low - 1) * spacing
            box_high = (high - 1) * spacing

            left = visible - BOX_HALF_WIDTH
            right = visible + BOX_HALF_WIDTH
            box_x = np.full((6, count), np.nan)
            box_x[0] = left
            box_x[1] = right
            box_x[2] = right
            box_x[3] = left
            box_x[4] = left
            box_y = np.full((6, count), np.nan)
            box_y[0] = box_low
            box_y[1] = box_low
            box_y[2] = box_high
            box_y[3] = box_high
            box_y[4] = box_low
            xs.append(box_x.ravel(order="F"))
            ys.append(box_y.ravel(order="F"))

    if not xs:
        return np.array([]), np.array([])
    return np.concatenate(xs), np.concatenate(ys)


def _channel_or(info: Mapping[str, Any], key: str, default: int) -> int:
    """INFO's channel under KEY, or DEFAULT when it has none."""
    value = info.get(key)
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return int(number)


#: MATLAB's spelling.
transformSpikeData = transform_spike_data
