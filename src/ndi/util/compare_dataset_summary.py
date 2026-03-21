"""Compare two dataset summaries and return a report of differences.

MATLAB equivalent: ``ndi.util.compareDatasetSummary``

Compares two summary dicts (as produced by :func:`datasetSummary`) and
returns a list of human-readable difference strings.
"""

from __future__ import annotations

from typing import Any

from .compare_session_summary import compareSessionSummary


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

    # 1. Compare numSessions
    if "numSessions" not in excludeFields:
        n1 = summary1.get("numSessions", 0)
        n2 = summary2.get("numSessions", 0)
        if n1 != n2:
            report.append(
                f"numSessions differs: {n1} vs {n2}"
            )

    # 2. Compare references
    if "references" not in excludeFields:
        refs1 = sorted(summary1.get("references", []))
        refs2 = sorted(summary2.get("references", []))
        if refs1 != refs2:
            report.append(
                f"references differ: {refs1} vs {refs2}"
            )

    # 3. Compare sessionIds
    if "sessionIds" not in excludeFields:
        ids1 = sorted(summary1.get("sessionIds", []))
        ids2 = sorted(summary2.get("sessionIds", []))
        if ids1 != ids2:
            report.append(
                f"sessionIds differ: {ids1} vs {ids2}"
            )

    # 4. Compare sessionSummaries
    if "sessionSummaries" not in excludeFields:
        ss1 = summary1.get("sessionSummaries", [])
        ss2 = summary2.get("sessionSummaries", [])

        if len(ss1) != len(ss2):
            report.append(
                f"sessionSummaries count differs: {len(ss1)} vs {len(ss2)}"
            )
        else:
            # Match session summaries by sessionId when available,
            # otherwise compare by index order.
            ids1 = summary1.get("sessionIds", [])
            ids2 = summary2.get("sessionIds", [])

            if len(ids1) == len(ss1) and len(ids2) == len(ss2):
                # Build lookup by sessionId for summary2
                lookup2: dict[str, dict] = {}
                for sid, ss in zip(ids2, ss2):
                    lookup2[sid] = ss

                for i, sid in enumerate(ids1):
                    match = lookup2.get(sid)
                    if match is None:
                        report.append(
                            f"sessionSummaries: session {sid} not found in summary2"
                        )
                        continue
                    sub = compareSessionSummary(
                        ss1[i],
                        match,
                        excludeFiles=excludeFiles,
                        excludeFields=excludeFields,
                    )
                    for s in sub:
                        report.append(f"sessionSummaries[{sid}]: {s}")
            else:
                # Fallback: compare by index
                for i, (s1, s2) in enumerate(zip(ss1, ss2)):
                    sub = compareSessionSummary(
                        s1,
                        s2,
                        excludeFiles=excludeFiles,
                        excludeFields=excludeFields,
                    )
                    for s in sub:
                        report.append(f"sessionSummaries[{i}]: {s}")

    return report
