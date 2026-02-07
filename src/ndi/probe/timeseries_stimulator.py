"""
ndi.probe.timeseries_stimulator - Stimulus delivery probe.

Provides the ProbeTimeseriesStimulator class for reading stimulus
delivery data from probes that control stimulus presentation.

MATLAB equivalent: src/ndi/+ndi/+probe/+timeseries/stimulator.m
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .timeseries import ProbeTimeseries


class ProbeTimeseriesStimulator(ProbeTimeseries):
    """
    Probe for stimulus delivery devices.

    Reads stimulus presentation data from probes that deliver stimuli,
    extracting stimulus identity, timing, and parameters from marker,
    dimension, metadata, event, and analog channels.

    Channel types used:
        - mk (marker): 3 channels for stim on/off, ID, setup/clear
        - dimp/dimn (dimension): One channel per stimulus dimension
        - md (metadata): Stimulus parameter data
        - e (event): Stimulus event triggers
        - ai (analog): Analog stimulus data

    Return data structure:
        - data.stimid: Stimulus identity codes
        - data.parameters: Stimulus parameters (from metadata)
        - data.analog: Analog data
        - t.stimon: Stimulus onset times
        - t.stimoff: Stimulus offset times
        - t.stimopenclose: Setup/shutdown times
        - t.stimevents: Optional event triggers

    Example:
        >>> stim = ProbeTimeseriesStimulator(session, 'visual_stim', 1, 'stimulator')
        >>> result = stim.readtimeseriesepoch(1, 0, 100)
    """

    def __init__(
        self,
        session: Any | None = None,
        name: str = "",
        reference: int = 1,
        type: str = "stimulator",
    ):
        super().__init__(
            session=session,
            name=name,
            reference=reference,
            type=type,
        )

    def readtimeseriesepoch(
        self,
        epoch: int | str,
        t0: float = 0.0,
        t1: float = float("inf"),
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Any | None]:
        """
        Read stimulus delivery data from an epoch.

        Returns structured data with stimulus identity, timing,
        parameters, and optional analog data.

        Args:
            epoch: Epoch number (1-indexed) or epoch_id
            t0: Start time
            t1: End time

        Returns:
            Tuple of (data_dict, time_dict, timeref):
            - data_dict: Dict with 'stimid', 'parameters', 'analog'
            - time_dict: Dict with 'stimon', 'stimoff', 'stimopenclose', 'stimevents'
            - timeref: Time reference for the epoch
        """
        if self._session is None:
            return None, None, None

        data = {
            "stimid": np.array([], dtype=int),
            "parameters": [],
            "analog": np.array([]),
        }

        times = {
            "stimon": np.array([]),
            "stimoff": np.array([]),
            "stimopenclose": np.array([]).reshape(0, 2),
            "stimevents": np.array([]),
        }

        # Read marker channels to extract stimulus timing
        mk_data = self._read_marker_channels(epoch, t0, t1)
        if mk_data is not None:
            data["stimid"] = mk_data.get("stimid", data["stimid"])
            times["stimon"] = mk_data.get("stimon", times["stimon"])
            times["stimoff"] = mk_data.get("stimoff", times["stimoff"])
            times["stimopenclose"] = mk_data.get("stimopenclose", times["stimopenclose"])

        # Read metadata channels for parameters
        md_data = self._read_metadata_channels(epoch, t0, t1)
        if md_data is not None:
            data["parameters"] = md_data

        # Read event channels
        ev_data = self._read_event_channels(epoch, t0, t1)
        if ev_data is not None:
            times["stimevents"] = ev_data

        # Read analog channels
        ai_data = self._read_analog_channels(epoch, t0, t1)
        if ai_data is not None:
            data["analog"] = ai_data

        # Get time reference
        timeref = self._get_epoch_timeref(epoch)

        return data, times, timeref

    def _read_marker_channels(
        self,
        epoch: int | str,
        t0: float,
        t1: float,
    ) -> dict[str, Any] | None:
        """
        Read marker channels to extract stimulus timing.

        Marker channel protocol:
            mk1: +1 = stim on, -1 = stim off
            mk2: stimulus ID at onset
            mk3: +1 = setup, -1 = clear

        Returns:
            Dict with stimid, stimon, stimoff, stimopenclose arrays
        """
        # Framework stub - actual implementation requires DAQ reader access
        return None

    def _read_metadata_channels(
        self,
        epoch: int | str,
        t0: float,
        t1: float,
    ) -> list[dict[str, Any]] | None:
        """Read metadata channels for stimulus parameters."""
        return None

    def _read_event_channels(
        self,
        epoch: int | str,
        t0: float,
        t1: float,
    ) -> np.ndarray | None:
        """Read event channels for stimulus triggers."""
        return None

    def _read_analog_channels(
        self,
        epoch: int | str,
        t0: float,
        t1: float,
    ) -> np.ndarray | None:
        """Read analog channels from the stimulator."""
        return None

    def _get_epoch_timeref(self, epoch: int | str) -> Any | None:
        """Get the time reference for an epoch."""
        if self._session is None:
            return None
        from ..time import ClockType

        return ClockType.DEV_LOCAL_TIME

    def parse_marker_data(
        self,
        mk_timestamps: np.ndarray,
        mk_values: np.ndarray,
    ) -> dict[str, Any]:
        """
        Parse raw marker channel data into structured stimulus events.

        This is a utility method for processing marker channel data
        that has already been read from the DAQ system.

        Args:
            mk_timestamps: Timestamps array (N x 3) for mk1, mk2, mk3
            mk_values: Values array (N x 3) for mk1, mk2, mk3

        Returns:
            Dict with stimid, stimon, stimoff, stimopenclose arrays
        """
        if mk_timestamps.size == 0 or mk_values.size == 0:
            return {
                "stimid": np.array([], dtype=int),
                "stimon": np.array([]),
                "stimoff": np.array([]),
                "stimopenclose": np.array([]).reshape(0, 2),
            }

        # Ensure 2D
        if mk_timestamps.ndim == 1:
            mk_timestamps = mk_timestamps.reshape(-1, 1)
        if mk_values.ndim == 1:
            mk_values = mk_values.reshape(-1, 1)

        stimon_times = []
        stimoff_times = []
        stimids = []
        openclose_times = []

        ncols = min(mk_values.shape[1], mk_timestamps.shape[1])

        # Parse mk1 (on/off) if available
        if ncols >= 1:
            col0_vals = mk_values[:, 0]
            col0_times = mk_timestamps[:, 0]
            on_mask = col0_vals > 0
            off_mask = col0_vals < 0
            stimon_times = col0_times[on_mask].tolist()
            stimoff_times = col0_times[off_mask].tolist()

        # Parse mk2 (stimulus ID) if available
        if ncols >= 2:
            col1_vals = mk_values[:, 1]
            mk_timestamps[:, 1]
            # IDs recorded at onset events
            id_mask = col1_vals > 0
            stimids = col1_vals[id_mask].astype(int).tolist()

        # Parse mk3 (setup/clear) if available
        if ncols >= 3:
            col2_vals = mk_values[:, 2]
            col2_times = mk_timestamps[:, 2]
            setup_mask = col2_vals > 0
            clear_mask = col2_vals < 0
            setup_times = col2_times[setup_mask].tolist()
            clear_times = col2_times[clear_mask].tolist()
            for s, c in zip(setup_times, clear_times):
                openclose_times.append([s, c])

        return {
            "stimid": np.array(stimids, dtype=int),
            "stimon": np.array(stimon_times),
            "stimoff": np.array(stimoff_times),
            "stimopenclose": (
                np.array(openclose_times).reshape(-1, 2)
                if openclose_times
                else np.array([]).reshape(0, 2)
            ),
        }

    def __repr__(self) -> str:
        return f"ProbeTimeseriesStimulator(name='{self._name}', " f"reference={self._reference})"
