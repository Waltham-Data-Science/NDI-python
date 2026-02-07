"""
ndi.daq.reader.mfdaq.cedspike2 - CED Spike2 SMR reader.

Thin wrapper around SpikeInterfaceReader for CED Spike2 data files.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/cedspike2.m
"""

from __future__ import annotations

import logging

from ...mfdaq import ChannelInfo, MFDAQReader

logger = logging.getLogger(__name__)


class CEDSpike2Reader(MFDAQReader):
    """
    Reader for CED Spike2 SMR files.

    File extensions: .smr, .smrx
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.mfdaq.cedspike2"
    FILE_EXTENSIONS = [".smr", ".smrx"]

    def __init__(self, identifier=None, session=None, document=None):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS

    def _get_si_reader(self):
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
            return SI().getchannelsepoch(epochfiles)
        except Exception as exc:
            logger.warning("CEDSpike2Reader.getchannelsepoch failed: %s", exc)
            return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading CED Spike2 data")
        return SI().readchannels_epochsamples(channeltype, channel, epochfiles, s0, s1)

    def samplerate(self, epochfiles, channeltype, channel):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading CED Spike2 data")
        return SI().samplerate(epochfiles, channeltype, channel)

    def __repr__(self):
        return f"CEDSpike2Reader(id={self.id[:8]}...)"
