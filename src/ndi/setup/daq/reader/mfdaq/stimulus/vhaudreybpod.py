"""ndi.setup.daq.reader.mfdaq.stimulus.VHAudreyBPod — VH Lab Audrey BPod stimulus reader.

Reads stimulus trigger data from BPod behavioral task systems used in
the VH Lab taste experiments.

MATLAB equivalent: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/VHAudreyBPod.m``

The associated DAQ system configuration expects these epoch files:

- ``#_stimulus_triggers_log.tsv`` — stimulus trigger timing log
- ``#.*_summary_log.json`` — experiment summary metadata
"""

from __future__ import annotations

import logging

from ndi.daq.mfdaq import ChannelInfo, ndi_daq_reader_mfdaq

logger = logging.getLogger(__name__)


class ndi_setup_daq_reader_mfdaq_stimulus_VHAudreyBPod(ndi_daq_reader_mfdaq):
    """VH Lab Audrey BPod stimulus reader.

    Reads stimulus timing and trigger information from BPod behavioral
    task systems.  Stimulus metadata is read by the companion
    ``ndi.daq.metadatareader.VHAudreyBPod`` configured alongside this
    reader in the DAQ system.
    """

    NDI_DAQREADER_CLASS = "ndi.setup.daq.reader.mfdaq.stimulus.VHAudreyBPod"

    def __init__(self, identifier=None, session=None, document=None):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS

    def getchannelsepoch(self, epochfiles: list[str]) -> list[ChannelInfo]:
        return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        raise NotImplementedError("VHAudreyBPod stimulus reader does not support sample reading")

    def samplerate(self, epochfiles, channeltype, channel):
        raise NotImplementedError("VHAudreyBPod stimulus reader does not support sample rates")

    def __repr__(self) -> str:
        return f"ndi_setup_daq_reader_mfdaq_stimulus_VHAudreyBPod(id={self.id[:8]}...)"
