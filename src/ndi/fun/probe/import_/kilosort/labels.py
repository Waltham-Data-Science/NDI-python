"""
ndi.fun.probe.import_.kilosort.labels - read curated cluster labels from kilosort/Phy output.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/labels.m

NAMING DIVERGENCE: the MATLAB package is ``+ndi/+fun/+probe/+import/+kilosort``.
``import`` is a reserved word in Python, so the subpackage directory is named
``import_`` and the importable path is
``ndi.fun.probe.import_.kilosort.labels``.
"""

from __future__ import annotations

import csv
from pathlib import Path

# Candidate label files, in order of preference (manual Phy curation first), and
# the name of the label column to read from each. Mirrors labels.m exactly.
_CANDIDATES = ("cluster_group.tsv", "cluster_KSLabel.tsv", "cluster_info.tsv")
_LABEL_COLUMNS = ("group", "KSLabel", "group")


def labels(kdir: str | Path) -> tuple[list[int], list[str]]:
    """Read the per-cluster curation labels from a kilosort/Phy output directory.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.labels``

    Looks for (in order of preference) ``cluster_group.tsv`` (manual Phy
    curation), ``cluster_KSLabel.tsv`` (automatic Kilosort labels), or
    ``cluster_info.tsv``.

    Args:
        kdir: The kilosort/Phy output directory.

    Returns:
        Tuple ``(cluster_ids, cluster_labels)`` where ``cluster_ids`` is a list
        of integer cluster ids and ``cluster_labels`` is the parallel list of
        their labels (e.g. ``"good"``, ``"mua"``, ``"noise"``, or any custom tag
        applied during curation).

    Raises:
        FileNotFoundError: If none of the candidate label files are present.
    """
    kdir = Path(kdir)

    for candidate, label_column in zip(_CANDIDATES, _LABEL_COLUMNS):
        f = kdir / candidate
        if not f.is_file():
            continue

        with open(f, newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            rows = [row for row in reader if row]

        if not rows:
            continue

        header = rows[0]
        # the id column is named 'cluster_id' (or 'id' in some Phy versions)
        idcol = _find_column(header, ("cluster_id", "id"))
        labcol = _find_column(header, (label_column,))
        if labcol is None:
            # fall back to any column literally called 'group'
            labcol = _find_column(header, ("group",))
        if idcol is None or labcol is None:
            continue

        cluster_ids: list[int] = []
        cluster_labels: list[str] = []
        for row in rows[1:]:
            if idcol >= len(row) or labcol >= len(row):
                continue
            cluster_ids.append(int(float(row[idcol])))
            cluster_labels.append(str(row[labcol]))
        return cluster_ids, cluster_labels

    raise FileNotFoundError(
        "No cluster label file (cluster_group.tsv, cluster_KSLabel.tsv, or "
        f"cluster_info.tsv) found in {kdir}."
    )


def _find_column(header: list[str], names: tuple[str, ...]) -> int | None:
    """Return the index of the first header entry matching *names* (case-insensitive)."""
    lowered = [h.strip().lower() for h in header]
    for name in names:
        target = name.lower()
        for i, h in enumerate(lowered):
            if h == target:
                return i
    return None
