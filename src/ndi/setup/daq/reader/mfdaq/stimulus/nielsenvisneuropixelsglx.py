"""ndi.setup.daq.reader.mfdaq.stimulus.nielsenvisneuropixelsglx — Nielsen Lab visual stimulus NeuropixelsGLX reader.

Extends the NDR reader with support for Nielsen Lab visual stimulus
files (.analyzer) recorded on a Neuropixels GLX system.

MATLAB equivalent: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/nielsenvisneuropixelsglx.m``

The associated DAQ system configuration expects these epoch files:

- ``#.nidq.bin`` — NI-DAQ binary data (SpikeGLX)
- ``#.nidq.meta`` — NI-DAQ metadata
- ``#.imec0.ap.meta`` — Imec probe metadata
- ``#.analyzer`` — Nielsen Lab Analyzer stimulus structure
- ``epochprobemap.txt`` — epoch-to-probe mapping

Stimulus metadata is read by the companion
:class:`~ndi.daq.metadatareader.nielsenlab_stims.ndi_daq_metadatareader_NielsenLabStims`.
"""

from __future__ import annotations

import logging

from ndi.daq.reader.mfdaq.ndr import ndi_daq_reader_mfdaq_ndr

logger = logging.getLogger(__name__)


class ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisneuropixelsglx(ndi_daq_reader_mfdaq_ndr):
    """Nielsen Lab visual stimulus reader built on Neuropixels GLX via NDR.

    Inherits all channel reading and sample-rate logic from the NDR
    reader.  The stimulus-specific behaviour (extracting Analyzer
    parameters) is handled by the metadata reader
    ``ndi.daq.metadatareader.NielsenLabStims`` configured alongside this
    reader in the DAQ system.
    """

    NDI_DAQREADER_CLASS = "ndi.setup.daq.reader.mfdaq.stimulus.nielsenvisneuropixelsglx"

    def __repr__(self) -> str:
        return f"ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisneuropixelsglx(id={self.id[:8]}...)"
