"""ndi.gui.app.pyraview.make_pyraview_doc - build a probe/epoch's pyramid.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/makePyraviewDoc.m``

Reads an epoch in chunks, filters each chunk, hands it to Pyraview to append
to the pyramid, and records the result as a ``pyraview`` document whose files
are the pyramid levels. This is what the viewer calls the first time a probe,
epoch and band are asked for and no document exists yet.

WHY THE CHUNKS OVERLAP AND THEN GET TRIMMED
Each chunk is read with ``chunk_excess`` seconds of context either side and
then trimmed back to its central span before being appended. Without the
excess the filter's start-up transient would land at the head of every chunk
and be written into the pyramid -- a ringing artefact every ``chunk_duration``
seconds, at every zoom level, permanently. The excess is read, filtered, and
thrown away.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any

import numpy as np

__all__ = ["make_pyraview_doc", "makePyraviewDoc", "DECIMATION_STEPS", "REQUIRED_CLOCK"]

#: The pyramid's decimation steps: 100x, then 10x per level after it.
#: Cumulative, so level 1 is 100x coarser than raw and level 7 is 10^8.
DECIMATION_STEPS = (100, 10, 10, 10, 10, 10, 10)

#: The clock a pyramid is built against. An epoch without it is refused
#: rather than guessed at: every time in the document -- the epoch bounds, the
#: level start times -- would otherwise be in an unstated frame.
REQUIRED_CLOCK = "dev_local_time"

#: MATLAB's defaults for the read loop, in seconds.
DEFAULT_CHUNK_DURATION = 50
DEFAULT_CHUNK_EXCESS = 1


def make_pyraview_doc(
    probe: Any,
    epochid: str,
    filterband: str,
    chunk_duration: float = DEFAULT_CHUNK_DURATION,
    chunk_excess: float = DEFAULT_CHUNK_EXCESS,
    progress: Any = None,
) -> Any:
    """Create and add the ``pyraview`` document for PROBE, EPOCHID, FILTERBAND.

    FILTERBAND is ``'low'``, ``'high'`` or ``'all'``; a pyramid is built for
    every band, ``'all'`` storing the unfiltered signal.

    PROGRESS, if given, is called with a fraction in 0..1 as the epoch is
    worked through -- the Python stand-in for MATLAB's NDIProgressBar, which
    it builds inside this function. Keeping it a callback rather than a window
    is what lets this run headless, in a script or a test.
    """
    import pyraview as pyraview_lib

    from .filter_data import filter_data

    t0, t1 = epoch_bounds(probe, epochid)
    sample_rate = float(probe.samplerate(epochid))

    # The filter struct is wanted for the document even when no data is read.
    _, filter_struct = filter_data(np.zeros((1, 1)), sample_rate, filterband)

    temp_dir = tempfile.mkdtemp(prefix="ndi_pyraview_")
    prefix = os.path.join(temp_dir, f"pyraview_{uuid.uuid4().hex}")

    steps = list(DECIMATION_STEPS)
    channels = 0
    total_duration = (t1 - t0) or 1

    current = t0
    while current < t1:
        if progress is not None:
            progress(min((current - t0) / total_duration, 1.0))

        data = probe.readtimeseries(
            epochid, current - chunk_excess, current + chunk_duration + chunk_excess
        )
        if isinstance(data, tuple):
            data = data[0]
        data = np.asarray(data, dtype=float)
        if data.size:
            if data.ndim == 1:
                data = data.reshape(-1, 1)
            data, _ = filter_data(data, sample_rate, filterband)
            if channels == 0:
                channels = data.shape[1]

            # readtimeseries clamps to the epoch, so the data may start later
            # than asked; offsets are measured from where it actually starts.
            data_start = max(t0, current - chunk_excess)
            start_index = round((current - data_start) * sample_rate)
            end_index = round((current + chunk_duration - data_start) * sample_rate)
            start_index = max(start_index, 0)
            end_index = min(end_index, data.shape[0])

            if start_index < end_index:
                central = data[start_index:end_index, :]
                pyraview_lib.process_chunk(
                    central, prefix, steps, sample_rate, start_time=t0, append=True
                )

        current += chunk_duration

    if progress is not None:
        progress(1.0)

    return _build_document(
        probe, epochid, filterband, filter_struct, prefix, steps, sample_rate, t0, t1, channels
    )


def epoch_bounds(probe: Any, epochid: str) -> tuple[float, float]:
    """The epoch's ``(t0, t1)`` on the clock a pyramid needs."""
    table = probe.epochtable()
    if isinstance(table, tuple):
        table = table[0]

    entry = None
    for candidate in table or []:
        if str(candidate.get("epoch_id")) == str(epochid):
            entry = candidate
            break
    if entry is None:
        raise ValueError(f"Epoch {epochid} not found in probe {probe.elementstring()}")

    clocks = entry.get("epoch_clock") or []
    times = entry.get("t0_t1") or []
    for index, clock in enumerate(clocks):
        clock_type = getattr(clock, "type", None) or (
            clock.get("type") if isinstance(clock, dict) else str(clock)
        )
        if clock_type == REQUIRED_CLOCK and index < len(times):
            bounds = times[index]
            return float(bounds[0]), float(bounds[1])

    raise ValueError(f"Epoch does not have '{REQUIRED_CLOCK}' clock type.")


def _build_document(
    probe: Any,
    epochid: str,
    filterband: str,
    filter_struct: dict[str, Any],
    prefix: str,
    steps: list[int],
    sample_rate: float,
    t0: float,
    t1: float,
    channels: int,
) -> Any:
    """Assemble the pyraview document, attach the level files, and add it."""
    from ....document import ndi_document
    from ....fun.utils import identifier

    rates = sample_rate / np.cumprod(steps)
    pyraview_properties = {
        "label": filterband,
        "nativeRate": sample_rate,
        "nativeStartTime": t0,
        "channels": int(channels),
        "dataType": "double",
        "decimationLevels": [int(s) for s in steps],
        "decimationSamplingRates": [float(r) for r in rates],
        "decimationStartTimes": [float(t0)] * len(steps),
    }

    session = probe.session
    doc = ndi_document(
        "pyraview",
        **{
            "pyraview": pyraview_properties,
            "epochid": {"epochid": str(epochid)},
            "filter": filter_struct,
            "epochclocktimes": {"clocktype": REQUIRED_CLOCK, "t0_t1": [float(t0), float(t1)]},
            "base.session_id": session.id(),
        },
    )
    doc = doc.set_dependency_value("element_id", identifier(probe))

    # The writer names its files <prefix>_L1.bin; the document stores them as
    # level1.bin, which is the name get_data asks for. Both namings are real
    # and they are not interchangeable -- this is where they meet.
    for index in range(1, len(steps) + 1):
        doc = doc.add_file(f"level{index}.bin", f"{prefix}_L{index}.bin")

    session.database_add(doc)
    return doc


#: MATLAB's spelling.
makePyraviewDoc = make_pyraview_doc
