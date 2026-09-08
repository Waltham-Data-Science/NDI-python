"""
ndi.fun.session - ndi_session comparison utilities.

MATLAB equivalent: +ndi/+fun/+session/diff.m
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from .doc import diff as doc_diff

__all__ = ["diff"]


def _sizeless_entry(doc1: Any, doc2: Any, fname: str, fuid1: str, fuid2: str) -> dict[str, Any]:
    """Build one ``fileDifferences`` record, MATLAB's field-for-field.

    MATLAB seeds every field before it tries to open anything, so an entry
    that is later discarded still has the same shape as one that is kept.
    ``documentA_size`` starts at NaN and stays NaN when the file could not
    be opened, which is how a caller tells "no size" from "size zero".
    """
    return {
        "documentA_uid": doc1.id,
        "documentB_uid": doc2.id,
        "sessionA_id": doc1.session_id,
        "sessionB_id": doc2.session_id,
        "documentA_fuid": fuid1,
        "documentA_fname": fname,
        "documentB_fuid": fuid2,
        "documentB_fname": fname,
        "documentA_size": math.nan,
        "documentB_size": math.nan,
        "documentA_errormsg": "",
        "documentB_errormsg": "",
        "documentDiff": "",
    }


def _measure(opener: Callable[[Any, str], Any], doc: Any, fname: str) -> tuple[Any, float, str]:
    """Open one file and measure it, returning MATLAB's (handle, size, errormsg).

    MATLAB wraps each open in its own try/catch and records ``e.message``
    rather than raising, so one unreadable file does not abandon the
    comparison of every later one.
    """
    try:
        handle = opener(doc, fname)
        handle.seek(0, 2)
        size = float(handle.tell())
        handle.seek(0)
        return handle, size, ""
    except Exception as exc:  # noqa: BLE001 -- MATLAB catches and records too
        return None, math.nan, str(exc)


def _close(access: Any, handle: Any) -> None:
    if handle is None:
        return
    try:
        access.close(handle)
    except Exception:  # noqa: BLE001
        pass


class _Access:
    """Open and close a document's files through one session.

    MATLAB writes ``S1.database_openbinarydoc(...)`` at the point of use, so
    a session that cannot open binary documents is only a problem for a
    document that actually HAS files. Binding the method up front instead
    would fail on the empty case, which is most of them.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def open(self, doc: Any, fname: str) -> Any:
        return self._session.database_openbinarydoc(doc, fname)

    def close(self, handle: Any) -> None:
        self._session.database_closebinarydoc(handle)


def _compare_one_file(
    doc1: Any,
    doc2: Any,
    fname: str,
    access1: Any,
    access2: Any,
) -> dict[str, Any] | None:
    """Compare one file across two documents; return an entry, or None if it matches.

    Mirrors the inner loop both MATLAB ``diff`` functions share: a missing
    fuid is reported as 'not present' WITHOUT attempting to open the file,
    each side is opened and sized independently, and the bytes are compared
    only when both handles were obtained. An entry is kept when either side
    errored or the contents differ -- a file that is fine on both sides
    leaves no trace in the report.
    """
    from ndi.util import getHexDiffFromFileObj

    fuid1 = doc1.get_fuid(fname)
    fuid2 = doc2.get_fuid(fname)
    entry = _sizeless_entry(doc1, doc2, fname, fuid1, fuid2)

    handle1 = handle2 = None
    if not fuid1:
        entry["documentA_errormsg"] = "not present"
    else:
        handle1, entry["documentA_size"], entry["documentA_errormsg"] = _measure(
            access1.open, doc1, fname
        )

    if not fuid2:
        entry["documentB_errormsg"] = "not present"
    else:
        handle2, entry["documentB_size"], entry["documentB_errormsg"] = _measure(
            access2.open, doc2, fname
        )

    if handle1 is not None and handle2 is not None:
        identical, diff_output = getHexDiffFromFileObj(handle1, handle2)
        if not identical:
            entry["documentDiff"] = diff_output

    _close(access1, handle1)
    _close(access2, handle2)

    if entry["documentA_errormsg"] or entry["documentB_errormsg"] or entry["documentDiff"]:
        return entry
    return None


def _file_differences(
    doc1: Any,
    doc2: Any,
    access1: Any,
    access2: Any,
) -> list[dict[str, Any]]:
    """Compare every file named by either document. MATLAB's ``union`` sorts."""
    names = sorted(set(doc1.current_file_list()) | set(doc2.current_file_list()))
    out = []
    for fname in names:
        entry = _compare_one_file(doc1, doc2, fname, access1, access2)
        if entry is not None:
            out.append(entry)
    return out


def _recheck_entries(report: Any) -> list[dict[str, Any]]:
    """Pull the file entries out of a previous report.

    MATLAB is given the whole report and reads ``.fileDifferences``. A bare
    list is accepted too, because the old Python signature typed this
    parameter ``list | None`` and callers may already be passing one.
    """
    if report is None:
        return []
    if isinstance(report, dict):
        return list(report.get("fileDifferences", []))
    return list(report)


def _empty_report() -> dict[str, Any]:
    return {
        "documentsInAOnly": [],
        "documentsInBOnly": [],
        "mismatchedDocuments": [],
        "fileDifferences": [],
        "common_count": 0,
    }


