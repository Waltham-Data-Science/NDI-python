"""One cluster's wide mean waveform, read from the raw binary.

MATLAB counterpart:
``+ndi/+fun/+probe/+import/+kilosort/recalculatemeanwaveform.m``

The single-cluster counterpart of
:func:`~ndi.fun.probe.import_.kilosort.recalculate_mean_waveforms.recalculatemeanwaveforms`,
which the importer uses instead because it reads the file once for every
cluster rather than once per cluster. This one stays because it is the
readable statement of what the batched pass does -- and because a caller
inspecting a single unit should not have to hand it a cluster list.

The two share their spike selection, window arithmetic and filter design (see
that module), so a change to what counts as a usable spike cannot land in one
and not the other.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

from .recalculate_mean_waveforms import DTYPES, design_highpass, select_spikes, window_offsets

__all__ = ["recalculatemeanwaveform", "recalculate_mean_waveform"]


def recalculatemeanwaveform(
    binfile: str | Path,
    num_channels: int,
    spike_samples_global: Any,
    sample_rate: float,
    t0: float,
    t1: float,
    *,
    dtype: str = "int16",
    byteOrder: str = "ieee-le",  # noqa: N803 - MATLAB's parameter name
    headerOffsetBytes: int = 0,  # noqa: N803 - MATLAB's parameter name
    multiplier: float = 1,
    maxSpikes: float = 1000,  # noqa: N803 - MATLAB's parameter name
    epochBounds: Any = None,  # noqa: N803 - MATLAB's parameter name
    highpass: bool = False,
    hp_cutoff: float = 300.0,
    hp_order: int = 4,
    hp_ripple: float = 0.8,
) -> tuple[np.ndarray, np.ndarray, int]:
    """The mean waveform over SPIKE_SAMPLES_GLOBAL, nSamples x NUM_CHANNELS.

    Returns ``(mean_waveform, wst, n_used)``. Spikes whose padded window falls
    off the recording, or across an epoch seam when EPOCH_BOUNDS is given, are
    skipped; over MAX_SPIKES an evenly spaced subset is averaged.
    """
    if t1 < t0:
        raise ValueError(f"The window end t1 ({t1}) must be >= the window start t0 ({t0}).")
    if str(dtype).lower() not in DTYPES:
        raise ValueError(f"Unsupported dtype '{dtype}'.")

    numpy_dtype, bytes_per = DTYPES[str(dtype).lower()]
    endian = ">" if "be" in str(byteOrder).lower() else "<"
    read_dtype = np.dtype(endian + numpy_dtype)

    off0, off1, wst = window_offsets(sample_rate, t0, t1)
    n_window = off1 - off0 + 1

    b_coef, a_coef, pad = (None, None, 0)
    if highpass:
        b_coef, a_coef, pad = design_highpass(
            sample_rate, cutoff=hp_cutoff, order=hp_order, ripple=hp_ripple
        )
    do_filter = b_coef is not None

    read_off0 = off0 - pad
    read_off1 = off1 + pad
    n_read = read_off1 - read_off0 + 1

    path = Path(binfile)
    if not path.is_file():
        raise FileNotFoundError(f"Binary file not found: {binfile}.")
    total_samples = int((os.path.getsize(path) - headerOffsetBytes) // (bytes_per * num_channels))

    mean_waveform = np.zeros((n_window, num_channels))
    samples = select_spikes(
        np.asarray(spike_samples_global, dtype=float).ravel(),
        read_off0,
        read_off1,
        total_samples,
        epoch_bounds=epochBounds,
        max_spikes=maxSpikes,
    )
    if samples.size == 0:
        return mean_waveform, wst, 0

    accumulator = np.zeros((n_window, num_channels))
    n_used = 0
    with open(path, "rb") as handle:
        for spike in samples:
            start_sample = int(spike) + read_off0
            handle.seek(headerOffsetBytes + start_sample * num_channels * bytes_per)
            raw = np.fromfile(handle, dtype=read_dtype, count=num_channels * n_read)
            if raw.size < num_channels * n_read:
                continue  # short read; the validity check should have prevented it
            # the binary is channel-interleaved per sample
            window = raw.astype(np.float64).reshape(n_read, num_channels)
            if do_filter:
                from scipy.signal import filtfilt

                window = filtfilt(b_coef, a_coef, window, axis=0)
            if pad > 0:
                window = window[pad : pad + n_window, :]
            accumulator += window
            n_used += 1

    if n_used > 0:
        mean_waveform = accumulator / n_used
    if multiplier not in (0, 1):
        mean_waveform = mean_waveform / multiplier

    return mean_waveform, wst, n_used


#: The readable spelling beside MATLAB's.
recalculate_mean_waveform = recalculatemeanwaveform
