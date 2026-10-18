"""ndi.update.modification_summary - describe the user's own code changes.

MATLAB counterpart: ``src/ndi/+ndi/+update/modificationSummary.m``
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, validate_call

__all__ = ["modificationSummary"]


@validate_call
def modificationSummary(result: dict[str, Any], MaxFiles: int = Field(10, gt=0)) -> str:
    """Describe the user's code changes that an update affects.

    MATLAB::

        TXT = ndi.update.modificationSummary(RESULT)
        TXT = ndi.update.modificationSummary(RESULT, MaxFiles=N)

    Given RESULT from :func:`ndi.update.check`, returns a human-readable
    string listing, for each repository with modifications, the changed
    files, the new files and the number of local commits, followed by what
    updating does to each kind of change. Returns ``""`` if there are none.
    At most ``MaxFiles`` files are listed per repository; the rest are
    counted.
    """
    mods = result.get("Modifications") or []
    if not mods:
        return ""

    parts = ["You have changed code that the update will touch:"]
    for m in mods:
        counts = []
        if m["ChangedFiles"]:
            counts.append(f"{len(m['ChangedFiles'])} changed file(s)")
        if m["NewFiles"]:
            counts.append(f"{len(m['NewFiles'])} new file(s)")
        if m["CommitsAhead"] > 0:
            counts.append(f"{m['CommitsAhead']} local commit(s)")
        parts.append(f"\n{m['Name']} ({m['Path']}): " + ", ".join(counts))

        files = [f"  changed: {f}" for f in m["ChangedFiles"]] + [
            f"  new:     {f}" for f in m["NewFiles"]
        ]
        parts.extend(files[:MaxFiles])
        if len(files) > MaxFiles:
            parts.append(f"  ... and {len(files) - MaxFiles} more")

    parts.append(
        "\nIf you update: changed files are stashed and put back after the "
        "update (if they no longer apply cleanly, 'git stash list' in that "
        "folder still has them), new files are left in place, and local "
        "commits are merged with the update, which can stop with a merge "
        "conflict."
    )
    return "\n".join(parts)
