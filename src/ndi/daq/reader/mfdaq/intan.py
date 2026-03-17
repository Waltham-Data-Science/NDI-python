"""
ndi.daq.reader.mfdaq.intan - Intan RHD/RHS reader.

Native reader for Intan Technologies RHD2000 data files.
Uses vlt.hardware.intan for header parsing and reads raw binary data directly,
mirroring the MATLAB NDI approach (which uses vhlab-toolbox-matlab).

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/intan.m
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from vlt.hardware.intan import read_Intan_RHD2000_header

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq, standardize_channel_type

logger = logging.getLogger(__name__)


class ndi_daq_reader_mfdaq_intan(ndi_daq_reader_mfdaq):
    """
    Reader for Intan RHD2000 data files.

    Uses vlt.hardware.intan.read_Intan_RHD2000_header for header parsing
    and reads raw binary sample data directly from the .rhd file, matching
    the approach used in NDI-matlab with vhlab-toolbox-matlab.

    File extensions: .rhd

    Example:
        >>> reader = ndi_daq_reader_mfdaq_intan()
        >>> channels = reader.getchannelsepoch(['data.rhd'])
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.mfdaq.intan"
    FILE_EXTENSIONS = [".rhd", ".rhs"]

    def __init__(
        self,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS
        self._header_cache: dict[str, dict] = {}

    def _get_header(self, epochfiles: list[str]) -> dict | None:
        """Read and cache the Intan RHD header for the first .rhd file."""
        for filepath in epochfiles:
            if filepath.lower().endswith(".rhd"):
                if filepath not in self._header_cache:
                    try:
                        self._header_cache[filepath] = read_Intan_RHD2000_header(filepath)
                    except Exception as exc:
                        logger.warning("Failed to read Intan header from %s: %s", filepath, exc)
                        return None
                return self._header_cache[filepath]
        return None

    @staticmethod
    def _rhd_file(epochfiles: list[str]) -> str | None:
        """Return the first .rhd file path from epochfiles, or None."""
        for f in epochfiles:
            if f.lower().endswith(".rhd"):
                return f
        return None

    def getchannelsepoch(self, epochfiles: list[str]) -> list[ChannelInfo]:
        header = self._get_header(epochfiles)
        if header is None:
            return []

        channels: list[ChannelInfo] = []
        sr = header["sample_rate"]

        # Amplifier channels → analog_in
        for i, _ch in enumerate(header.get("amplifier_channels", [])):
            channels.append(
                ChannelInfo(
                    name=f"ai{i + 1}",
                    type="analog_in",
                    time_channel=1,
                    number=i + 1,
                    sample_rate=sr,
                )
            )

        # Auxiliary input channels → auxiliary_in
        aux_sr = header["frequency_parameters"].get("aux_input_sample_rate", sr / 4)
        for i, _ch in enumerate(header.get("aux_input_channels", [])):
            channels.append(
                ChannelInfo(
                    name=f"aux{i + 1}",
                    type="auxiliary_in",
                    time_channel=1,
                    number=i + 1,
                    sample_rate=aux_sr,
                )
            )

        # Board ADC channels → analog_in (numbered after amplifier channels)
        n_amp = header["num_amplifier_channels"]
        for i, _ch in enumerate(header.get("board_adc_channels", [])):
            channels.append(
                ChannelInfo(
                    name=f"ai{n_amp + i + 1}",
                    type="analog_in",
                    time_channel=1,
                    number=n_amp + i + 1,
                    sample_rate=sr,
                )
            )

        # Digital input channels
        for i, _ch in enumerate(header.get("board_dig_in_channels", [])):
            channels.append(
                ChannelInfo(
                    name=f"di{i + 1}",
                    type="digital_in",
                    time_channel=1,
                    number=i + 1,
                    sample_rate=sr,
                )
            )

        # Digital output channels
        for i, _ch in enumerate(header.get("board_dig_out_channels", [])):
            channels.append(
                ChannelInfo(
                    name=f"do{i + 1}",
                    type="digital_out",
                    time_channel=1,
                    number=i + 1,
                    sample_rate=sr,
                )
            )

        # Time channel
        channels.append(
            ChannelInfo(
                name="t1",
                type="time",
                time_channel=None,
                number=1,
                sample_rate=sr,
            )
        )

        return channels

    def _read_raw_data(self, filepath: str, header: dict) -> dict:
        """Read all raw data blocks from an Intan RHD file.

        Returns a dict with keys: 'timestamps', 'amplifier_data',
        'aux_input_data', 'board_adc_data', 'board_dig_in_raw',
        'board_dig_out_raw', 'supply_voltage_data', 'temp_sensor_data'.
        """
        n_amp = header["num_amplifier_channels"]
        n_aux = header["num_aux_input_channels"]
        n_supply = header["num_supply_voltage_channels"]
        n_adc = header["num_board_adc_channels"]
        n_dig_in = header["num_board_dig_in_channels"]
        n_dig_out = header["num_board_dig_out_channels"]
        n_temp = header.get("num_temp_sensor_channels", 0)
        spb = header["num_samples_per_data_block"]  # samples per block
        num_samples = header["num_samples"]
        num_blocks = num_samples // spb if spb > 0 else 0

        # Pre-allocate arrays
        timestamps = np.zeros(num_samples, dtype=np.int32)
        amplifier_data = np.zeros((n_amp, num_samples), dtype=np.uint16) if n_amp > 0 else None
        aux_input_data = (
            np.zeros(
                (n_aux, (num_samples // 4) * num_blocks // num_blocks if num_blocks > 0 else 0),
                dtype=np.uint16,
            )
            if n_aux > 0
            else None
        )
        aux_samples_per_block = spb // 4
        if n_aux > 0:
            aux_input_data = np.zeros((n_aux, aux_samples_per_block * num_blocks), dtype=np.uint16)
        board_adc_data = np.zeros((n_adc, num_samples), dtype=np.uint16) if n_adc > 0 else None
        board_dig_in_raw = np.zeros(num_samples, dtype=np.uint16) if n_dig_in > 0 else None
        board_dig_out_raw = np.zeros(num_samples, dtype=np.uint16) if n_dig_out > 0 else None
        supply_voltage_data = (
            np.zeros((n_supply, num_blocks), dtype=np.uint16) if n_supply > 0 else None
        )
        temp_sensor_data = np.zeros((n_temp, num_blocks), dtype=np.uint16) if n_temp > 0 else None

        with open(filepath, "rb") as fid:
            fid.seek(header["header_size"])

            for block in range(num_blocks):
                s0 = block * spb
                s1 = s0 + spb

                # Timestamps
                timestamps[s0:s1] = np.frombuffer(fid.read(spb * 4), dtype="<i4")

                # Amplifier data
                if n_amp > 0:
                    raw = np.frombuffer(fid.read(spb * n_amp * 2), dtype="<u2")
                    amplifier_data[:, s0:s1] = raw.reshape(n_amp, spb, order="F")

                # Auxiliary input data
                if n_aux > 0:
                    a0 = block * aux_samples_per_block
                    a1 = a0 + aux_samples_per_block
                    raw = np.frombuffer(fid.read(aux_samples_per_block * n_aux * 2), dtype="<u2")
                    aux_input_data[:, a0:a1] = raw.reshape(n_aux, aux_samples_per_block, order="F")

                # Supply voltage (1 sample per block per channel)
                if n_supply > 0:
                    raw = np.frombuffer(fid.read(n_supply * 2), dtype="<u2")
                    supply_voltage_data[:, block] = raw

                # Temperature sensor (1 sample per block per channel)
                if n_temp > 0:
                    raw = np.frombuffer(fid.read(n_temp * 2), dtype="<u2")
                    temp_sensor_data[:, block] = raw

                # Board ADC data
                if n_adc > 0:
                    raw = np.frombuffer(fid.read(spb * n_adc * 2), dtype="<u2")
                    board_adc_data[:, s0:s1] = raw.reshape(n_adc, spb, order="F")

                # Digital inputs (packed into uint16)
                if n_dig_in > 0:
                    raw = np.frombuffer(fid.read(spb * 2), dtype="<u2")
                    board_dig_in_raw[s0:s1] = raw

                # Digital outputs (packed into uint16)
                if n_dig_out > 0:
                    raw = np.frombuffer(fid.read(spb * 2), dtype="<u2")
                    board_dig_out_raw[s0:s1] = raw

        # Convert amplifier data to microvolts: (raw - 32768) * 0.195
        if amplifier_data is not None:
            amplifier_data_uv = (amplifier_data.astype(np.float64) - 32768) * 0.195
        else:
            amplifier_data_uv = None

        # Convert aux input to volts: raw * 37.4e-6
        if aux_input_data is not None:
            aux_input_volts = aux_input_data.astype(np.float64) * 37.4e-6
        else:
            aux_input_volts = None

        # Convert board ADC to volts (depends on eval_board_mode)
        if board_adc_data is not None:
            eval_board_mode = header.get("eval_board_mode", 0)
            if eval_board_mode == 1:
                board_adc_volts = (board_adc_data.astype(np.float64) - 32768) * 312.5e-6
            else:
                board_adc_volts = (board_adc_data.astype(np.float64) - 32768) * 0.0003125
        else:
            board_adc_volts = None

        return {
            "timestamps": timestamps,
            "amplifier_data": amplifier_data_uv,
            "aux_input_data": aux_input_volts,
            "board_adc_data": board_adc_volts,
            "board_dig_in_raw": board_dig_in_raw,
            "board_dig_out_raw": board_dig_out_raw,
            "supply_voltage_data": supply_voltage_data,
            "temp_sensor_data": temp_sensor_data,
            "sample_rate": header["sample_rate"],
        }

    def readchannels_epochsamples(
        self,
        channeltype,
        channel,
        epochfiles,
        s0,
        s1,
    ) -> np.ndarray:
        header = self._get_header(epochfiles)
        if header is None:
            raise FileNotFoundError("No valid .rhd file found in epochfiles")

        filepath = self._rhd_file(epochfiles)
        data = self._read_raw_data(filepath, header)

        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        channeltype = [standardize_channel_type(ct) for ct in channeltype]

        # Convert 1-indexed to 0-indexed samples
        i0 = s0 - 1
        i1 = s1  # exclusive end

        n_samples = i1 - i0
        result = np.zeros((n_samples, len(channel)))
        n_amp = header["num_amplifier_channels"]

        for col, (ct, ch_num) in enumerate(zip(channeltype, channel)):
            if ct == "time":
                sr = data["sample_rate"]
                result[:, col] = data["timestamps"][i0:i1] / sr
            elif ct == "analog_in":
                ch_idx = ch_num - 1  # 0-indexed
                if ch_idx < n_amp and data["amplifier_data"] is not None:
                    result[:, col] = data["amplifier_data"][ch_idx, i0:i1]
                elif data["board_adc_data"] is not None:
                    adc_idx = ch_idx - n_amp
                    result[:, col] = data["board_adc_data"][adc_idx, i0:i1]
            elif ct == "auxiliary_in" and data["aux_input_data"] is not None:
                ch_idx = ch_num - 1
                # Aux is sampled at 1/4 rate
                aux_i0 = i0 // 4
                aux_i1 = i1 // 4
                if aux_i1 > aux_i0:
                    result[:, col] = np.interp(
                        np.arange(i0, i1),
                        np.arange(aux_i0 * 4, aux_i1 * 4, 4),
                        data["aux_input_data"][ch_idx, aux_i0:aux_i1],
                    )
            elif ct == "digital_in" and data["board_dig_in_raw"] is not None:
                ch_idx = ch_num - 1
                result[:, col] = (data["board_dig_in_raw"][i0:i1] >> ch_idx) & 1
            elif ct == "digital_out" and data["board_dig_out_raw"] is not None:
                ch_idx = ch_num - 1
                result[:, col] = (data["board_dig_out_raw"][i0:i1] >> ch_idx) & 1

        return result

    def t0_t1(self, epochfiles: list[str]) -> list[tuple[float, float]]:
        header = self._get_header(epochfiles)
        if header is None:
            return [(np.nan, np.nan)]
        sr = header["sample_rate"]
        num_samples = header["num_samples"]
        if num_samples == 0 or sr == 0:
            return [(np.nan, np.nan)]
        t0 = 0.0
        t1 = (num_samples - 1) / sr
        return [(t0, t1)]

    def samplerate(self, epochfiles, channeltype, channel) -> np.ndarray:
        header = self._get_header(epochfiles)
        if header is None:
            raise FileNotFoundError("No valid .rhd file found in epochfiles")

        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        channeltype = [standardize_channel_type(ct) for ct in channeltype]
        sr = header["sample_rate"]
        freq = header["frequency_parameters"]

        rates = []
        for ct in channeltype:
            if ct == "auxiliary_in":
                rates.append(freq.get("aux_input_sample_rate", sr / 4))
            elif ct in ("supply_voltage",):
                rates.append(
                    freq.get(
                        "supply_voltage_sample_rate", sr / header["num_samples_per_data_block"]
                    )
                )
            else:
                rates.append(sr)

        return np.array(rates)

    def __repr__(self) -> str:
        return f"ndi_daq_reader_mfdaq_intan(id={self.id[:8]}...)"
