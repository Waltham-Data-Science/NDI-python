"""Wide mean waveforms for many clusters, in one pass over the raw binary.

MATLAB counterpart:
``+ndi/+fun/+probe/+import/+kilosort/recalculatemeanwaveforms.m``

WHY READ THE RAW BINARY AT ALL
A Kilosort template is only about 2 ms wide, which is enough to detect a spike
and too narrow to show its shape. These functions re-read the recording around
each spike over a window the caller chooses (-5 ms to +5 ms by default) and
average, so the stored ``mean_waveform`` is a waveform someone can look at.

WHY ONE PASS
Doing that cluster by cluster re-sweeps -- and, when high-pass filtering,
re-filters -- the whole recording once per cluster. Here the file is streamed
once: each chunk is read and filtered a single time and every spike whose
window falls inside it is added to its own cluster's running mean. For N
clusters that is ~N times less reading and filtering.

THE FILTER, AND WHY WINDOWS ARE PADDED
A hand-selected raw recording is unfiltered -- it still carries the DC offset
and LFP band that Kilosort's temporary file had already removed -- so spike
shapes taken from it need a high-pass first. Each read block extends ``pad``
samples beyond the outermost window so the zero-phase filter has settled data
on either side before any window is sliced out of it; filtering the exact
window instead would put the filter's transient inside the waveform.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "recalculatemeanwaveforms",
    "recalculate_mean_waveforms",
    "DTYPES",
    "design_highpass",
    "window_offsets",
    "select_spikes",
]

#: MATLAB's dtype names, and the ones Phy writes in params.py, mapped to the
#: numpy dtype and its size. ``byteOrder`` picks the endianness at read time.
DTYPES: dict[str, tuple[str, int]] = {
    "int16": ("i2", 2),
    "short": ("i2", 2),
    "uint16": ("u2", 2),
    "ushort": ("u2", 2),
    "int32": ("i4", 4),
    "int": ("i4", 4),
    "single": ("f4", 4),
    "float": ("f4", 4),
    "float32": ("f4", 4),
    "double": ("f8", 8),
    "float64": ("f8", 8),
}


def window_offsets(sample_rate: float, t0: float, t1: float) -> tuple[int, int, np.ndarray]:
    """``(off0, off1, wst)``: the window in samples, and its times in seconds.

    ``wst`` runs from T0 to T1 with 0 at the spike, which is (approximately)
    the trough -- so a reader of the stored document knows where the spike is
    without another convention to look up.
    """
    off0 = int(round(t0 * sample_rate))
    off1 = int(round(t1 * sample_rate))
    return off0, off1, (np.arange(off0, off1 + 1, dtype=float) / sample_rate).reshape(-1, 1)


def design_highpass(
    sample_rate: float,
    *,
    cutoff: float = 300.0,
    order: int = 4,
    ripple: float = 0.8,
) -> tuple[Any, Any, int]:
    """A zero-phase Chebyshev type I high-pass, and the padding it needs.

    Returns ``(b, a, pad)``, or ``(None, None, 0)`` when the filter cannot be
    designed -- an out-of-range cutoff, or no scipy. MATLAB warns and leaves
    the data unfiltered in exactly those two cases rather than failing an
    import for want of a filter, and so does this.
    """
    import warnings

    nyquist = 0.5 * sample_rate
    wn = cutoff / nyquist
    if not 0 < wn < 1:
        warnings.warn(
            f"High-pass cutoff {cutoff} Hz is not valid for sample rate {sample_rate} Hz "
            f"(must be 0 < cutoff < Nyquist = {nyquist} Hz); leaving the data unfiltered.",
            stacklevel=2,
        )
        return None, None, 0
    try:
        from scipy.signal import cheby1
    except ImportError:  # pragma: no cover - scipy is a core dependency here
        warnings.warn(
            "highpass is true but scipy.signal is not available; leaving the data " "unfiltered.",
            stacklevel=2,
        )
        return None, None, 0

    b, a = cheby1(int(order), float(ripple), wn, btype="high")
    # enough for the filter to settle: a few cutoff periods, and at least
    # filtfilt's own minimum length requirement.
    pad = max(math.ceil(3 * sample_rate / cutoff), 3 * (int(order) + 1))
    return b, a, pad


def select_spikes(
    spike_samples: np.ndarray,
    read_off0: int,
    read_off1: int,
    total_samples: int,
    *,
    epoch_bounds: Sequence[float] | None = None,
    max_spikes: float = 1000,
) -> np.ndarray:
    """The spikes whose full padded window can be read, capped at MAX_SPIKES.

    A window must lie inside the recording, and -- when EPOCH_BOUNDS is given
    -- inside the single epoch its spike belongs to. The second condition is
    the one that is easy to miss: epochs are concatenated head to tail for
    sorting, so a window straddling a seam would average in samples from a
    different recording session entirely.

    Over the cap, an evenly spaced subset is taken rather than the first N, so
    the average is drawn from the whole recording rather than its opening
    minutes.
    """
    samples = np.asarray(spike_samples, dtype=float).ravel()
    if samples.size == 0:
        return samples

    valid = ((samples + read_off0) >= 0) & ((samples + read_off1) <= (total_samples - 1))

    bounds = np.asarray(epoch_bounds, dtype=float).ravel() if epoch_bounds is not None else None
    if bounds is not None and bounds.size >= 2:
        # epoch index of each spike = how many left edges it is at or past
        index = np.sum(samples[:, None] >= bounds[None, :-1], axis=1)
        index = np.clip(index, 1, bounds.size - 1)
        low = bounds[index - 1]
        high = bounds[index] - 1
        valid &= ((samples + read_off0) >= low) & ((samples + read_off1) <= high)

    samples = samples[valid]
    if samples.size == 0:
        return samples

    if math.isfinite(max_spikes) and samples.size > max_spikes:
        picks = np.unique(np.round(np.linspace(0, samples.size - 1, int(max_spikes))).astype(int))
        samples = samples[picks]
    return samples


def recalculatemeanwaveforms(
    binfile: str | Path,
    num_channels: int,
    spike_samples_global: Any,
    spike_clusters: Any,
    cluster_ids: Any,
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
    maxChunkBytes: float = 2e9,  # noqa: N803 - MATLAB's parameter name
    chunkSamples: float = float("nan"),  # noqa: N803 - MATLAB's parameter name
    progressfcn: Callable[[float, str], None] | None = None,
    verbose: bool = False,
) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
    """Mean waveforms for every cluster in CLUSTER_IDS, in one pass.

    Returns ``(mean_waveforms, wst, n_used)``: a list of nSamples x
    NUM_CHANNELS arrays in CLUSTER_IDS order, the shared column of sample
    times, and how many spikes contributed to each. A cluster with no usable
    spikes gets zeros, so every returned waveform has the same shape.

    Units follow the recording: samples are divided by MULTIPLIER, the same
    int16-to-physical decode the exporter applied in reverse.
    """
    if t1 < t0:
        raise ValueError(f"The window end t1 ({t1}) must be >= the window start t0 ({t0}).")
    if str(dtype).lower() not in DTYPES:
        raise ValueError(f"Unsupported dtype '{dtype}'.")

    numpy_dtype, bytes_per = DTYPES[str(dtype).lower()]
    endian = ">" if "be" in str(byteOrder).lower() else "<"
    read_dtype = np.dtype(endian + numpy_dtype)

    cluster_ids = np.asarray(cluster_ids, dtype=float).ravel()
    n_clusters = cluster_ids.size

    off0, off1, wst = window_offsets(sample_rate, t0, t1)
    n_window = off1 - off0 + 1

    mean_waveforms = [np.zeros((n_window, num_channels)) for _ in range(n_clusters)]
    n_used = np.zeros(n_clusters, dtype=float)

    b_coef, a_coef, pad = (None, None, 0)
    if highpass:
        b_coef, a_coef, pad = design_highpass(
            sample_rate, cutoff=hp_cutoff, order=hp_order, ripple=hp_ripple
        )
    do_filter = b_coef is not None

    read_off0 = off0 - pad
    read_off1 = off1 + pad

    path = Path(binfile)
    if not path.is_file():
        raise FileNotFoundError(f"Binary file not found: {binfile}.")
    total_samples = int((os.path.getsize(path) - headerOffsetBytes) // (bytes_per * num_channels))

    samples_all = np.asarray(spike_samples_global, dtype=float).ravel()
    clusters_all = np.asarray(spike_clusters, dtype=float).ravel()
    if samples_all.size == 0 or n_clusters == 0:
        return mean_waveforms, wst, n_used

    # the flat list of (sample, cluster slot) to read, selected exactly as the
    # single-cluster function selects, so the two agree spike for spike
    flat_samples: list[np.ndarray] = []
    flat_slots: list[np.ndarray] = []
    for slot in range(n_clusters):
        chosen = select_spikes(
            samples_all[clusters_all == cluster_ids[slot]],
            read_off0,
            read_off1,
            total_samples,
            epoch_bounds=epochBounds,
            max_spikes=maxSpikes,
        )
        if chosen.size:
            flat_samples.append(chosen)
            flat_slots.append(np.full(chosen.size, slot, dtype=int))

    if not flat_samples:
        return mean_waveforms, wst, n_used

    all_samples = np.concatenate(flat_samples)
    all_slots = np.concatenate(flat_slots)
    order = np.argsort(all_samples, kind="stable")  # read strictly front to back
    all_samples = all_samples[order]
    all_slots = all_slots[order]
    n_spikes = all_samples.size

    chunk_samples = _chunk_size(
        chunkSamples, maxChunkBytes, n_clusters, n_window, num_channels, do_filter
    )

    accumulators = [np.zeros((n_window, num_channels)) for _ in range(n_clusters)]
    last_report = 0.0

    with open(path, "rb") as handle:
        index = 0
        while index < n_spikes:
            # grow a chunk whose spikes span at most chunk_samples, so the read
            # block stays bounded however densely the spikes fall
            span_limit = all_samples[index] + chunk_samples
            end = index
            while end + 1 < n_spikes and all_samples[end + 1] <= span_limit:
                end += 1

            chunk_positions = all_samples[index : end + 1]
            chunk_slots = all_slots[index : end + 1]

            start_sample = int(chunk_positions[0]) + read_off0
            stop_sample = int(chunk_positions[-1]) + read_off1
            n_block = stop_sample - start_sample + 1

            handle.seek(headerOffsetBytes + start_sample * num_channels * bytes_per)
            raw = np.fromfile(handle, dtype=read_dtype, count=num_channels * n_block)
            if raw.size < num_channels * n_block:
                index = end + 1
                continue  # short read; the validity check should have prevented it
            block = raw.astype(np.float64).reshape(n_block, num_channels)
            del raw
            if do_filter:
                from scipy.signal import filtfilt

                block = filtfilt(b_coef, a_coef, block, axis=0)

            for position, slot in zip(chunk_positions, chunk_slots):
                first = int(position) + off0 - start_sample
                accumulators[slot] += block[first : first + n_window, :]
                n_used[slot] += 1

            index = end + 1
            fraction = index / n_spikes
            if progressfcn is not None:
                progressfcn(fraction, "Recalculating mean waveforms")
            if verbose and (fraction - last_report) >= 0.10:
                last_report = fraction
                print(
                    f"  Recalculating mean waveforms: {round(100 * fraction)}% "
                    f"({index} of {n_spikes} spikes)."
                )

    for slot in range(n_clusters):
        if n_used[slot] > 0:
            waveform = accumulators[slot] / n_used[slot]
            if multiplier not in (0, 1):
                waveform = waveform / multiplier
            mean_waveforms[slot] = waveform
        accumulators[slot] = np.zeros((0, 0))  # free as we go, as MATLAB does

    if progressfcn is not None:
        progressfcn(1.0, "Recalculating mean waveforms")
    return mean_waveforms, wst, n_used


def _chunk_size(
    chunk_samples: float,
    max_chunk_bytes: float,
    n_clusters: int,
    n_window: int,
    num_channels: int,
    do_filter: bool,
) -> int:
    """Samples per chunk, from an explicit value or the memory budget.

    The peak working set is the per-cluster accumulators (held for the whole
    pass) plus one chunk's transient buffers. Filtering multiplies a chunk's
    footprint, since filtfilt allocates its own reflected and directional
    temporaries, so the factor accounts for it and the whole pass stays under
    the ceiling.
    """
    if not (isinstance(chunk_samples, float) and math.isnan(chunk_samples)):
        if chunk_samples < 1:
            raise ValueError(f"chunkSamples must be >= 1 (got {chunk_samples}).")
        return int(chunk_samples)

    memory_factor = 6 if do_filter else 2.5
    accumulator_bytes = 2 * n_clusters * n_window * num_channels * 8
    floor_bytes = memory_factor * 4 * n_window * num_channels * 8
    budget = max(floor_bytes, max_chunk_bytes - accumulator_bytes)
    return int(max(n_window, math.floor(budget / (memory_factor * num_channels * 8))))


#: The readable spelling beside MATLAB's.
recalculate_mean_waveforms = recalculatemeanwaveforms
