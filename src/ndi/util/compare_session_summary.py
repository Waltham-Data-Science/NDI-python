"""Compare two session summaries and return a report of differences.

MATLAB equivalent: ``ndi.util.compareSessionSummary``

Compares two summary dicts (as produced by :func:`sessionSummary`) and
returns a list of human-readable difference strings.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def compareSessionSummary(
    summary1: dict[str, Any],
    summary2: dict[str, Any],
    *,
    excludeFiles: list[str] | None = None,
) -> list[str]:
    """Compare two session summaries and return a report.

    MATLAB equivalent: ``ndi.util.compareSessionSummary(s1, s2, ...)``

    Args:
        summary1: First session summary dict.
        summary2: Second session summary dict.
        excludeFiles: Filenames to ignore when comparing ``files``
            and ``filesInDotNDI`` fields.

    Returns:
        List of difference strings. Empty list means summaries match.
    """
    if excludeFiles is None:
        excludeFiles = []

    report: list[str] = []

    # 1. Fields check
    fields1 = set(summary1.keys())
    fields2 = set(summary2.keys())

    for f in sorted(fields1 - fields2):
        report.append(f"Field {f} is in summary1 but not summary2")
    for f in sorted(fields2 - fields1):
        report.append(f"Field {f} is in summary2 but not summary1")

    common_fields = sorted(fields1 & fields2)

    # 2. Compare common fields
    for field in common_fields:
        val1 = summary1[field]
        val2 = summary2[field]

        # Filter excluded files
        if excludeFiles and field in ("files", "filesInDotNDI"):
            if isinstance(val1, list):
                val1 = [v for v in val1 if v not in excludeFiles]
            if isinstance(val2, list):
                val2 = [v for v in val2 if v not in excludeFiles]

        # Handle empty values
        _empty1 = val1 is None or (isinstance(val1, (list, dict)) and len(val1) == 0)
        _empty2 = val2 is None or (isinstance(val2, (list, dict)) and len(val2) == 0)
        if _empty1 and _empty2:
            continue

        # Unwrap single-element lists for comparison
        if isinstance(val1, list) and not isinstance(val2, list) and len(val1) == 1:
            val1 = val1[0]
        elif isinstance(val2, list) and not isinstance(val1, list) and len(val2) == 1:
            val2 = val2[0]

        if isinstance(val1, list) and isinstance(val2, list):
            if len(val1) != len(val2):
                report.append(
                    f"Field {field} has different lengths in summary1 ({len(val1)}) "
                    f"and summary2 ({len(val2)})"
                )
                continue

            for j, (item1, item2) in enumerate(zip(val1, val2)):
                if isinstance(item1, str) and isinstance(item2, str):
                    s1 = re.sub(r"[\r\n]+", "", item1)
                    s2 = re.sub(r"[\r\n]+", "", item2)
                    if s1 != s2:
                        # Check if it's just an absolute path difference
                        n1 = os.path.basename(s1)
                        n2 = os.path.basename(s2)
                        if not (n1 and n1 == n2):
                            report.append(
                                f'Field {field}[{j}] differs: "{s1}" vs "{s2}"'
                            )
                elif isinstance(item1, dict) and isinstance(item2, dict):
                    sub = compareSessionSummary(item1, item2)
                    for s in sub:
                        report.append(f"Field {field}[{j}] struct diff: {s}")
                else:
                    if item1 != item2:
                        report.append(f"Field {field}[{j}] differs in content")

        elif isinstance(val1, dict) and isinstance(val2, dict):
            # Both are dicts — could be a single struct or a struct array
            sub = compareSessionSummary(val1, val2)
            for s in sub:
                report.append(f"Field {field} struct diff: {s}")

        elif isinstance(val1, str) and isinstance(val2, str):
            s1 = re.sub(r"[\r\n\t]+", "", val1)
            s2 = re.sub(r"[\r\n\t]+", "", val2)
            if s1 != s2:
                n1 = os.path.basename(s1)
                n2 = os.path.basename(s2)
                if not (n1 and n1 == n2):
                    report.append(f'Field {field} differs: "{s1}" vs "{s2}"')

        else:
            is_same = False
            if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                is_same = val1 == val2
            elif isinstance(val1, bool) and isinstance(val2, bool):
                is_same = val1 == val2
            else:
                is_same = val1 == val2

                # Fallback: compare JSON representations
                if not is_same:
                    try:
                        j1 = re.sub(r"[\r\n\t]+", "", json.dumps(val1, sort_keys=True))
                        j2 = re.sub(r"[\r\n\t]+", "", json.dumps(val2, sort_keys=True))
                        is_same = j1 == j2
                    except (TypeError, ValueError):
                        pass

            if not is_same:
                try:
                    v1s = json.dumps(val1)
                    v2s = json.dumps(val2)
                except (TypeError, ValueError):
                    v1s = "<unprintable>"
                    v2s = "<unprintable>"
                report.append(
                    f"Field {field} differs in value/object:\n"
                    f"  Val1: {v1s}\n  Val2: {v2s}"
                )

    return report
