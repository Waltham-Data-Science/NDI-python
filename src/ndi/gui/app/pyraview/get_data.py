"""ndi.gui.app.pyraview.get_data - read a view's worth of data.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/getData.m``

WHY THE LEVEL TABLE IS BUILT HERE RATHER THAN BY pyraview.PyraviewDataset
The Pyraview library has two bindings and they have drifted from each other.
MATLAB's ``pyraview.Dataset`` is constructed from PROPERTIES -- native rate,
channels, decimation levels and rates, and an explicit list of files -- which
is how NDI uses it: the numbers come out of the pyraview DOCUMENT and the
level files live inside that document, not in a folder. Python's
``PyraviewDataset`` instead scans a folder for ``*_L*.bin``, has no level-0
(raw) candidate at all, truncates sample indices where MATLAB floors and
ceils, uses one start time for every level, and returns
``(samples x channels*2)`` where MATLAB returns ``(samples x channels x 2)``.

Building a view on it would make the Python viewer behave differently from
the MATLAB one, on the same documents. So the level table and the level
choice are mirrored from ``pyraview.Dataset.getLevelForReading`` here, and
the actual reads go through ``pyraview.read_file``, which IS identical across
the two bindings -- same 0-based inclusive sample range, same
``(samples x channels x 2)`` result. Same format, same inputs, same answer.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["get_data", "getData", "LevelTable", "Level", "level_file_names", "DEFAULT_READ_EXCESS"]

#: Seconds read either side of the request before filtering, so the filter's
#: transient lands outside the data that is kept. MATLAB's readExcess.
DEFAULT_READ_EXCESS = 1.0


@dataclass(frozen=True)
class Level:
    """One candidate resolution: level 0 is raw, above 0 is a pyramid file."""

    level: int
    rate: float
    start_time: float


@dataclass
class LevelTable:
    """The resolutions a pyraview document offers, and how to choose one.

    Mirrors the parts of MATLAB's ``pyraview.Dataset`` that NDI uses: built
    from the document's properties rather than from a folder scan.
    """

    native_rate: float
    native_start_time: float
    channels: int
    data_type: str
    decimation_levels: list[int] = field(default_factory=list)
    decimation_sampling_rates: list[float] = field(default_factory=list)
    decimation_start_times: list[float] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def candidates(self) -> list[Level]:
        """Every resolution available, raw first, as MATLAB assembles them."""
        levels = [Level(0, float(self.native_rate), float(self.native_start_time))]
        for index, rate in enumerate(self.decimation_sampling_rates):
            if index < len(self.decimation_start_times):
                start = float(self.decimation_start_times[index])
            else:
                start = float(self.native_start_time)
            levels.append(Level(index + 1, float(rate), start))
        return levels

    def level_for_reading(
        self, t_start: float, t_end: float, pixels: float
    ) -> tuple[np.ndarray, int | None, int, int]:
        """Choose a level for the window, and the samples to read from it.

        Returns ``(t_vec, level, sample_start, sample_end)``, with ``level``
        None when there is nothing to read.

        The rule is MATLAB's: of the levels whose rate is at least one sample
        per pixel, take the COARSEST -- the least data that still fills the
        screen. When every level is too coarse, which is what zooming far in
        means, take the finest available instead.
        """
        duration = t_end - t_start
        if duration <= 0:
            return np.array([]), None, 0, 0

        target_rate = pixels / duration
        candidates = self.candidates()
        if not candidates:
            return np.array([]), None, 0, 0

        sufficient = [c for c in candidates if c.rate >= target_rate]
        chosen = (
            min(sufficient, key=lambda c: c.rate)
            if sufficient
            else max(candidates, key=lambda c: c.rate)
        )

        # Samples are 0-based from the start of the level: t = start + idx/rate.
        index_start = math.floor((t_start - chosen.start_time) * chosen.rate)
        index_end = math.ceil((t_end - chosen.start_time) * chosen.rate)
        index_start = max(index_start, 0)
        index_end = max(index_end, index_start)

        count = index_end - index_start
        if count > 0:
            t_vec = chosen.start_time + (index_start + np.arange(count)) / chosen.rate
        else:
            t_vec = np.array([])
        return t_vec, chosen.level, index_start, index_end


def level_file_names(count: int) -> list[str]:
    """``level1.bin`` .. ``levelN.bin`` -- the names NDI stores them under.

    MATLAB builds the same list. This is the naming that matters for
    interoperability: Pyraview's own Python Dataset looks for ``*_L*.bin``
    instead, which is why it cannot read an NDI document's files.
    """
    return [f"level{index}.bin" for index in range(1, count + 1)]


def table_from_document(doc: Any) -> LevelTable:
    """The level table a pyraview document describes."""
    properties = doc.document_properties
    if "pyraview" not in properties:
        raise ValueError("Document is not a valid pyraview document.")
    pv = properties["pyraview"]

    # MATLAB accepts either spelling and falls back to the native start time.
    starts = pv.get("decimationStartTimes", pv.get("decimationStartTime"))
    if starts is None:
        starts = [pv["nativeStartTime"]]

    levels = list(np.atleast_1d(np.asarray(pv.get("decimationLevels", []))).ravel())
    return LevelTable(
        native_rate=float(pv["nativeRate"]),
        native_start_time=float(pv["nativeStartTime"]),
        channels=int(pv["channels"]),
        data_type=str(pv.get("dataType", "double")),
        decimation_levels=[int(v) for v in levels],
        decimation_sampling_rates=[
            float(v)
            for v in np.atleast_1d(np.asarray(pv.get("decimationSamplingRates", []))).ravel()
        ],
        decimation_start_times=[float(v) for v in np.atleast_1d(np.asarray(starts)).ravel()],
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
    ``(samples x channels x 2)`` min/max pairs from the pyramid.

    A window either side of the request is read as well -- MATLAB reads
    ``delta`` before and after -- so panning by less than a screen width
    usually needs no new read at all.
    """
    table = table_from_document(doc)

    delta = t1 - t0
    read_t0 = t0 - delta
    read_t1 = t1 + delta

    t_vec, level, sample_start, sample_end = table.level_for_reading(read_t0, read_t1, pixel_span)
    if level is None:
        return np.array([]), np.array([]), None

    if level == 0:
        return _read_raw(probe, doc, read_t0, read_t1, read_excess)

    if level > len(table.files):
        warnings.warn(
            f"Level {level} requested but only {len(table.files)} files available.",
            stacklevel=2,
        )
        return np.array([]), np.array([]), None

    data = _read_level(probe, doc, table.files[level - 1], sample_start, sample_end)
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

    The extra ``read_excess`` seconds either side are read and then trimmed
    off, so the filter's start-up transient never reaches the screen.
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
            # 0-based, inclusive of the end sample -- MATLAB passes sEnd-1 for
            # the same reason, and read_file means the same thing in both.
            return np.asarray(pyraview.read_file(str(path), sample_start, sample_end - 1))
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"Failed to read file {path}: {exc}", stacklevel=2)
            return None
    finally:
        session.database_closebinarydoc(handle)


#: MATLAB's spelling.
getData = get_data
