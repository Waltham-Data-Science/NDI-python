"""
ndi.fun.probe.location - Find probe location documents for an element.

MATLAB equivalent: +ndi/+fun/+probe/location.m
"""

from __future__ import annotations

from typing import Any


def location(
    session: Any,
    element: Any | str,
) -> tuple[list[Any], Any | None]:
    """Find probe location documents and probe object for an NDI element.

    MATLAB equivalent: ndi.fun.probe.location

    Given an NDI element *element*, traverse down the ``underlying_element``
    dependency tree until an :class:`ndi.probe.ndi_probe` object is found, then
    return all ``probe_location`` documents associated with that probe.

    Args:
        session: An NDI session or dataset object.
        element: An :class:`ndi.element.ndi_element` object **or** the string
            identifier of an element.

    Returns:
        Tuple of ``(probe_locations, probe_obj)`` where *probe_locations*
        is a list of probe-location documents and *probe_obj* is the
        :class:`ndi.probe.ndi_probe` found (or ``None`` if none was found).
    """
    from ndi.database_fun import ndi_document2ndi_object
    from ndi.probe import ndi_probe
    from ndi.query import ndi_query

    # Step 1: resolve string identifier to an element object
    if isinstance(element, str):
        docs = session.database_search(ndi_query("base.id", "exact_string", element, ""))
        if not docs:
            raise ValueError(f"Could not find an element with id '{element}'.")
        element = ndi_document2ndi_object(docs[0], session)

    # Step 2: traverse down to the probe
    current = element
    while not isinstance(current, ndi_probe):
        underlying = getattr(current, "underlying_element", None)
        if underlying is None:
            break
        if callable(underlying) and not isinstance(underlying, property):
            underlying = underlying()
        current = underlying

    probe_obj: Any | None = current if isinstance(current, ndi_probe) else None

    if probe_obj is None:
        return [], None

    # Step 3: get probe identifier
    probe_id = probe_obj.id
    if callable(probe_id):
        probe_id = probe_id()

    # Step 4: query for probe_location documents
    q = ndi_query("", "depends_on", "probe_id", probe_id) & ndi_query("", "isa", "probe_location")
    probe_locations = session.database_search(q)

    return probe_locations, probe_obj
