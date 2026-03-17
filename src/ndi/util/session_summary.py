"""ndi_session summary utility for symmetry testing.

MATLAB equivalent: ``ndi.util.sessionSummary``

Creates a summary dict of an ``ndi.session`` object containing key fields
and properties, intended for symmetry testing between NDI language
implementations.
"""

from __future__ import annotations

import os
from typing import Any

from .classname import ndi_matlab_classname


def sessionSummary(session_obj: Any) -> dict[str, Any]:
    """Create a summary structure of an ndi.session object.

    MATLAB equivalent: ``ndi.util.sessionSummary(session_obj)``

    Args:
        session_obj: An NDI session object.

    Returns:
        Dict with keys: reference, sessionId, files, filesInDotNDI,
        daqSystemNames, daqSystemDetails, probes.
    """
    summary: dict[str, Any] = {}

    # 1. ndi_session basics
    summary["reference"] = session_obj.reference
    summary["sessionId"] = session_obj.id()

    # 2. Files in session path
    session_path = str(session_obj.path)
    if os.path.isdir(session_path):
        entries = os.listdir(session_path)
        summary["files"] = sorted(entries)
    else:
        summary["files"] = []

    # 3. Files in .ndi folder
    dot_ndi_path = os.path.join(session_path, ".ndi")
    if os.path.isdir(dot_ndi_path):
        entries = os.listdir(dot_ndi_path)
        summary["filesInDotNDI"] = sorted(entries)
    else:
        summary["filesInDotNDI"] = []

    # 4. DAQ Systems
    daqs = session_obj.daqsystem_load(name="(.*)")
    if daqs is None:
        daqs = []
    elif not isinstance(daqs, list):
        daqs = [daqs]

    daq_names: list[str] = []
    daq_details: list[dict[str, Any]] = []

    for sys in daqs:
        daq_names.append(getattr(sys, "name", ""))

        details: dict[str, Any] = {}

        # Get filenavigator class (use MATLAB-compatible name for symmetry)
        fn = getattr(sys, "filenavigator", None)
        if fn is not None:
            details["filenavigator_class"] = getattr(
                fn, "NDI_FILENAVIGATOR_CLASS", type(fn).__qualname__
            )
            try:
                details["epochNodes_filenavigator"] = fn.epochnodes()
            except Exception:
                details["epochNodes_filenavigator"] = []
        else:
            details["filenavigator_class"] = ""
            details["epochNodes_filenavigator"] = []

        # Get daqreader class (use MATLAB-compatible name for symmetry)
        dr = getattr(sys, "daqreader", None)
        if dr is not None:
            details["daqreader_class"] = getattr(
                dr, "NDI_DAQREADER_CLASS", ndi_matlab_classname(dr)
            )
        else:
            details["daqreader_class"] = ""

        # Get epoch nodes of daq system
        try:
            details["epochNodes_daqsystem"] = sys.epochnodes()
        except Exception:
            details["epochNodes_daqsystem"] = []

        daq_details.append(details)

    summary["daqSystemNames"] = daq_names
    summary["daqSystemDetails"] = daq_details

    # 5. Probes
    probes = session_obj.getprobes()
    probe_structs: list[dict[str, Any]] = []
    for p in probes:
        probe_structs.append(
            {
                "name": p.name,
                "reference": p.reference,
                "type": p.type,
                "subject_id": getattr(p, "subject_id", ""),
            }
        )

    summary["probes"] = probe_structs

    return summary
