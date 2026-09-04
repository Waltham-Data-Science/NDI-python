"""ndi.gui.app.pyraview.transform_plot_data - traces as one polyline.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/transformPlotData.m``

WHY ONE VECTOR AND NOT ONE LINE PER CHANNEL
A 32-channel view is 32 lines to a plotting library and one line to a
renderer if the channels are strung together with NaN between them: NaN
breaks the polyline, so a single draw call paints every channel. That is the
difference between a viewer that pans smoothly and one that does not, and it
is why both ports return flat X and Y rather than a matrix.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any

import numpy as np

__all__ = ["transform_plot_data", "transformPlotData"]


def transform_plot_data(
    data: Any,
    t_vec: Any,
    level: float,
    spacing: float,
    mapping: Sequence[int] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Lay DATA out for plotting, channels stacked SPACING apart.

    LEVEL 0 is raw data, ``(samples x channels)``: each channel becomes its
    own segment of the polyline, offset by ``(channel - 1) * spacing``.

    LEVEL above 0 is decimated data, ``(samples x channels x 2)`` holding the
    min and max of each bin: each sample becomes a vertical bar from min to
    max. Drawing the pair is what keeps a spike visible when a screen pixel
    covers a thousand samples -- a decimated view that plotted means would
    show a flat line where the data has transients.

    MAPPING reorders the channels (see :func:`ndi.gui.app.pyraview.mappings`);
    a mapping that does not fit the data is warned about and ignored, as in
    MATLAB, rather than taking the window down.
    """
    array = np.asarray(data, dtype=float)
    times = np.asarray(t_vec, dtype=float).ravel()

    if array.size == 0:
        return np.array([]), np.array([])

    if mapping is not None and len(mapping) > 0:
        index = np.asarray(mapping, dtype=int) - 1  # 1-based channels
        try:
            array = array[:, index, ...]
        except IndexError:
            warnings.warn(
                "Failed to apply mapping in transform_plot_data. Using raw channel order.",
                stacklevel=2,
            )

    n_samples = array.shape[0]
    n_channels = array.shape[1] if array.ndim > 1 else 1
    if array.ndim == 1:
        array = array.reshape(-1, 1)

    if level == 0:
        # One (samples + 1) block per channel; the trailing slot stays NaN and
        # is what breaks the polyline between channels.
        x = np.full(n_channels * (n_samples + 1), np.nan)
        y = np.full(n_channels * (n_samples + 1), np.nan)
        for channel in range(n_channels):
            start = channel * (n_samples + 1)
            stop = start + n_samples
            x[start:stop] = times[:n_samples]
            y[start:stop] = array[:, channel] + channel * spacing
        return x, y

    # Decimated: (t, min) -> (t, max) -> break, three points per sample.
    if array.ndim != 3:
        raise ValueError("decimated data must be (samples x channels x 2).")

    x = np.full(n_samples * 3 * n_channels, np.nan)
    y = np.full(n_samples * 3 * n_channels, np.nan)
    for channel in range(n_channels):
        offset = channel * spacing
        block = np.full((3, n_samples), np.nan)
        block[0] = array[:, channel, 0] + offset
        block[1] = array[:, channel, 1] + offset
        column_y = block.ravel(order="F")

        block_x = np.full((3, n_samples), np.nan)
        block_x[0] = times[:n_samples]
        block_x[1] = times[:n_samples]
        column_x = block_x.ravel(order="F")

        start = channel * column_y.size
        x[start : start + column_x.size] = column_x
        y[start : start + column_y.size] = column_y
    return x, y


#: MATLAB's spelling.
transformPlotData = transform_plot_data
