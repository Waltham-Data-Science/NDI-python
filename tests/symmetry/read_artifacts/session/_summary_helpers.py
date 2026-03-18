"""Shared helpers for read_artifacts session symmetry tests."""

from __future__ import annotations

from typing import Any


def sort_daq_systems_by_name(summary: dict[str, Any]) -> None:
    """Sort daqSystemNames and daqSystemDetails in a summary by name.

    The database may return DAQ systems in different order on re-open.
    Sorting both summaries by name before comparison avoids spurious
    ordering mismatches.  Modifies *summary* in place.
    """
    names = summary.get("daqSystemNames", [])
    details = summary.get("daqSystemDetails", [])

    if len(names) == len(details) and len(names) > 1:
        paired = sorted(zip(names, details), key=lambda x: x[0])
        summary["daqSystemNames"] = [p[0] for p in paired]
        summary["daqSystemDetails"] = [p[1] for p in paired]
