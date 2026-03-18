"""
ndi.daq.reader.mfdaq.ndr - NDR (Neuroscience Data Reader) wrapper.

Thin wrapper around ndi_daq_reader_SpikeInterfaceReader for file formats
supported by the NDR library (e.g. Axon ABF files).

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/ndr.m
"""

from __future__ import annotations

import logging

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq

logger = logging.getLogger(__name__)


class ndi_daq_reader_mfdaq_ndr(ndi_daq_reader_mfdaq):
    """
    Reader for data files handled by the NDR library.

    Currently supports Axon ABF files via spikeinterface/neo.

    File extensions: .abf
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.mfdaq.ndr"
    FILE_EXTENSIONS = [".abf"]

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
            logger.warning("ndi_daq_reader_mfdaq_ndr.getchannelsepoch failed: %s", exc)
            return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading NDR data")
        return SI().readchannels_epochsamples(channeltype, channel, epochfiles, s0, s1)

    def samplerate(self, epochfiles, channeltype, channel):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading NDR data")
        return SI().samplerate(epochfiles, channeltype, channel)

    def __repr__(self):
        return f"ndi_daq_reader_mfdaq_ndr(id={self.id[:8]}...)"
