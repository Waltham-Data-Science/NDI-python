"""
ndi.daq.reader.mfdaq - Format-specific MFDAQ reader subclasses.

Thin wrappers around SpikeInterfaceReader that set format-specific defaults.

Each reader class:
- Sets the correct ndi_daqreader_class for document serialization
- Provides the expected file extensions
- Delegates all data reading to SpikeInterfaceReader
"""

from .blackrock import BlackrockReader
from .cedspike2 import CEDSpike2Reader
from .intan import IntanReader
from .spikegadgets import SpikeGadgetsReader

__all__ = [
    "IntanReader",
    "BlackrockReader",
    "CEDSpike2Reader",
    "SpikeGadgetsReader",
]
