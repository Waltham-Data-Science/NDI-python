"""ndi.setup.daq.reader.mfdaq.stimulus — Stimulus-specific DAQ readers.

Lab-specific DAQ reader variants that handle stimulus presentation
data in addition to standard electrophysiology recordings.

MATLAB equivalent: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/``
"""

from .nielsenvisintan import ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisintan
from .nielsenvisneuropixelsglx import (
    ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisneuropixelsglx,
)
from .vhaudreybpod import ndi_setup_daq_reader_mfdaq_stimulus_VHAudreyBPod
from .vhlabvisspike2 import ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2

__all__ = [
    "ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2",
    "ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisintan",
    "ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisneuropixelsglx",
    "ndi_setup_daq_reader_mfdaq_stimulus_VHAudreyBPod",
]
