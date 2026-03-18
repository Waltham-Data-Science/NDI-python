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


def _daq_detail_from_object(sys: Any) -> dict[str, Any]:
    """Extract DAQ detail dict from a fully-loaded DAQ system object."""
    details: dict[str, Any] = {}

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

    dr = getattr(sys, "daqreader", None)
    if dr is not None:
        details["daqreader_class"] = getattr(dr, "NDI_DAQREADER_CLASS", ndi_matlab_classname(dr))
    else:
        details["daqreader_class"] = ""

    try:
        details["epochNodes_daqsystem"] = sys.epochnodes()
    except Exception:
        details["epochNodes_daqsystem"] = []

    return details


def _daq_detail_from_document(session_obj: Any, doc: Any) -> dict[str, Any]:
    """Extract DAQ detail dict from a raw database document.

    Used as a fallback when the DAQ system object cannot be fully
    reconstructed (e.g. reader class not implemented in Python).
    """
    from ..query import ndi_query

    details: dict[str, Any] = {}

    # Look up the reader document via dependency
    reader_class = ""
    reader_id = doc.dependency_value("daqreader_id", error_if_not_found=False)
    if reader_id:
        reader_docs = session_obj.database_search(ndi_query("base.id") == reader_id)
        if reader_docs:
            props = reader_docs[0].document_properties
            if isinstance(props, dict):
                reader_class = props.get("daqreader", {}).get("ndi_daqreader_class", "")
    details["daqreader_class"] = reader_class

    # Look up the navigator document via dependency
    nav_class = ""
    nav_id = doc.dependency_value("filenavigator_id", error_if_not_found=False)
    if nav_id:
        nav_docs = session_obj.database_search(ndi_query("base.id") == nav_id)
        if nav_docs:
            props = nav_docs[0].document_properties
            if isinstance(props, dict):
                nav_class = props.get("filenavigator", {}).get("ndi_filenavigator_class", "")
    details["filenavigator_class"] = nav_class
    details["epochNodes_filenavigator"] = []
    details["epochNodes_daqsystem"] = []

    return details


def sessionSummary(session_obj: Any) -> dict[str, Any]:
    """Create a summary structure of an ndi.session object.

    MATLAB equivalent: ``ndi.util.sessionSummary(session_obj)``

    Args:
        session_obj: An NDI session object.

    Returns:
        Dict with keys: reference, sessionId, files, filesInDotNDI,
        daqSystemNames, daqSystemDetails, probes.
    """
    from ..query import ndi_query

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

    # 4. DAQ Systems — query all daqsystem documents from the database,
    #    then try full object reconstruction.  Fall back to reading raw
    #    document properties for systems whose reader/navigator classes
    #    are not yet implemented in Python.
    q = ndi_query("").isa("daqsystem") & (ndi_query("base.session_id") == session_obj.id())
    all_docs = session_obj.database_search(q)

    daq_names: list[str] = []
    daq_details: list[dict[str, Any]] = []

    for doc in all_docs:
        props = doc.document_properties
        name = ""
        if isinstance(props, dict):
            name = props.get("base", {}).get("name", "")
        daq_names.append(name)

        # Try full reconstruction first
        try:
            obj = session_obj._document_to_object(doc)
            if obj is not None:
                daq_details.append(_daq_detail_from_object(obj))
                continue
        except Exception:
            pass

        # Fallback: extract what we can from the raw documents
        daq_details.append(_daq_detail_from_document(session_obj, doc))

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
