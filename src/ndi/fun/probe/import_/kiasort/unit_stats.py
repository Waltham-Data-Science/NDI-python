"""ndi.fun.probe.import.kiasort.unitstats - per-unit statistics from a KIASORT sort.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/unitstats.m``

KIASORT's per-spike HDF5 output says which unit each spike belongs to but
carries no waveform. The mean waveform of each cross-channel unit is written
during the sample-sorting stage instead, into a ``.mat``; this module reads
that file and normalises it to the three fields the importer wants.

WHY THE .mat IS READ TWO WAYS
MATLAB's ``save`` writes v7 (a compressed MAT container that
``scipy.io.loadmat`` reads) or, for anything over 2 GB or when the user asked
for it, v7.3 (which is HDF5 and which ``loadmat`` refuses outright). KIASORT
picks neither explicitly, so a real sort can arrive as either. Both are read
here, because "your sort is too big to import" would be an absurd failure to
hand a user.

AND WHY v7.3 NEEDS A TRANSPOSE
MATLAB writes HDF5 in column-major order and reverses the dimension order on
the way out, so a (units x samples x channels) array in MATLAB comes back
from h5py as (channels x samples x units). Reading it without reversing that
would hand every unit a waveform belonging to some other unit's channel --
silently, and with plausible-looking numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["unitstats", "unit_stats", "UnitStats", "CURATED_SUFFIX"]

#: The file-name suffix KIASORT gives its curated output.
CURATED_SUFFIX = "_curated"


class UnitStats:
    """The per-unit statistics, normalised to what the importer reads.

    A small class rather than a dict because MATLAB reads these by name
    (``stats.label``, ``stats.meanWaveforms``) and the same code should read
    the same way here. The MATLAB field spellings are kept for exactly that
    reason.
    """

    def __init__(
        self,
        label: Any = None,
        channelID: Any = None,  # noqa: N803 - MATLAB's field name
        meanWaveforms: Any = None,  # noqa: N803 - MATLAB's field name
        source: str = "",
    ):
        self.label = np.asarray([] if label is None else label, dtype=float).ravel()
        self.channelID = np.asarray([] if channelID is None else channelID, dtype=float).ravel()
        self.meanWaveforms = (
            None if meanWaveforms is None else np.asarray(meanWaveforms, dtype=float)
        )
        #: Which file these came from. Python only; useful in a report.
        self.source = source

    def __len__(self) -> int:
        return int(self.label.size)

    def __repr__(self) -> str:
        shape = None if self.meanWaveforms is None else self.meanWaveforms.shape
        return f"UnitStats(units={len(self)}, meanWaveforms={shape})"


def unitstats(kdir: str | Path, suffix: str = "") -> UnitStats | None:
    """Load the per-unit statistics from the KIASORT output folder KDIR.

    *suffix* is ``"_curated"`` when a curated sort is being read, ``""``
    otherwise. The preference order mirrors KIASORT's own
    ``load_sorted_results``:

    1. for a curated sort, ``KDIR/RES_Sorted/curated_sample.mat``
       (``curatedSamples``);
    2. otherwise ``KDIR/Sorted_Samples/sorted_samples.mat``
       (``crossChannelStats.unified_labels``).

    Returns None -- MATLAB's ``[]`` -- when neither file is there, which is a
    legitimate state: the per-spike output alone is enough to import spike
    trains, it just cannot carry waveforms.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.unitstats``.
    """
    kdir = Path(kdir)

    if suffix == CURATED_SUFFIX:
        curated = kdir / "RES_Sorted" / "curated_sample.mat"
        if curated.is_file():
            stats = _from_curated(curated)
            if stats is not None:
                return stats

    sorted_samples = kdir / "Sorted_Samples" / "sorted_samples.mat"
    if sorted_samples.is_file():
        return _from_sorted_samples(sorted_samples)

    return None


def _from_curated(path: Path) -> UnitStats | None:
    """``curatedSamples`` from a curated-sample file, or None if absent."""
    contents = _load_mat(path)
    curated = _field(contents, "curatedSamples")
    if curated is None:
        return None
    return UnitStats(
        label=_field(curated, "unifiedLabels"),
        channelID=_field(curated, "channelNum"),
        meanWaveforms=_field(curated, "waveform"),
        source=str(path),
    )


def _from_sorted_samples(path: Path) -> UnitStats | None:
    """``crossChannelStats.unified_labels`` from the sample-sorting output."""
    contents = _load_mat(path)
    cross = _field(contents, "crossChannelStats")
    unified = _field(cross, "unified_labels") if cross is not None else None
    if unified is None:
        return None
    return UnitStats(
        label=_field(unified, "label"),
        channelID=_field(unified, "channelID"),
        meanWaveforms=_field(unified, "meanWaveforms"),
        source=str(path),
    )


# ----------------------------------------------------------------------
# reading a MATLAB .mat, whichever version it is
# ----------------------------------------------------------------------
def _load_mat(path: Path) -> Any:
    """The contents of a ``.mat``, v7 or v7.3.

    Returns something ``_field`` can read: a dict for v7, an open-and-read
    HDF5 tree converted to nested dicts for v7.3.
    """
    from scipy.io import loadmat

    try:
        return loadmat(str(path), struct_as_record=False, squeeze_me=True)
    except NotImplementedError:
        # scipy's own signal for "this is v7.3, use an HDF5 reader"
        return _load_mat_v73(path)


def _load_mat_v73(path: Path) -> dict[str, Any]:
    """A v7.3 (HDF5) ``.mat`` as nested dicts, with MATLAB's axis order restored."""
    import h5py

    with h5py.File(str(path), "r") as handle:
        return {key: _h5_value(handle[key], handle) for key in handle if key != "#refs#"}


def _h5_value(node: Any, root: Any) -> Any:
    """One node of a v7.3 file: a group becomes a dict, a dataset an array."""
    import h5py

    if isinstance(node, h5py.Group):
        return {key: _h5_value(node[key], root) for key in node}

    data = node[()]
    if isinstance(data, np.ndarray) and data.dtype == object:
        # A cell array or struct array: each element is a reference into #refs#.
        return [_h5_value(root[ref], root) for ref in data.ravel()]
    if isinstance(data, np.ndarray) and data.ndim > 1:
        # MATLAB reverses the dimension order when it writes HDF5; put it back
        # so downstream indexing means what it means on the MATLAB side.
        return np.transpose(data)
    return data


def _field(container: Any, name: str) -> Any:
    """Field NAME of a loaded ``.mat`` value, or None.

    Reads a dict (v7.3, and the top level of a v7 file) and a scipy
    ``mat_struct`` (v7 nested structs) the same way, so callers do not have to
    know which reader produced the value.
    """
    if container is None:
        return None
    if isinstance(container, dict):
        return container.get(name)
    value = getattr(container, name, None)
    if value is None and hasattr(container, "_fieldnames"):
        return None
    return value


#: The readable spelling beside MATLAB's.
unit_stats = unitstats
