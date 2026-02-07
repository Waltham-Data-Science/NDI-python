"""
ndi.daq.reader - Concrete DAQ reader implementations.

This submodule provides concrete implementations of DAQ readers
for various data acquisition systems.

Classes:
    SpikeInterfaceReader: Reader using spikeinterface library
    NeoReader: Reader using neo library

Example:
    >>> from ndi.daq.reader import SpikeInterfaceReader
    >>> reader = SpikeInterfaceReader()
    >>> channels = reader.getchannelsepoch(['data.rhd'])
"""

from .mfdaq import BlackrockReader, CEDSpike2Reader, IntanReader, SpikeGadgetsReader
from .spikeinterface_adapter import SpikeInterfaceReader

__all__ = [
    "SpikeInterfaceReader",
    "IntanReader",
    "BlackrockReader",
    "CEDSpike2Reader",
    "SpikeGadgetsReader",
]
