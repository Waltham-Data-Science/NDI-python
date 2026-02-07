"""
ndi.daq.reader.mfdaq.spikegadgets - SpikeGadgets reader.

Thin wrapper around SpikeInterfaceReader for SpikeGadgets data files.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/spikegadgets.m
"""

from __future__ import annotations
import logging
from typing import Any, List, Optional, Tuple, Union

import numpy as np

from ...mfdaq import MFDAQReader, ChannelInfo

logger = logging.getLogger(__name__)


class SpikeGadgetsReader(MFDAQReader):
    """
    Reader for SpikeGadgets .rec files.

    File extensions: .rec
    """

    NDI_DAQREADER_CLASS = 'ndi.daq.reader.mfdaq.spikegadgets'
    FILE_EXTENSIONS = ['.rec']

    def __init__(self, identifier=None, session=None, document=None):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS

    def _get_si_reader(self):
        try:
            from ..spikeinterface_adapter import SpikeInterfaceReader
            return SpikeInterfaceReader
        except ImportError:
            return None

    def getchannelsepoch(self, epochfiles: List[str]) -> List[ChannelInfo]:
        SI = self._get_si_reader()
        if SI is None:
            return []
        try:
            return SI().getchannelsepoch(epochfiles)
        except Exception as exc:
            logger.warning('SpikeGadgetsReader.getchannelsepoch failed: %s', exc)
            return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading SpikeGadgets data")
        return SI().readchannels_epochsamples(channeltype, channel, epochfiles, s0, s1)

    def samplerate(self, epochfiles, channeltype, channel):
        SI = self._get_si_reader()
        if SI is None:
            raise ImportError("spikeinterface required for reading SpikeGadgets data")
        return SI().samplerate(epochfiles, channeltype, channel)

    def __repr__(self):
        return f"SpikeGadgetsReader(id={self.id[:8]}...)"
