"""ndi.fun.probe.import.kiasort.labels - the units in a sort, and their labels.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/labels.m``

WHY EVERY UNIT IS "good"
Kilosort/Phy hand each cluster a curation tag -- good, mua, noise -- and
``ndi.fun.probe.import.kilosort.labels`` reads those tags off disk. A plain
KIASORT sort has no such tags: every cross-channel unit it emits is a
candidate single unit. So this labels them all "good", which is what makes
the importer's default quality filter (``["good"]``) import all of them
rather than none.

That is a real difference between the two sorters, not a placeholder: it
means a KIASORT import is unfiltered unless the user curates. The isolation
statistics KIASORT does produce are in ``Results.unit_stats``, ready for a
future quality mapping.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .unit_stats import CURATED_SUFFIX, unitstats

__all__ = ["labels", "DEFAULT_LABEL"]

#: The label every unit of an uncurated KIASORT sort is given.
DEFAULT_LABEL = "good"


def labels(
    kdir: str | Path,
    *,
    curated: bool = False,
    default_label: str = DEFAULT_LABEL,
) -> tuple[np.ndarray, list[str]]:
    """The unit ids in the KIASORT output KDIR, and a parallel list of labels.

    Unit ids come from the per-unit statistics when they are there, and from
    the distinct values in the per-spike output when they are not -- the two
    agree, but the statistics are the cheaper read and are the only place a
    unit with no spikes could still be listed.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.labels``.
    """
    stats = unitstats(kdir, CURATED_SUFFIX if curated else "")

    if stats is not None and stats.label.size:
        unit_ids = np.asarray(stats.label, dtype=float).ravel()
    else:
        from .results import results

        found = results(kdir, curated=curated, need_stats=False)
        unit_ids = np.unique(found.spike_units)

    return unit_ids, [str(default_label)] * int(unit_ids.size)
