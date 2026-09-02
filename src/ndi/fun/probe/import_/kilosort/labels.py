"""ndi.fun.probe.import.kilosort.labels - read curated cluster labels.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/labels.m``
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

__all__ = ["labels"]

#: The label files Phy and Kilosort write, in MATLAB's order of preference,
#: paired with the column each keeps its label in. Manual curation
#: (cluster_group.tsv) wins over Kilosort's automatic labels, which win over
#: the omnibus cluster_info.tsv -- a hand-curated label is the one the person
#: meant.
CANDIDATES = (
    ("cluster_group.tsv", "group"),
    ("cluster_KSLabel.tsv", "KSLabel"),
    ("cluster_info.tsv", "group"),
)

#: The column holding the cluster id. Phy has used both spellings.
ID_COLUMNS = ("cluster_id", "id")


def labels(kdir: str | Path) -> tuple[np.ndarray, list[str]]:
    """The curated cluster ids and their labels from a Phy output directory.

    Returns ``(cluster_ids, cluster_labels)`` -- a numeric array and a list of
    the same length, holding whatever tag the curator applied (``good``,
    ``mua``, ``noise``, or a custom one).

    Raises FileNotFoundError when no label file is present, as MATLAB errors:
    a sort with no labels is not a sort this importer can filter.
    """
    directory = Path(kdir)
    for filename, label_column in CANDIDATES:
        path = directory / filename
        if not path.is_file():
            continue
        rows = _read_tsv(path)
        if not rows:
            continue
        header = rows[0]
        id_index = _column_index(header, ID_COLUMNS)
        # MATLAB falls back to any column literally called 'group' when the
        # file's expected label column is missing -- cluster_info.tsv from
        # some Phy versions carries several label-ish columns.
        label_index = _column_index(header, (label_column,))
        if label_index is None:
            label_index = _column_index(header, ("group",))
        if id_index is None or label_index is None:
            continue
        ids = []
        found = []
        for row in rows[1:]:
            if len(row) <= max(id_index, label_index):
                continue
            try:
                ids.append(float(row[id_index]))
            except ValueError:
                continue
            found.append(str(row[label_index]))
        return np.asarray(ids, dtype=float), found

    raise FileNotFoundError(
        "No cluster label file (cluster_group.tsv, cluster_KSLabel.tsv, or "
        f"cluster_info.tsv) found in {directory}."
    )


def _read_tsv(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [row for row in csv.reader(handle, delimiter="\t") if row]


def _column_index(header: list[str], names: tuple[str, ...]) -> int | None:
    """The index of the first of NAMES in HEADER, matched case-insensitively."""
    lowered = [column.strip().lower() for column in header]
    for name in names:
        if name.lower() in lowered:
            return lowered.index(name.lower())
    return None
