"""
ndi.daq.reader - Concrete DAQ reader implementations.

This submodule provides concrete implementations of DAQ readers
for various data acquisition systems.

Classes:
    ndi_daq_reader_SpikeInterfaceReader: Reader using spikeinterface library
    NeoReader: Reader using neo library

Example:
    >>> from ndi.daq.reader import ndi_daq_reader_SpikeInterfaceReader
    >>> reader = ndi_daq_reader_SpikeInterfaceReader()
    >>> channels = reader.getchannelsepoch(['data.rhd'])
"""

from .mfdaq import (
    ndi_daq_reader_mfdaq_blackrock,
    ndi_daq_reader_mfdaq_cedspike2,
    ndi_daq_reader_mfdaq_intan,
    ndi_daq_reader_mfdaq_ndr,
    ndi_daq_reader_mfdaq_spikegadgets,
)
from .spikeinterface_adapter import ndi_daq_reader_SpikeInterfaceReader

__all__ = [
    "ndi_daq_reader_SpikeInterfaceReader",
    "ndi_daq_reader_mfdaq_intan",
    "ndi_daq_reader_mfdaq_blackrock",
    "ndi_daq_reader_mfdaq_cedspike2",
    "ndi_daq_reader_mfdaq_ndr",
    "ndi_daq_reader_mfdaq_spikegadgets",
]
