"""
ndi.daq.reader.mfdaq.intan - Intan RHD/RHS reader.

Thin wrapper around ndi_daq_reader_SpikeInterfaceReader for Intan data files.
Falls back gracefully if spikeinterface is not installed.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/intan.m
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq


class ndi_daq_reader_mfdaq_intan(ndi_daq_reader_mfdaq):
    """
    Reader for Intan RHD/RHS data files.

    Supports Intan Technologies recording systems including
    RHD2000 and RHS2000 series. Uses spikeinterface for data access
    when available.

    File extensions: .rhd, .rhs

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

    def _get_si_reader(self):
        """Get ndi_daq_reader_SpikeInterfaceReader lazily."""
        try:
            from ..spikeinterface_adapter import ndi_daq_reader_SpikeInterfaceReader

            return ndi_daq_reader_SpikeInterfaceReader
        except ImportError:
            return None

    def getchannelsepoch(self, epochfiles: list[str]) -> list[ChannelInfo]:
        SI = self._get_si_reader()
        if SI is None:
            return []
        try:
            reader = SI()
            return reader.getchannelsepoch(epochfiles)
        except Exception as exc:
            logger.warning("ndi_daq_reader_mfdaq_intan.getchannelsepoch failed: %s", exc)
            return []

    def readchannels_epochsamples(
        self,
        channeltype,
        channel,
        epochfiles,
        s0,
        s1,
    ) -> np.ndarray:
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading Intan data")
        reader = SI()
        return reader.readchannels_epochsamples(channeltype, channel, epochfiles, s0, s1)

    def t0_t1(self, epochfiles: list[str]) -> list[tuple[float, float]]:
        SI = self._get_si_reader()
        if SI is None:
            return [(np.nan, np.nan)]
        try:
            reader = SI()
            return reader.t0_t1(epochfiles)
        except Exception:
            return [(np.nan, np.nan)]

    def samplerate(self, epochfiles, channeltype, channel) -> np.ndarray:
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading Intan data")
        reader = SI()
        return reader.samplerate(epochfiles, channeltype, channel)

    def __repr__(self) -> str:
        return f"ndi_daq_reader_mfdaq_intan(id={self.id[:8]}...)"
