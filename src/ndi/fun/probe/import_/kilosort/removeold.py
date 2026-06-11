"""
ndi.fun.probe.import_.kilosort.removeold - remove a previous kilosort import.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/removeold.m

NAMING DIVERGENCE: ``import`` is a reserved word in Python, so the subpackage
directory is named ``import_`` (see this package's ``__init__``).
"""

from __future__ import annotations

from typing import Any


def removeold(session: Any, kc_doc: Any) -> None:
    """Remove a previously imported set of kilosort neurons from a session.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.removeold``

    *kc_doc* is a ``kilosort_clusters`` ndi.document. This function finds every
    ``neuron_extracellular`` document that depends on *kc_doc* (via its
    ``spike_clusters_id`` dependency), removes those documents, removes the
    underlying neuron elements (including their epoch documents), and finally
    removes *kc_doc* itself.

    Args:
        session: The ndi.session to remove documents from.
        kc_doc: The ``kilosort_clusters`` ndi.document being removed.
    """
    from ndi.query import ndi_query

    # find neuron_extracellular docs that point at this cluster document
    q = ndi_query("").isa("neuron_extracellular") & ndi_query("").depends_on(
        "spike_clusters_id", kc_doc.id
    )
    neuron_docs = session.database_search(q)

    for ndoc in neuron_docs:
        element_id = ndoc.dependency_value("element_id", error_if_not_found=False)
        if element_id:
            # Remove the neuron element document and anything that depends on it
            # (its epoch documents). MATLAB issues this as a single OR query
            # (base.id==element_id OR depends_on element_id); NDI-python's
            # ndi_query does not compose an OR of a base.id match with a
            # depends_on clause correctly (it matches nothing), so we run the two
            # halves separately and union them. Identical result.
            elem_docs = session.database_search(ndi_query("base.id") == element_id)
            dep_docs = session.database_search(ndi_query("").depends_on("element_id", element_id))
            seen = {d.id for d in elem_docs}
            elem_docs = elem_docs + [d for d in dep_docs if d.id not in seen]
            if elem_docs:
                session.database_rm(elem_docs)

    if neuron_docs:
        session.database_rm(neuron_docs)

    session.database_rm(kc_doc)
