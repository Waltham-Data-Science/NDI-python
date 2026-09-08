"""ndi_dataset summary utility for symmetry testing.

MATLAB equivalent: ``ndi.util.datasetSummary``

Creates a summary dict of an ``ndi.dataset.Dataset`` object containing key
fields and properties, intended for symmetry testing between NDI language
implementations.
"""

from __future__ import annotations

from typing import Any

from .session_summary import sessionSummary


def datasetSummary(
    dataset_obj: Any,
    *,
    includeDocumentCounts: bool = False,
) -> dict[str, Any]:
    """Create a summary structure of an ndi.dataset.Dataset object.

    MATLAB equivalent: ``ndi.util.datasetSummary(dataset_obj)``

    Args:
        dataset_obj: An NDI Dataset object.
        includeDocumentCounts: If true, also count the documents in each
            session and add them as a ``documentCounts`` list of
            ``{'sessionId': ..., 'count': ...}`` entries.  MATLAB has had
            this option since the function was written; without it here, a
            MATLAB-produced summary carrying ``documentCounts`` compared
            against a Python one reported the field as missing.

    Returns:
        Dict with keys: numSessions, references, sessionIds,
        sessionSummaries, and documentCounts when asked for.
    """
    refs, session_ids, *_ = dataset_obj.session_list()

    # Build a session summary for each session in the dataset
    session_summaries = []
    for sid in session_ids:
        sess = dataset_obj.open_session(sid)
        session_summaries.append(sessionSummary(sess))

    summary: dict[str, Any] = {
        "numSessions": len(refs),
        "references": refs,
        "sessionIds": session_ids,
        "sessionSummaries": session_summaries,
    }

    if includeDocumentCounts:
        from ..query import ndi_query

        document_counts = []
        for sid in session_ids:
            sess = dataset_obj.open_session(sid)
            docs = sess.database_search(ndi_query("base.id", "regexp", "(.*)"))
            document_counts.append({"sessionId": sid, "count": len(docs)})
        summary["documentCounts"] = document_counts

    return summary
