"""
ndi.daq.reader.mfdaq.intan - Intan RHD/RHS reader.

Thin wrapper around SpikeInterfaceReader for Intan data files.
Falls back gracefully if spikeinterface is not installed.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/intan.m
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

from ...mfdaq import ChannelInfo, MFDAQReader


class IntanReader(MFDAQReader):
    """
    Reader for Intan RHD/RHS data files.

    Supports Intan Technologies recording systems including
    RHD2000 and RHS2000 series. Uses spikeinterface for data access
    when available.

    File extensions: .rhd, .rhs

    Example:
        >>> reader = IntanReader()
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
        """Get SpikeInterfaceReader lazily."""
        try:
            from ..spikeinterface_adapter import SpikeInterfaceReader

            return SpikeInterfaceReader
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
            logger.warning("IntanReader.getchannelsepoch failed: %s", exc)
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

    def samplerate(self, epochfiles, channeltype, channel) -> np.ndarray:
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading Intan data")
        reader = SI()
        return reader.samplerate(epochfiles, channeltype, channel)

    def __repr__(self) -> str:
        return f"IntanReader(id={self.id[:8]}...)"
