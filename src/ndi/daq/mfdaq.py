"""
ndi.daq.mfdaq - Multi-function DAQ reader class.

This module provides the ndi_daq_reader_mfdaq class for reading data from
multi-function data acquisition systems that sample various data types.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
import warnings
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from ..time import DEV_LOCAL_TIME, ndi_time_clocktype
from .daqsystemstring import ndi_daq_daqsystemstring
from .reader_base import ndi_daq_reader

logger = logging.getLogger(__name__)


class ChannelType(Enum):
    """Channel types for multi-function DAQ systems."""

    ANALOG_IN = "analog_in"
    ANALOG_OUT = "analog_out"
    DIGITAL_IN = "digital_in"
    DIGITAL_OUT = "digital_out"
    AUXILIARY_IN = "auxiliary_in"
    TIME = "time"
    EVENT = "event"
    MARKER = "marker"
    TEXT = "text"

    @classmethod
    def from_abbreviation(cls, abbrev: str) -> ChannelType:
        """Convert abbreviation to ChannelType."""
        abbrev_map = {
            "ai": cls.ANALOG_IN,
            "ao": cls.ANALOG_OUT,
            "di": cls.DIGITAL_IN,
            "do": cls.DIGITAL_OUT,
            "ax": cls.AUXILIARY_IN,
            "aux": cls.AUXILIARY_IN,
            "t": cls.TIME,
            "e": cls.EVENT,
            "mk": cls.MARKER,
            "tx": cls.TEXT,
        }
        return abbrev_map.get(abbrev.lower(), cls.ANALOG_IN)

    @property
    def abbreviation(self) -> str:
        """Get the abbreviation for this channel type."""
        abbrev_map = {
            ChannelType.ANALOG_IN: "ai",
            ChannelType.ANALOG_OUT: "ao",
            ChannelType.DIGITAL_IN: "di",
            ChannelType.DIGITAL_OUT: "do",
            ChannelType.AUXILIARY_IN: "ax",
            ChannelType.TIME: "t",
            ChannelType.EVENT: "e",
            ChannelType.MARKER: "mk",
            ChannelType.TEXT: "tx",
        }
        return abbrev_map[self]


@dataclass
class ChannelInfo:
    """Information about a single channel."""

    name: str
    type: str  # Use string for JSON serialization
    time_channel: int | None = None
    number: int | None = None
    sample_rate: float | None = None
    offset: float = 0.0
    scale: float = 1.0
    group: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> ChannelInfo:
        return cls(
            name=d.get("name", ""),
            type=d.get("type", ""),
            time_channel=d.get("time_channel"),
            number=d.get("number"),
            sample_rate=d.get("sample_rate"),
            offset=d.get("offset", 0.0),
            scale=d.get("scale", 1.0),
            group=d.get("group", 1),
        )


def standardize_channel_type(channel_type: str | ChannelType) -> str:
    """
    Standardize a channel type to its full name.

    Args:
        channel_type: Channel type string or abbreviation

    Returns:
        Standardized channel type name
    """
    if isinstance(channel_type, ChannelType):
        return channel_type.value

    abbrev_map = {
        "ai": "analog_in",
        "ao": "analog_out",
        "di": "digital_in",
        "do": "digital_out",
        "ax": "auxiliary_in",
        "aux": "auxiliary_in",
        "t": "time",
        "e": "event",
        "mk": "marker",
        "tx": "text",
    }
    return abbrev_map.get(channel_type.lower(), channel_type)


def standardize_channel_types(channel_types: list[str]) -> list[str]:
    """Standardize a list of channel types."""
    return [standardize_channel_type(ct) for ct in channel_types]


class ndi_daq_reader_mfdaq(ndi_daq_reader):
    """
    Multi-function DAQ reader for various data types.

    This reader handles multi-function data acquisition systems that
    sample various data types simultaneously:
    - Analog inputs/outputs
    - Digital inputs/outputs
    - Events, markers, and text
    - Time channels

    This is an abstract class that should be subclassed for specific
    DAQ systems (Intan, Blackrock, etc.).

    Channel Types:
        - 'analog_in' / 'ai': Analog input
        - 'analog_out' / 'ao': Analog output
        - 'digital_in' / 'di': Digital input
        - 'digital_out' / 'do': Digital output
        - 'auxiliary_in' / 'ax': Auxiliary channels
        - 'time' / 't': Time samples
        - 'event' / 'e': Event triggers
        - 'marker' / 'mk': Marker channels
        - 'text' / 'tx': Text markers

    Example:
        >>> class ndi_daq_reader_mfdaq_intan(ndi_daq_reader_mfdaq):
        ...     def getchannelsepoch(self, epochfiles):
        ...         # Return channels from Intan file
        ...         ...
    """

    # Class-level channel type definitions
    CHANNEL_TYPES = [
        "analog_in",
        "analog_out",
        "auxiliary_in",
        "digital_in",
        "digital_out",
        "event",
        "marker",
        "text",
        "time",
    ]
    CHANNEL_ABBREVS = ["ai", "ao", "ax", "di", "do", "e", "mk", "tx", "t"]

    def __init__(
        self,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        """
        Create a new ndi_daq_reader_mfdaq.

        Args:
            identifier: Optional identifier
            session: Optional session object
            document: Optional document to load from
        """
        super().__init__(identifier, session, document)

    def epochclock(
        self,
        epochfiles: list[str],
    ) -> list[ndi_time_clocktype]:
        """
        Return the clock types for an epoch.

        For MFDAQ, this returns DEV_LOCAL_TIME by default.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List containing DEV_LOCAL_TIME
        """
        return [DEV_LOCAL_TIME]

    def t0_t1(
        self,
        epochfiles: list[str],
    ) -> list[tuple[float, float]]:
        """
        Return the start and end times for an epoch.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of (t0, t1) tuples. Base class returns [(NaN, NaN)].
        """
        return [(np.nan, np.nan)]

    @abstractmethod
    def getchannelsepoch(
        self,
        epochfiles: list[str],
    ) -> list[ChannelInfo]:
        """
        List channels that were sampled for this epoch.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of ChannelInfo objects with:
            - name: Channel name (e.g., 'ai1')
            - type: Channel type (e.g., 'analog_in')
            - time_channel: Number of the time channel (or None)
        """
        pass

    @abstractmethod
    def readchannels_epochsamples(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        s0: int,
        s1: int,
    ) -> np.ndarray:
        """
        Read channel data as samples.

        Args:
            channeltype: Type(s) of channel to read
            channel: Channel number(s) to read (1-indexed)
            epochfiles: Files for this epoch
            s0: Start sample (1-indexed)
            s1: End sample (1-indexed)

        Returns:
            Array with shape (num_samples, num_channels)
        """
        pass

    @abstractmethod
    def samplerate(
        self,
        epochfiles: list[str],
        channeltype: str | list[str],
        channel: int | list[int],
    ) -> np.ndarray:
        """
        Get sample rate for channels.

        Args:
            epochfiles: Files for this epoch
            channeltype: Type(s) of channel
            channel: Channel number(s)

        Returns:
            Array of sample rates
        """
        pass

    def readevents_epochsamples(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
    ) -> tuple[np.ndarray | list[np.ndarray], np.ndarray | list[np.ndarray]]:
        """
        Read event data for specified channels.

        Args:
            channeltype: Type(s) of event channel to read
            channel: Channel number(s)
            epochfiles: Files for this epoch
            t0: Start time
            t1: End time

        Returns:
            Tuple of (timestamps, data):
            - timestamps: Array or list of arrays with event times
            - data: Array or list of arrays with event data
        """
        if isinstance(channeltype, str):
            channeltype = [channeltype]
        if isinstance(channel, int):
            channel = [channel]

        channeltype = standardize_channel_types(channeltype)

        # Handle derived digital event channels
        derived = {"dep", "den", "dimp", "dimn"}
        if set(channeltype) & derived:
            return self._read_derived_events(channeltype, channel, epochfiles, t0, t1)

        # Handle analog event channels (aep, aen, aimp, aimn)
        is_analog, _, _ = ndi_daq_reader_mfdaq.is_analog_event_type(channeltype)
        if is_analog:
            return self._read_analog_events(channeltype, channel, epochfiles, t0, t1)

        # Otherwise read native events
        return self.readevents_epochsamples_native(channeltype, channel, epochfiles, t0, t1)

    def _read_derived_events(
        self,
        channeltype: list[str],
        channel: list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
    ) -> tuple[list[np.ndarray], list[np.ndarray]]:
        """Read events derived from digital channels."""
        timestamps = []
        data = []

        for i, ch in enumerate(channel):
            ct = channeltype[i] if i < len(channeltype) else channeltype[0]

            # Get sample range for time window
            sd = self.epochtimes2samples(["di"], [ch], epochfiles, np.array([t0, t1]))
            s0, s1 = int(sd[0]), int(sd[1])

            # Read digital and time data
            di_data = self.readchannels_epochsamples("di", [ch], epochfiles, s0, s1)
            time_data = self.readchannels_epochsamples("time", [ch], epochfiles, s0, s1)

            di_data = di_data.flatten()
            time_data = time_data.flatten()

            # Find transitions
            if ct in ("dep", "dimp"):  # positive transitions
                on_samples = np.where((di_data[:-1] == 0) & (di_data[1:] == 1))[0]
                if ct == "dimp":
                    off_samples = 1 + np.where((di_data[:-1] == 1) & (di_data[1:] == 0))[0]
                else:
                    off_samples = np.array([], dtype=int)
            else:  # negative transitions (den, dimn)
                on_samples = np.where((di_data[:-1] == 1) & (di_data[1:] == 0))[0]
                if ct == "dimn":
                    off_samples = 1 + np.where((di_data[:-1] == 0) & (di_data[1:] == 1))[0]
                else:
                    off_samples = np.array([], dtype=int)

            ts = np.concatenate(
                [
                    time_data[on_samples],
                    time_data[off_samples] if len(off_samples) else np.array([]),
                ]
            )
            d = np.concatenate(
                [
                    np.ones(len(on_samples)),
                    -np.ones(len(off_samples)) if len(off_samples) else np.array([]),
                ]
            )

            if len(off_samples) > 0:
                order = np.argsort(ts)
                ts = ts[order]
                d = d[order]

            timestamps.append(ts)
            data.append(d)

        if len(channel) == 1:
            return timestamps[0], data[0]
        return timestamps, data

    def _read_analog_events(
        self,
        channeltype: list[str],
        channel: list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
    ) -> tuple[list[np.ndarray] | np.ndarray, list[np.ndarray] | np.ndarray]:
        """Read events derived from analog channels via threshold crossing."""
        _, base_types, thresholds = ndi_daq_reader_mfdaq.is_analog_event_type(channeltype)

        timestamps = []
        data = []

        for i, ch in enumerate(channel):
            bt = base_types[i]
            thresh = thresholds[i]

            # Get sample range for time window from analog input
            sd = self.epochtimes2samples(["ai"], [ch], epochfiles, np.array([t0, t1]))
            s0, s1 = int(sd[0]), int(sd[1])

            # Read analog and time data
            ai_data = self.readchannels_epochsamples("ai", [ch], epochfiles, s0, s1)
            time_data = self.readchannels_epochsamples("time", [ch], epochfiles, s0, s1)

            ai_data = ai_data.flatten()
            time_data = time_data.flatten()

            below = ai_data[:-1] < thresh
            above = ai_data[1:] >= thresh

            if bt in ("aep", "aimp"):
                # Below-to-above threshold crossings
                on_samples = 1 + np.where(below & above)[0]
                off_samples = (
                    1 + np.where(~below & ~above)[0] if bt == "aimp" else np.array([], dtype=int)
                )
                on_sign, off_sign = 1, -1
            else:  # aen, aimn
                # Above-to-below threshold crossings
                on_samples = 1 + np.where(~below & ~above)[0]
                off_samples = (
                    1 + np.where(below & above)[0] if bt == "aimn" else np.array([], dtype=int)
                )
                on_sign, off_sign = -1, 1

            ts = np.concatenate(
                [
                    time_data[on_samples],
                    time_data[off_samples] if len(off_samples) else np.array([]),
                ]
            )
            d = np.concatenate(
                [
                    on_sign * np.ones(len(on_samples)),
                    off_sign * np.ones(len(off_samples)) if len(off_samples) else np.array([]),
                ]
            )

            if len(off_samples) > 0:
                order = np.argsort(ts)
                ts = ts[order]
                d = d[order]

            timestamps.append(ts)
            data.append(d)

        if len(channel) == 1:
            return timestamps[0], data[0]
        return timestamps, data

    def readevents_epochsamples_native(
        self,
        channeltype: list[str],
        channel: list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
    ) -> tuple[list[np.ndarray], list[np.ndarray]]:
        """
        Read native event data. Override in subclasses.

        Args:
            channeltype: Types of event channels
            channel: Channel numbers
            epochfiles: Files for this epoch
            t0: Start time
            t1: End time

        Returns:
            Tuple of (timestamps, data) as lists of arrays
        """
        return [], []

    def epochsamples2times(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        samples: np.ndarray,
    ) -> np.ndarray:
        """
        Convert 0-based sample indices to time.

        Note:
            Unlike MATLAB (1-based), Python sample indices are 0-based.
            Sample 0 corresponds to time t0 of the epoch.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch
            samples: Sample indices (0-based)

        Returns:
            Time values
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        sr = self.samplerate(epochfiles, channeltype, channel)
        sr_unique = np.unique(sr)
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sample rates across channels")
        sr = sr_unique[0]

        t0t1 = self.t0_t1(epochfiles)
        t0 = t0t1[0][0]

        samples = np.asarray(samples)
        t = t0 + samples / sr

        # Handle infinite values
        if np.any(np.isinf(samples)):
            t[np.isinf(samples) & (samples < 0)] = t0

        return t

    def epochtimes2samples(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        times: np.ndarray,
    ) -> np.ndarray:
        """
        Convert time to 0-based sample indices.

        Note:
            Unlike MATLAB (1-based), Python sample indices are 0-based.
            Sample 0 corresponds to time t0 of the epoch.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch
            times: Time values

        Returns:
            Sample indices (0-based)
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        sr = self.samplerate(epochfiles, channeltype, channel)
        sr_unique = np.unique(sr)
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sample rates across channels")
        sr = sr_unique[0]

        t0t1 = self.t0_t1(epochfiles)
        t0 = t0t1[0][0]

        times = np.asarray(times)
        s = np.round((times - t0) * sr).astype(int)

        # Handle infinite values
        if np.any(np.isinf(times)):
            s[np.isinf(times) & (times < 0)] = 0
            pos_inf = np.isinf(times) & (times > 0)
            if np.any(pos_inf):
                t1 = t0t1[0][1]
                s_end = round((t1 - t0) * sr)
                s[pos_inf] = s_end

        return s

    #: Samples per stored segment of analog/time data, as MATLAB's ingest_epochfiles.
    SAMPLE_ANALOG_SEGMENT = 1_000_000
    #: Samples per stored segment of digital data, as MATLAB's ingest_epochfiles.
    SAMPLE_DIGITAL_SEGMENT = 10_000_000

    #: File-record prefix for each channel type's segments.
    INGEST_FILE_PREFIX = {
        "analog_in": "ai",
        "analog_out": "ao",
        "auxiliary_in": "ax",
        "digital_in": "di",
        "digital_out": "do",
        "eventmarktext": "evmktx",
        "time": "ti",
    }

    def ingest_epochfiles(
        self,
        epochfiles: list[str],
        epoch_id: str,
        ProgressFcn: Callable[[float], Any] | None = None,  # noqa: N803 (MATLAB name)
    ) -> Any:
        """
        Create a document holding the data read by this reader for one epoch.

        MATLAB equivalent: ndi.daq.reader.mfdaq/ingest_epochfiles

        Creates an ndi_document of type ``daqreader_mfdaq_epochdata_ingested``
        with the epoch's channel list (``channel_list.bin``) and its data,
        compressed with ``ndicompress`` into segments of
        ``SAMPLE_ANALOG_SEGMENT`` (analog, auxiliary, time) or
        ``SAMPLE_DIGITAL_SEGMENT`` (digital) samples per channel group, plus
        one file per group of event/marker/text channels. Analog data are
        stored in the type given by :meth:`underlying_datatype` (e.g. Intan's
        uint16). The document is not added to any database; its files are
        temporary files that the database takes over when it is added.

        Runs :meth:`ingest_epochfiles_plan`, :meth:`ingest_segment` for each
        planned segment, then :meth:`ingest_attach_segments`, so the segments
        can also be written one at a time elsewhere (see
        ``ndi.daq.fun.ingestEpochDocuments``).

        Args:
            epochfiles: Files for this epoch
            epoch_id: The epoch id
            ProgressFcn: Called as ``ProgressFcn(F)`` with F, the fraction of
                this epoch done (0..1), after each segment is written. Each
                channel group counts in proportion to its number of channels.
                Errors in it are turned into warnings.

        Returns:
            ndi_document of type daqreader_mfdaq_epochdata_ingested
        """
        d, plan = self.ingest_epochfiles_plan(epochfiles, epoch_id)
        _report_ingest_progress(ProgressFcn, 0)
        weight_total = sum(entry["weight"] for entry in plan)
        weight_done = 0.0
        segment_files = []
        for entry in plan:
            segment_files.append(self.ingest_segment(epochfiles, entry))
            weight_done += entry["weight"]
            _report_ingest_progress(ProgressFcn, weight_done / max(weight_total, 1e-300))
        d = self.ingest_attach_segments(d, plan, segment_files)
        _report_ingest_progress(ProgressFcn, 1)
        return d

    def ingest_epochfiles_plan(
        self,
        epochfiles: list[str],
        epoch_id: str,
    ) -> tuple[Any, list[dict[str, Any]]]:
        """
        Plan the ingestion of an epoch, segment by segment.

        MATLAB equivalent: ndi.daq.reader.mfdaq/ingest_epochfiles_plan

        Creates the ``daqreader_mfdaq_epochdata_ingested`` document for the
        epoch, with its channel list already attached, and the plan: one dict
        per data segment still to be written, in the order the segment files
        are added to the document. Each entry can be computed independently
        (and in another process) with :meth:`ingest_segment`;
        :meth:`ingest_attach_segments` then adds the resulting files.

        Each entry has MATLAB's fields: ``kind`` (``"ephys"``, ``"digital"``,
        ``"eventmarktext"`` or ``"time"``), ``channeltype``, ``channels``,
        ``eventchanneltypes`` (eventmarktext: the type of each channel),
        ``s0`` and ``s1`` (first and last sample, 1-based), ``poly``,
        ``datasize``, ``underlying_format``, ``docfilename`` (e.g.
        ``"ai_group1_seg.nbf_3"``), ``segment`` and ``numSegments`` (this
        segment's number within its group), and ``weight`` (its share of the
        epoch's work; the weights sum to 1).

        Args:
            epochfiles: Files for this epoch
            epoch_id: The epoch id

        Returns:
            ``(d, plan)``. The document is not added to any database.

        Python-specific Notes:
            Sample numbers are 1-based, as :meth:`readchannels_epochsamples`
            takes them; ``epochtimes2samples`` here is 0-based, so the last
            sample is its answer plus 1. Digital-output segments are stored as
            ``do_group*`` (the document's file list and the ingested reader use
            ``do``); MATLAB writes them as ``di_group*``, which collides with
            digital-input segments of the same group. The time group computes
            its own sample range, where MATLAB reuses the group planned before
            it (the same whenever the time channel shares that group's rate).
        """
        from ..document import ndi_document
        from ..file.type.mfdaq_epoch_channel import ndi_file_type_mfdaq__epoch__channel
        from ..fun.utils import channelname2prefixnumber

        # the epoch table (clock and t0_t1), as the base reader writes it
        base_doc = super().ingest_epochfiles(epochfiles, epoch_id)
        epochtable = base_doc.document_properties["daqreader_epochdata_ingested"]["epochtable"]

        d = ndi_document(
            "ingestion/daqreader_mfdaq_epochdata_ingested",
            daqreader_mfdaq_epochdata_ingested={
                "parameters": {
                    "sample_analog_segment": self.SAMPLE_ANALOG_SEGMENT,
                    "sample_digital_segment": self.SAMPLE_DIGITAL_SEGMENT,
                }
            },
            daqreader_epochdata_ingested={"epochtable": epochtable},
            epochid={"epochid": epoch_id},
        )
        d.set_dependency_value("daqreader_id", self.id)

        # Step 1: the channel list, with each channel's sample rate, offset and scale
        ch = self.getchannelsepoch(epochfiles)
        names = [c.name if hasattr(c, "name") else c["name"] for c in ch]
        types = [c.type if hasattr(c, "type") else c["type"] for c in ch]
        numbers = [channelname2prefixnumber(n)[1] for n in names]
        sample_rates = [float("nan")] * len(ch)
        for rate_type in (
            "analog_in",
            "analog_out",
            "auxiliary_in",
            "digital_in",
            "digital_out",
            "time",
        ):
            idx = [i for i, t in enumerate(types) if t == rate_type]
            if idx:
                sr = np.atleast_1d(
                    self.samplerate(epochfiles, rate_type, [numbers[i] for i in idx])
                )
                for j, i in enumerate(idx):
                    sample_rates[i] = float(sr[j])
        records = []
        for i, c in enumerate(ch):
            _, poly, _ = self.underlying_datatype(epochfiles, types[i], numbers[i])
            poly = np.atleast_2d(poly)
            time_channel = c.time_channel if hasattr(c, "time_channel") else c.get("time_channel")
            records.append(
                {
                    "name": names[i],
                    "type": types[i],
                    "time_channel": float("nan") if time_channel is None else time_channel,
                    "sample_rate": sample_rates[i],
                    "offset": float(poly[0, 0]),
                    "scale": float(poly[0, 1]),
                }
            )

        mec = ndi_file_type_mfdaq__epoch__channel().create_properties(records)
        channel_file_name = _ingest_temp_name()
        b, errmsg = mec.writeToFile(channel_file_name)
        if not b:
            raise RuntimeError(errmsg)
        d.add_file("channel_list.bin", channel_file_name)

        ci = mec.channel_information

        # Step 2: plan the data, one channel type and group at a time; event,
        # marker and text channels are stored together
        all_types, _ = self.channel_types()
        emt = ("event", "marker", "text")
        store_types = [t for t in all_types if t not in emt] + ["eventmarktext"]

        def entries_of(type_name: str) -> list[Any]:
            if type_name == "eventmarktext":
                return [c for c in ci if c.type in emt]
            return [c for c in ci if c.type == type_name]

        # each channel group counts in proportion to its number of channels,
        # which tracks the work of reading and compressing it
        weight_total = max(sum(len(entries_of(t)) for t in store_types), 1)
        plan: list[dict[str, Any]] = []

        for type_name in store_types:
            entries = entries_of(type_name)
            prefix = self.INGEST_FILE_PREFIX[type_name]
            for group in sorted({c.group for c in entries}):
                members = [c for c in entries if c.group == group]
                group_weight = len(members) / weight_total
                channels_here = [c.number for c in members]
                underlying_format, mypoly, datasize = self.underlying_datatype(
                    epochfiles, type_name, channels_here
                )
                # event/marker/text channels have no scalar sample rate
                if type_name == "eventmarktext":
                    rates = [float("nan")]
                else:
                    rates = np.atleast_1d(
                        self.samplerate(epochfiles, [c.type for c in members], channels_here)
                    ).tolist()
                unique_rates = {r for r in rates if not np.isnan(r)}
                if len(unique_rates) > 1:
                    raise ValueError(
                        f"Sample rates are not all identical for {type_name} group {group}."
                    )

                entry: dict[str, Any] = {
                    "kind": "",
                    "channeltype": type_name,
                    "channels": channels_here,
                    "eventchanneltypes": [],
                    "s0": None,
                    "s1": None,
                    "poly": np.atleast_2d(mypoly),
                    "datasize": datasize,
                    "underlying_format": underlying_format,
                    "docfilename": "",
                    "segment": None,
                    "numSegments": None,
                    "weight": None,
                }
                kind = members[0].dataclass
                if kind == "eventmarktext":
                    entry.update(
                        kind="eventmarktext",
                        eventchanneltypes=[c.type for c in members],
                        docfilename=f"evmktx_group{group}_seg.nbf_1",
                        segment=1,
                        numSegments=1,
                        weight=group_weight,
                    )
                    plan.append(entry)
                    continue
                if kind not in ("ephys", "digital", "time"):
                    raise ValueError(f"Unknown channel type {type_name}.")
                if not unique_rates:
                    raise ValueError("Analog records have a NaN sample rate.")
                t0t1 = self.t0_t1(epochfiles)
                # epochtimes2samples is 0-based; S1 is the 1-based last sample
                S1 = (
                    int(
                        np.asarray(
                            self.epochtimes2samples(
                                type_name, channels_here, epochfiles, t0t1[0][-1]
                            )
                        ).ravel()[0]
                    )
                    + 1
                )
                segment_length = (
                    self.SAMPLE_DIGITAL_SEGMENT if kind == "digital" else self.SAMPLE_ANALOG_SEGMENT
                )
                s_starts = list(range(1, S1 + 1, segment_length))
                for s, s0 in enumerate(s_starts, start=1):
                    plan.append(
                        {
                            **entry,
                            "kind": kind,
                            "s0": s0,
                            "s1": min(s0 + segment_length - 1, S1),
                            "docfilename": f"{prefix}_group{group}_seg.nbf_{s}",
                            "segment": s,
                            "numSegments": len(s_starts),
                            "weight": group_weight / len(s_starts),
                        }
                    )
        return d, plan

    def ingest_segment(self, epochfiles: list[str], planEntry: dict[str, Any]) -> str:  # noqa: N803
        """
        Read and compress one planned segment of an epoch.

        MATLAB equivalent: ndi.daq.reader.mfdaq/ingest_segment

        Reads the data described by PLANENTRY (one entry of the plan from
        :meth:`ingest_epochfiles_plan`) and writes it, compressed, to a new
        temporary file. Touches no database, so it can run in a worker
        process.

        Args:
            epochfiles: Files for this epoch
            planEntry: One entry of the plan

        Returns:
            The full path of the ``.nbf.tgz`` file written.
        """
        import ndicompress

        kind = planEntry["kind"]
        filename_here = _ingest_temp_name()
        if kind in ("ephys", "digital", "time"):
            logger.info(
                "Working on %s ingestion segment %d of %d.",
                {"ephys": "ephys/analog"}.get(kind, kind),
                planEntry["segment"],
                planEntry["numSegments"],
            )
            data = self.readchannels_epochsamples(
                planEntry["channeltype"],
                planEntry["channels"],
                epochfiles,
                planEntry["s0"],
                planEntry["s1"],
            )
            if kind == "ephys":
                _compress_ephys_underlying(
                    _scaled2underlying(data, planEntry["poly"]),
                    filename_here,
                    planEntry["underlying_format"],
                    planEntry["datasize"],
                )
            elif kind == "digital":
                ndicompress.compress_digital(
                    _scaled2underlying(data, planEntry["poly"]), filename_here
                )
            else:
                ndicompress.compress_time(np.asarray(data, dtype=float), filename_here)
        elif kind == "eventmarktext":
            logger.info("Working on event/marker/text ingestion segment 1 of 1.")
            T, D = self.readevents_epochsamples_native(
                planEntry["eventchanneltypes"], planEntry["channels"], epochfiles, -np.inf, np.inf
            )
            ndicompress.compress_eventmarktext(
                planEntry["eventchanneltypes"], planEntry["channels"], T, D, filename_here
            )
        else:
            raise ValueError(f"Unknown segment kind {kind}.")
        return filename_here + ".nbf.tgz"

    @staticmethod
    def ingest_attach_segments(
        d: Any, plan: list[dict[str, Any]], segmentFiles: list[str]  # noqa: N803 (MATLAB name)
    ) -> Any:
        """
        Add planned segment files to an ingested-epoch document, in plan order.

        MATLAB equivalent: ndi.daq.reader.mfdaq.ingest_attach_segments

        Args:
            d: The document from :meth:`ingest_epochfiles_plan`
            plan: Its plan
            segmentFiles: ``segmentFiles[t]``, the file :meth:`ingest_segment`
                wrote for ``plan[t]``

        Returns:
            The document, with the files added under each entry's ``docfilename``.
        """
        for entry, filename in zip(plan, segmentFiles):
            d.add_file(entry["docfilename"], filename)
        return d

    def underlying_datatype(
        self,
        epochfiles: list[str],
        channeltype: str,
        channel: int | list[int],
    ) -> tuple[str, np.ndarray, int]:
        """
        Get the underlying data type for channels.

        Args:
            epochfiles: Files for this epoch
            channeltype: Channel type
            channel: Channel number(s)

        Returns:
            Tuple of (datatype, polynomial, datasize):
            - datatype: NumPy dtype string (e.g., 'float64', 'uint16')
            - polynomial: Conversion polynomial [offset, scale]
            - datasize: Size in bits
        """
        if isinstance(channel, int):
            channel = [channel]

        channeltype = standardize_channel_type(channeltype)

        if channeltype in ("analog_in", "analog_out", "auxiliary_in", "time"):
            datatype = "float64"
            datasize = 64
            poly = np.tile([0.0, 1.0], (len(channel), 1))
        elif channeltype in ("digital_in", "digital_out"):
            datatype = "uint8"
            datasize = 8
            poly = np.tile([0.0, 1.0], (len(channel), 1))
        elif channeltype in ("event", "marker", "text", "eventmarktext"):
            datatype = "float64"
            datasize = 64
            poly = np.tile([0.0, 1.0], (len(channel), 1))
        else:
            raise ValueError(f"Unknown channel type: {channeltype}")

        return datatype, poly, datasize

    @staticmethod
    def channel_types() -> tuple[list[str], list[str]]:
        """
        Return available channel types and abbreviations.

        Returns:
            Tuple of (types, abbreviations)
        """
        types = [
            "analog_in",
            "analog_out",
            "auxiliary_in",
            "digital_in",
            "digital_out",
            "event",
            "marker",
            "text",
            "time",
        ]
        abbrevs = ["ai", "ao", "ax", "di", "do", "e", "mk", "tx", "t"]
        return types, abbrevs

    @staticmethod
    def is_analog_event_type(
        channeltype: str | list[str],
    ) -> tuple[bool, list[str], list[float]]:
        """
        Check if channel type(s) are analog event types.

        Analog event types derive events from analog input channels by
        detecting threshold crossings:

        - ``aep`` / ``aep_tX``: positive (upward) threshold crossings
        - ``aen`` / ``aen_tX``: negative (downward) threshold crossings
        - ``aimp`` / ``aimp_tX``: analog input mark positive (pulse above then below)
        - ``aimn`` / ``aimn_tX``: analog input mark negative (pulse below then above)

        Args:
            channeltype: Channel type string or list of strings

        Returns:
            Tuple of (is_analog_event, base_types, thresholds):
            - is_analog_event: True if any channel type is an analog event type
            - base_types: List of base type strings with threshold stripped
            - thresholds: List of threshold values (0.0 if not specified)
        """
        analog_event_prefixes = {"aep", "aen", "aimp", "aimn"}
        if isinstance(channeltype, str):
            channeltype = [channeltype]

        base_types = []
        thresholds = []
        for ct in channeltype:
            bt, th = ndi_daq_daqsystemstring.parse_analog_event_channeltype(ct)
            base_types.append(bt)
            thresholds.append(th)

        tf = bool(set(base_types) & analog_event_prefixes)
        return tf, base_types, thresholds

    # =========================================================================
    # Ingested data methods - for reading from database-stored epochs
    # =========================================================================

    def getchannelsepoch_ingested(
        self,
        epochfiles: list[str],
        session: Any,
    ) -> list[ChannelInfo]:
        """
        List channels for an ingested epoch.

        Reads channel information from the ``channel_list.bin`` binary file
        attached to the ingested document, matching the MATLAB approach.

        Args:
            epochfiles: List of file paths (starting with epochid://)
            session: ndi_session object with database access

        Returns:
            List of ChannelInfo objects
        """
        doc = self.getingesteddocument(epochfiles, session)
        try:
            fobj = session.database_openbinarydoc(doc, "channel_list.bin")
            tname = fobj.name
            fobj.close()
            from ..file.type.mfdaq_epoch_channel import ndi_file_type_mfdaq__epoch__channel

            mec = ndi_file_type_mfdaq__epoch__channel()
            mec.readFromFile(tname)
            return mec.channel_information
        except Exception as _exc:
            # Fallback: try reading from epochtable JSON (older format)
            et = doc.document_properties.get(
                "daqreader_mfdaq_epochdata_ingested",
                doc.document_properties.get("daqreader_epochdata_ingested", {}),
            ).get("epochtable", {})
            channels_raw = et.get("channels", [])
            if channels_raw:
                return [ChannelInfo.from_dict(ch) for ch in channels_raw]
            # Neither path worked — raise with context
            raise ValueError(
                f"Cannot read channel info: channel_list.bin failed ({_exc}), "
                f"and no channels in epochtable JSON"
            ) from _exc

    def readchannels_epochsamples_ingested(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        s0: int,
        s1: int,
        session: Any,
    ) -> np.ndarray:
        """
        Read channel data from an ingested epoch.

        Reads compressed segment files (``ai_group*_seg.nbf_*``) from the
        ingested document using ``ndicompress``, matching the MATLAB approach.

        Args:
            channeltype: Type(s) of channel to read
            channel: Channel number(s) to read (1-indexed)
            epochfiles: Files for this epoch (starting with epochid://)
            s0: Start sample (0-indexed; may be ``-np.inf`` or a value
                before the epoch's first sample, both of which clamp to
                the epoch's start)
            s1: End sample (0-indexed; may be ``np.inf`` or a value past
                the epoch's last sample, both of which clamp to the
                epoch's end)
            session: ndi_session object with database access

        Returns:
            Array with shape (num_samples, num_channels). Empty
            ``np.zeros((0, len(channel)))`` when the requested window
            lies entirely outside the epoch.

        Raises:
            ValueError: If ``s0 > s1``.
        """
        import ndicompress

        doc = self.getingesteddocument(epochfiles, session)

        # Normalize inputs
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)
        channeltype = standardize_channel_types(channeltype)

        ch_unique = list(set(channeltype))
        if len(ch_unique) != 1:
            raise ValueError("Only one type of channel may be read per function call")

        # Get sample rate, offset, scale
        sr, offset, scale = self.samplerate_ingested(epochfiles, channeltype, channel, session)
        sr_unique = np.unique(sr)
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sampling rates across channels")

        # Clamp the requested window to what the epoch actually has.
        # The ingested reader addresses concrete _seg.nbf_N files, so it
        # cannot pass an out-of-range sample number through to disk the
        # way the local readers can; a filter-warm-up read like
        # pyraview's (which asks for t = t0 - excess on the first chunk)
        # would otherwise ask for a _seg.nbf_0 that no writer has ever
        # produced.
        t0_t1 = self.t0_t1_ingested(epochfiles, session)
        abs_s = self.epochtimes2samples_ingested(
            channeltype, channel, epochfiles, np.array(t0_t1[0]), session
        )
        absolute_beginning = int(abs_s[0])
        absolute_end = int(abs_s[1])

        # A caller who passes s0 > s1 has inverted the endpoints; that is
        # a coding error, not a request. Check before the clamp so an
        # inversion is not silently absorbed by clipping one endpoint
        # into the other.
        if s0 > s1:
            raise ValueError("s0 must be less than or equal to s1")

        # -Inf and any finite value before the epoch mean "start at the
        # first sample"; +Inf and any finite value past the epoch mean
        # "end at the last sample". A window that lies entirely outside
        # [t0, t1] returns an empty slice -- read past the edge, get
        # nothing there.
        s0 = max(s0, absolute_beginning)
        s1 = min(s1, absolute_end)
        if s0 > s1:
            return np.zeros((0, len(channel)))
        s0 = int(s0)
        s1 = int(s1)

        # Get channel info for group decoding
        full_channel_info = self.getchannelsepoch_ingested(epochfiles, session)

        from ..file.type.mfdaq_epoch_channel import ndi_file_type_mfdaq__epoch__channel

        groups, ch_idx_in_groups, ch_idx_in_output = (
            ndi_file_type_mfdaq__epoch__channel.channelgroupdecoding(
                full_channel_info, ch_unique[0], channel
            )
        )

        # Determine segment parameters and file prefix
        props = doc.document_properties
        mfdaq_params = props.get("daqreader_mfdaq_epochdata_ingested", {}).get("parameters", {})

        analog_types = {"analog_in", "analog_out", "auxiliary_in", "auxiliary_out"}
        digital_types = {"digital_in", "digital_out"}

        if ch_unique[0] in analog_types:
            samples_segment = mfdaq_params.get("sample_analog_segment", 1_000_000)
            expand_fn = ndicompress.expand_ephys
        elif ch_unique[0] in digital_types:
            samples_segment = mfdaq_params.get("sample_digital_segment", 1_000_000)
            expand_fn = ndicompress.expand_digital
        elif ch_unique[0] == "time":
            samples_segment = mfdaq_params.get("sample_analog_segment", 1_000_000)
            expand_fn = ndicompress.expand_time
        else:
            raise ValueError(f"Unknown channel type {ch_unique[0]}. Use readevents for events.")

        # Map channel type to file prefix
        prefix_map = {
            "analog_in": "ai",
            "analog_out": "ao",
            "auxiliary_in": "ax",
            "auxiliary_out": "ax",
            "digital_in": "di",
            "digital_out": "do",
            "time": "ti",
        }
        prefix = prefix_map.get(ch_unique[0], ch_unique[0])

        # Read segments — s0/s1 are 0-based Python indices
        seg_start = (s0 // samples_segment) + 1  # 1-based segment number
        seg_stop = (s1 // samples_segment) + 1

        data = np.full((s1 - s0 + 1, len(channel)), np.nan)
        count = 0

        for seg in range(seg_start, seg_stop + 1):
            # Compute 0-based sample range within this segment
            seg_offset = (seg - 1) * samples_segment  # 0-based start of segment
            if seg == seg_start:
                s0_ = s0 - seg_offset  # 0-based within segment
            else:
                s0_ = 0
            if seg == seg_stop:
                s1_ = s1 - seg_offset  # 0-based within segment
            else:
                s1_ = samples_segment - 1

            n_samples_here = s1_ - s0_ + 1

            for g_idx, grp in enumerate(groups):
                fname = f"{prefix}_group{grp}_seg.nbf_{seg}"
                fobj = session.database_openbinarydoc(doc, fname)
                tname = fobj.name
                fobj.close()

                # Remove .tgz extension for ndicompress (it adds it back)
                tname_base = tname
                if tname_base.endswith(".tgz"):
                    tname_base = tname_base[:-4]
                if tname_base.endswith(".nbf"):
                    tname_base = tname_base[:-4]

                result = expand_fn(tname_base)
                # expand_* functions return (data, error_signal) tuple
                data_here = result[0] if isinstance(result, tuple) else result

                # Handle last segment possibly having fewer samples
                if data_here.shape[0] <= s1_:
                    s1_ = data_here.shape[0] - 1
                    n_samples_here = s1_ - s0_ + 1

                rows = slice(count, count + n_samples_here)
                data[rows, ch_idx_in_output[g_idx]] = data_here[
                    s0_ : s1_ + 1, ch_idx_in_groups[g_idx]
                ]

            count += n_samples_here

        # Trim if last segment was shorter
        if count < data.shape[0]:
            data = data[:count, :]

        # Apply underlying2scaled: (data - offset) * scale
        data = (data - np.array(offset)) * np.array(scale)

        return data

    def readevents_epochsamples_ingested(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
        session: Any,
    ) -> tuple[list[np.ndarray] | np.ndarray, list[np.ndarray] | np.ndarray]:
        """
        Read event/marker/text data from an ingested epoch.

        Matches MATLAB ``readevents_epochsamples_ingested``. For derived
        digital event types (dep/den/dimp/dimn), reads digital channels
        and detects transitions. For native events/markers/text, reads
        from compressed ``evmktx_group*_seg.nbf_*`` files.

        Args:
            channeltype: Event channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch (starting with epochid://)
            t0: Start time
            t1: End time
            session: ndi_session object with database access

        Returns:
            Tuple of (timestamps, data)
        """
        import ndicompress

        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)
        channeltype = standardize_channel_types(channeltype)

        # Handle analog event types (aep, aen, aimp, aimn)
        is_analog, _, _ = ndi_daq_reader_mfdaq.is_analog_event_type(channeltype)
        if is_analog:
            return self._read_analog_events_ingested(
                channeltype, channel, epochfiles, t0, t1, session
            )

        derived = {"dep", "den", "dimp", "dimn"}
        if set(channeltype) & derived:
            # Handle derived digital event types
            timestamps_list = []
            data_list = []
            for i, ch_num in enumerate(zip(channel)):
                sd = self.epochtimes2samples_ingested(
                    ["digital_in"], [ch_num], epochfiles, np.array([t0, t1]), session
                )
                s0d, s1d = int(sd[0]), int(sd[1])
                data_here = self.readchannels_epochsamples_ingested(
                    ["digital_in"], [ch_num], epochfiles, s0d, s1d, session
                )
                time_here = self.readchannels_epochsamples_ingested(
                    ["time"], [ch_num], epochfiles, s0d, s1d, session
                )
                data_here = data_here.ravel()
                time_here = time_here.ravel()

                ct = channeltype[i]
                if ct in ("dep", "dimp"):
                    on_samples = np.where((data_here[:-1] == 0) & (data_here[1:] == 1))[0] + 1
                    off_samples = (
                        np.where((data_here[:-1] == 1) & (data_here[1:] == 0))[0] + 1
                        if ct == "dimp"
                        else np.array([], dtype=int)
                    )
                else:  # den, dimn
                    on_samples = np.where((data_here[:-1] == 1) & (data_here[1:] == 0))[0] + 1
                    off_samples = (
                        np.where((data_here[:-1] == 0) & (data_here[1:] == 1))[0] + 1
                        if ct == "dimn"
                        else np.array([], dtype=int)
                    )

                ts = np.concatenate([time_here[on_samples], time_here[off_samples]])
                dd = np.concatenate(
                    [
                        np.ones(len(on_samples)),
                        -np.ones(len(off_samples)),
                    ]
                )
                if len(off_samples) > 0:
                    order = np.argsort(ts)
                    ts = ts[order]
                    dd = dd[order]
                timestamps_list.append(ts)
                data_list.append(dd)

            if len(channel) == 1:
                return timestamps_list[0], data_list[0]
            return timestamps_list, data_list

        # Native events/markers/text
        doc = self.getingesteddocument(epochfiles, session)
        fname = "evmktx_group1_seg.nbf_1"
        try:
            fobj = session.database_openbinarydoc(doc, fname)
            tname = fobj.name
            fobj.close()
            tname_base = tname
            if tname_base.endswith(".tgz"):
                tname_base = tname_base[:-4]
            if tname_base.endswith(".nbf"):
                tname_base = tname_base[:-4]
            ct_out, ch_out, T, D = ndicompress.expand_eventmarktext(tname_base)
        except Exception as exc:
            raise ValueError(f"No event data found for this epoch: {exc}") from exc

        # Standardize the output channel types for matching
        if isinstance(ct_out, list):
            ct_out_std = standardize_channel_types(ct_out)
        else:
            ct_out_std = standardize_channel_types(list(ct_out))

        timestamps_list = []
        data_list = []
        for ct, ch_num in zip(channeltype, channel):
            ct_std = standardize_channel_type(ct)
            matches = [
                j
                for j, (cto, cho) in enumerate(zip(ct_out_std, ch_out))
                if cto == ct_std and cho == ch_num
            ]
            if not matches:
                raise ValueError(f"Channel type {ct} and channel {ch_num} not found in event data")
            idx = matches[0]
            ts = np.asarray(T[idx])
            dd = np.asarray(D[idx])
            # Filter by time range
            included = (ts >= t0) & (ts <= t1)
            if ts.ndim > 1:
                included = included[:, 0] if included.ndim > 1 else included
            timestamps_list.append(ts[included])
            data_list.append(dd[included] if dd.ndim <= 1 else dd[included])

        if len(channel) == 1:
            return timestamps_list[0], data_list[0]
        return timestamps_list, data_list

    def _read_analog_events_ingested(
        self,
        channeltype: list[str],
        channel: list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
        session: Any,
    ) -> tuple[list[np.ndarray] | np.ndarray, list[np.ndarray] | np.ndarray]:
        """Read events derived from analog channels via threshold crossing (ingested)."""
        _, base_types, thresholds = ndi_daq_reader_mfdaq.is_analog_event_type(channeltype)

        timestamps = []
        data = []

        for i, ch in enumerate(channel):
            bt = base_types[i]
            thresh = thresholds[i]

            sd = self.epochtimes2samples_ingested(
                ["ai"], [ch], epochfiles, np.array([t0, t1]), session
            )
            s0, s1 = int(sd[0]), int(sd[1])

            ai_data = self.readchannels_epochsamples_ingested(
                ["ai"], [ch], epochfiles, s0, s1, session
            )
            time_data = self.readchannels_epochsamples_ingested(
                ["time"], [ch], epochfiles, s0, s1, session
            )

            ai_data = ai_data.flatten()
            time_data = time_data.flatten()

            below = ai_data[:-1] < thresh
            above = ai_data[1:] >= thresh

            if bt in ("aep", "aimp"):
                on_samples = 1 + np.where(below & above)[0]
                off_samples = (
                    1 + np.where(~below & ~above)[0] if bt == "aimp" else np.array([], dtype=int)
                )
                on_sign, off_sign = 1, -1
            else:  # aen, aimn
                on_samples = 1 + np.where(~below & ~above)[0]
                off_samples = (
                    1 + np.where(below & above)[0] if bt == "aimn" else np.array([], dtype=int)
                )
                on_sign, off_sign = -1, 1

            ts = np.concatenate(
                [
                    time_data[on_samples],
                    time_data[off_samples] if len(off_samples) else np.array([]),
                ]
            )
            d = np.concatenate(
                [
                    on_sign * np.ones(len(on_samples)),
                    off_sign * np.ones(len(off_samples)) if len(off_samples) else np.array([]),
                ]
            )

            if len(off_samples) > 0:
                order = np.argsort(ts)
                ts = ts[order]
                d = d[order]

            timestamps.append(ts)
            data.append(d)

        if len(channel) == 1:
            return timestamps[0], data[0]
        return timestamps, data

    def samplerate_ingested(
        self,
        epochfiles: list[str],
        channeltype: str | list[str],
        channel: int | list[int],
        session: Any,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Get sample rate, offset, and scale for channels from an ingested epoch.

        Reads channel metadata from the ``channel_list.bin`` binary file,
        matching the MATLAB approach which returns (sr, offset, scale).

        Args:
            epochfiles: Files for this epoch (starting with epochid://)
            channeltype: Type(s) of channel
            channel: Channel number(s)
            session: ndi_session object with database access

        Returns:
            Tuple of (sample_rates, offsets, scales) arrays
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)
        channeltype = standardize_channel_types(channeltype)

        full_channel_info = self.getchannelsepoch_ingested(epochfiles, session)

        sr = np.zeros(len(channel))
        offset = np.zeros(len(channel))
        scale = np.ones(len(channel))

        for i, (ct, ch_num) in enumerate(zip(channeltype, channel)):
            ct_std = standardize_channel_type(ct)
            match = [
                ci
                for ci in full_channel_info
                if standardize_channel_type(ci.type) == ct_std and ci.number == ch_num
            ]
            if not match:
                raise ValueError(
                    f"No such channel: {ct} : {ch_num}. "
                    f"Available: {[(ci.type, ci.number) for ci in full_channel_info[:5]]}"
                )
            sr[i] = match[0].sample_rate
            offset[i] = match[0].offset
            scale[i] = match[0].scale

        return sr, offset, scale

    def epochsamples2times_ingested(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        samples: np.ndarray,
        session: Any,
    ) -> np.ndarray:
        """
        Convert 0-based sample indices to time for an ingested epoch.

        Note:
            Unlike MATLAB (1-based), Python sample indices are 0-based.
            Sample 0 corresponds to time t0 of the epoch.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch (starting with epochid://)
            samples: Sample indices (0-based)
            session: ndi_session object with database access

        Returns:
            Time values
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        sr_arr, _, _ = self.samplerate_ingested(epochfiles, channeltype, channel, session)
        sr_unique = np.unique(sr_arr)
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sample rates across channels")
        sr = sr_unique[0]

        t0t1 = self.t0_t1_ingested(epochfiles, session)
        t0 = t0t1[0][0]

        samples = np.asarray(samples)
        t = t0 + samples / sr

        if np.any(np.isinf(samples)):
            t[np.isinf(samples) & (samples < 0)] = t0

        return t

    def epochtimes2samples_ingested(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        times: np.ndarray,
        session: Any,
    ) -> np.ndarray:
        """
        Convert time to 0-based sample indices for an ingested epoch.

        Note:
            Unlike MATLAB (1-based), Python sample indices are 0-based.
            Sample 0 corresponds to time t0 of the epoch.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch (starting with epochid://)
            times: Time values
            session: ndi_session object with database access

        Returns:
            Sample indices (0-based)
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        sr_arr, _, _ = self.samplerate_ingested(epochfiles, channeltype, channel, session)
        sr_unique = np.unique(sr_arr)
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sample rates across channels")
        sr = sr_unique[0]

        t0t1 = self.t0_t1_ingested(epochfiles, session)
        t0 = t0t1[0][0]

        times = np.asarray(times)
        s = np.round((times - t0) * sr).astype(int)

        if np.any(np.isinf(times)):
            s[np.isinf(times) & (times < 0)] = 0
            pos_inf = np.isinf(times) & (times > 0)
            if np.any(pos_inf):
                t1 = t0t1[0][1]
                s_end = round((t1 - t0) * sr)
                s[pos_inf] = s_end

        return s


def _ingest_temp_name() -> str:
    """A new temporary file name (no extension), as MATLAB's ndi.file.temp_name."""
    return os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)


def _report_ingest_progress(progress_fcn: Callable[[float], Any] | None, fraction: float) -> None:
    """Call PROGRESS_FCN(FRACTION); progress reporting must never break an ingest.

    MATLAB equivalent: ndi.daq.reader.mfdaq.reportIngestProgress
    """
    if progress_fcn is None:
        return
    try:
        progress_fcn(min(max(float(fraction), 0.0), 1.0))
    except Exception as exc:  # noqa: BLE001 - progress must never break an ingest
        warnings.warn(f"Progress reporting failed: {exc}", stacklevel=2)


def _scaled2underlying(data: Any, poly: Any) -> np.ndarray:
    """Scaled data to underlying values: D ./ scale + offset, per column.

    MATLAB equivalent: ndi.compress.scaled2underlying
    """
    poly = np.atleast_2d(np.asarray(poly, dtype=float))
    data = np.asarray(data, dtype=float)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    return data / poly[:, 1][np.newaxis, :] + poly[:, 0][np.newaxis, :]


_FLOAT_TYPES = {
    "float64": np.float64,
    "double": np.float64,
    "float32": np.float32,
    "single": np.float32,
}


def _compress_ephys_underlying(
    data: np.ndarray, filename: str, underlying_format: str, datasize: int
) -> None:
    """Compress underlying-valued DATA as MATLAB's ingest does.

    MATLAB calls ndi.compress.compress_ephys(DATA, DATASIZE, FILENAME,
    'data_format', ndi.compress.datatypestring(FORMAT), 'data_is_unsigned', ...),
    whose integer path rounds the samples to integers of the underlying type.
    The C encoder takes the samples in that type, so they are rounded and
    clipped to its range here.
    """
    import ndicompress

    fmt = underlying_format.lower()
    if fmt in _FLOAT_TYPES:
        ndicompress.compress_ephys(
            np.asarray(data, dtype=_FLOAT_TYPES[fmt]),
            filename,
            output_size_bits=int(datasize),
            data_is_unsigned=False,
            data_format="float",
        )
        return
    dtype = np.dtype(fmt)
    if not np.issubdtype(dtype, np.integer):
        raise ValueError(f"Unknown underlying data type {underlying_format}.")
    info = np.iinfo(dtype)
    values = np.clip(np.round(data), info.min, info.max).astype(dtype)
    ndicompress.compress_ephys(
        values,
        filename,
        output_size_bits=int(datasize),
        data_is_unsigned=fmt.startswith("u"),
        data_format="integer",
    )
