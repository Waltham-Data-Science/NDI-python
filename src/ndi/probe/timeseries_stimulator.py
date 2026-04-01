"""
ndi.probe.timeseries_stimulator - Stimulus delivery probe.

Provides the ndi_probe_timeseries_stimulator class for reading stimulus
delivery data from probes that control stimulus presentation.

MATLAB equivalent: src/ndi/+ndi/+probe/+timeseries/stimulator.m
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .timeseries import ndi_probe_timeseries

logger = logging.getLogger("ndi")


class ndi_probe_timeseries_stimulator(ndi_probe_timeseries):
    """
    ndi_probe for stimulus delivery devices.

    Reads stimulus presentation data from probes that deliver stimuli,
    extracting stimulus identity, timing, and parameters from marker,
    dimension, metadata, event, and analog channels.

    Supports two modes:
    - Marker mode: Uses mk/marker/text channels for stim on/off/ID,
      plus optional event and metadata channels.
    - Dimension mode: Uses dimp/dimn channels where each channel
      represents a stimulus type.

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
        - t.analog: Analog sample times

    Example:
        >>> stim = ndi_probe_timeseries_stimulator(session, 'visual_stim', 1, 'stimulator')
        >>> data, t, timeref = stim.readtimeseriesepoch(1, 0, 100)
    """

    def __init__(
        self,
        session: Any | None = None,
        name: str = "",
        reference: int = 1,
        type: str = "stimulator",
        **kwargs: Any,
    ):
        super().__init__(
            session=session,
            name=name,
            reference=reference,
            type=type,
            **kwargs,
        )

    def ndi_element_class(self) -> str:
        """Return ``'ndi.probe.timeseries.stimulator'``."""
        return "ndi.probe.timeseries.stimulator"

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
            epoch: ndi_epoch_epoch number (1-indexed) or epoch_id
            t0: Start time
            t1: End time

        Returns:
            Tuple of (data_dict, time_dict, timeref):
            - data_dict: Dict with 'stimid', 'parameters', 'analog'
            - time_dict: Dict with 'stimon', 'stimoff', 'stimopenclose',
                         'stimevents', 'analog'
            - timeref: Time reference for the epoch
        """
        if self._session is None:
            return None, None, None

        # Build default empty structures
        empty_data = {
            "stimid": np.array([], dtype=int),
            "parameters": [],
            "analog": np.array([]),
        }
        empty_t = {
            "stimon": np.array([]),
            "stimoff": np.array([]),
            "stimopenclose": np.array([]).reshape(0, 2),
            "stimevents": [],
        }

        # Get device and channel info
        devinfo = self.getchanneldevinfo(epoch)
        if devinfo is None:
            return empty_data, empty_t, self._get_epoch_timeref(epoch)

        dev = devinfo.get("daqsystem")
        devepoch = devinfo.get("device_epoch_number", devinfo.get("device_epoch_id"))
        channeltype = devinfo.get("channeltype", [])
        channel = devinfo.get("channel", [])

        if dev is None:
            return empty_data, empty_t, self._get_epoch_timeref(epoch)

        # Ensure lists
        if isinstance(channeltype, str):
            channeltype = [channeltype]
        if isinstance(channel, (int, float)):
            channel = [channel]

        data = {}
        t = {}

        # Separate metadata channels from other channels
        md_indices = [i for i, ct in enumerate(channeltype) if ct == "md"]
        non_md_indices = [i for i in range(len(channeltype)) if i not in md_indices]

        channeltype_metadata = [channeltype[i] for i in md_indices]
        channel_metadata = [channel[i] for i in md_indices]
        channeltype_nonmd = [channeltype[i] for i in non_md_indices]
        channel_nonmd = [channel[i] for i in non_md_indices]

        # Handle analog channels
        analog_indices = [i for i, ct in enumerate(channeltype_nonmd) if ct == "ai"]
        if analog_indices:
            try:
                sr = dev.samplerate(devepoch, channeltype_nonmd, channel_nonmd)
                if hasattr(sr, "__len__"):
                    sr_vals = [float(s) for s in sr]
                    if len(set(sr_vals)) != 1:
                        raise ValueError(
                            "Do not know how to handle multiple sampling rates across channels."
                        )
                    sr_val = sr_vals[0]
                else:
                    sr_val = float(sr)

                # 0-based sample indices (Python convention)
                s0 = round(sr_val * t0)
                s1 = round(sr_val * t1)

                analog_channeltype = [channeltype_nonmd[i] for i in analog_indices]
                analog_channel = [channel_nonmd[i] for i in analog_indices]
                data["analog"] = dev.readchannels_epochsamples(
                    analog_channeltype, analog_channel, devepoch, s0, s1
                )

                # Try to read time channel for analog data
                try:
                    t_analog = dev.readchannels_epochsamples(["time"], [1], devepoch, s0, s1)
                    t["analog"] = np.asarray(t_analog).ravel()
                except Exception as exc:
                    logger.warning("stimulator: failed to read time channel: %s", exc)
                    t["analog"] = np.nan
            except Exception as exc:
                logger.warning("stimulator: failed to read analog channels: %s", exc)
                data["analog"] = np.array([])
                t["analog"] = np.nan
        else:
            data["analog"] = np.array([])

        # Read events from non-metadata, non-analog channels
        event_channeltype = [
            ct for i, ct in enumerate(channeltype_nonmd) if i not in analog_indices
        ]
        event_channel = [ch for i, ch in enumerate(channel_nonmd) if i not in analog_indices]

        timestamps_list = []
        edata_list = []
        if event_channeltype:
            try:
                result = dev.readevents_epochsamples(
                    event_channeltype, event_channel, devepoch, t0, t1
                )
                if isinstance(result, tuple) and len(result) == 2:
                    ts, ed = result
                    # Ensure lists of arrays
                    if not isinstance(ts, list):
                        timestamps_list = [ts]
                        edata_list = [ed]
                    else:
                        timestamps_list = ts
                        edata_list = ed
                else:
                    timestamps_list = []
                    edata_list = []
            except Exception as exc:
                logger.warning("stimulator: readevents_epochsamples failed: %s", exc, exc_info=True)
                timestamps_list = []
                edata_list = []

        # Determine mode: marker vs dimension
        marker_types = {"mk", "marker", "text", "e", "event", "dep", "den"}
        dim_types = {"dimp", "dimn"}

        # Reconstruct full channel type/channel lists (event channels + metadata)
        all_channeltype = event_channeltype + channeltype_metadata
        all_channel = event_channel + channel_metadata

        markermode = any(ct in marker_types for ct in event_channeltype)
        dimmode = any(ct in dim_types for ct in event_channeltype)

        event_data_list: list[Any] = []
        mk_count = 0
        e_count = 0

        if markermode:
            for i, ct in enumerate(all_channeltype):
                if ct in ("mk", "marker", "text"):
                    mk_count += 1
                    if i < len(timestamps_list):
                        ts_i = np.asarray(timestamps_list[i])
                        ed_i = np.asarray(edata_list[i])
                    else:
                        ts_i = np.array([])
                        ed_i = np.array([])

                    if mk_count == 1:
                        # First marker: stim on/off times
                        if ed_i.size > 0:
                            vals = ed_i.ravel() if ed_i.ndim == 1 else ed_i[:, 0]
                            t_vals = ts_i.ravel() if ts_i.ndim == 1 else ts_i[:, 0]
                            on_mask = vals > 0
                            off_mask = vals == -1
                            t["stimon"] = t_vals[on_mask]
                            t["stimoff"] = t_vals[off_mask]
                        else:
                            t["stimon"] = np.array([])
                            t["stimoff"] = np.array([])

                    elif mk_count == 2:
                        # Second marker: stimulus IDs
                        stimids = []
                        if ed_i.size > 0:
                            for dd in range(len(ed_i)):
                                if ct == "text" and isinstance(ed_i[dd], str):
                                    try:
                                        stimids.append(int(ed_i[dd]))
                                    except (ValueError, SyntaxError):
                                        stimids.append(0)
                                else:
                                    row = ed_i[dd] if ed_i.ndim > 1 else ed_i[dd : dd + 1]
                                    stimids.append(row)
                        data["stimid"] = np.array(stimids)

                    elif mk_count == 3:
                        # Third marker: stim open/close
                        if ed_i.size > 0:
                            vals = ed_i.ravel() if ed_i.ndim == 1 else ed_i[:, 0]
                            t_vals = ts_i.ravel() if ts_i.ndim == 1 else ts_i[:, 0]
                            on_ = t_vals[vals > 0]
                            off_ = t_vals[vals == -1]
                            openclose = np.full((max(len(on_), len(off_)), 2), np.nan)
                            if len(on_) > 0:
                                openclose[: len(on_), 0] = on_
                            if len(off_) > 0:
                                openclose[: len(off_), 1] = off_
                                # If no stimoff from mk1, use mk3 off times
                                if "stimoff" not in t or len(t["stimoff"]) == 0:
                                    t["stimoff"] = off_
                            t["stimopenclose"] = openclose
                        else:
                            t["stimopenclose"] = np.array([]).reshape(0, 2)
                    else:
                        raise ValueError("Got more mark channels than expected.")

                elif ct in ("e", "event", "dep", "den"):
                    e_count += 1
                    if i < len(timestamps_list):
                        event_data_list.append(np.asarray(timestamps_list[i]))
                    else:
                        event_data_list.append(np.array([]))

                elif ct == "md":
                    # Read metadata
                    try:
                        md_ch_idx = all_channel[i]
                        data["parameters"] = dev.getmetadata(devepoch, md_ch_idx)
                    except Exception as exc:
                        logger.warning("stimulator: failed to read metadata: %s", exc)
                        data["parameters"] = []

            t["stimevents"] = event_data_list

        elif dimmode:
            t["stimon"] = np.array([])
            t["stimoff"] = np.array([])
            data["stimid"] = np.array([], dtype=int)
            counter = 0
            event_data_list = []

            for i, ct in enumerate(all_channeltype):
                if ct in ("dimp", "dimn"):
                    counter += 1
                    if i < len(timestamps_list):
                        ts_i = np.asarray(timestamps_list[i])
                        ed_i = np.asarray(edata_list[i])
                    else:
                        continue

                    if ed_i.size > 0:
                        vals = ed_i.ravel() if ed_i.ndim == 1 else ed_i[:, 0]
                        t_vals = ts_i.ravel() if ts_i.ndim == 1 else ts_i[:, 0]

                        on_mask = vals > 0
                        off_mask = vals == -1

                        t["stimon"] = np.concatenate([t["stimon"], t_vals[on_mask]])
                        t["stimoff"] = np.concatenate([t["stimoff"], t_vals[off_mask]])
                        n_on = int(np.sum(vals == 1))
                        data["stimid"] = np.concatenate(
                            [
                                data["stimid"],
                                np.full(n_on, counter, dtype=int),
                            ]
                        )

                elif ct == "md":
                    try:
                        md_ch_idx = all_channel[i]
                        data["parameters"] = dev.getmetadata(devepoch, md_ch_idx)
                    except Exception as exc:
                        logger.warning("stimulator: failed to read metadata: %s", exc)
                        data["parameters"] = []

                elif ct in ("e", "event"):
                    if i < len(timestamps_list):
                        event_data_list.append(np.asarray(timestamps_list[i]))

            # Sort by stimon time
            if len(t["stimon"]) > 0:
                order = np.argsort(t["stimon"])
                t["stimon"] = t["stimon"][order]
                t["stimoff"] = (
                    t["stimoff"][order] if len(t["stimoff"]) == len(order) else t["stimoff"]
                )
                data["stimid"] = (
                    data["stimid"][order] if len(data["stimid"]) == len(order) else data["stimid"]
                )

            # In dim mode, stimopenclose = [stimon, stimoff]
            if len(t["stimon"]) > 0:
                t["stimopenclose"] = (
                    np.column_stack([t["stimon"], t["stimoff"]])
                    if len(t["stimoff"]) == len(t["stimon"])
                    else np.column_stack([t["stimon"], np.full_like(t["stimon"], np.nan)])
                )
            else:
                t["stimopenclose"] = np.array([]).reshape(0, 2)

            t["stimevents"] = event_data_list

        # Ensure defaults for missing fields
        data.setdefault("stimid", np.array([], dtype=int))
        data.setdefault("parameters", [])
        data.setdefault("analog", np.array([]))
        t.setdefault("stimon", np.array([]))
        t.setdefault("stimoff", np.array([]))
        t.setdefault("stimopenclose", np.array([]).reshape(0, 2))
        t.setdefault("stimevents", [])

        # Build time reference
        from ..time import ndi_time_clocktype

        eid = self.epochid(epoch) if hasattr(self, "epochid") else str(epoch)

        try:
            from ..time.timereference import ndi_time_timereference

            timeref = ndi_time_timereference(self, ndi_time_clocktype.DEV_LOCAL_TIME, eid, 0)
        except Exception as exc:
            logger.warning("stimulator: failed to create timeref: %s", exc)
            timeref = ndi_time_clocktype.DEV_LOCAL_TIME

        return data, t, timeref

    def getchanneldevinfo(
        self,
        epoch: int | str,
    ) -> dict[str, Any] | None:
        """
        Get device and channel information for an epoch.

        Returns device, device epoch, and per-channel type/number arrays
        needed by readtimeseriesepoch.

        Args:
            epoch: ndi_epoch_epoch number (1-indexed) or epoch_id

        Returns:
            Dict with daqsystem, device_epoch_id, channeltype, channel
        """
        # Use the parent ndi_probe.getchanneldevinfo which returns a dict
        # with daqsystem, device_epoch_id, epochprobemap
        try:
            base_info = super().getchanneldevinfo(epoch)
        except (IndexError, KeyError):
            return None
        if base_info is None:
            return None

        dev = base_info.get("daqsystem")
        devepoch = base_info.get("device_epoch_id")

        if dev is None:
            return None

        # Get channel info from the epochprobemap's devicestring
        epms = base_info.get("epochprobemap", [])
        channeltype = []
        channel = []

        for epm in epms:
            if hasattr(epm, "devicestring") and epm.devicestring:
                try:
                    from ..daq.daqsystemstring import ndi_daq_daqsystemstring

                    dss = ndi_daq_daqsystemstring.parse(epm.devicestring)
                    for ct, ch_list in dss.channels:
                        for ch in ch_list:
                            channeltype.append(ct)
                            channel.append(ch)
                except Exception as exc:
                    logger.warning(
                        "stimulator: failed to parse devicestring '%s': %s",
                        epm.devicestring if hasattr(epm, "devicestring") else "?",
                        exc,
                    )

        return {
            "daqsystem": dev,
            "device_epoch_id": devepoch,
            "channeltype": channeltype,
            "channel": channel,
        }

    def _get_epoch_timeref(self, epoch: int | str) -> Any | None:
        """Get the time reference for an epoch."""
        if self._session is None:
            return None
        from ..time import ndi_time_clocktype

        return ndi_time_clocktype.DEV_LOCAL_TIME

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
        return (
            f"ndi_probe_timeseries_stimulator(name='{self._name}', " f"reference={self._reference})"
        )
