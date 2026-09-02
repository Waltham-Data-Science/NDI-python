"""ndi.fun.probe.extracellularInfo - the neurons already imported from a probe.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+probe/extracellularInfo.m``

The database-side counterpart to
``ndi.fun.probe.import_.kilosort.getInfo``: that one reports what a sort on
disk holds, this one reports what has already been imported. Nothing is read
from disk and nothing is changed.

WHAT MAKES A NEURON "THIS PROBE'S"
It is an element whose underlying element is the probe, AND which has a
``neuron_extracellular`` document naming it. That is exactly the pair
``ndi.fun.probe.import_.kilosort.probe`` creates, so what this lists is what
the importer imported -- an element with no document (a half-written import)
is not counted, and neither is a document whose element belongs elsewhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = ["extracellularInfo", "extracellular_info", "summarize"]


def extracellularInfo(  # noqa: N802 - MATLAB's function name
    session: Any,
    probe: Any,
    *,
    quality_labels: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], str]:
    """The extracellular neurons imported from PROBE, sorted by cluster index.

    Returns ``(info, summary)``. INFO is one mapping per neuron with
    ``element_name``, ``element_id``, ``cluster_index``, ``quality_label``,
    ``quality_number``, ``pipeline`` (the ``app.name`` provenance recorded at
    import), ``number_of_channels``, ``number_of_samples_per_channel``, the
    whole ``neuron_extracellular`` property mapping, and the ``document``.

    ``quality_labels``, when given, keeps only neurons carrying one of those
    labels, matched case-insensitively.
    """
    from ...query import ndi_query

    # the elements built on this probe, and their names
    element_docs = session.database_search(
        ndi_query("").isa("element")
        & ndi_query("").depends_on("underlying_element_id", _identifier(probe))
    )
    names = {
        doc.id: doc.document_properties.get("element", {}).get("name", "") for doc in element_docs
    }

    # their neuron_extracellular documents. The dependency filter is OR'd over
    # this probe's elements rather than loading every such document in the
    # session: in a session with several probes, the others' neurons are not
    # this query's business.
    neuron_docs: list[Any] = []
    if names:
        dependency = None
        for element_id in names:
            clause = ndi_query("").depends_on("element_id", element_id)
            dependency = clause if dependency is None else (dependency | clause)
        neuron_docs = session.database_search(
            ndi_query("").isa("neuron_extracellular") & dependency
        )

    wanted = {str(label).lower() for label in quality_labels}
    entries: list[dict[str, Any]] = []
    for doc in neuron_docs:
        element_id = doc.dependency_value("element_id", error_if_not_found=False)
        if not element_id or element_id not in names:
            continue  # this neuron does not belong to PROBE
        properties = doc.document_properties.get("neuron_extracellular", {}) or {}
        if wanted and str(properties.get("quality_label", "")).lower() not in wanted:
            continue
        entries.append(
            {
                "element_name": names[element_id],
                "element_id": element_id,
                "cluster_index": properties.get("cluster_index", 0),
                "quality_label": properties.get("quality_label", ""),
                "quality_number": properties.get("quality_number", 0),
                "pipeline": (doc.document_properties.get("app", {}) or {}).get("name", ""),
                "number_of_channels": properties.get("number_of_channels", 0),
                "number_of_samples_per_channel": properties.get("number_of_samples_per_channel", 0),
                "neuron_extracellular": properties,
                "document": doc,
            }
        )

    entries.sort(key=lambda entry: _sortable(entry["cluster_index"]))
    return entries, summarize(entries, probe)


def summarize(entries: Sequence[dict[str, Any]], probe: Any) -> str:
    """ENTRIES as the multiline text MATLAB's second output returns."""
    lines = [
        f"Imported extracellular neurons for probe '{probe.elementstring()}'",
        f"  Neurons:          {len(entries)}",
    ]
    if not entries:
        lines.append("  (no neuron_extracellular documents depend on this probe)")
        return "\n".join(lines)

    labels = [str(entry["quality_label"]) for entry in entries]
    lines.append("  Quality labels:")
    for tag in sorted(set(labels)):
        lines.append(f"     {tag}: {labels.count(tag)} neuron(s)")

    lines.append("  Neurons (name, cluster, quality, waveform):")
    for entry in entries:
        lines.append(
            f"     {entry['element_name']} (cluster {entry['cluster_index']}, "
            f"{entry['quality_label']}, quality {entry['quality_number']}, "
            f"{entry['number_of_channels']} ch x "
            f"{entry['number_of_samples_per_channel']} samp)"
        )
    return "\n".join(lines)


def _identifier(obj: Any) -> str:
    """OBJ's ndi id; ``id`` is a property on elements and a method on sessions."""
    ident = getattr(obj, "id", None)
    if callable(ident):
        ident = ident()
    return str(ident) if ident is not None else ""


def _sortable(value: Any) -> float:
    """CLUSTER_INDEX as a number, so a stored string still orders sensibly."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


#: The readable spelling beside MATLAB's.
extracellular_info = extracellularInfo
