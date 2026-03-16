"""
ndi.daq.reader.mfdaq.blackrock - Blackrock NSx/NEV reader.

Thin wrapper around ndi_daq_reader_SpikeInterfaceReader for Blackrock data files.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/blackrock.m
"""

from __future__ import annotations

import logging

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq

logger = logging.getLogger(__name__)


class ndi_daq_reader_mfdaq_blackrock(ndi_daq_reader_mfdaq):
    """
    Reader for Blackrock Microsystems NSx/NEV data files.

    File extensions: .ns1-.ns6, .nev
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.mfdaq.blackrock"
    FILE_EXTENSIONS = [".ns1", ".ns2", ".ns3", ".ns4", ".ns5", ".ns6", ".nev"]

    def __init__(self, identifier=None, session=None, document=None):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS

    def _get_si_reader(self):
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
            return SI().getchannelsepoch(epochfiles)
        except Exception as exc:
            logger.warning("ndi_daq_reader_mfdaq_blackrock.getchannelsepoch failed: %s", exc)
            return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading Blackrock data")
        return SI().readchannels_epochsamples(channeltype, channel, epochfiles, s0, s1)

    def samplerate(self, epochfiles, channeltype, channel):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading Blackrock data")
        return SI().samplerate(epochfiles, channeltype, channel)

    def __repr__(self):
        return f"ndi_daq_reader_mfdaq_blackrock(id={self.id[:8]}...)"
