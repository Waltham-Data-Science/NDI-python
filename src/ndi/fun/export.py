"""
ndi.fun.export - Export NDI data into other analysis packages' formats.

MATLAB equivalent: +ndi/+fun/+export/

Currently provides :func:`blech_clust_write`, the low-level writer for
blech_clust HMM HDF5 files.

``blech_clust`` itself -- the acquisition wrapper that assembles these arrays
from an NDI stimulator and probe -- is **not** ported here. It depends on
``ndi.fun.ensemble.load`` / ``read`` / ``filter`` / ``neuronQuality``, on
``ndi.element.ensemble``, and on ``ndi.app.stimulus.decoder``, none of which
exist on this side yet. The MATLAB writer was deliberately factored to have no
session, syncgraph or database dependencies precisely so it could be used and
tested on its own, and that is what this module takes advantage of.

``h5py`` is not declared in pyproject because ``vhlab-toolbox-python``, a core
dependency, already requires it; the import is guarded anyway so a broken
environment produces a useful message rather than a traceback from the middle
of a write.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover - exercised only without h5py
    h5py = None  # type: ignore[assignment]

__all__ = ["blech_clust_write"]

# The compound type MATLAB builds by hand with H5T.create: three native ints.
_UNIT_DESCRIPTOR_DTYPE = np.dtype(
    [("single_unit", "i4"), ("regular_spiking", "i4"), ("fast_spiking", "i4")]
)


def _require_h5py() -> None:
    if h5py is None:
        raise ImportError("h5py is required for ndi.fun.export. Install it with: pip install h5py")


def _matlab_round(x: Any) -> np.ndarray:
    """Round half AWAY FROM ZERO, as MATLAB's ``round`` does.

    numpy rounds half to even, so ``np.round(0.5)`` is 0 where MATLAB's
    ``round(0.5)`` is 1. Spike times land exactly on a half-sample often
    enough that this is a real difference and not a curiosity: at 30 kHz a
    time recorded to microsecond precision hits a half sample whenever it is
    an odd multiple of 1/60000 s.
    """
    a = np.asarray(x, dtype=float)
    return np.where(a >= 0, np.floor(a + 0.5), np.ceil(a - 0.5))


def blech_clust_write(
    outputfile: str | os.PathLike,
    unit_spiketimes: Sequence[Any],
    unit_info: Sequence[Mapping[str, Any]],
    onset_times: Any,
    trial_stimid: Any,
    stimid_tastant: Mapping[Any, str],
    *,
    pre_stim: float = 2000.0,
    post_stim: float = 5000.0,
    sample_rate: float = 30000.0,
    stimulus_order: Any = None,
    include_stimids: Any = None,
    epoch_id: str = "",
    verbose: bool = True,
) -> None:
    """Write a blech_clust HMM HDF5 file from prepared arrays.

    MATLAB equivalent: ``ndi.fun.export.blech_clust_write``

    Given ensemble spike times and per-trial stimulus identities and delivery
    times already expressed in a single common clock in seconds, bins the
    activity into blech_clust's binary millisecond ``spike_array`` layout and
    writes *outputfile* (overwritten if it exists).

    Args:
        outputfile: Path of the HDF5 file to write.
        unit_spiketimes: One entry per unit; each a sequence of spike times in
            seconds, in the common clock.
        unit_info: One mapping per unit with keys ``name``, ``single_unit``,
            ``regular_spiking`` and ``fast_spiking``; the last three are
            written to ``/unit_descriptor``.
        onset_times: Stimulus delivery times, seconds, one per trial.
        trial_stimid: Integer stimulus id of each trial.
        stimid_tastant: Maps a stimid to a tastant name, for the ``dig_in``
            group's ``tastant`` attribute. MATLAB uses a ``containers.Map``.
        pre_stim: Milliseconds retained before delivery (MATLAB ``preStim``).
            Delivery is placed at column ``pre_stim`` of ``spike_array``.
        post_stim: Milliseconds retained after delivery (MATLAB ``postStim``).
        sample_rate: Acquisition sample rate in Hz, for ``/sorted_units``
            (MATLAB ``sampleRate``).
        stimulus_order: Order of stimids mapping onto ``dig_in_0``,
            ``dig_in_1``, ...; if None, the unique stimids present, ascending
            (MATLAB ``stimulusOrder``).
        include_stimids: If given, restrict exported stimids to these
            (MATLAB ``includeStimids``).
        epoch_id: Recorded as the ``/ndi_epochid`` root attribute.
        verbose: Print progress, as MATLAB's ``verbose`` option does.

    Raises:
        ImportError: If h5py is not installed.
        ValueError: If no tastant stimuli remain to export.

    **Axis order of** ``/spike_trains/dig_in_<N>/spike_array``

    blech_clust requires the raster to have numpy shape
    ``(n_trials, n_units, trial_duration_ms)``, and that is exactly the shape
    written here -- h5py is row-major, so no transpose is involved on this
    side.

    The MATLAB writer reaches the same file by the opposite route: it is
    column-major, so it permutes to ``[trial_dur_ms n_units n_trials]`` and
    HDF5 reverses that back. Reading the file with MATLAB's ``h5read``
    therefore returns ``[trial_dur_ms n_units n_trials]``, and that is
    correct. A Python consumer must **not** apply a compensating
    ``np.transpose(spike_array, (2, 1, 0))``: the file is already in blech's
    order. That transpose was the workaround for VH-Lab/NDI-matlab#855, which
    is fixed; applying it now transposes correct data back into the bug.

    A tastant with no trials is skipped with a warning, because HDF5 datasets
    cannot have a zero-length dimension. **Its ``dig_in`` index is still
    consumed**, so the numbering has a gap rather than closing up -- matching
    MATLAB, where the loop counter names the group before the skip.
    """
    _require_h5py()

    pre_stim_ms = int(_matlab_round(pre_stim))
    post_stim_ms = int(_matlab_round(post_stim))
    trial_dur_ms = pre_stim_ms + post_stim_ms
    n_units = len(unit_spiketimes)

    onset_times = np.asarray(onset_times, dtype=float).ravel()
    trial_stimid = np.asarray(trial_stimid, dtype=float).ravel()

    if stimulus_order is not None and len(np.asarray(stimulus_order).ravel()):
        dig_in_stimids = np.asarray(stimulus_order, dtype=float).ravel()
    else:
        dig_in_stimids = np.unique(trial_stimid)
    if include_stimids is not None and len(np.asarray(include_stimids).ravel()):
        wanted = np.asarray(include_stimids, dtype=float).ravel()
        dig_in_stimids = dig_in_stimids[np.isin(dig_in_stimids, wanted)]
    if dig_in_stimids.size == 0:
        raise ValueError("No tastant stimuli were found to export.")

    outputfile = os.fspath(outputfile)
    if os.path.exists(outputfile):
        os.remove(outputfile)

    with h5py.File(outputfile, "w") as handle:
        for n, this_stimid in enumerate(dig_in_stimids):
            trials = np.flatnonzero(trial_stimid == this_stimid)
            n_trials = trials.size
            group_name = f"/spike_trains/dig_in_{n}"  # blech is 0-indexed

            if n_trials == 0:
                warnings.warn(
                    f"stimid {this_stimid:g} has no trials; skipping dig_in_{n}.",
                    stacklevel=2,
                )
                continue

            spike_array = np.zeros((n_trials, n_units, trial_dur_ms), dtype=np.uint8)
            for ti, trial in enumerate(trials):
                win_start = onset_times[trial] - pre_stim_ms / 1000.0  # seconds
                for u in range(n_units):
                    st = np.asarray(unit_spiketimes[u], dtype=float).ravel()
                    if st.size == 0:
                        continue
                    # ms bin index; delivery lands in column pre_stim_ms.
                    # MATLAB adds 1 for its 1-based columns and keeps
                    # 1 <= idx <= trial_dur_ms; this is the 0-based form of
                    # the same window.
                    idx = np.floor((st - win_start) * 1000.0).astype(np.int64)
                    idx = idx[(idx >= 0) & (idx < trial_dur_ms)]
                    spike_array[ti, u, idx] = 1

            group = handle.require_group(group_name)
            group.create_dataset("spike_array", data=spike_array, dtype="uint8")

            this_tastant = "unknown"
            for key, value in stimid_tastant.items():
                if float(key) == float(this_stimid) and value:
                    this_tastant = value
                    break

            # MATLAB's h5writeatt stores a numeric scalar as a double; these
            # are written as float64 so the two files carry the same types.
            group.attrs["stimid"] = np.float64(this_stimid)
            group.attrs["tastant"] = this_tastant
            group.attrs["n_trials"] = np.float64(n_trials)
            group.attrs["pre_stim_ms"] = np.float64(pre_stim_ms)
            group.attrs["post_stim_ms"] = np.float64(post_stim_ms)

            if verbose:
                print(
                    f"  dig_in_{n}: stimid {this_stimid:g} ({this_tastant}), "
                    f"{n_trials} trials, {n_units} units, {trial_dur_ms} ms/trial."
                )

        if verbose:
            print("Writing /sorted_units and /unit_descriptor...")
        _write_units(handle, unit_spiketimes, unit_info, sample_rate)

        handle.attrs["source"] = "NDI-python ndi.fun.export.blech_clust"
        handle.attrs["ndi_epochid"] = epoch_id
        handle.attrs["sample_rate_hz"] = np.float64(sample_rate)

    if verbose:
        print(f"Wrote blech_clust HDF5 file: {outputfile}")


def _write_units(
    handle: Any,
    unit_spiketimes: Sequence[Any],
    unit_info: Sequence[Mapping[str, Any]],
    sample_rate: float,
) -> None:
    """Write /sorted_units/unitNNN/times and the /unit_descriptor table."""
    for u, times in enumerate(unit_spiketimes):
        st = np.asarray(times, dtype=float).ravel()
        samples = _matlab_round(st * sample_rate)
        samples = samples[samples >= 0].astype(np.uint64)
        group = handle.require_group(f"/sorted_units/unit{u:03d}")
        if samples.size == 0:
            # A zero-length dimension is not allowed, so MATLAB writes a
            # single 0 rather than an empty dataset.
            group.create_dataset("times", data=np.zeros(1, dtype=np.uint64))
        else:
            group.create_dataset("times", data=samples)

    n_units = len(unit_info)
    table = np.zeros(max(n_units, 1), dtype=_UNIT_DESCRIPTOR_DTYPE)
    for i, info in enumerate(unit_info):
        table[i] = (
            np.int32(info["single_unit"]),
            np.int32(info["regular_spiking"]),
            np.int32(info["fast_spiking"]),
        )
    # With no units MATLAB creates the dataset and never writes it, so HDF5
    # leaves one zero-filled row; the zeros() above matches that.
    handle.create_dataset("unit_descriptor", data=table)