def _doc_by_id(container: Any, doc_id: str) -> Any | None:
    """Fetch one document by id, as MATLAB's recheck branch does."""
    from ndi.query import ndi_query

    found = container.database_search(ndi_query("base.id", "exact_string", doc_id, ""))
    return found[0] if found else None


def _all_documents(container: Any) -> list[Any]:
    """Every document, via MATLAB's own query.

    MATLAB uses ``ndi.query('base.id','regexp','(.*)')`` -- every document
    that has a base.id. The port previously used ``ndi_query('').isa('base')``,
    a different question (class membership), which is why this is spelled
    out rather than left to a convenience helper.
    """
    from ndi.query import ndi_query

    return container.database_search(ndi_query("base.id", "regexp", "(.*)"))


def _id_map(docs: list[Any]) -> dict[str, Any]:
    return {d.id: d for d in docs if d.id}


def diff(
    session1: Any,
    session2: Any,
    exclude_fields: list[str] = None,
    *,
    verbose: bool = True,
    recheckFileReport: Any = None,
) -> dict[str, Any]:
    """Compare two sessions for document AND file differences.

    MATLAB equivalent: ``ndi.fun.session.diff``

    Args:
        session1: First session (MATLAB's S1).
        session2: Second session (MATLAB's S2).
        exclude_fields: Field paths to skip when comparing documents.
            Defaults to ``['base.session_id']``, which is what MATLAB
            hard-codes. Python-only; MATLAB offers no way to change it.
        verbose: If True (default), print progress, as MATLAB does.
        recheckFileReport: A previous report from this function. When given,
            only the files named in its ``fileDifferences`` are re-checked
            and the document comparison is skipped entirely.

    Returns:
        A report dict with MATLAB's four fields:

        ``documentsInAOnly`` / ``documentsInBOnly``
            Sorted lists of document ids found in only one session.
        ``mismatchedDocuments``
            List of ``{'id', 'mismatch'}`` for documents present in both
            whose contents differ.
        ``fileDifferences``
            List of records describing each file that is missing, could not
            be read, or whose bytes differ. See :func:`_sizeless_entry`
            for the fields.

        Plus two Python-only conveniences: ``equal``, True when all four
        are empty, and ``common_count``, the number of documents compared --
        which MATLAB computes and prints but does not return.
    """
    if exclude_fields is None:
        exclude_fields = ["base.session_id"]

    report = _empty_report()
    access1 = _Access(session1)
    access2 = _Access(session2)

    if recheckFileReport is not None:
        entries = _recheck_entries(recheckFileReport)
        if verbose:
            print(f"Re-checking {len(entries)} file differences from the provided report...")

        for entry in entries:
            doc1 = _doc_by_id(session1, entry["documentA_uid"])
            doc2 = _doc_by_id(session2, entry["documentB_uid"])
            if doc1 is None or doc2 is None:
                if verbose:
                    print("Could not find document(s) for recheck.")
                continue

            found = _compare_one_file(doc1, doc2, entry["documentA_fname"], access1, access2)
            if found is not None:
                report["fileDifferences"].append(found)
                if verbose:
                    _report_verbose(found, doc1.id)

        report["equal"] = not report["fileDifferences"]
        return report

    docs1 = _all_documents(session1)
    docs2 = _all_documents(session2)

    map1 = _id_map(docs1)
    map2 = _id_map(docs2)
    ids1, ids2 = set(map1), set(map2)

    report["documentsInAOnly"] = sorted(ids1 - ids2)
    report["documentsInBOnly"] = sorted(ids2 - ids1)
    common = sorted(ids1 & ids2)
    report["common_count"] = len(common)

    if verbose:
        print(
            f"Found {len(ids1)} documents in the first session and "
            f"{len(ids2)} documents in the second."
        )
        print(f"Comparing {len(common)} common documents...")

    for i, doc_id in enumerate(common, start=1):
        if verbose and i % 500 == 0:
            print(f"...examined {i} documents...")

        doc1 = map1[doc_id]
        doc2 = map2[doc_id]

        result = doc_diff(doc1, doc2, ignoreFields=exclude_fields, checkFileList=True)
        if not result["equal"]:
            report["mismatchedDocuments"].append(
                {"id": doc_id, "mismatch": " ".join(result["details"])}
            )

        report["fileDifferences"].extend(_file_differences(doc1, doc2, access1, access2))

    report["equal"] = not (
        report["documentsInAOnly"]
        or report["documentsInBOnly"]
        or report["mismatchedDocuments"]
        or report["fileDifferences"]
    )
    return report


def _report_verbose(entry: dict[str, Any], doc_id: str) -> None:
    """MATLAB's per-entry recheck printout."""
    if entry["documentA_errormsg"]:
        print(
            f"File {entry['documentA_fname']} in document {doc_id} "
            f"has an error: {entry['documentA_errormsg']}"
        )
    if entry["documentB_errormsg"]:
        print(
            f"File {entry['documentB_fname']} in document {doc_id} "
            f"has an error: {entry['documentB_errormsg']}"
        )
    if entry["documentDiff"]:
        print(f"File {entry['documentA_fname']} in document {doc_id} has a mismatch.")
