"""Helpers for reading values out of calculator-produced documents.

Python port of MATLAB ``ndi.fun.calc``.
"""

from __future__ import annotations

from typing import Any


def stimulus_tuningcurve_log(S: Any, doc: Any) -> str:
    """Retrieve the ``log`` string from a document's tuningcurve_calc dependency.

    Given a document carrying a ``stimulus_tuningcurve_id`` dependency created
    by ``ndi.calc.stimulus.tuningcurve``, look up that tuningcurve_calc
    document and return its ``log`` field.

    Returns the empty string when the dependency resolves to nothing, or when
    the resolved document has no ``log`` field -- matching MATLAB, which
    initialises ``log_str = ''`` and only overwrites it on a hit.

    Python port of MATLAB ``ndi.fun.calc.stimulus_tuningcurve_log``.
    """
    from ndi.query import ndi_query

    log_str = ""

    stim_tune_doc_id = doc.dependency_value("stimulus_tuningcurve_id")

    q1 = ndi_query("base.id", "exact_string", stim_tune_doc_id)
    q2 = ndi_query("").isa("tuningcurve_calc")

    stim_tune_doc = S.database_search(q1 & q2)

    if stim_tune_doc:
        first = stim_tune_doc[0]
        props = first.document_properties if hasattr(first, "document_properties") else first
        if isinstance(props, dict):
            tc = props.get("tuningcurve_calc", {})
            if isinstance(tc, dict) and "log" in tc:
                log_str = tc["log"]

    return log_str
