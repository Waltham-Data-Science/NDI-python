"""ndi.fun.probe.import.resolveExistingNeurons - neurons an earlier import left behind.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/resolveExistingNeurons.m``

The spike-sorting importers (``import_.kilosort.probe``, ``import_.kiasort.probe``)
name each imported neuron ``<probe name>_<probe reference>_<cluster id>`` and find
a previous import through its cluster document (``kilosort_clusters`` or
``kiasort_clusters``), which depends on the probe's id. Neurons whose cluster
document is not found that way -- because the probe's id changed between imports,
or an earlier import stopped part-way -- are not removed when the sort is imported
again, and ``add_multiple`` then writes a second element document with the same
name and reference for each of them. In MATLAB every later use of either neuron
fails in ``ndi.element/load_element_doc`` ("More than one document matches the
ELEMENT definition"); in Python nothing fails, and each such unit is silently
analysed twice.

This function looks for such neurons before an import writes anything.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Sequence
from typing import Any

__all__ = ["resolveExistingNeurons", "resolve_existing_neurons", "ExistingNeuronsError"]

#: The values ``ExistingNeurons`` accepts.
MODES = ("ask", "remove", "error")


class ExistingNeuronsError(RuntimeError):
    """Raised when neurons from an earlier import block an import.

    MATLAB's error identifier is ``ndi:fun:probe:import:existingNeurons``.
    """


def _doc_id(doc: Any) -> str:
    return doc.id() if callable(doc.id) else doc.id


def _probe_id(probe_obj: Any) -> str:
    pid = probe_obj.id
    return pid() if callable(pid) else pid


def _interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def resolveExistingNeurons(  # noqa: N802 - MATLAB's function name
    session: Any,
    probe_obj: Any,
    cluster_docs: Sequence[Any] = (),
    *,
    ExistingNeurons: str = "ask",  # noqa: N803 - MATLAB's parameter name
    dryRun: bool = False,  # noqa: N803 - MATLAB's parameter name
    verbose: bool = True,
    importer: str = "import",
    ask: Callable[[str], str] | None = None,
) -> int:
    """Find neurons from an earlier import of PROBE_OBJ and decide what to do with them.

    CLUSTER_DOCS are the cluster documents the importer already found for
    PROBE_OBJ; neurons that belong to them are the importer's to handle and are
    not reported. The neurons found are every ``ndi.neuron`` element in SESSION
    with PROBE_OBJ's reference whose name is
    ``<probe name>_<probe reference>_<integer>`` and that is not linked to
    CLUSTER_DOCS.

    ``ExistingNeurons`` says what happens when any are found:

    * ``'ask'`` (default) -- list them and ask whether to remove them and
      continue (``r``) or cancel. Without an interactive terminal this behaves
      like ``'error'``.
    * ``'remove'`` -- remove them, with their epoch and ``neuron_extracellular``
      documents and any cluster document left with no neurons.
    * ``'error'`` -- raise :class:`ExistingNeuronsError`.

    Cancelling at the prompt also raises :class:`ExistingNeuronsError`, so the
    database is left unchanged. Under ``dryRun`` the neurons are only reported.

    ``ask`` replaces the prompt: a callable given the question that returns the
    answer (MATLAB asks with ``input``). It is how a GUI or a test answers.

    Returns the number of neuron elements removed.
    """
    from ....query import ndi_query

    if ExistingNeurons not in MODES:
        raise ValueError(f"ExistingNeurons must be one of {MODES}; got {ExistingNeurons!r}.")

    # 1) every ndi.neuron in this session with the probe's reference and an
    #    importer-style name
    reference = int(probe_obj.reference)
    query = (
        ndi_query("base.session_id", "exact_string", session.id(), "")
        & ndi_query("").isa("element")
        & ndi_query("element.ndi_element_class", "exact_string", "ndi.neuron", "")
        & ndi_query("element.reference", "exact_number", reference, "")
    )
    pattern = re.compile(rf"^{re.escape(f'{probe_obj.name}_{reference}_')}\d+$")
    candidates = [
        doc
        for doc in session.database_search(query)
        if pattern.match(str(doc.document_properties["element"]["name"]))
    ]
    if not candidates:
        return 0

    # 2) leave out the neurons that belong to the cluster documents the importer found
    owned: set[str] = set()
    for cluster_doc in cluster_docs:
        neuron_docs = session.database_search(
            ndi_query("").isa("neuron_extracellular")
            & ndi_query("").depends_on("spike_clusters_id", _doc_id(cluster_doc))
        )
        for doc in neuron_docs:
            element_id = doc.dependency_value("element_id", error_if_not_found=False)
            if element_id:
                owned.add(element_id)
    strays = [doc for doc in candidates if _doc_id(doc) not in owned]
    if not strays:
        return 0

    # 3) describe them
    names = [str(doc.document_properties["element"]["name"]) for doc in strays]
    n_duplicated = len(names) - len(set(names))
    shown = "".join(f"    {name}\n" for name in names[:10])
    if len(names) > 10:
        shown += f"    ... and {len(names) - 10} more\n"
    message = (
        f"{importer}: found {len(strays)} neuron element(s) for probe "
        f"{probe_obj.elementstring()} that were made by an earlier import of this probe "
        f"but are not linked to its current cluster document:\n{shown}"
    )
    if n_duplicated:
        message += (
            f"  {n_duplicated} of these names appear more than once already, which makes "
            'ndi.element/load_element_doc fail in MATLAB with "More than one document '
            'matches the ELEMENT definition".\n'
        )
    message += (
        "  Importing again without removing them would create a second neuron with the "
        "same name for each one.\n"
    )

    if dryRun:
        action = {
            "ask": "ask whether to remove them",
            "remove": "remove them",
            "error": "stop with an error",
        }[ExistingNeurons]
        print(f"[dry run] {message}[dry run] A real run would {action} (ExistingNeurons).")
        return 0

    # 4) decide
    mode = ExistingNeurons
    if mode == "ask" and ask is None and not _interactive():
        mode = "error"

    if mode == "error":
        raise ExistingNeuronsError(
            message + "  Pass ExistingNeurons='remove' to remove them and import, or remove "
            "them yourself with ndi.fun.probe.import_.resolveExistingNeurons."
        )
    if mode == "ask":
        print(message)
        prompt = "  Remove them and continue with the import (r), or cancel (c)? [c]: "
        answer = (ask or input)(prompt)
        if str(answer).strip().lower() != "r":
            raise ExistingNeuronsError(f"{importer} cancelled; the database was not changed.")
    elif verbose:
        print(message)

    # 5) remove each neuron, the documents that depend on it, and any cluster
    #    document left with no neurons
    current = {_doc_id(doc) for doc in cluster_docs}
    stale_cluster_ids: set[str] = set()
    removed = 0
    for doc in strays:
        dependents = session.database_search(ndi_query("").depends_on("element_id", _doc_id(doc)))
        for dependent in dependents:
            if "neuron_extracellular" in dependent.document_properties:
                cluster_id = dependent.dependency_value(
                    "spike_clusters_id", error_if_not_found=False
                )
                if cluster_id:
                    stale_cluster_ids.add(cluster_id)
        session.database_rm([doc, *dependents])
        removed += 1

    for cluster_id in sorted(stale_cluster_ids - current):
        remaining = session.database_search(
            ndi_query("").depends_on("spike_clusters_id", cluster_id)
        )
        if not remaining:
            session.database_rm(cluster_id)

    if verbose:
        print(
            f"{importer}: removed {removed} earlier neuron element(s) for probe "
            f"{probe_obj.elementstring()}."
        )
    return removed


#: The readable spelling beside MATLAB's.
resolve_existing_neurons = resolveExistingNeurons
