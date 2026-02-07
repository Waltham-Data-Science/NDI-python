"""
ndi.fun.epoch - Epoch utility functions.

MATLAB equivalents: +ndi/+fun/+epoch/epochid2element.m, filename2epochid.m
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import numpy as np


def epochid2element(
    session: Any,
    epoch_ids: List[str],
    element_name: str = '',
    element_type: str = '',
) -> Dict[str, List[Any]]:
    """Find elements containing specified epoch IDs.

    MATLAB equivalent: ndi.fun.epoch.epochid2element

    Args:
        session: An NDI session instance.
        epoch_ids: List of epoch ID strings to search for.
        element_name: Optional name filter for elements.
        element_type: Optional type filter for elements.

    Returns:
        Dict mapping each epoch_id to a list of matching elements.
    """
    from ndi.query import Query

    # Get all elements
    q = Query('').isa('element')
    if element_name:
        q = q & (Query('element.name') == element_name)
    docs = session.database_search(q)

    result: Dict[str, List[Any]] = {eid: [] for eid in epoch_ids}

    for doc in docs:
        props = doc.document_properties if hasattr(doc, 'document_properties') else doc
        if not isinstance(props, dict):
            continue

        if element_type:
            classes = props.get('document_class', {}).get('class_list', [])
            type_names = [c.get('class_name', '') for c in classes]
            if element_type not in type_names:
                continue

        # Check epoch table
        et = props.get('element', {}).get('epoch_table', [])
        if not isinstance(et, list):
            et = []
        doc_epoch_ids = set()
        for entry in et:
            if isinstance(entry, dict):
                eid = entry.get('epoch_id', '')
                if eid:
                    doc_epoch_ids.add(eid.lower())

        for search_eid in epoch_ids:
            if search_eid.lower() in doc_epoch_ids:
                result[search_eid].append(doc)

    return result


def filename2epochid(
    session: Any,
    filenames: List[str],
) -> Dict[str, List[str]]:
    """Map filenames to their epoch IDs by searching DAQ epoch tables.

    MATLAB equivalent: ndi.fun.epoch.filename2epochid

    Args:
        session: An NDI session instance.
        filenames: List of filename strings.

    Returns:
        Dict mapping each filename to a list of matching epoch IDs.
    """
    from ndi.query import Query

    # Search for DAQ system documents
    docs = session.database_search(Query('').isa('daq_system'))

    result: Dict[str, List[str]] = {fn: [] for fn in filenames}

    for doc in docs:
        props = doc.document_properties if hasattr(doc, 'document_properties') else doc
        if not isinstance(props, dict):
            continue

        et = props.get('daqsystem', {}).get('epoch_table', [])
        if not isinstance(et, list):
            et = []

        for entry in et:
            if not isinstance(entry, dict):
                continue
            epoch_id = entry.get('epoch_id', '')
            underlying = entry.get('underlying_files', [])
            if isinstance(underlying, str):
                underlying = [underlying]
            for uf in underlying:
                if not isinstance(uf, str):
                    continue
                for fn in filenames:
                    if fn in uf:
                        result[fn].append(epoch_id)

    return result


def t0_t1_to_array(
    t0t1_in: Union[List, Any],
) -> np.ndarray:
    """Convert a list of ``[t0, t1]`` interval pairs to an Nx2 numpy array.

    MATLAB equivalent: ndi.fun.doc.t0_t1cell2array

    Converts epoch table t0/t1 cell entries (list of ``[t0, t1]`` pairs)
    into a numeric array suitable for inclusion in NDI documents.

    Args:
        t0t1_in: List of ``[t0, t1]`` pairs. Each element can be a list,
            tuple, or array of two numbers.

    Returns:
        Numpy array of shape ``(N, 2)`` where N is the number of intervals.
        Returns an empty ``(0, 2)`` array if input is empty.

    Example:
        >>> t0_t1_to_array([[0.0, 1.5], [2.0, 3.5]])
        array([[0. , 1.5],
               [2. , 3.5]])
    """
    if not t0t1_in:
        return np.empty((0, 2), dtype=float)

    result = np.zeros((len(t0t1_in), 2), dtype=float)
    for k, pair in enumerate(t0t1_in):
        result[k, 0] = pair[0]
        result[k, 1] = pair[1]

    return result
