"""Compare two dataset summaries and return a report of differences.

MATLAB equivalent: ``ndi.util.compareDatasetSummary``

Compares two summary dicts (as produced by :func:`datasetSummary`) and
returns a list of human-readable difference strings.
"""

from __future__ import annotations

from typing import Any

from .compare_session_summary import compareSessionSummary


def _as_list(value: Any) -> list[Any]:
    """MATLAB's ensureCell/ensureCellStr: a lone value is a one-element list.

    MATLAB's jsondecode turns a one-element JSON array into a scalar, so both
    sides have to accept a bare value where a list is expected.
    """
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    if isinstance(value, list):
        return value
    return [value]


def _find_by_session_id(summaries: list[Any], session_id: str) -> dict[str, Any] | None:
    """Find the summary whose own sessionId matches, as MATLAB does."""
    for entry in summaries:
        if isinstance(entry, dict) and entry.get("sessionId") == session_id:
            return entry
    return None


def _find_document_count(counts: list[Any], session_id: str) -> Any:
    for entry in counts:
        if isinstance(entry, dict) and entry.get("sessionId") == session_id:
            return entry.get("count")
    return None


def compareDatasetSummary(
    summary1: dict[str, Any],
    summary2: dict[str, Any],
    *,
    excludeFiles: list[str] | None = None,
    excludeFields: list[str] | None = None,
) -> list[str]:
    """Compare two dataset summaries and return a report.

    MATLAB equivalent: ``ndi.util.compareDatasetSummary(s1, s2, ...)``

    Args:
        summary1: First dataset summary dict.
        summary2: Second dataset summary dict.
        excludeFiles: Filenames to ignore when comparing file lists
            within session summaries.
        excludeFields: Field names to skip entirely during comparison.

    Returns:
        List of difference strings. Empty list means summaries match.
    """
    if excludeFiles is None:
        excludeFiles = []
    if excludeFields is None:
        excludeFields = []

    report: list[str] = []

    # 1. Compare numSessions.  MATLAB RETURNS HERE on a mismatch -- "no point
    # continuing if session counts differ" -- and reports the missing-field
    # case separately.  Continuing produced a cascade of consequential
    # differences behind the one that mattered, and `.get(..., 0)` made a
    # summary with no numSessions field compare equal to one with no sessions.
    if "numSessions" not in excludeFields:
        has1 = "numSessions" in summary1
        has2 = "numSessions" in summary2
        if has1 and has2:
            n1 = summary1["numSessions"]
            n2 = summary2["numSessions"]
            if n1 != n2:
                report.append(f"numSessions differs: {n1} vs {n2}")
                return report
        elif has1 != has2:
            report.append("numSessions field is missing from one summary")
            return report

    # 2. Compare references
    if "references" not in excludeFields:
        refs1 = sorted(_as_list(summary1.get("references", [])))
        refs2 = sorted(_as_list(summary2.get("references", [])))
        if refs1 != refs2:
            report.append(f"references differ: {refs1} vs {refs2}")

    # 3. Compare sessionIds.  MATLAB returns here too: "can't match sessions
    # if IDs differ".
    ids1 = _as_list(summary1.get("sessionIds", []))
    ids2 = _as_list(summary2.get("sessionIds", []))
    if "sessionIds" not in excludeFields:
        if sorted(ids1) != sorted(ids2):
            report.append(f"sessionIds differ: {sorted(ids1)} vs {sorted(ids2)}")
            return report

    # 4. Compare per-session summaries.  MATLAB looks each session up by the
    # sessionId INSIDE the summary, on both sides; this zipped sessionIds
    # against sessionSummaries positionally, so any summary list that was not
    # in sessionIds order was compared against the wrong session.
    if "sessionSummaries" not in excludeFields:
        ss1 = _as_list(summary1.get("sessionSummaries", []))
        ss2 = _as_list(summary2.get("sessionSummaries", []))

        # Python-only consistency check, kept from the earlier implementation.
        # MATLAB never counts the summaries -- it works off numSessions and
        # sessionIds alone -- so a summary claiming one session while carrying
        # two summary structs passes there unnoticed. That can only happen to a
        # malformed summary, and saying so is more use than ignoring it.
        if len(ss1) != len(ss2):
            report.append(f"sessionSummaries count differs: {len(ss1)} vs {len(ss2)}")

        for sid in ids1:
            match1 = _find_by_session_id(ss1, sid)
            match2 = _find_by_session_id(ss2, sid)
            if match1 is None:
                report.append(f"No session summary found for session ID {sid} in summary1")
                continue
            if match2 is None:
                report.append(f"No session summary found for session ID {sid} in summary2")
                continue
            sub = compareSessionSummary(
                match1,
                match2,
                excludeFiles=excludeFiles,
                excludeFields=excludeFields,
            )
            for s in sub:
                report.append(f"Session {sid}: {s}")

    # 5. Compare document counts if both have them.  Not ported at all before,
    # so a MATLAB summary built with includeDocumentCounts carried a field
    # nothing here ever looked at.
    if (
        "documentCounts" not in excludeFields
        and "documentCounts" in summary1
        and "documentCounts" in summary2
    ):
        dc1 = _as_list(summary1["documentCounts"])
        dc2 = _as_list(summary2["documentCounts"])
        for sid in ids1:
            count1 = _find_document_count(dc1, sid)
            count2 = _find_document_count(dc2, sid)
            if count1 is not None and count2 is not None and count1 != count2:
                report.append(f"Document count mismatch for session {sid}: {count1} vs {count2}")

    return report
