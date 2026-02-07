"""
ndi.daq.mfdaq - Multi-function DAQ reader class.

This module provides the MFDAQReader class for reading data from
multi-function data acquisition systems that sample various data types.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from ..time import DEV_LOCAL_TIME, ClockType
from .reader_base import DAQReader


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


class MFDAQReader(DAQReader):
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
        >>> class IntanReader(MFDAQReader):
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
        Create a new MFDAQReader.

        Args:
            identifier: Optional identifier
            session: Optional session object
            document: Optional document to load from
        """
        super().__init__(identifier, session, document)

    def epochclock(
        self,
        epochfiles: list[str],
    ) -> list[ClockType]:
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

        Retrieves channel information from the ingested document stored
        in the database.

        Args:
            epochfiles: List of file paths (starting with epochid://)
            session: Session object with database access

        Returns:
            List of ChannelInfo objects

        See also: getchannelsepoch
        """
        doc = self.getingesteddocument(epochfiles, session)
        et = doc.document_properties.daqreader_epochdata_ingested.epochtable

        channels_raw = et.get("channels", [])
        channels = []

        for ch_dict in channels_raw:
            channels.append(
                ChannelInfo(
                    name=ch_dict.get("name", ""),
                    type=ch_dict.get("type", "analog_in"),
                    time_channel=ch_dict.get("time_channel"),
                    number=ch_dict.get("number"),
                    sample_rate=ch_dict.get("sample_rate"),
                    offset=ch_dict.get("offset", 0.0),
                    scale=ch_dict.get("scale", 1.0),
                    group=ch_dict.get("group", 1),
                )
            )

        return channels

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

        Retrieves the data from the binary file referenced by the
        ingested document in the database.

        Args:
            channeltype: Type(s) of channel to read
            channel: Channel number(s) to read (1-indexed)
            epochfiles: Files for this epoch (starting with epochid://)
            s0: Start sample (1-indexed)
            s1: End sample (1-indexed)
            session: Session object with database access

        Returns:
            Array with shape (num_samples, num_channels)

        See also: readchannels_epochsamples
        """
        doc = self.getingesteddocument(epochfiles, session)
        et = doc.document_properties.daqreader_epochdata_ingested.epochtable

        # Normalize inputs
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        channeltype = standardize_channel_types(channeltype)

        # Get data file reference from document
        data_file = et.get("data_file", None)
        if data_file is None:
            return np.full((s1 - s0 + 1, len(channel)), np.nan)

        # Read from VHSB format
        try:
            from vlt.file.custom_file_formats import vhsb_read

            data = vhsb_read(
                data_file,
                channels=channel,
                sample_start=s0,
                sample_end=s1,
            )
            return data
        except ImportError:
            # Fallback: return NaN if vlt not available
            return np.full((s1 - s0 + 1, len(channel)), np.nan)

    def samplerate_ingested(
        self,
        epochfiles: list[str],
        channeltype: str | list[str],
        channel: int | list[int],
        session: Any,
    ) -> np.ndarray:
        """
        Get sample rate for channels from an ingested epoch.

        Args:
            epochfiles: Files for this epoch (starting with epochid://)
            channeltype: Type(s) of channel
            channel: Channel number(s)
            session: Session object with database access

        Returns:
            Array of sample rates

        See also: samplerate
        """
        if isinstance(channel, int):
            channel = [channel]

        # Get channels from ingested document
        channels = self.getchannelsepoch_ingested(epochfiles, session)

        # Build lookup by channel number
        sr_lookup = {}
        for ch in channels:
            if ch.number is not None and ch.sample_rate is not None:
                sr_lookup[ch.number] = ch.sample_rate

        # Return sample rates for requested channels
        sr = np.zeros(len(channel))
        for i, ch_num in enumerate(channel):
            sr[i] = sr_lookup.get(ch_num, np.nan)

        return sr

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
            session: Session object with database access

        Returns:
            Time values

        See also: epochsamples2times
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        sr = self.samplerate_ingested(epochfiles, channeltype, channel, session)
        sr_unique = np.unique(sr[~np.isnan(sr)])
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sample rates across channels")
        sr = sr_unique[0]

        t0t1 = self.t0_t1_ingested(epochfiles, session)
        t0 = t0t1[0][0]

        samples = np.asarray(samples)
        t = t0 + (samples - 1) / sr

        # Handle infinite values
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
            session: Session object with database access

        Returns:
            Sample indices (1-indexed)

        See also: epochtimes2samples
        """
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        sr = self.samplerate_ingested(epochfiles, channeltype, channel, session)
        sr_unique = np.unique(sr[~np.isnan(sr)])
        if len(sr_unique) != 1:
            raise ValueError("Cannot handle different sample rates across channels")
        sr = sr_unique[0]

        t0t1 = self.t0_t1_ingested(epochfiles, session)
        t0 = t0t1[0][0]

        times = np.asarray(times)
        s = 1 + np.round((times - t0) * sr).astype(int)

        # Handle infinite values
        if np.any(np.isinf(times)):
            s[np.isinf(times) & (times < 0)] = 1

        return s
