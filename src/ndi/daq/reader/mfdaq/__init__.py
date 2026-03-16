"""
ndi.daq.reader.mfdaq - Format-specific MFDAQ reader subclasses.

Thin wrappers around ndi_daq_reader_SpikeInterfaceReader that set format-specific defaults.

Each reader class:
- Sets the correct ndi_daqreader_class for document serialization
- Provides the expected file extensions
- Delegates all data reading to ndi_daq_reader_SpikeInterfaceReader
"""

from .blackrock import ndi_daq_reader_mfdaq_blackrock
from .cedspike2 import ndi_daq_reader_mfdaq_cedspike2
from .intan import ndi_daq_reader_mfdaq_intan
from .spikegadgets import ndi_daq_reader_mfdaq_spikegadgets

__all__ = [
    "ndi_daq_reader_mfdaq_intan",
    "ndi_daq_reader_mfdaq_blackrock",
    "ndi_daq_reader_mfdaq_cedspike2",
    "ndi_daq_reader_mfdaq_spikegadgets",
]
