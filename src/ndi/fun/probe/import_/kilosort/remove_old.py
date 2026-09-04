"""ndi.fun.probe.import.kilosort.removeold - remove a previous kilosort import.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/removeold.m``
"""

from __future__ import annotations

from typing import Any

__all__ = ["removeold", "remove_old"]


def removeold(session: Any, kc_doc: Any) -> None:
    """Remove the neurons imported under the ``kilosort_clusters`` document KC_DOC.

    Every ``neuron_extracellular`` document depending on KC_DOC is found, its
    neuron element and that element's epoch documents are removed, then the
    neuron documents themselves, then KC_DOC.

    ORDER MATTERS: the elements go before the document that named them, so a
    partial failure leaves orphaned provenance rather than neurons that point
    at nothing -- and the importer's own cleanup path knows how to clear an
    orphaned marker, while a neuron with no cluster document is invisible to
    it.
    """
    from .....query import ndi_query

    query = ndi_query("").isa("neuron_extracellular") & ndi_query("").depends_on(
        "spike_clusters_id", kc_doc.id
    )
    neuron_docs = session.database_search(query)

    for doc in neuron_docs:
        element_id = doc.dependency_value("element_id", error_if_not_found=False)
        if not element_id:
            continue
        # the element document itself, plus everything depending on it (its
        # epoch documents, and their binaries with them)
        element_query = (ndi_query("base.id") == element_id) | ndi_query("").depends_on(
            "element_id", element_id
        )
        element_docs = session.database_search(element_query)
        if element_docs:
            session.database_rm(element_docs)

    if neuron_docs:
        session.database_rm(neuron_docs)

    session.database_rm(kc_doc)


#: The readable spelling beside MATLAB's.
remove_old = removeold
