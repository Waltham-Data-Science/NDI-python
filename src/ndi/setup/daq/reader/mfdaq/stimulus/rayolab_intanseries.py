"""ndi.setup.daq.reader.mfdaq.stimulus.rayolab_intanseries -- RayoLab stimulator Intan reader.

Extends the Intan RHD reader for the RayoLab visual stimulator.  The
stimulus identifier (always 1) is reported on the mk2 marker channel
of the Intan stream; the actual per-stimulus parameter set is provided
by the companion metadata reader
:class:`~ndi.daq.metadatareader.rayolab_stims.ndi_daq_metadatareader_RayoLabStims`.

MATLAB equivalent: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/rayolab_intanseries.m``
"""

from __future__ import annotations

import logging

from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

logger = logging.getLogger(__name__)


class ndi_setup_daq_reader_mfdaq_stimulus_rayolab_intanseries(ndi_daq_reader_mfdaq_intan):
    """RayoLab stimulator reader built on Intan RHD.

    Inherits all channel reading and sample-rate logic from the Intan
    reader.  The stimulus-specific behaviour (extracting stimid from the
    mk2 marker channel) is handled by the metadata reader
    :class:`~ndi.daq.metadatareader.rayolab_stims.ndi_daq_metadatareader_RayoLabStims`
    configured alongside this reader in the DAQ system.
    """

    NDI_DAQREADER_CLASS = "ndi.setup.daq.reader.mfdaq.stimulus.rayolab_intanseries"

    def __repr__(self) -> str:
        return f"ndi_setup_daq_reader_mfdaq_stimulus_rayolab_intanseries(id={self.id[:8]}...)"
