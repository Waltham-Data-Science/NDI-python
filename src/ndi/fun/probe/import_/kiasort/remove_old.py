"""ndi.fun.probe.import.kiasort.removeold - remove a previous KIASORT import.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/removeold.m``
"""

from __future__ import annotations

from typing import Any

__all__ = ["removeold", "remove_old"]


def removeold(S: Any, kc_doc: Any) -> None:  # noqa: N803 - MATLAB's parameter name
    """Remove the neurons imported under the ``kiasort_clusters`` document KC_DOC.

    Every ``neuron_extracellular`` document depending on KC_DOC is found, its
    neuron element and that element's epoch documents go, then the neuron
    documents, then KC_DOC.

    ORDER MATTERS: the elements go before the document that named them, so a
    partial failure leaves orphaned provenance rather than neurons pointing at
    nothing -- the importer knows how to clear an orphaned marker, while a
    neuron with no cluster document is invisible to it and would be duplicated
    on the next import.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.removeold``.
    """
    from .....fun.utils import identifier
    from .....query import ndi_query

    query = ndi_query("").isa("neuron_extracellular") & ndi_query("").depends_on(
        "spike_clusters_id", identifier(kc_doc)
    )
    neuron_docs = S.database_search(query)

    for doc in neuron_docs:
        element_id = doc.dependency_value("element_id", error_if_not_found=False)
        if not element_id:
            continue
        element_query = (ndi_query("base.id") == element_id) | ndi_query("").depends_on(
            "element_id", element_id
        )
        element_docs = S.database_search(element_query)
        if element_docs:
            S.database_rm(element_docs)

    if neuron_docs:
        S.database_rm(neuron_docs)

    S.database_rm(kc_doc)


#: The readable spelling beside MATLAB's.
remove_old = removeold
