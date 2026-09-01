"""
ndi.fun.ensemble - Operations on spiking-neuron ensembles.

MATLAB equivalent: +ndi/+fun/+ensemble/

Currently provides :func:`filter`, the one function of the MATLAB package that
is a pure in-memory operation on an ensemble structure.

The other eight are **not** ported yet, and most of them cannot be. They go
through ``ndi.element.ensemble``, which does not exist on this side, and that
class in turn needs the element-timeseries binary store to round-trip
irregular timestamps. It does not: ``ndi_element_timeseries._store_timeseries_data``
writes only ``datapoints.tobytes()`` and drops the timepoints, and the read
path reconstructs times as ``arange(len(data)) / samplerate``. That is fine for
a regularly sampled series and wrong for a marked point process, which is
exactly what an ensemble epoch stores -- the spike times *are* the data and are
not on a grid. Building ``spikeMatrix`` on top of it would return silently
wrong spike times.

``filter`` has no such dependency: it takes the structure ``read`` returns and
subsets it.

The ensemble structure
----------------------
A mapping with:

``activity``
    An N-neurons-by-Smax matrix (dense or scipy sparse); ``activity[i, n]`` is
    the time of the n-th spike of neuron i, zero-padded on the right.
``neuron_ids``, ``neuron_names``
    Sequences of length N, in the row order of ``activity``.
``epoch``
    The epoch id.
``info``
    A mapping; ``info['num_neurons']`` is updated by :func:`filter`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

__all__ = ["filter"]


def _member_mask(values: Sequence[Any], targets: Sequence[Any] | None) -> np.ndarray:
    """True where ``values[i]`` appears in *targets*."""
    mask = np.zeros(len(values), dtype=bool)
    if not targets:
        return mask
    wanted = set(targets)
    for i, value in enumerate(values):
        mask[i] = value in wanted
    return mask


def _index_mask(n: int, indices: Any) -> np.ndarray:
    """True at the **1-based** positions in *indices*.

    Indices are 1-based because the shared symmetry battery feeds the same
    case list to both languages, and MATLAB's ``IncludeIndex`` is 1-based. A
    0-based Python variant would make identical inputs mean different things
    in the two ports, which is the one thing the battery exists to prevent.
    """
    mask = np.zeros(n, dtype=bool)
    if indices is None:
        return mask
    arr = np.asarray(indices, dtype=float).ravel()
    if arr.size == 0:
        return mask
    if np.any((arr < 1) | (arr > n) | (arr != np.round(arr))):
        raise ValueError(f"Index values must be integers between 1 and {n}.")
    mask[arr.astype(int) - 1] = True
    return mask


def _keep_mask(n: int, keep: Any) -> np.ndarray:
    """True from either a length-N boolean mask or a 1-based index vector."""
    mask = np.zeros(n, dtype=bool)
    if keep is None:
        return mask
    arr = np.asarray(keep)
    if arr.size == 0:
        return mask
    if arr.dtype == bool:
        if arr.size != n:
            raise ValueError(f"A boolean Keep mask must have {n} elements.")
        return arr.ravel().astype(bool)
    return _index_mask(n, arr)


def _trim_columns(activity: Any) -> Any:
    """Drop all-zero trailing columns, keeping at least one.

    An activity matrix with **no rows** is returned unchanged, including its
    column count: MATLAB's ``isempty`` guard returns early on a 0-by-Smax
    matrix, so a filter that keeps nothing does not also collapse the width.
    """
    if activity is None:
        return activity
    if hasattr(activity, "toarray"):  # scipy sparse
        nonzero_cols = np.asarray((activity != 0).sum(axis=0)).ravel()
    else:
        activity = np.asarray(activity)
        if activity.ndim == 1:
            activity = activity.reshape(1, -1)
        nonzero_cols = (activity != 0).sum(axis=0)
    if activity.shape[0] == 0 or activity.shape[1] == 0:
        return activity
    occupied = np.flatnonzero(nonzero_cols)
    last_col = int(occupied[-1]) + 1 if occupied.size else 1
    return activity[:, :last_col]


def filter(  # noqa: A001 - mirrors ndi.fun.ensemble.filter
    E: Mapping[str, Any],
    *,
    include_names: Sequence[str] | None = None,
    exclude_names: Sequence[str] | None = None,
    include_index: Any = None,
    exclude_index: Any = None,
    include_ids: Sequence[str] | None = None,
    exclude_ids: Sequence[str] | None = None,
    keep: Any = None,
) -> dict[str, Any]:
    """Select a subset of the neurons in an ensemble structure.

    MATLAB equivalent: ``ndi.fun.ensemble.filter``

    Returns the same structure with only the kept neurons: the rows of
    ``activity`` and the entries of ``neuron_ids`` and ``neuron_names`` are
    subset, ``info['num_neurons']`` is updated, and all-zero trailing columns
    of ``activity`` are trimmed. Pure and in-memory -- no database access.

    **How the kept set is computed.** If any *include* criterion is given
    (*include_names*, *include_index*, *include_ids* or *keep*), the kept set
    starts as the **union** of everything those select; otherwise it starts as
    every neuron. Then every *exclude* criterion is removed. So **an exclude
    always beats an include**, including on the same neuron.

    Args:
        E: An ensemble structure, as returned by MATLAB's
            ``ndi.fun.ensemble.read``. Not modified.
        include_names: Keep neurons with these names (MATLAB ``IncludeNames``).
        exclude_names: Drop neurons with these names (``ExcludeNames``).
        include_index: Keep neurons at these **1-based** positions
            (``IncludeIndex``).
        exclude_index: Drop neurons at these 1-based positions
            (``ExcludeIndex``).
        include_ids: Keep neurons with these element ids (``IncludeIds``).
        exclude_ids: Drop neurons with these element ids (``ExcludeIds``).
        keep: An explicit selection: a length-N boolean mask or a vector of
            1-based indices (``Keep``). Counts as an include criterion.

    Returns:
        A new structure; the input is left alone.

    Raises:
        ValueError: If an index is not an integer in 1..N, or a boolean *keep*
            mask is the wrong length.
    """
    neuron_ids = list(E["neuron_ids"])
    neuron_names = list(E["neuron_names"])
    n = len(neuron_ids)

    has_include = bool(
        (include_names is not None and len(include_names))
        or (include_index is not None and np.asarray(include_index).size)
        or (include_ids is not None and len(include_ids))
        or (keep is not None and np.asarray(keep).size)
    )

    if has_include:
        mask = np.zeros(n, dtype=bool)
        mask |= _member_mask(neuron_names, include_names)
        mask |= _index_mask(n, include_index)
        mask |= _member_mask(neuron_ids, include_ids)
        mask |= _keep_mask(n, keep)
    else:
        mask = np.ones(n, dtype=bool)

    # Excludes always remove from the kept set.
    mask &= ~_member_mask(neuron_names, exclude_names)
    mask &= ~_index_mask(n, exclude_index)
    mask &= ~_member_mask(neuron_ids, exclude_ids)

    idx = np.flatnonzero(mask)

    out = dict(E)
    activity = E.get("activity")
    if activity is not None:
        if hasattr(activity, "tocsr"):
            selected = activity.tocsr()[idx, :]
        else:
            selected = np.asarray(activity)[idx, :]
        out["activity"] = _trim_columns(selected)
    out["neuron_ids"] = [neuron_ids[i] for i in idx]
    out["neuron_names"] = [neuron_names[i] for i in idx]

    info = E.get("info")
    if isinstance(info, Mapping) and "num_neurons" in info:
        new_info = dict(info)
        new_info["num_neurons"] = int(idx.size)
        out["info"] = new_info

    return out
