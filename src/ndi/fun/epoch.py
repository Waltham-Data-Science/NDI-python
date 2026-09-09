"""
ndi.fun.epoch - ndi_epoch_epoch utility functions.

MATLAB equivalents: +ndi/+fun/+epoch/epochid2element.m, filename2epochid.m
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np


def epochid2element(
    session: Any,
    epoch_ids: list[str],
    element_name: str = "",
    element_type: str = "",
) -> dict[str, list[Any]]:
    """Find elements containing specified epoch IDs.

    MATLAB equivalent: ndi.fun.epoch.epochid2element

    This used to read ``element.epoch_table`` out of the stored element
    DOCUMENTS. There is no such field: it appears in no document schema and
    nothing in this tree ever writes one, so the lookup came back empty for
    every epoch id ever passed in. MATLAB asks the ELEMENT OBJECT for its
    ``epochtable()``, which is built from the epoch files, and so does this
    now.

    Args:
        session: An NDI session instance.
        epoch_ids: List of epoch ID strings to search for.
        element_name: Optional name filter for elements.
        element_type: Optional type filter for elements.

    Returns:
        Dict mapping each epoch_id to a list of matching elements. MATLAB
        returns a cell array the same size as the input; a dict keyed by the
        epoch id is the same information in the shape a Python caller
        indexes, as in :func:`filename2epochid`.

    Warns:
        UserWarning: naming any epoch id no element claims, as MATLAB does.
    """
    filters: dict[str, str] = {}
    if element_name:
        filters["element.name"] = element_name
    if element_type:
        # The type filter used to look for element_type among
        # document_class.class_list, a key element documents do not have --
        # so an empty list was searched and EVERY element was skipped
        # whenever a type was given. MATLAB filters on element.type.
        filters["element.type"] = element_type

    elements = session.getelements(**filters)

    result: dict[str, list[Any]] = {eid: [] for eid in epoch_ids}
    wanted = {eid.lower(): eid for eid in epoch_ids}

    for element in elements:
        try:
            epoch_table, _ = element.epochtable()
        except Exception:
            # One element whose epoch files cannot be read must not cost the
            # rest their answer.
            continue
        for entry in epoch_table or []:
            epoch_id = entry.get("epoch_id", "") if isinstance(entry, dict) else ""
            key = wanted.get(str(epoch_id).lower())
            if key is not None and element not in result[key]:
                result[key].append(element)

    missing = [eid for eid in epoch_ids if not result[eid]]
    if missing:
        warnings.warn(
            "No element was found matching the epoch id(s):\n " + "\n".join(missing),
            stacklevel=2,
        )

    return result


def filename2epochid(
    session: Any,
    filenames: list[str],
) -> dict[str, list[str]]:
    """Map filenames to their epoch IDs by searching DAQ epoch tables.

    MATLAB equivalent: ndi.fun.epoch.filename2epochid

    Args:
        session: An NDI session instance.
        filenames: List of filename strings.

    Returns:
        Dict mapping each filename to a list of matching epoch IDs.
    """
    from ndi.query import ndi_query

    # Search for DAQ system documents
    docs = session.database_search(ndi_query("").isa("daq_system"))

    result: dict[str, list[str]] = {fn: [] for fn in filenames}

    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        et = props.get("daqsystem", {}).get("epoch_table", [])
        if not isinstance(et, list):
            et = []

        for entry in et:
            if not isinstance(entry, dict):
                continue
            epoch_id = entry.get("epoch_id", "")
            underlying = entry.get("underlying_files", [])
            if isinstance(underlying, str):
                underlying = [underlying]
            for uf in underlying:
                if not isinstance(uf, str):
                    continue
                for fn in filenames:
                    if fn in uf:
                        result[fn].append(epoch_id)

    return result


def t0_t1cell2array(
    t0t1_in: list | Any,
) -> np.ndarray:
    """Convert a list of ``[t0, t1]`` interval pairs to a 2xN numpy array.

    MATLAB equivalent: ndi.fun.doc.t0_t1cell2array

    Each input pair becomes a column: ``result[:, k] == [t0_k, t1_k]``. This
    matches MATLAB's schema for ``element_epoch.t0_t1`` (``parameters:
    [2, NaN]``, i.e. 2 rows x N columns, one column per epoch clocktype).

    Args:
        t0t1_in: List of ``[t0, t1]`` pairs. Each element can be a list,
            tuple, or array of two numbers.

    Returns:
        Numpy array of shape ``(2, N)`` where N is the number of intervals.
        Row 0 holds the t0's, row 1 holds the t1's. Returns an empty
        ``(2, 0)`` array if input is empty.

    Example:
        >>> t0_t1cell2array([[0.0, 1.5], [2.0, 3.5]])
        array([[0. , 2. ],
               [1.5, 3.5]])
    """
    if not t0t1_in:
        return np.empty((2, 0), dtype=float)

    result = np.zeros((2, len(t0t1_in)), dtype=float)
    for k, pair in enumerate(t0t1_in):
        result[0, k] = pair[0]
        result[1, k] = pair[1]

    return result


# Backward-compatible alias
t0_t1_to_array = t0_t1cell2array
