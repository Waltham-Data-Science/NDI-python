"""
ndi.daq.mfdaq - Multi-function DAQ reader class.

This module provides the ndi_daq_reader_mfdaq class for reading data from
multi-function data acquisition systems that sample various data types.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from ..time import DEV_LOCAL_TIME, ndi_time_clocktype
from .reader_base import ndi_daq_reader


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
        Convert sample indices to time.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch
            samples: Sample indices (1-indexed)

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
        t = t0 + (samples - 1) / sr

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
        Convert time to sample indices.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch
            times: Time values

        Returns:
            Sample indices (1-indexed)
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
        s = 1 + np.round((times - t0) * sr).astype(int)

        # Handle infinite values
        if np.any(np.isinf(times)):
            s[np.isinf(times) & (times < 0)] = 1

        return s

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
        except Exception:
            # Fallback: try reading from epochtable JSON (older format)
            et = doc.document_properties.get(
                "daqreader_mfdaq_epochdata_ingested",
                doc.document_properties.get("daqreader_epochdata_ingested", {}),
            ).get("epochtable", {})
            channels_raw = et.get("channels", [])
            return [ChannelInfo.from_dict(ch) for ch in channels_raw]

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
            s0: Start sample (1-indexed)
            s1: End sample (1-indexed)
            session: ndi_session object with database access

        Returns:
            Array with shape (num_samples, num_channels)
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

        # Handle infinite bounds
        t0_t1 = self.t0_t1_ingested(epochfiles, session)
        abs_s = self.epochtimes2samples_ingested(
            channeltype, channel, epochfiles, np.array(t0_t1[0]), session
        )
        if np.isinf(s0):
            s0 = int(abs_s[0])
        if np.isinf(s1):
            s1 = int(abs_s[1])

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

        # Read segments
        import math

        seg_start = math.ceil(s0 / samples_segment)
        seg_stop = math.ceil(s1 / samples_segment)

        data = np.full((s1 - s0 + 1, len(channel)), np.nan)
        count = 0

        for seg in range(seg_start, seg_stop + 1):
            # Compute sample range within this segment
            if seg == seg_start:
                s0_ = ((s0 - 1) % samples_segment) + 1
            else:
                s0_ = 1
            if seg == seg_stop:
                s1_ = ((s1 - 1) % samples_segment) + 1
            else:
                s1_ = samples_segment

            n_samples_here = s1_ - s0_ + 1

            for g_idx, grp in enumerate(groups):
                fname = f"{prefix}_group{grp}_seg.nbf_{seg}"
                try:
                    fobj = session.database_openbinarydoc(doc, fname)
                    tname = fobj.name
                    fobj.close()

                    # Remove .tgz extension for ndicompress (it adds it back)
                    tname_base = tname
                    if tname_base.endswith(".tgz"):
                        tname_base = tname_base[:-4]
                    if tname_base.endswith(".nbf"):
                        tname_base = tname_base[:-4]

                    data_here = expand_fn(tname_base)

                    # Handle last segment possibly having fewer samples
                    if data_here.shape[0] < s1_:
                        s1_ = data_here.shape[0]
                        n_samples_here = s1_ - s0_ + 1

                    rows = slice(count, count + n_samples_here)
                    data[rows, ch_idx_in_output[g_idx]] = data_here[
                        s0_ - 1 : s1_, ch_idx_in_groups[g_idx]
                    ]
                except Exception:
                    pass  # Leave as NaN

            count += n_samples_here

        # Trim if last segment was shorter
        if count < data.shape[0]:
            data = data[:count, :]

        # Apply offset and scale
        data = data * np.array(scale) + np.array(offset)

        return data

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
        Convert sample indices to time for an ingested epoch.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch (starting with epochid://)
            samples: Sample indices (1-indexed)
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
        t = t0 + (samples - 1) / sr

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
        Convert time to sample indices for an ingested epoch.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epochfiles: Files for this epoch (starting with epochid://)
            times: Time values
            session: ndi_session object with database access

        Returns:
            Sample indices (1-indexed)
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
        s = 1 + np.round((times - t0) * sr).astype(int)

        if np.any(np.isinf(times)):
            s[np.isinf(times) & (times < 0)] = 1

        return s
