"""ndi.setup.daq.reader.mfdaq.stimulus.nielsenvisintan — Nielsen Lab visual stimulus Intan reader.

Extends the Intan RHD reader with support for Nielsen Lab visual
stimulus files (.analyzer).

MATLAB equivalent: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/nielsenvisintan.m``

The associated DAQ system configuration expects these epoch files:

- ``#_info.rhd`` — Intan recording info header
- ``#_digitalin.dat`` — digital input data
- ``#.analyzer`` — Nielsen Lab Analyzer stimulus structure
- ``epochprobemap.txt`` — epoch-to-probe mapping

Stimulus metadata is read by the companion
:class:`~ndi.daq.metadatareader.nielsenlab_stims.ndi_daq_metadatareader_NielsenLabStims`.
"""

from __future__ import annotations

import logging

from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

logger = logging.getLogger(__name__)


class ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisintan(ndi_daq_reader_mfdaq_intan):
    """Nielsen Lab visual stimulus reader built on Intan RHD.

    Inherits all channel reading and sample-rate logic from the Intan
    reader.  The stimulus-specific behaviour (extracting Analyzer
    parameters) is handled by the metadata reader
    ``ndi.daq.metadatareader.NielsenLabStims`` configured alongside this
    reader in the DAQ system.
    """

    NDI_DAQREADER_CLASS = "ndi.setup.daq.reader.mfdaq.stimulus.nielsenvisintan"

    def __repr__(self) -> str:
        return f"ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisintan(id={self.id[:8]}...)"
