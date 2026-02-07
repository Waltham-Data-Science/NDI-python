"""
ndi.daq.system_mfdaq - Multi-function DAQ system class.

Extends DAQSystem with multi-function DAQ specific behavior including
support for various channel types and time/sample conversions.

MATLAB equivalent: src/ndi/+ndi/+daq/+system/mfdaq.m
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .system import DAQSystem
from .mfdaq import MFDAQReader, standardize_channel_type
from ..time import ClockType, DEV_LOCAL_TIME


class DAQSystemMFDAQ(DAQSystem):
    """
    Multi-function DAQ system.

    Extends DAQSystem for multi-function data acquisition systems
    that support various channel types (analog, digital, time,
    auxiliary, event, marker).

    The MFDAQ system delegates data reading to its MFDAQReader and
    provides time/sample conversion methods.

    Example:
        >>> sys = DAQSystemMFDAQ('intan1', navigator, reader)
        >>> channels = sys.getchannelsepoch(1)
        >>> data = sys.readchannels_epochsamples('ai', [1, 2], 1, 0, 1000)
    """

    CHANNEL_TYPES = {
        'analog_in': 'ai', 'analog_out': 'ao',
        'digital_in': 'di', 'digital_out': 'do',
        'auxiliary_in': 'ax', 'time': 't',
        'event': 'e', 'marker': 'mk',
    }

    def epochclock(self, epoch_number: int) -> List[ClockType]:
        """
        Return clock types for an epoch.

        MFDAQ systems return DEV_LOCAL_TIME by default.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            List containing DEV_LOCAL_TIME
        """
        return [DEV_LOCAL_TIME]

    def t0_t1(self, epoch_number: int) -> List[Tuple[float, float]]:
        """
        Return start/end times for an epoch.

        Delegates to the DAQ reader if available.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            List of (t0, t1) tuples per clock type
        """
        if self._daqreader is not None and self._filenavigator is not None:
            epochfiles = self._filenavigator.getepochfiles(epoch_number)
            return self._daqreader.t0_t1(epochfiles)
        return [(np.nan, np.nan)]

    def getchannelsepoch(self, epoch_number: int) -> List[Any]:
        """
        Get available channels for an epoch.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            List of ChannelInfo objects
        """
        if self._daqreader is None or self._filenavigator is None:
            return []

        epochfiles = self._filenavigator.getepochfiles(epoch_number)

        if isinstance(self._daqreader, MFDAQReader):
            return self._daqreader.getchannelsepoch(epochfiles)
        return []

    def getchannels(self) -> List[Any]:
        """
        Get all available channels across all epochs.

        Returns:
            List of unique ChannelInfo objects
        """
        et = self.epochtable()
        all_channels = []
        seen = set()

        for entry in et:
            epoch_num = entry['epoch_number']
            channels = self.getchannelsepoch(epoch_num)
            for ch in channels:
                key = (ch.name, ch.type)
                if key not in seen:
                    seen.add(key)
                    all_channels.append(ch)

        return all_channels

    def readchannels_epochsamples(
        self,
        channeltype: Union[str, List[str]],
        channel: Union[int, List[int]],
        epoch_number: int,
        s0: int,
        s1: int,
    ) -> np.ndarray:
        """
        Read channel data by sample indices.

        Args:
            channeltype: Channel type(s) (e.g., 'ai', 'analog_in')
            channel: Channel number(s) (1-indexed)
            epoch_number: Epoch number (1-indexed)
            s0: Start sample (1-indexed)
            s1: End sample (1-indexed)

        Returns:
            Array with shape (num_samples, num_channels)
        """
        if self._daqreader is None or self._filenavigator is None:
            raise RuntimeError("No DAQ reader or file navigator configured")

        epochfiles = self._filenavigator.getepochfiles(epoch_number)
        if isinstance(self._daqreader, MFDAQReader):
            return self._daqreader.readchannels_epochsamples(
                channeltype, channel, epochfiles, s0, s1
            )
        raise TypeError("DAQ reader is not an MFDAQReader")

    def readevents_epochsamples(
        self,
        channeltype: Union[str, List[str]],
        channel: Union[int, List[int]],
        epoch_number: int,
        t0: float,
        t1: float,
    ) -> Tuple:
        """
        Read event data for an epoch.

        Args:
            channeltype: Event channel type(s)
            channel: Channel number(s)
            epoch_number: Epoch number (1-indexed)
            t0: Start time
            t1: End time

        Returns:
            Tuple of (timestamps, data)
        """
        if self._daqreader is None or self._filenavigator is None:
            raise RuntimeError("No DAQ reader or file navigator configured")

        epochfiles = self._filenavigator.getepochfiles(epoch_number)
        if isinstance(self._daqreader, MFDAQReader):
            return self._daqreader.readevents_epochsamples(
                channeltype, channel, epochfiles, t0, t1
            )
        raise TypeError("DAQ reader is not an MFDAQReader")

    def samplerate(
        self,
        epoch_number: int,
        channeltype: Union[str, List[str]],
        channel: Union[int, List[int]],
    ) -> np.ndarray:
        """
        Get sample rate for channels in an epoch.

        Args:
            epoch_number: Epoch number (1-indexed)
            channeltype: Channel type(s)
            channel: Channel number(s)

        Returns:
            Array of sample rates
        """
        if self._daqreader is None or self._filenavigator is None:
            raise RuntimeError("No DAQ reader or file navigator configured")

        epochfiles = self._filenavigator.getepochfiles(epoch_number)
        if isinstance(self._daqreader, MFDAQReader):
            return self._daqreader.samplerate(epochfiles, channeltype, channel)
        raise TypeError("DAQ reader is not an MFDAQReader")

    def epochsamples2times(
        self,
        channeltype: Union[str, List[str]],
        channel: Union[int, List[int]],
        epoch_number: int,
        samples: np.ndarray,
    ) -> np.ndarray:
        """
        Convert sample indices to time.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epoch_number: Epoch number (1-indexed)
            samples: Sample indices (1-indexed)

        Returns:
            Time values
        """
        if self._daqreader is None or self._filenavigator is None:
            raise RuntimeError("No DAQ reader or file navigator configured")

        epochfiles = self._filenavigator.getepochfiles(epoch_number)
        if isinstance(self._daqreader, MFDAQReader):
            return self._daqreader.epochsamples2times(
                channeltype, channel, epochfiles, samples
            )
        raise TypeError("DAQ reader is not an MFDAQReader")

    def epochtimes2samples(
        self,
        channeltype: Union[str, List[str]],
        channel: Union[int, List[int]],
        epoch_number: int,
        times: np.ndarray,
    ) -> np.ndarray:
        """
        Convert time to sample indices.

        Args:
            channeltype: Channel type(s)
            channel: Channel number(s)
            epoch_number: Epoch number (1-indexed)
            times: Time values

        Returns:
            Sample indices (1-indexed)
        """
        if self._daqreader is None or self._filenavigator is None:
            raise RuntimeError("No DAQ reader or file navigator configured")

        epochfiles = self._filenavigator.getepochfiles(epoch_number)
        if isinstance(self._daqreader, MFDAQReader):
            return self._daqreader.epochtimes2samples(
                channeltype, channel, epochfiles, times
            )
        raise TypeError("DAQ reader is not an MFDAQReader")

    @staticmethod
    def mfdaq_channeltypes() -> List[str]:
        """Get list of supported MFDAQ channel types."""
        return [
            'analog_in', 'analog_out', 'digital_in', 'digital_out',
            'time', 'auxiliary_in', 'event', 'marker',
        ]

    @staticmethod
    def mfdaq_prefix(channeltype: str) -> str:
        """
        Get the standard prefix for a channel type.

        Args:
            channeltype: Full channel type name

        Returns:
            Abbreviated prefix (e.g., 'ai' for 'analog_in')
        """
        prefixes = {
            'analog_in': 'ai', 'analog_out': 'ao',
            'digital_in': 'di', 'digital_out': 'do',
            'auxiliary_in': 'ax', 'time': 't',
            'event': 'e', 'marker': 'mk',
        }
        return prefixes.get(standardize_channel_type(channeltype), channeltype)

    @staticmethod
    def mfdaq_type(channeltype: str) -> str:
        """
        Get the preferred full type name for a channel type.

        Args:
            channeltype: Channel type string or abbreviation

        Returns:
            Full standardized channel type name
        """
        return standardize_channel_type(channeltype)
