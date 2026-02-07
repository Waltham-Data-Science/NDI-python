"""
ndi.daq - Data acquisition module for NDI framework.

This module provides classes for reading data from various data acquisition
systems used in neuroscience experiments.

Classes:
    DAQReader: Abstract base for DAQ readers
    MFDAQReader: Multi-function DAQ reader
    DAQSystem: Combines file navigator, reader, and metadata reader
    MetadataReader: Reads stimulus/metadata parameters

Submodules:
    reader: Concrete reader implementations

Example:
    >>> from ndi.daq import DAQReader, DAQSystem
    >>> from ndi.daq.reader import MFDAQReader
"""

from .reader_base import DAQReader
from .mfdaq import MFDAQReader
from .system import DAQSystem
from .system_mfdaq import DAQSystemMFDAQ
from .metadatareader import MetadataReader
from .metadatareader import NewStimStimsReader, NielsenLabStimsReader
from .daqsystemstring import DAQSystemString

__all__ = [
    'DAQReader',
    'MFDAQReader',
    'DAQSystem',
    'DAQSystemMFDAQ',
    'MetadataReader',
    'NewStimStimsReader',
    'NielsenLabStimsReader',
    'DAQSystemString',
]
