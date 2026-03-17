"""
ndi.daq.reader.mfdaq.intan - Intan RHD/RHS reader.

Native reader for Intan Technologies RHD2000 data files.
Uses ndr.format.intan for header parsing and data file reading.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/intan.m
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from ndr.format.intan import (
    Intan_RHD2000_blockinfo,
    read_Intan_RHD2000_datafile,
    read_Intan_RHD2000_header,
)

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq, standardize_channel_type

logger = logging.getLogger(__name__)


class ndi_daq_reader_mfdaq_intan(ndi_daq_reader_mfdaq):
    """
    Reader for Intan RHD2000 data files.

    Uses ndr.format.intan for header parsing and data file reading.

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
        sr = header["frequency_parameters"]["amplifier_sample_rate"]

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
        n_amp = len(header.get("amplifier_channels", []))
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

        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        channeltype = [standardize_channel_type(ct) for ct in channeltype]

        sr = header["frequency_parameters"]["amplifier_sample_rate"]
        n_amp = len(header.get("amplifier_channels", []))

        # Convert 1-indexed samples to time (seconds) for NDR
        t0_sec = (s0 - 1) / sr
        t1_sec = (s1 - 1) / sr

        n_samples = s1 - s0 + 1
        result = np.zeros((n_samples, len(channel)))

        # Cache NDR reads by channel type to avoid re-reading the file
        ndr_cache: dict[str, np.ndarray] = {}

        for col, (ct, ch_num) in enumerate(zip(channeltype, channel)):
            if ct == "time":
                if "time" not in ndr_cache:
                    ndr_cache["time"] = read_Intan_RHD2000_datafile(
                        filepath, channeltype="time", channel=1, t0=t0_sec, t1=t1_sec
                    )
                data = ndr_cache["time"]
                n = min(n_samples, data.shape[0])
                result[:n, col] = data[:n, 0]

            elif ct == "analog_in":
                if ch_num <= n_amp:
                    # Amplifier channel
                    if "amp" not in ndr_cache:
                        ndr_cache["amp"] = read_Intan_RHD2000_datafile(
                            filepath,
                            channeltype="amp",
                            channel=list(range(1, n_amp + 1)),
                            t0=t0_sec,
                            t1=t1_sec,
                        )
                    data = ndr_cache["amp"]
                    n = min(n_samples, data.shape[0])
                    result[:n, col] = data[:n, ch_num - 1]
                else:
                    # Board ADC channel
                    n_adc = len(header.get("board_adc_channels", []))
                    if "adc" not in ndr_cache and n_adc > 0:
                        raw_adc = read_Intan_RHD2000_datafile(
                            filepath,
                            channeltype="adc",
                            channel=list(range(1, n_adc + 1)),
                            t0=t0_sec,
                            t1=t1_sec,
                        )
                        # NDR returns raw ADC values; apply voltage conversion
                        eval_board_mode = header.get("eval_board_mode", 0)
                        if eval_board_mode == 1:
                            ndr_cache["adc"] = (raw_adc - 32768) * 312.5e-6
                        else:
                            ndr_cache["adc"] = (raw_adc - 32768) * 0.0003125
                    if "adc" in ndr_cache:
                        adc_idx = ch_num - n_amp - 1
                        data = ndr_cache["adc"]
                        n = min(n_samples, data.shape[0])
                        result[:n, col] = data[:n, adc_idx]

            elif ct == "auxiliary_in":
                if "aux" not in ndr_cache:
                    n_aux = len(header.get("aux_input_channels", []))
                    if n_aux > 0:
                        # Read all aux data to interpolate correctly
                        ndr_cache["aux"] = read_Intan_RHD2000_datafile(
                            filepath,
                            channeltype="aux",
                            channel=list(range(1, n_aux + 1)),
                            t0=0.0,
                            t1=float("inf"),
                        )
                if "aux" in ndr_cache:
                    ch_idx = ch_num - 1
                    aux_data = ndr_cache["aux"]
                    # Aux is sampled at 1/4 rate; interpolate to main rate
                    i0 = s0 - 1
                    i1 = s1  # exclusive end
                    aux_i0 = i0 // 4
                    aux_i1 = i1 // 4
                    if aux_i1 > aux_i0 and aux_i1 <= aux_data.shape[0]:
                        result[:, col] = np.interp(
                            np.arange(i0, i1),
                            np.arange(aux_i0 * 4, aux_i1 * 4, 4),
                            aux_data[aux_i0:aux_i1, ch_idx],
                        )

            elif ct == "digital_in":
                if "din" not in ndr_cache:
                    ndr_cache["din"] = read_Intan_RHD2000_datafile(
                        filepath,
                        channeltype="din",
                        channel=list(range(1, 17)),
                        t0=t0_sec,
                        t1=t1_sec,
                    )
                data = ndr_cache["din"]
                n = min(n_samples, data.shape[0])
                result[:n, col] = data[:n, ch_num - 1]

            elif ct == "digital_out":
                if "dout" not in ndr_cache:
                    ndr_cache["dout"] = read_Intan_RHD2000_datafile(
                        filepath,
                        channeltype="dout",
                        channel=list(range(1, 17)),
                        t0=t0_sec,
                        t1=t1_sec,
                    )
                data = ndr_cache["dout"]
                n = min(n_samples, data.shape[0])
                result[:n, col] = data[:n, ch_num - 1]

        return result

    def t0_t1(self, epochfiles: list[str]) -> list[tuple[float, float]]:
        header = self._get_header(epochfiles)
        filepath = self._rhd_file(epochfiles)
        if header is None or filepath is None:
            return [(np.nan, np.nan)]
        sr = header["frequency_parameters"]["amplifier_sample_rate"]
        if sr == 0:
            return [(np.nan, np.nan)]
        blockinfo, _, _, num_data_blocks = Intan_RHD2000_blockinfo(filepath, header)
        total_samples = blockinfo["samples_per_block"] * num_data_blocks
        if total_samples == 0:
            return [(np.nan, np.nan)]
        t0 = 0.0
        t1 = (total_samples - 1) / sr
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
        sr = header["frequency_parameters"]["amplifier_sample_rate"]
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
