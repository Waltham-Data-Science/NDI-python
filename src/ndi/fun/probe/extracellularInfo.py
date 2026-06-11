"""
ndi.fun.probe.extracellularInfo - summarize imported extracellular neurons for a probe.

MATLAB equivalent: +ndi/+fun/+probe/extracellularInfo.m
"""

from __future__ import annotations

from typing import Any


def extracellularInfo(
    session: Any,
    probe: Any,
    *,
    quality_labels: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Summarize the extracellular neurons imported from a probe (database-side).

    MATLAB equivalent: ``ndi.fun.probe.extracellularInfo``

    Returns information about the extracellular neurons that were determined
    (e.g. spike-sorted and imported) from *probe* in *session*. This views data
    that has ALREADY been imported into the database; nothing is read from disk
    and nothing is changed. It is the database-side counterpart to
    :func:`ndi.fun.probe.import_.kilosort.getInfo`.

    A neuron is considered to belong to *probe* if it is an ndi.element whose
    underlying element is *probe* (``depends_on 'underlying_element_id' ==
    probe.id``) and that has an associated ``neuron_extracellular`` document
    (``depends_on 'element_id' ==`` that neuron element). This is exactly the
    relationship created by :func:`ndi.fun.probe.import_.kilosort.probe`.

    Args:
        session: The ndi.session.
        probe: The ndi.probe / ndi.element to summarize.
        quality_labels: If given, restrict the result to neurons whose
            ``quality_label`` is in the list (matched case-insensitively).

    Returns:
        Tuple ``(info, summary)``. ``info`` is a list of dicts (one per neuron,
        sorted by ``cluster_index``) with keys ``element_name``, ``element_id``,
        ``cluster_index``, ``quality_label``, ``quality_number``, ``pipeline``,
        ``number_of_channels``, ``number_of_samples_per_channel``,
        ``neuron_extracellular``, and ``document``. ``summary`` is a multiline
        human-readable string.
    """
    from ...query import ndi_query

    # Step 1: find the neuron ndi.elements whose underlying element is this probe.
    q_elem = ndi_query("").isa("element") & ndi_query("").depends_on(
        "underlying_element_id", probe.id
    )
    elem_docs = session.database_search(q_elem)

    # Map neuron element id -> element name for quick lookup.
    elem_name_map: dict[str, str] = {}
    for ed in elem_docs:
        elem_name_map[ed.id] = ed.document_properties["element"]["name"]

    # Step 2: find this probe's neuron_extracellular documents.
    #
    # MATLAB OR's one depends_on('element_id', ...) clause per neuron element to
    # avoid loading other probes' neurons (a performance optimization). NDI-python's
    # ndi_query does not currently compose an OR of multiple depends_on clauses
    # correctly (`depends_on(a) | depends_on(b)` matches nothing), so here we load
    # every neuron_extracellular document and let the element_id-membership check in
    # Step 3 do the (authoritative, identical) filtering. Same RESULT as MATLAB;
    # only the query-time pruning optimization is dropped. Correctness is unchanged.
    if not elem_name_map:
        ne_docs: list[Any] = []
    else:
        ne_docs = session.database_search(ndi_query("").isa("neuron_extracellular"))

    # Step 3: assemble the result entries.
    want = {str(s).lower() for s in quality_labels} if quality_labels else set()

    entries: list[dict[str, Any]] = []
    for nd in ne_docs:
        element_id = nd.dependency_value("element_id", error_if_not_found=False)
        if not element_id or element_id not in elem_name_map:
            continue  # this neuron does not belong to PROBE
        ne = nd.document_properties["neuron_extracellular"]
        if want and str(ne.get("quality_label", "")).lower() not in want:
            continue  # filtered out by quality_labels
        props = nd.document_properties
        pipeline = ""
        app = props.get("app")
        if isinstance(app, dict) and "name" in app:
            pipeline = app["name"]
        entries.append(
            {
                "element_name": elem_name_map[element_id],
                "element_id": element_id,
                "cluster_index": ne.get("cluster_index"),
                "quality_label": ne.get("quality_label"),
                "quality_number": ne.get("quality_number"),
                "pipeline": pipeline,
                "number_of_channels": ne.get("number_of_channels"),
                "number_of_samples_per_channel": ne.get("number_of_samples_per_channel"),
                "neuron_extracellular": ne,
                "document": nd,
            }
        )

    # Step 4: sort by cluster_index for a stable, intuitive ordering.
    entries.sort(key=lambda e: (e["cluster_index"] is None, e["cluster_index"]))
    info = entries

    # Step 5: build the multiline summary.
    lines: list[str] = []
    lines.append(f"Imported extracellular neurons for probe '{probe.elementstring()}'")
    lines.append(f"  Neurons:          {len(info)}")
    if not info:
        lines.append("  (no neuron_extracellular documents depend on this probe)")
    else:
        labels_list = [str(e["quality_label"]) for e in info]
        utags = sorted(set(labels_list))
        lines.append("  Quality labels:")
        for tag in utags:
            lines.append(f"     {tag}: {labels_list.count(tag)} neuron(s)")
        lines.append("  Neurons (name, cluster, quality, waveform):")
        for e in info:
            lines.append(
                f"     {e['element_name']} (cluster {e['cluster_index']}, "
                f"{e['quality_label']}, quality {e['quality_number']}, "
                f"{e['number_of_channels']} ch x "
                f"{e['number_of_samples_per_channel']} samp)"
            )

    summary = "\n".join(lines)

    return info, summary
