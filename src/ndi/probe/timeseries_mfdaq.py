"""
ndi.probe.timeseries_mfdaq - MFDAQ timeseries probe.

Provides ProbeTimeseriesMFDAQ that reads data from multi-function
DAQ systems via the probe's underlying DAQ system and device info.

MATLAB equivalent: src/ndi/+ndi/+probe/+timeseries/mfdaq.m
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Union

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
        epoch: Union[int, str],
        s0: int,
        s1: int,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[Any]]:
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
        devinfo = self.getchanneldevinfo(epoch)
        if devinfo is None:
            return None, None, None

        dev, devepoch, channeltype, channellist = devinfo

        if dev is None:
            return None, None, None

        # Read data from the device
        try:
            data = dev.readchannels_epochsamples(
                channeltype, channellist, devepoch, s0, s1
            )
        except (AttributeError, TypeError):
            return None, None, None

        # Get time values
        try:
            t = dev.epochsamples2times(
                channeltype, channellist, devepoch, np.arange(s0, s1 + 1)
            )
        except (AttributeError, TypeError):
            t = None

        return data, t, None

    def readtimeseriesepoch(
        self,
        epoch: Union[int, str],
        t0: float = 0.0,
        t1: float = float('inf'),
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[Any]]:
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
        devinfo = self.getchanneldevinfo(epoch)
        if devinfo is None:
            return None, None, None

        dev, devepoch, channeltype, channellist = devinfo

        if dev is None:
            return None, None, None

        # Convert times to samples
        try:
            samples = dev.epochtimes2samples(
                channeltype, channellist, devepoch, np.array([t0, t1])
            )
            s0 = int(samples[0])
            s1 = int(samples[1])
        except (AttributeError, TypeError):
            return None, None, None

        return self.read_epochsamples(epoch, s0, s1)

    def samplerate(self, epoch: Union[int, str]) -> float:
        """
        Get sample rate for this probe in an epoch.

        Args:
            epoch: Epoch number or epoch_id

        Returns:
            Sample rate in Hz
        """
        devinfo = self.getchanneldevinfo(epoch)
        if devinfo is None:
            return -1.0

        dev, devepoch, channeltype, channellist = devinfo

        if dev is None:
            return -1.0

        try:
            sr = dev.samplerate(devepoch, channeltype, channellist)
            if hasattr(sr, '__len__'):
                return float(sr[0]) if len(sr) > 0 else -1.0
            return float(sr)
        except (AttributeError, TypeError):
            return -1.0

    def getchanneldevinfo(
        self,
        epoch: Union[int, str],
    ) -> Optional[Tuple[Any, Any, Any, List[int]]]:
        """
        Get device info for channels in an epoch.

        Looks up the epoch probe map to find which DAQ system and
        channels are associated with this probe in the given epoch.

        Args:
            epoch: Epoch number or epoch_id

        Returns:
            Tuple of (device, device_epoch, channeltype, channellist)
            or None if not found
        """
        if self._session is None:
            return None

        # Get epoch probe map
        et = self.epochtable()
        if not et:
            return None

        # Resolve epoch to table entry
        entry = None
        if isinstance(epoch, int):
            if 0 < epoch <= len(et):
                entry = et[epoch - 1]
        else:
            for e in et:
                if e.get('epoch_id') == epoch:
                    entry = e
                    break

        if entry is None:
            return None

        epm = entry.get('epochprobemap')
        if epm is None:
            return None

        # Find matching probe map entry
        maps = epm if isinstance(epm, list) else [epm]
        for m in maps:
            if hasattr(m, 'matches'):
                if m.matches(name=self._name, reference=self._reference):
                    return self._resolve_device(m, entry)

        return None

    def _resolve_device(
        self,
        probe_map: Any,
        epoch_entry: Dict,
    ) -> Optional[Tuple[Any, Any, Any, List[int]]]:
        """
        Resolve device info from a probe map entry.

        Args:
            probe_map: EpochProbeMap object
            epoch_entry: Epoch table entry

        Returns:
            Tuple of (device, device_epoch, channeltype, channellist)
        """
        if not hasattr(probe_map, 'devicestring') or not probe_map.devicestring:
            return None

        # Parse device string to get device name and channels
        from ..daq.daqsystemstring import DAQSystemString
        dss = DAQSystemString.parse(probe_map.devicestring)

        # Find the DAQ system by name
        if self._session is None:
            return None

        # Get all DAQ systems from the session
        daq_systems = getattr(self._session, 'daqsystem', [])
        if callable(daq_systems):
            daq_systems = daq_systems()

        device = None
        for ds in (daq_systems if isinstance(daq_systems, list) else []):
            if hasattr(ds, 'name') and ds.name == dss.devicename:
                device = ds
                break

        if device is None:
            return None

        # Get channel info
        channels = dss.channels
        if channels:
            channeltype = channels[0][0]
            channellist = channels[0][1]
        else:
            channeltype = 'ai'
            channellist = [1]

        devepoch = epoch_entry.get('epoch_number', 1)

        return device, devepoch, channeltype, channellist

    def __repr__(self) -> str:
        return (
            f"ProbeTimeseriesMFDAQ(name='{self._name}', "
            f"reference={self._reference}, type='{self._type}')"
        )
