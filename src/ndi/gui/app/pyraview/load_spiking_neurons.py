"""ndi.gui.app.pyraview.load_spiking_neurons - the units recorded on a probe.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/load_spiking_neurons.m``

WHAT IS DELIBERATELY NOT DONE HERE
Two operations dominate load time for a population of hundreds of units:
rebuilding each element OBJECT from its document, and reading each unit's
spike TRAIN. Neither happens here. ``element_obj`` is left None and
``spike_times`` empty with ``times_loaded`` False; the viewer builds the
object and reads the train the first time a unit is actually selected. That
is MATLAB's design and the reason this returns in a moment on a session where
doing it eagerly took minutes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["load_spiking_neurons", "SIGNIFICANT_AMPLITUDE_FRACTION"]

#: A channel counts as carrying the waveform when its peak-to-peak amplitude
#: is at least this fraction of the largest channel's. It sets the box drawn
#: around each spike -- see transform_spike_data.
SIGNIFICANT_AMPLITUDE_FRACTION = 0.10


def load_spiking_neurons(session: Any, probe: Any, epochid: str) -> list[dict[str, Any]]:
    """The spiking units recorded on PROBE, one record each.

    Each record carries ``element_doc``, ``neuron_doc``, ``label``, ``name``,
    ``quality``, ``best_channel``, ``low_channel``, ``high_channel``, and the
    lazily-filled ``element_obj`` / ``spike_times`` / ``times_loaded``.

    EPOCHID is accepted and unused, as in MATLAB: the units belong to the
    probe rather than to one epoch, and the epoch only matters when the spike
    times are finally read.
    """
    from ....fun.utils import identifier
    from ....query import ndi_query

    element_docs = session.database_search(
        ndi_query("element.type", "exact_string", "spikes", "")
        & ndi_query("").depends_on("underlying_element_id", identifier(probe))
    )
    if not element_docs:
        return []

    # One pass over the neuron documents, then O(1) lookups -- MATLAB builds
    # the same map for the same reason: matching each element by rescanning
    # would be quadratic in the number of units.
    neuron_by_element: dict[str, Any] = {}
    for doc in session.database_search(ndi_query("").isa("neuron_extracellular")):
        try:
            neuron_by_element[doc.dependency_value("element_id")] = doc
        except Exception:  # noqa: BLE001 - a document without the dependency
            continue

    records: list[dict[str, Any]] = []
    for number, element_doc in enumerate(element_docs, start=1):
        neuron_doc = neuron_by_element.get(identifier(element_doc))
        quality = 0
        best_channel = low_channel = high_channel = 1

        if neuron_doc is not None:
            properties = neuron_doc.document_properties.get("neuron_extracellular", {})
            quality = properties.get("quality_number", properties.get("quality", 0)) or 0
            waveform = properties.get("mean_waveform")
            if waveform is not None:
                best_channel, low_channel, high_channel = waveform_channels(waveform)

        name = _element_name(element_doc)
        records.append(
            {
                # Built the first time the unit is selected. See the module note.
                "element_obj": None,
                "element_doc": element_doc,
                "neuron_doc": neuron_doc,
                "label": f"{number} {name} Q{int(quality)}",
                "name": name,
                "quality": quality,
                "spike_times": [],
                "times_loaded": False,
                "best_channel": best_channel,
                "low_channel": low_channel,
                "high_channel": high_channel,
            }
        )
    return records


def waveform_channels(mean_waveform: Any) -> tuple[int, int, int]:
    """``(best, low, high)`` channels of a mean waveform (samples x channels).

    BEST is the channel of greatest energy -- where the unit was recorded most
    strongly, and where its spike ticks are drawn. LOW and HIGH bound the
    channels whose peak-to-peak amplitude reaches
    :data:`SIGNIFICANT_AMPLITUDE_FRACTION` of the largest, which is the extent
    the per-spike box spans.

    All three are 1-BASED channel numbers, as MATLAB returns and as the rest
    of the viewer treats channels.
    """
    waveform = np.asarray(mean_waveform, dtype=float)
    if waveform.ndim == 1:
        waveform = waveform.reshape(-1, 1)
    if waveform.size == 0:
        return 1, 1, 1

    energy = np.sum(waveform**2, axis=0)
    best = int(np.argmax(energy)) + 1 if energy.size else 1

    amplitude = waveform.max(axis=0) - waveform.min(axis=0)
    largest = amplitude.max() if amplitude.size else 0
    if largest > 0:
        significant = np.flatnonzero(amplitude >= SIGNIFICANT_AMPLITUDE_FRACTION * largest)
        if significant.size:
            return best, int(significant.min()) + 1, int(significant.max()) + 1
    return best, 1, 1


def _element_name(element_doc: Any) -> str:
    """The element's display name, without building the element.

    Matches ``ndi.element.elementstring`` -- ``name | reference`` -- read
    straight off the document, which is the point: constructing the object
    was one of the two costs this function exists to avoid.
    """
    from ....fun.utils import identifier

    try:
        properties = element_doc.document_properties["element"]
        if "reference" in properties:
            return f"{properties['name']} | {int(properties['reference'])}"
        return str(properties["name"])
    except Exception:  # noqa: BLE001 - a document that will not say
        return str(identifier(element_doc))
