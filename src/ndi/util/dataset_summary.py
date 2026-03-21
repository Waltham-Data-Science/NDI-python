"""ndi_dataset summary utility for symmetry testing.

MATLAB equivalent: ``ndi.util.datasetSummary``

Creates a summary dict of an ``ndi.dataset.Dataset`` object containing key
fields and properties, intended for symmetry testing between NDI language
implementations.
"""

from __future__ import annotations

from typing import Any

from .session_summary import sessionSummary


def datasetSummary(dataset_obj: Any) -> dict[str, Any]:
    """Create a summary structure of an ndi.dataset.Dataset object.

    MATLAB equivalent: ``ndi.util.datasetSummary(dataset_obj)``

    Args:
        dataset_obj: An NDI Dataset object.

    Returns:
        Dict with keys: numSessions, references, sessionIds,
        sessionSummaries.
    """
    refs, session_ids, *_ = dataset_obj.session_list()

    # Build a session summary for each session in the dataset
    session_summaries = []
    for sid in session_ids:
        sess = dataset_obj.open_session(sid)
        session_summaries.append(sessionSummary(sess))

    return {
        "numSessions": len(refs),
        "references": refs,
        "sessionIds": session_ids,
        "sessionSummaries": session_summaries,
    }
