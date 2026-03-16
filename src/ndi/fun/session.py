"""
ndi.fun.session - ndi_session comparison utilities.

MATLAB equivalent: +ndi/+fun/+session/diff.m
"""

from __future__ import annotations

from typing import Any

from .doc import diff as doc_diff


def diff(
    session1: Any,
    session2: Any,
    exclude_fields: list[str] = None,
    *,
    verbose: bool = True,
    recheckFileReport: list | None = None,
) -> dict[str, Any]:
    """Compare two sessions for document differences.

    MATLAB equivalent: ndi.fun.session.diff

    Args:
        session1: First session.
        session2: Second session.
        exclude_fields: Field paths to exclude (defaults to
            ``['base.session_id']``).
        verbose: If True (default), print progress information.
        recheckFileReport: Optional list of previous file report
            entries to recheck.

    Returns:
        Dict with ``'equal'``, ``'only_in_s1'``, ``'only_in_s2'``,
        ``'common_count'``, ``'mismatches'``.
    """
    if exclude_fields is None:
        exclude_fields = ["base.session_id"]

    from ndi.query import ndi_query

    if verbose:
        print("Searching session 1 for documents...")
    docs1 = session1.database_search(ndi_query("").isa("base"))
    if verbose:
        print("Searching session 2 for documents...")
    docs2 = session2.database_search(ndi_query("").isa("base"))

    def _doc_id(doc: Any) -> str:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            return props.get("base", {}).get("id", "")
        return ""

    map1 = {_doc_id(d): d for d in docs1 if _doc_id(d)}
    map2 = {_doc_id(d): d for d in docs2 if _doc_id(d)}

    ids1 = set(map1.keys())
    ids2 = set(map2.keys())

    only_s1 = sorted(ids1 - ids2)
    only_s2 = sorted(ids2 - ids1)
    common = ids1 & ids2

    if verbose:
        print(
            f"Found {len(docs1)} docs in session 1, {len(docs2)} in session 2. "
            f"{len(common)} in common, {len(only_s1)} only in s1, {len(only_s2)} only in s2."
        )
        print(f"Comparing {len(common)} common documents...")

    mismatches: list[dict[str, Any]] = []
    for doc_id in sorted(common):
        result = doc_diff(map1[doc_id], map2[doc_id], ignoreFields=exclude_fields)
        if not result["equal"]:
            mismatches.append(
                {
                    "doc_id": doc_id,
                    "details": result["details"],
                }
            )

    if verbose:
        if mismatches:
            print(f"Found {len(mismatches)} mismatched documents.")
        else:
            print("All common documents match.")

    return {
        "equal": len(only_s1) == 0 and len(only_s2) == 0 and len(mismatches) == 0,
        "only_in_s1": only_s1,
        "only_in_s2": only_s2,
        "common_count": len(common),
        "mismatches": mismatches,
    }
