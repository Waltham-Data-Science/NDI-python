"""
ndi.daq.reader.spikeinterface_adapter - SpikeInterface-based DAQ reader.

This module provides a DAQ reader that uses the spikeinterface library
to read data from various neuroscience data formats.

Supported formats (via spikeinterface):
- Intan RHD/RHS
- Blackrock (NSx, NEV)
- Open Ephys
- SpikeGLX
- And many more...
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ...time import DEV_LOCAL_TIME, ClockType
from ..mfdaq import ChannelInfo, MFDAQReader, standardize_channel_type

# Try to import spikeinterface
try:
    import spikeinterface as si
    import spikeinterface.extractors as se

    HAS_SPIKEINTERFACE = True
except ImportError:
    HAS_SPIKEINTERFACE = False
    si = None
    se = None


def _get_extractor_for_file(filepath: str) -> Any | None:
    """
    Get the appropriate spikeinterface extractor for a file.

    Args:
        filepath: Path to the data file

    Returns:
        SpikeInterface recording extractor or None
    """
    if not HAS_SPIKEINTERFACE:
        return None

    path = Path(filepath)
    suffix = path.suffix.lower()

    try:
        # Intan RHD
        if suffix == ".rhd":
            return se.read_intan(filepath, stream_id="0")

        # Intan RHS
        if suffix == ".rhs":
            return se.read_intan(filepath, stream_id="0")

        # Blackrock
        if suffix in (".ns1", ".ns2", ".ns3", ".ns4", ".ns5", ".ns6"):
            return se.read_blackrock(filepath)

        # Open Ephys binary
        if suffix == ".oebin" or path.name == "structure.oebin":
            return se.read_openephys(path.parent)

        # SpikeGLX
        if suffix == ".ap.bin" or suffix == ".lf.bin":
            return se.read_spikeglx(path.parent)

        # Binary raw
        if suffix == ".bin" or suffix == ".dat":
            # Need additional parameters for raw binary
            return None

        # Try auto-detect
        return si.load_extractor(filepath)

    except Exception:
        return None


class SpikeInterfaceReader(MFDAQReader):
    """
    DAQ reader using spikeinterface for data access.

    This reader wraps the spikeinterface library to provide access
    to many neuroscience data formats. It implements the MFDAQReader
    interface for seamless integration with NDI.

    Supported formats include:
    - Intan RHD/RHS
    - Blackrock (NSx, NEV)
    - Open Ephys
    - SpikeGLX
    - And many more via spikeinterface

    Attributes:
        stream_id: Stream ID for multi-stream formats

    Example:
        >>> reader = SpikeInterfaceReader()
        >>> channels = reader.getchannelsepoch(['recording.rhd'])
        >>> data = reader.readchannels_epochsamples('ai', [1, 2], ['recording.rhd'], 0, 1000)
    """

    def __init__(
        self,
        stream_id: str | None = None,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        """
        Create a SpikeInterfaceReader.

        Args:
            stream_id: Stream ID for multi-stream formats (e.g., Intan)
            identifier: Optional unique identifier
            session: Optional session object
            document: Optional document to load from
        """
        if not HAS_SPIKEINTERFACE:
            raise ImportError(
                "spikeinterface is required for SpikeInterfaceReader. "
                "Install with: pip install spikeinterface"
            )

        super().__init__(identifier, session, document)
        self._stream_id = stream_id
        self._recording_cache: dict[str, Any] = {}

    def _get_recording(self, epochfiles: list[str]) -> Any | None:
        """Get or create recording extractor for epoch files."""
        if not epochfiles:
            return None

        # Use first file as cache key
        cache_key = epochfiles[0]
        if cache_key in self._recording_cache:
            return self._recording_cache[cache_key]

        # Try each file until one works
        for filepath in epochfiles:
            recording = _get_extractor_for_file(filepath)
            if recording is not None:
                self._recording_cache[cache_key] = recording
                return recording

        return None

    def epochclock(
        self,
        epochfiles: list[str],
    ) -> list[ClockType]:
        """Return clock types for epoch. Returns DEV_LOCAL_TIME."""
        return [DEV_LOCAL_TIME]

    def t0_t1(
        self,
        epochfiles: list[str],
    ) -> list[tuple[float, float]]:
        """
        Return start and end times for epoch.

        Args:
            epochfiles: Files for this epoch

        Returns:
            List with single (t0, t1) tuple
        """
        recording = self._get_recording(epochfiles)
        if recording is None:
            return [(np.nan, np.nan)]

        try:
            num_samples = recording.get_num_samples()
            sr = recording.get_sampling_frequency()
            t0 = 0.0
            t1 = (num_samples - 1) / sr
            return [(t0, t1)]
        except Exception:
            return [(np.nan, np.nan)]

    def getchannelsepoch(
        self,
        epochfiles: list[str],
    ) -> list[ChannelInfo]:
        """
        List channels for this epoch.

        Args:
            epochfiles: Files for this epoch

        Returns:
            List of ChannelInfo objects
        """
        recording = self._get_recording(epochfiles)
        if recording is None:
            return []

        channels = []
        try:
            channel_ids = recording.get_channel_ids()
            sr = recording.get_sampling_frequency()

            for i, ch_id in enumerate(channel_ids):
                # Determine channel type from properties if available
                ch_type = "analog_in"  # Default

                # Try to get gain/offset for scaling
                gain = 1.0
                offset = 0.0
                if recording.has_channel_property(ch_id, "gain_to_uV"):
                    gain = recording.get_channel_property(ch_id, "gain_to_uV")
                if recording.has_channel_property(ch_id, "offset_to_uV"):
                    offset = recording.get_channel_property(ch_id, "offset_to_uV")

                channels.append(
                    ChannelInfo(
                        name=f"ai{i + 1}",
                        type=ch_type,
                        time_channel=1,  # Time channel index
                        number=i + 1,
                        sample_rate=sr,
                        offset=offset,
                        scale=gain,
                        group=1,
                    )
                )

            # Add time channel
            channels.append(
                ChannelInfo(
                    name="t1",
                    type="time",
                    time_channel=None,
                    number=1,
                    sample_rate=sr,
                    group=1,
                )
            )

        except Exception:
            pass

        return channels

    def readchannels_epochsamples(
        self,
        channeltype: str | list[str],
        channel: int | list[int],
        epochfiles: list[str],
        s0: int,
        s1: int,
    ) -> np.ndarray:
        """
        Read channel data.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s) (1-indexed)
            epochfiles: Files for this epoch
            s0: Start sample (1-indexed)
            s1: End sample (1-indexed)

        Returns:
            Array with shape (num_samples, num_channels)
        """
        recording = self._get_recording(epochfiles)
        if recording is None:
            if isinstance(channel, int):
                channel = [channel]
            return np.full((s1 - s0 + 1, len(channel)), np.nan)

        # Normalize inputs
        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        channeltype = [standardize_channel_type(ct) for ct in channeltype]

        # Convert to 0-indexed
        start_sample = s0 - 1
        end_sample = s1  # spikeinterface end is exclusive

        try:
            # Handle time channel specially
            if all(ct == "time" for ct in channeltype):
                sr = recording.get_sampling_frequency()
                t0_t1 = self.t0_t1(epochfiles)
                t0 = t0_t1[0][0]
                samples = np.arange(start_sample, end_sample)
                return (t0 + samples / sr).reshape(-1, 1)

            # Read analog data
            channel_ids = recording.get_channel_ids()
            # Convert 1-indexed channel numbers to channel IDs
            ch_indices = [ch - 1 for ch in channel]
            selected_ids = [channel_ids[i] for i in ch_indices if i < len(channel_ids)]

            if not selected_ids:
                return np.full((end_sample - start_sample, len(channel)), np.nan)

            traces = recording.get_traces(
                channel_ids=selected_ids,
                start_frame=start_sample,
                end_frame=end_sample,
            )

            return traces

        except Exception:
            return np.full((s1 - s0 + 1, len(channel)), np.nan)

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
            channeltype: Channel type(s)
            channel: Channel number(s)

        Returns:
            Array of sample rates
        """
        recording = self._get_recording(epochfiles)
        if recording is None:
            if isinstance(channel, int):
                channel = [channel]
            return np.full(len(channel), np.nan)

        if isinstance(channel, int):
            channel = [channel]

        try:
            sr = recording.get_sampling_frequency()
            return np.full(len(channel), sr)
        except Exception:
            return np.full(len(channel), np.nan)

    def readevents_epochsamples_native(
        self,
        channeltype: list[str],
        channel: list[int],
        epochfiles: list[str],
        t0: float,
        t1: float,
    ) -> tuple[list[np.ndarray], list[np.ndarray]]:
        """
        Read native event data.

        Currently returns empty arrays. Override in format-specific
        subclasses to read events from the native file format.

        Args:
            channeltype: Channel types
            channel: Channel numbers
            epochfiles: Files for this epoch
            t0: Start time
            t1: End time

        Returns:
            Tuple of empty (timestamps, data) lists
        """
        # Event reading not yet implemented
        return [np.array([]) for _ in channel], [np.array([]) for _ in channel]

    def underlying_datatype(
        self,
        epochfiles: list[str],
        channeltype: str,
        channel: int | list[int],
    ) -> tuple[str, np.ndarray, int]:
        """
        Get underlying data type for channels.

        Args:
            epochfiles: Files for this epoch
            channeltype: Channel type
            channel: Channel number(s)

        Returns:
            Tuple of (datatype, polynomial, datasize)
        """
        recording = self._get_recording(epochfiles)
        if isinstance(channel, int):
            channel = [channel]

        if recording is None:
            return super().underlying_datatype(epochfiles, channeltype, channel)

        try:
            dtype = recording.get_dtype()
            dtype_str = str(dtype)

            if "int16" in dtype_str:
                datatype = "int16"
                datasize = 16
            elif "float32" in dtype_str or "float" in dtype_str:
                datatype = "float32"
                datasize = 32
            elif "float64" in dtype_str:
                datatype = "float64"
                datasize = 64
            else:
                datatype = "int16"
                datasize = 16

            # Get gain/offset for each channel
            poly = np.zeros((len(channel), 2))
            channel_ids = recording.get_channel_ids()

            for i, ch in enumerate(channel):
                ch_idx = ch - 1
                if ch_idx < len(channel_ids):
                    ch_id = channel_ids[ch_idx]
                    if recording.has_channel_property(ch_id, "offset_to_uV"):
                        poly[i, 0] = recording.get_channel_property(ch_id, "offset_to_uV")
                    if recording.has_channel_property(ch_id, "gain_to_uV"):
                        poly[i, 1] = recording.get_channel_property(ch_id, "gain_to_uV")
                    else:
                        poly[i, 1] = 1.0
                else:
                    poly[i, 1] = 1.0

            return datatype, poly, datasize

        except Exception:
            return super().underlying_datatype(epochfiles, channeltype, channel)

    def newdocument(self) -> Any:
        """Create document for this reader."""
        from ...document import Document

        doc = Document(
            "daq/daqreader",
            **{
                "daqreader.ndi_daqreader_class": "SpikeInterfaceReader",
                "base.id": self.id,
            },
        )
        return doc
