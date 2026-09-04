"""
ndi.daq.reader.mfdaq.cedspike2 - CED Spike2 SMR/SMRX reader.

Thin wrapper around NDR-python's sonpipe-backed CED helpers
(``ndr.format.ced.read_SOMSMR_header`` and ``read_SOMSMR_datafile``),
which drive CED's own ``sonpy`` binding out of process. That covers
both 32-bit ``.smr`` and 64-bit ``.smrx`` files. Install sonpipe from
https://github.com/VH-Lab/sonpipe; without it the sonpipe layer raises
a clear ``SonpipeNotFoundError`` rather than pretending the file has
no data.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/cedspike2.m
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq, standardize_channel_type

logger = logging.getLogger(__name__)

# CED channel kinds, matching ndr.format.ced.sonpipe.read_SOMSMR_datafile.
_WAVEFORM_KINDS = (1, 9)  # Adc, RealWave
_EVENT_KINDS = (2, 3, 4)  # EventFall, EventRise, EventBoth
_MARKER_KINDS = (5, 6, 7, 8)  # Marker, AdcMark, RealMark, TextMark
_TEXTMARK_KIND = 8


class ndi_daq_reader_mfdaq_cedspike2(ndi_daq_reader_mfdaq):
    """
    Reader for CED Spike2 SMR/SMRX files.

    File extensions: .smr, .smrx
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.mfdaq.cedspike2"
    FILE_EXTENSIONS = [".smr", ".smrx"]

    def __init__(
        self,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS
        self._header_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # File and header helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _cedfile(epochfiles: list[str]) -> str:
        cedfiles = [f for f in epochfiles if f.lower().endswith((".smr", ".smrx"))]
        if len(cedfiles) != 1:
            raise ValueError(
                "CED Spike2 reader expects exactly one .smr/.smrx file per epoch; "
                f"got {len(cedfiles)}"
            )
        return cedfiles[0]

    def _get_header(self, epochfiles: list[str]) -> dict[str, Any]:
        from ndr.format.ced.read_SOMSMR_header import read_SOMSMR_header

        cedfile = self._cedfile(epochfiles)
        if cedfile not in self._header_cache:
            self._header_cache[cedfile] = read_SOMSMR_header(cedfile)
        return self._header_cache[cedfile]

    @staticmethod
    def _channel_by_number(header: dict[str, Any], number: int) -> dict[str, Any]:
        for entry in header.get("channelinfo") or []:
            if int(entry["number"]) == int(number):
                return entry
        raise ValueError(f"CED channel {number} is not recorded in this file.")

    # ------------------------------------------------------------------
    # Channel introspection
    # ------------------------------------------------------------------
    def getchannelsepoch(self, epochfiles: list[str]) -> list[ChannelInfo]:
        header = self._get_header(epochfiles)

        channels: list[ChannelInfo] = []
        first_wave: dict[str, Any] | None = None

        for entry in header.get("channelinfo") or []:
            number = int(entry["number"])
            kind = int(entry.get("kind", 0))
            sr = entry.get("samplerate")

            if kind in _WAVEFORM_KINDS:
                channels.append(
                    ChannelInfo(
                        name=f"ai{number}",
                        type="analog_in",
                        time_channel=number,
                        number=number,
                        sample_rate=float(sr) if sr is not None else None,
                    )
                )
                if first_wave is None:
                    first_wave = entry
            elif kind in _EVENT_KINDS:
                channels.append(
                    ChannelInfo(
                        name=f"e{number}",
                        type="event",
                        time_channel=None,
                        number=number,
                    )
                )
            elif kind in _MARKER_KINDS:
                if kind == _TEXTMARK_KIND:
                    channels.append(
                        ChannelInfo(
                            name=f"text{number}",
                            type="text",
                            time_channel=None,
                            number=number,
                        )
                    )
                else:
                    channels.append(
                        ChannelInfo(
                            name=f"mk{number}",
                            type="marker",
                            time_channel=None,
                            number=number,
                        )
                    )

        if first_wave is not None:
            first_number = int(first_wave["number"])
            first_sr = first_wave.get("samplerate")
            channels.append(
                ChannelInfo(
                    name=f"t{first_number}",
                    type="time",
                    time_channel=None,
                    number=first_number,
                    sample_rate=float(first_sr) if first_sr is not None else None,
                )
            )

        return channels

    # ------------------------------------------------------------------
    # Sample rate and epoch bounds
    # ------------------------------------------------------------------
    def samplerate(self, epochfiles, channeltype, channel) -> np.ndarray:
        header = self._get_header(epochfiles)

        if isinstance(channel, int):
            channel = [channel]

        rates: list[float] = []
        for ch in channel:
            info = self._channel_by_number(header, int(ch))
            sr = info.get("samplerate")
            rates.append(float(sr) if sr is not None else float("nan"))
        return np.array(rates)

    def t0_t1(self, epochfiles) -> list[tuple[float, float]]:
        header = self._get_header(epochfiles)
        max_t = 0.0
        for entry in header.get("channelinfo") or []:
            mt = entry.get("max_time")
            if mt is not None and float(mt) > max_t:
                max_t = float(mt)
        return [(0.0, max_t)]

    # ------------------------------------------------------------------
    # Sample reads
    # ------------------------------------------------------------------
    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1) -> np.ndarray:
        from ndr.format.ced.read_SOMSMR_datafile import read_SOMSMR_datafile

        header = self._get_header(epochfiles)
        cedfile = self._cedfile(epochfiles)

        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)
        channeltype = [standardize_channel_type(ct) for ct in channeltype]

        columns: list[np.ndarray] = []

        for ct, ch in zip(channeltype, channel):
            info = self._channel_by_number(header, int(ch))
            sr = info.get("samplerate")
            total = int(info.get("num_samples") or 0)
            if sr is None or total == 0:
                raise ValueError(f"CED channel {ch} has no waveform samples; cannot read as {ct!r}")
            sr = float(sr)

            i0 = max(0, int(s0) - 1)
            if isinstance(s1, float) and math.isinf(s1):
                i1 = total
            else:
                i1 = min(total, int(s1))

            if i1 <= i0:
                columns.append(np.array([]))
                continue

            t0_sec = i0 / sr
            t1_sec = (i1 - 1) / sr

            data, _tot_samples, _tot_time, _blockinfo, time = read_SOMSMR_datafile(
                cedfile, header, int(ch), t0_sec, t1_sec
            )

            data = np.asarray(data).ravel()
            time_arr = np.asarray(time).ravel() if time is not None else None

            if ct == "time":
                columns.append(time_arr if time_arr is not None else np.array([]))
            else:
                columns.append(data)

        n_samples = min((c.size for c in columns), default=0)
        if n_samples == 0:
            return np.zeros((0, len(columns)))
        return np.column_stack([c[:n_samples] for c in columns])

    def readevents_epochsamples_native(self, channeltype, channel, epochfiles, t0, t1):
        from ndr.format.ced.read_SOMSMR_datafile import read_SOMSMR_datafile

        header = self._get_header(epochfiles)
        cedfile = self._cedfile(epochfiles)

        if isinstance(channel, int):
            channel = [channel]
        if isinstance(channeltype, str):
            channeltype = [channeltype] * len(channel)

        timestamps_all: list[np.ndarray] = []
        data_all: list[np.ndarray] = []

        for ch in channel:
            data, _tot_samples, _tot_time, _blockinfo, time = read_SOMSMR_datafile(
                cedfile, header, int(ch), float(t0), float(t1)
            )
            ts = np.asarray(time).ravel() if time is not None else np.asarray(data).ravel()
            d = np.asarray(data).ravel()
            timestamps_all.append(ts)
            data_all.append(d)

        if len(channel) == 1:
            return timestamps_all[0], data_all[0]
        return timestamps_all, data_all

    def __repr__(self):
        return f"ndi_daq_reader_mfdaq_cedspike2(id={self.id[:8]}...)"
