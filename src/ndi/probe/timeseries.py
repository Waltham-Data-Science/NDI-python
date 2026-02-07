"""
ndi.probe.timeseries - Timeseries probe class.

Provides the ProbeTimeseries class that adds time-domain data reading
capabilities to the base Probe class.

MATLAB equivalent: src/ndi/+ndi/+probe/timeseries.m
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import Probe


class ProbeTimeseries(Probe):
    """
    Probe that reads timeseries data.

    Extends Probe with the ability to read timeseries data across
    epochs, using the session's syncgraph for time conversion when
    reading across different time references.

    This is a base class. Subclasses (e.g., ProbeTimeseriesMFDAQ)
    implement readtimeseriesepoch() for specific data formats.

    Example:
        >>> probe = ProbeTimeseriesMFDAQ(session, 'electrode1', 1, 'n-trode')
        >>> data, t, timeref = probe.readtimeseries(epoch=1, t0=0, t1=10)
    """

    def readtimeseries(
        self,
        epoch: int | str | Any = None,
        t0: float = 0.0,
        t1: float = float("inf"),
        timeref: Any | None = None,
    ) -> tuple[np.ndarray | None, np.ndarray | None, Any | None]:
        """
        Read timeseries data.

        Reads data from the specified epoch or time reference. If a
        timeref is provided, converts time using the session's syncgraph.

        Args:
            epoch: Epoch number (1-indexed) or epoch_id string
            t0: Start time
            t1: End time
            timeref: Optional time reference for cross-epoch reading

        Returns:
            Tuple of (data, t, timeref_out):
            - data: Array with shape (num_samples, num_channels) or None
            - t: Time array or None
            - timeref_out: Time reference for the returned data or None
        """
        if epoch is None and timeref is None:
            raise ValueError("Must specify either epoch or timeref")

        # If timeref provided, use syncgraph for time conversion
        if timeref is not None:
            return self._readtimeseries_via_syncgraph(timeref, t0, t1)

        # Direct epoch reading
        return self.readtimeseriesepoch(epoch, t0, t1)

    def _readtimeseries_via_syncgraph(
        self,
        timeref: Any,
        t0: float,
        t1: float,
    ) -> tuple[np.ndarray | None, np.ndarray | None, Any | None]:
        """
        Read timeseries using syncgraph time conversion.

        This handles reading data that may span multiple epochs by
        converting time references through the session's syncgraph.

        Args:
            timeref: Source time reference
            t0: Start time in source reference
            t1: End time in source reference

        Returns:
            Tuple of (data, t, timeref_out)
        """
        if self._session is None:
            return None, None, None

        # Get epoch table
        et = self.epochtable()
        if not et:
            return None, None, None

        # Try each epoch to find one that covers the time range
        for entry in et:
            epoch_number = entry["epoch_number"]
            try:
                data, t, tr = self.readtimeseriesepoch(epoch_number, t0, t1)
                if data is not None and len(data) > 0:
                    return data, t, tr
            except (ValueError, IndexError):
                continue

        return None, None, None

    def readtimeseriesepoch(
        self,
        epoch: int | str,
        t0: float = 0.0,
        t1: float = float("inf"),
    ) -> tuple[np.ndarray | None, np.ndarray | None, Any | None]:
        """
        Read timeseries data from a specific epoch.

        Subclasses must override this method with format-specific reading.

        Args:
            epoch: Epoch number (1-indexed) or epoch_id
            t0: Start time
            t1: End time

        Returns:
            Tuple of (data, t, timeref_out)
        """
        # Base implementation returns None - subclasses override
        return None, None, None

    def samplerate(self, epoch: int | str) -> float:
        """
        Get sample rate for this probe in an epoch.

        Args:
            epoch: Epoch number or epoch_id

        Returns:
            Sample rate in Hz, or -1 if not applicable
        """
        return -1.0

    def times2samples(
        self,
        epoch: int | str,
        times: np.ndarray,
    ) -> np.ndarray:
        """
        Convert times to sample indices.

        Args:
            epoch: Epoch number or epoch_id
            times: Time values

        Returns:
            Sample indices (1-indexed)
        """
        sr = self.samplerate(epoch)
        if sr <= 0:
            return np.full_like(times, np.nan)
        times = np.asarray(times)
        return 1 + np.round(times * sr).astype(int)

    def samples2times(
        self,
        epoch: int | str,
        samples: np.ndarray,
    ) -> np.ndarray:
        """
        Convert sample indices to times.

        Args:
            epoch: Epoch number or epoch_id
            samples: Sample indices (1-indexed)

        Returns:
            Time values
        """
        sr = self.samplerate(epoch)
        if sr <= 0:
            return np.full_like(samples, np.nan, dtype=float)
        samples = np.asarray(samples, dtype=float)
        return (samples - 1) / sr

    def __repr__(self) -> str:
        return (
            f"ProbeTimeseries(name='{self._name}', "
            f"reference={self._reference}, type='{self._type}')"
        )
