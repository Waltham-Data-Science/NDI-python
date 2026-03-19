"""ndi.setup.daq.reader.mfdaq.stimulus.vhlabvisspike2 — VH Lab visual stimulus Spike2 reader.

Extends the CED Spike2 reader with support for VH Lab visual stimulus
files (stims.mat, stimtimes.txt, verticalblanking.txt).

MATLAB equivalent: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/vhlabvisspike2.m``

The associated DAQ system configuration expects these epoch files:

- ``reference.txt`` — epoch reference file
- ``stimtimes.txt`` — stimulus timing information
- ``verticalblanking.txt`` — vertical blanking timestamps
- ``stims.mat`` — NewStim stimulus script parameters
- ``spike2data.smr`` — CED Spike2 electrophysiology data

Stimulus metadata is read by the companion
:class:`~ndi.daq.metadatareader.newstim_stims.ndi_daq_metadatareader_NewStimStims`.
"""

from __future__ import annotations

import logging

from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2

logger = logging.getLogger(__name__)


class ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2(ndi_daq_reader_mfdaq_cedspike2):
    """VH Lab visual stimulus reader built on CED Spike2.

    Inherits all channel reading and sample-rate logic from the CED Spike2
    reader.  The stimulus-specific behaviour (extracting stim parameters,
    timing alignment) is handled by the metadata reader
    ``ndi.daq.metadatareader.NewStimStims`` configured alongside this
    reader in the DAQ system.
    """

    NDI_DAQREADER_CLASS = "ndi.setup.daq.reader.mfdaq.stimulus.vhlabvisspike2"

    def __repr__(self) -> str:
        return f"ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2(id={self.id[:8]}...)"
