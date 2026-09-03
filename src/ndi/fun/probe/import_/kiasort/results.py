"""ndi.fun.probe.import.kiasort.results - read one probe's KIASORT output.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/results.m``

KIASORT writes its sort into two subfolders of the output folder::

    KDIR/RES_Sorted/spike_idx.h5           sample index of each spike
    KDIR/RES_Sorted/unifiedLabels.h5       cross-channel unit id of each spike
    KDIR/RES_Sorted/channelNum.h5          detection channel of each spike
    KDIR/Sorted_Samples/sorted_samples.mat per-unit stats (mean waveforms)

THE INDEX BASE IS THE THING TO GET RIGHT
KIASORT stores 1-BASED sample indices, MATLAB-style. Everything downstream of
this function -- the epoch-boundary arithmetic in :func:`probe`, and the
sample bookkeeping ``ndi.fun.probe.export.binary`` wrote -- is 0-based, as
Kilosort's ``spike_times.npy`` is. So the conversion happens HERE, once, and
``spike_samples_global`` is 0-based from this point on. Doing it later, or
twice, moves every spike by one sample: too small to look wrong in a raster
and large enough to matter at a 30 kHz sample rate.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np

from .unit_stats import CURATED_SUFFIX, UnitStats, unitstats

__all__ = ["results", "Results", "RES_SORTED"]

#: The subfolder KIASORT writes its per-spike output into.
RES_SORTED = "RES_Sorted"


class Results:
    """One probe's KIASORT output -- MATLAB's ``R`` struct, field for field."""

    def __init__(
        self,
        res_dir: str,
        suffix: str,
        spike_samples_global: np.ndarray,
        spike_units: np.ndarray,
        spike_channels: np.ndarray | None,
        unit_stats: UnitStats | None,
    ):
        #: The ``RES_Sorted`` directory that was read.
        self.res_dir = res_dir
        #: ``""`` or ``"_curated"``: which output files these came from.
        self.suffix = suffix
        #: 0-BASED sample index of each spike in the concatenated stream.
        self.spike_samples_global = spike_samples_global
        #: Cross-channel unit id of each spike.
        self.spike_units = spike_units
        #: Detection channel of each spike, or None when KIASORT wrote none.
        self.spike_channels = spike_channels
        #: Per-unit statistics, or None -- see :mod:`.unit_stats`.
        self.unit_stats = unit_stats

    def __repr__(self) -> str:
        return (
            f"Results(spikes={self.spike_units.size}, "
            f"units={np.unique(self.spike_units).size}, suffix={self.suffix!r})"
        )


def results(
    kdir: str | Path,
    *,
    curated: bool = False,
    need_stats: bool = True,
) -> Results:
    """Read the KIASORT output in KDIR.

    With *curated* true the ``_curated`` files are preferred and their absence
    WARNS AND FALLS BACK to the plain output rather than failing: a user who
    has not curated yet still wants their sort imported, and a hard error here
    would make ``curated=True`` unusable as a default in a batch import.

    *need_stats* False skips the ``.mat`` holding the mean waveforms, which is
    the expensive read and is pointless when the caller wants no waveforms.

    Raises:
        FileNotFoundError: when KDIR holds no ``RES_Sorted``, or that folder
            lacks the two files every sort has.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.results``.
    """
    kdir = Path(kdir)
    res_dir = kdir / RES_SORTED
    if not res_dir.is_dir():
        raise FileNotFoundError(
            f"KIASORT {RES_SORTED} folder not found at {res_dir}. "
            "Was KIASORT run with this folder as its output?"
        )

    suffix = _resolve_suffix(res_dir, curated)

    spike_idx_file = res_dir / f"spike_idx{suffix}.h5"
    unified_file = res_dir / f"unifiedLabels{suffix}.h5"
    if not spike_idx_file.is_file() or not unified_file.is_file():
        raise FileNotFoundError(
            f"Expected KIASORT files spike_idx{suffix}.h5 and "
            f"unifiedLabels{suffix}.h5 in {res_dir}."
        )

    # 1-based on disk, 0-based from here on. See the module docstring.
    spike_samples_global = read_dataset(spike_idx_file, f"spike_idx{suffix}") - 1.0
    spike_units = read_dataset(unified_file, f"unifiedLabels{suffix}")

    channel_file = res_dir / f"channelNum{suffix}.h5"
    spike_channels = (
        read_dataset(channel_file, f"channelNum{suffix}") if channel_file.is_file() else None
    )

    stats = unitstats(kdir, suffix) if need_stats else None

    return Results(
        res_dir=str(res_dir),
        suffix=suffix,
        spike_samples_global=spike_samples_global,
        spike_units=spike_units,
        spike_channels=spike_channels,
        unit_stats=stats,
    )


def _resolve_suffix(res_dir: Path, curated: bool) -> str:
    """``"_curated"`` when curated output was asked for and exists, else ``""``."""
    if not curated:
        return ""
    have_curated = (res_dir / "spike_idx_curated.h5").is_file() and (
        res_dir / "unifiedLabels_curated.h5"
    ).is_file()
    if have_curated:
        return CURATED_SUFFIX
    warnings.warn(
        f"Curated KIASORT outputs missing in {res_dir}. Loading non-curated output.",
        stacklevel=3,
    )
    return ""


def read_dataset(path: str | Path, name: str) -> np.ndarray:
    """The one dataset ``/NAME`` from a KIASORT HDF5 file, as a flat array.

    KIASORT stores each field as a single top-level dataset. When the name it
    was asked for is not there, the file's only dataset is used instead --
    KIASORT has renamed these between versions (the ``_curated`` files in
    particular), and a sort that is readable should not fail over a key.
    """
    import h5py

    with h5py.File(str(path), "r") as handle:
        key = name if name in handle else _sole_dataset(handle)
        if key is None:
            raise KeyError(f"No dataset {name!r} in {path}, and no single dataset to fall back to.")
        return np.asarray(handle[key][()], dtype=float).ravel()


def _sole_dataset(handle: Any) -> str | None:
    """The name of the file's only dataset, or None when it has several."""
    keys = list(handle.keys())
    return keys[0] if len(keys) == 1 else None
