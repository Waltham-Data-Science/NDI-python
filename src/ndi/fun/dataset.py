"""
ndi.fun.dataset - ndi_dataset comparison utilities.

MATLAB equivalent: +ndi/+fun/+dataset/diff.m
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .session import (
    _all_documents,
    _compare_one_file,
    _doc_by_id,
    _empty_report,
    _file_differences,
    _id_map,
    _recheck_entries,
    _report_verbose,
)

__all__ = ["diff"]


def _isequaln(a: Any, b: Any) -> bool:
    """MATLAB's ``isequaln``: structural equality in which NaN equals NaN.

    Recursive, because document properties nest. Plain ``==`` is wrong for
    documents that legitimately carry NaN -- a missing sample rate, an
    unmeasured size -- which would otherwise compare unequal to themselves
    and report every such document as mismatched.
    """
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(_isequaln(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(_isequaln(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _strip(props: dict[str, Any], exclude_fields: list[str] | None) -> dict[str, Any]:
    """Remove ``files`` and any caller-named dotted paths before comparing.

    MATLAB removes only ``files`` -- the file half is compared separately,
    byte by byte, so leaving it in would double-report every difference and
    also flag documents whose file UIDs differ for no reason but being
    stored twice. ``exclude_fields`` has no MATLAB counterpart.
    """
    out = copy.deepcopy(props)
    out.pop("files", None)
    for path in exclude_fields or []:
        node = out
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return out


class _SessionResolver:
    """Resolve which object can open a document's binary files.

    A dataset holds documents belonging to its member sessions as well as
    its own. MATLAB opens a document's files through the dataset itself
    when the document's session_id IS the dataset's id, and otherwise
    through ``open_session(session_id)`` -- and it keeps the opened session
    around while consecutive documents share it, which is why the dataset
    comparison sorts the common ids by session_id first. This does the
    same caching, so the sort still pays for itself.
    """

    def __init__(self, dataset: Any) -> None:
        self._dataset = dataset
        self._session_id: str | None = None
        self._target: Any = None

    def _resolve(self, doc: Any) -> Any:
        session_id = doc.session_id
        if session_id != self._session_id:
            self._session_id = session_id
            if session_id == self._dataset.id():
                self._target = self._dataset
            else:
                self._target = self._dataset.open_session(session_id)
        if self._target is None:
            raise FileNotFoundError(f"Session {session_id} is not open in this dataset.")
        return self._target

    def open(self, doc: Any, fname: str) -> Any:
        return self._resolve(doc).database_openbinarydoc(doc, fname)

    def close(self, handle: Any) -> None:
        if self._target is not None:
            self._target.database_closebinarydoc(handle)


def diff(
    dataset1: Any,
    dataset2: Any,
    exclude_fields: list[str] = None,
    *,
    verbose: bool = True,
    recheckFileReport: Any = None,
) -> dict[str, Any]:
    """Compare two datasets for document AND file differences.

    MATLAB equivalent: ``ndi.fun.dataset.diff``

    This is NOT ``ndi.fun.session.diff`` applied to the datasets' own
    sessions. MATLAB's dataset comparison is its own algorithm: it searches
    the datasets directly, so documents belonging to member sessions are
    included, opens each document's files through whichever session owns
    them, and compares document properties with ``isequaln`` rather than
    through ``ndi.fun.doc.diff``.

    Args:
        dataset1: First dataset (MATLAB's D1).
        dataset2: Second dataset (MATLAB's D2).
        exclude_fields: Extra dotted field paths to drop before comparing
            properties. Python-only; MATLAB drops ``files`` and nothing
            else, which is this argument's default of None.
        verbose: If True (default), print progress, as MATLAB does.
        recheckFileReport: A previous report from this function. When given,
            only the files named in its ``fileDifferences`` are re-checked.

    Returns:
        The same report shape as :func:`ndi.fun.session.diff`.
    """
    report = _empty_report(self_alias="session_diff")
    resolver1 = _SessionResolver(dataset1)
    resolver2 = _SessionResolver(dataset2)

    if recheckFileReport is not None:
        entries = _recheck_entries(recheckFileReport)
        if verbose:
            print(f"Re-checking {len(entries)} file differences from the provided report...")

        for entry in entries:
            doc1 = _doc_by_id(dataset1, entry["documentA_uid"])
            doc2 = _doc_by_id(dataset2, entry["documentB_uid"])
            if doc1 is None or doc2 is None:
                if verbose:
                    print("Could not find document(s) for recheck.")
                continue

            found = _compare_one_file(doc1, doc2, entry["documentA_fname"], resolver1, resolver2)
            if found is not None:
                report["fileDifferences"].append(found)
                if verbose:
                    _report_verbose(found, doc1.id)

        report["equal"] = not report["fileDifferences"]
        return report

    docs1 = _all_documents(dataset1)
    docs2 = _all_documents(dataset2)

    map1 = _id_map(docs1)
    map2 = _id_map(docs2)
    ids1, ids2 = set(map1), set(map2)

    report["documentsInAOnly"] = sorted(ids1 - ids2)
    report["documentsInBOnly"] = sorted(ids2 - ids1)

    # MATLAB sorts the common ids by owning session so that consecutive
    # documents share an opened session; the sort is stable, so ids within
    # one session keep the order intersect() gave them.
    common = sorted(sorted(ids1 & ids2), key=lambda i: map1[i].session_id)
    report["common_count"] = len(common)

    if verbose:
        print(
            f"Found {len(ids1)} documents in the first dataset and "
            f"{len(ids2)} documents in the second."
        )
        print(f"Comparing {len(common)} common documents...")

    for i, doc_id in enumerate(common, start=1):
        if verbose and i % 500 == 0:
            print(f"...examined {i} documents...")

        doc1 = map1[doc_id]
        doc2 = map2[doc_id]

        props1 = _strip(doc1.document_properties, exclude_fields)
        props2 = _strip(doc2.document_properties, exclude_fields)
        if not _isequaln(props1, props2):
            report["mismatchedDocuments"].append(
                {"id": doc_id, "mismatch": "Document properties do not match."}
            )

        report["fileDifferences"].extend(_file_differences(doc1, doc2, resolver1, resolver2))

    report["equal"] = not (
        report["documentsInAOnly"]
        or report["documentsInBOnly"]
        or report["mismatchedDocuments"]
        or report["fileDifferences"]
    )
    return report
