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
    string listing, for each repository where updating touches the user's
    work, the changed files, the untracked files in the way of files the
    update adds, and the number of local commits, followed by what updating
    does to each. Returns ``""`` if there are none. Other untracked files are
    not listed: the update leaves them where they are.
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
        if m["BlockingFiles"]:
            counts.append(f"{len(m['BlockingFiles'])} untracked file(s) in the way of new files")
        if m["CommitsAhead"] > 0:
            counts.append(f"{m['CommitsAhead']} local commit(s)")
        parts.append(f"\n{m['Name']} ({m['Path']}): " + ", ".join(counts))

        files = [f"  changed:    {f}" for f in m["ChangedFiles"]] + [
            f"  in the way: {f}" for f in m["BlockingFiles"]
        ]
        parts.extend(files[:MaxFiles])
        if len(files) > MaxFiles:
            parts.append(f"  ... and {len(files) - MaxFiles} more")

    parts.append(
        "\nIf you update: changed files are stashed and put back after the "
        "update (if they no longer apply cleanly, 'git stash list' in that "
        "folder still has them), and local commits are merged with the "
        "update, which can stop with a merge conflict. An untracked file in "
        "the way of a file the update adds must be moved or renamed first: "
        "git will not overwrite it. Your other untracked files are left alone."
    )
    return "\n".join(parts)
