"""
ndi.daq - ndi_gui_Data acquisition module for NDI framework.

This module provides classes for reading data from various data acquisition
systems used in neuroscience experiments.

Classes:
    ndi_daq_reader: Abstract base for DAQ readers
    ndi_daq_reader_mfdaq: Multi-function DAQ reader
    ndi_daq_system: Combines file navigator, reader, and metadata reader
    ndi_daq_metadatareader: Reads stimulus/metadata parameters

Submodules:
    reader: Concrete reader implementations

Example:
    >>> from ndi.daq import ndi_daq_reader, ndi_daq_system
    >>> from ndi.daq.reader import ndi_daq_reader_mfdaq
"""

from .daqsystemstring import ndi_daq_daqsystemstring
from .metadatareader import ndi_daq_metadatareader, ndi_daq_metadatareader_NewStimStims, ndi_daq_metadatareader_NielsenLabStims
from .mfdaq import ndi_daq_reader_mfdaq
from .reader_base import ndi_daq_reader
from .system import ndi_daq_system
from .system_mfdaq import ndi_daq_system_mfdaq

__all__ = [
    "ndi_daq_reader",
    "ndi_daq_reader_mfdaq",
    "ndi_daq_system",
    "ndi_daq_system_mfdaq",
    "ndi_daq_metadatareader",
    "ndi_daq_metadatareader_NewStimStims",
    "ndi_daq_metadatareader_NielsenLabStims",
    "ndi_daq_daqsystemstring",
]
