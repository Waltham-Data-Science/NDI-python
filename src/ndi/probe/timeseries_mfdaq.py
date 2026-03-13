"""
ndi.probe.timeseries_mfdaq - MFDAQ timeseries probe.

Provides ProbeTimeseriesMFDAQ that reads data from multi-function
DAQ systems via the probe's underlying DAQ system and device info.

MATLAB equivalent: src/ndi/+ndi/+probe/+timeseries/mfdaq.m
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .timeseries import ProbeTimeseries


class ProbeTimeseriesMFDAQ(ProbeTimeseries):
    """
    MFDAQ timeseries probe.

    Reads data from multi-function DAQ systems. Uses the probe's
    device info (via getchanneldevinfo) to identify which DAQ system
    and channels to read from.

    Provides:
    - read_epochsamples(): Read by sample indices
    - readtimeseriesepoch(): Read by time bounds
    - samplerate(): Get sampling rate

    Example:
        >>> probe = ProbeTimeseriesMFDAQ(session, 'electrode1', 1, 'n-trode')
        >>> data, t, tr = probe.read_epochsamples(1, 0, 30000)
        >>> sr = probe.samplerate(1)
    """

    def read_epochsamples(
        self,
        epoch: int | str,
        s0: int,
        s1: int,
    ) -> tuple[np.ndarray | None, np.ndarray | None, Any | None]:
        """
        Read data from an epoch by sample indices.

        Args:
            epoch: Epoch number (1-indexed) or epoch_id
            s0: Start sample (1-indexed)
            s1: End sample (1-indexed)

        Returns:
            Tuple of (data, t, timeref_out):
            - data: Array (num_samples, num_channels) or None
            - t: Time array or None
            - timeref_out: Time reference or None
        """
        try:
            dev, devname, devepoch, channeltype, channellist = self.getchanneldevinfo(epoch)
        except (IndexError, ValueError):
            return None, None, None

        if not dev:
            return None, None, None

        # Use first device (all channels should be on same device)
        device = dev[0]

        # Read data from the device
        try:
            data = device.readchannels_epochsamples(channeltype, channellist, devepoch[0], s0, s1)
        except (AttributeError, TypeError):
            return None, None, None

        # Get time values
        try:
            t = device.epochsamples2times(
                channeltype, channellist, devepoch[0], np.arange(s0, s1 + 1)
            )
        except (AttributeError, TypeError):
            t = None

        return data, t, None

    def readtimeseriesepoch(
        self,
        epoch: int | str,
        t0: float = 0.0,
        t1: float = float("inf"),
    ) -> tuple[np.ndarray | None, np.ndarray | None, Any | None]:
        """
        Read data from an epoch by time bounds.

        Converts t0/t1 to sample indices and delegates to read_epochsamples.

        Args:
            epoch: Epoch number (1-indexed) or epoch_id
            t0: Start time
            t1: End time

        Returns:
            Tuple of (data, t, timeref_out)
        """
        try:
            dev, devname, devepoch, channeltype, channellist = self.getchanneldevinfo(epoch)
        except (IndexError, ValueError):
            return None, None, None

        if not dev:
            return None, None, None

        device = dev[0]

        # Convert times to samples
        try:
            samples = device.epochtimes2samples(
                channeltype, channellist, devepoch[0], np.array([t0, t1])
            )
            s0 = int(samples[0])
            s1 = int(samples[1])
        except (AttributeError, TypeError):
            return None, None, None

        return self.read_epochsamples(epoch, s0, s1)

    def samplerate(self, epoch: int | str) -> float:
        """
        Get sample rate for this probe in an epoch.

        Args:
            epoch: Epoch number or epoch_id

        Returns:
            Sample rate in Hz
        """
        try:
            dev, devname, devepoch, channeltype, channellist = self.getchanneldevinfo(epoch)
        except (IndexError, ValueError):
            return -1.0

        if not dev:
            return -1.0

        device = dev[0]

        try:
            sr = device.samplerate(devepoch[0], channeltype, channellist)
            if hasattr(sr, "__len__"):
                return float(sr[0]) if len(sr) > 0 else -1.0
            return float(sr)
        except (AttributeError, TypeError):
            return -1.0

    def __repr__(self) -> str:
        return (
            f"ProbeTimeseriesMFDAQ(name='{self._name}', "
            f"reference={self._reference}, type='{self._type}')"
        )
