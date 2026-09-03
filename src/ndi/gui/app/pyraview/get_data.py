"""ndi.gui.app.pyraview.get_data - read a view's worth of data.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/getData.m``

Both ports build a ``pyraview`` Dataset from the DOCUMENT's properties --
native rate and start time, channel count, data type, the decimation levels
and their rates and start times, and the level file names -- then ask it which
level to read for the window and how many samples. The library decides; this
function only supplies the document's numbers and reads what it is told to.

That is deliberate. An earlier version of this file mirrored the level-choice
algorithm here, because the Python binding then offered only a folder scan and
had no level-0 candidate. The binding now takes the same properties MATLAB's
does and its ``get_level_for_reading`` is the same algorithm, so mirroring it
would be the thing that drifts. One library, one level choice, two callers.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np

__all__ = [
    "get_data",
    "getData",
    "dataset_from_document",
    "level_file_names",
    "DEFAULT_READ_EXCESS",
]

#: Seconds read either side of the request before filtering, so the filter's
#: start-up transient lands outside the data that is kept. MATLAB's readExcess.
DEFAULT_READ_EXCESS = 1.0


def level_file_names(count: int) -> list[str]:
    """``level1.bin`` .. ``levelN.bin`` -- the names NDI stores the levels under.

    MATLAB's getData builds the same list. The pyramid writer emits
    ``<prefix>_L1.bin`` on disk and ``make_pyraview_doc`` attaches those to the
    document under these names, so these are what a document's files are
    called and what a reader must ask for.
    """
    return [f"level{index}.bin" for index in range(1, count + 1)]


def dataset_from_document(doc: Any) -> Any:
    """A ``pyraview.PyraviewDataset`` describing DOC's pyramid.

    Built from properties rather than by scanning a folder: an NDI document's
    level files live inside the document, not in a directory, and are named
    ``levelN.bin`` rather than the writer's ``<prefix>_LN.bin``.
    """
    import pyraview

    properties = doc.document_properties
    if "pyraview" not in properties:
        raise ValueError("Document is not a valid pyraview document.")
    pv = properties["pyraview"]

    # MATLAB accepts either spelling and falls back to the native start time.
    starts = pv.get("decimationStartTimes", pv.get("decimationStartTime"))
    if starts is None:
        starts = [pv["nativeStartTime"]]

    levels = [int(v) for v in np.atleast_1d(np.asarray(pv.get("decimationLevels", []))).ravel()]
    rates = [
        float(v) for v in np.atleast_1d(np.asarray(pv.get("decimationSamplingRates", []))).ravel()
    ]

    return pyraview.PyraviewDataset(
        native_rate=float(pv["nativeRate"]),
        native_start_time=float(pv["nativeStartTime"]),
        channels=int(pv["channels"]),
        data_type=pv.get("dataType", "double"),
        decimation_levels=levels,
        decimation_sampling_rates=rates,
        decimation_start_time=[float(v) for v in np.atleast_1d(np.asarray(starts)).ravel()],
        files=level_file_names(len(levels)),
    )


def get_data(
    probe: Any,
    doc: Any,
    t0: float,
    t1: float,
    pixel_span: float,
    read_excess: float = DEFAULT_READ_EXCESS,
) -> tuple[np.ndarray, np.ndarray, int | None]:
    """Data for the window ``[t0, t1]`` drawn across PIXEL_SPAN pixels.

    Returns ``(t_vec, data, level)``. At level 0 DATA is
    ``(samples x channels)`` raw filtered samples; above it,
    ``(samples x channels x 2)`` min/max pairs read from the pyramid.

    A window either side of the request is read as well -- MATLAB reads
    ``delta`` before and after -- so panning by less than a screen width
    usually needs no new read at all.
    """
    dataset = dataset_from_document(doc)

    delta = t1 - t0
    read_t0 = t0 - delta
    read_t1 = t1 + delta

    t_vec, level, sample_start, sample_end = dataset.get_level_for_reading(
        read_t0, read_t1, pixel_span
    )
    if level is None:
        return np.array([]), np.array([]), None

    if level == 0:
        return _read_raw(probe, doc, read_t0, read_t1, read_excess)

    if level > len(dataset.files):
        warnings.warn(
            f"Level {level} requested but only {len(dataset.files)} files available.",
            stacklevel=2,
        )
        return np.array([]), np.array([]), None

    data = _read_level(probe, doc, dataset.files[level - 1], sample_start, sample_end)
    if data is None:
        return np.array([]), np.array([]), None

    # A short read at the end of a file shortens the time vector with it.
    if data.shape[0] != t_vec.size:
        t_vec = t_vec[: data.shape[0]]
    return t_vec, data, level


def _read_raw(
    probe: Any, doc: Any, read_t0: float, read_t1: float, read_excess: float
) -> tuple[np.ndarray, np.ndarray, int | None]:
    """Level 0: read raw samples from the probe and filter them.

    The pyramid holds no raw level -- level 0 IS the probe -- so this is the
    one branch the library cannot serve. The extra ``read_excess`` seconds
    either side are read and then trimmed off, so the filter's start-up
    transient never reaches the screen.
    """
    from .filter_data import filter_data

    properties = doc.document_properties
    epochid = properties.get("epochid", {}).get("epochid")
    if not epochid:
        raise ValueError("Pyraview document missing epochid.")

    filter_type = properties.get("filter", {}).get("type")
    if not filter_type:
        filter_type = properties.get("pyraview", {}).get("label", "high")

    raw_start = read_t0 - read_excess
    raw_end = read_t1 + read_excess

    raw = probe.readtimeseries(epochid, raw_start, raw_end)
    if isinstance(raw, tuple):
        raw = raw[0]
    raw = np.asarray(raw, dtype=float)
    if raw.size == 0:
        return np.array([]), np.array([]), 0
    if raw.ndim == 1:
        raw = raw.reshape(-1, 1)

    sample_rate = float(probe.samplerate(epochid))
    filtered, _ = filter_data(raw, sample_rate, filter_type)

    index_start = round((read_t0 - raw_start) * sample_rate)
    index_end = round((read_t1 - raw_start) * sample_rate)
    index_start = max(index_start, 0)
    index_end = min(index_end, filtered.shape[0])
    if index_start >= index_end:
        return np.array([]), np.array([]), 0

    data = filtered[index_start:index_end, :]
    t_start = raw_start + index_start / sample_rate
    t_vec = t_start + np.arange(data.shape[0]) / sample_rate
    return t_vec, data, 0


def _read_level(
    probe: Any, doc: Any, filename: str, sample_start: int, sample_end: int
) -> np.ndarray | None:
    """Read one pyramid level's samples out of the document's binary file."""
    import pyraview

    session = probe.session
    try:
        handle = session.database_openbinarydoc(doc, filename)
    except Exception as exc:  # noqa: BLE001 - a missing level costs the view, not the app
        warnings.warn(f"Failed to open binary doc: {exc}", stacklevel=2)
        return None

    try:
        path = getattr(handle, "fullpathfilename", None) or getattr(handle, "name", None)
        if not path:
            warnings.warn("Binary doc object does not expose fullpathfilename.", stacklevel=2)
            return None
        try:
            # get_level_for_reading's end sample is EXCLUSIVE and read_file's
            # is INCLUSIVE, so the -1 is required, not an off-by-one. MATLAB
            # passes sEnd-1 for the same reason.
            return np.asarray(pyraview.read_file(str(path), sample_start, sample_end - 1))
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"Failed to read file {path}: {exc}", stacklevel=2)
            return None
    finally:
        session.database_closebinarydoc(handle)


#: MATLAB's spelling.
getData = get_data
