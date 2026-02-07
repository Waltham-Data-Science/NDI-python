"""
ndi.fun.dataset - Dataset comparison utilities.

MATLAB equivalent: +ndi/+fun/+dataset/diff.m
"""

from __future__ import annotations

from typing import Any

from .session import diff as session_diff


def diff(
    dataset1: Any,
    dataset2: Any,
    exclude_fields: list[str] = None,
) -> dict[str, Any]:
    """Compare two datasets for document and file differences.

    MATLAB equivalent: ndi.fun.dataset.diff

    Compares via the dataset's internal session.

    Args:
        dataset1: First dataset.
        dataset2: Second dataset.
        exclude_fields: Field paths to exclude.

    Returns:
        Dict with ``'equal'``, ``'session_diff'`` keys.
    """
    s1 = dataset1.session if hasattr(dataset1, "session") else dataset1
    s2 = dataset2.session if hasattr(dataset2, "session") else dataset2

    s_diff = session_diff(s1, s2, exclude_fields=exclude_fields)

    return {
        "equal": s_diff["equal"],
        "session_diff": s_diff,
    }
