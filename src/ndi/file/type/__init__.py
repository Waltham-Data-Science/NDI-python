"""
ndi.file.type - File type classes for NDI.

Contains dataclasses describing channel metadata for various file types.

MATLAB equivalents:
    ndi.file.type.mfdaq_epoch_channel -> ndi.file.type.mfdaq_epoch_channel
"""

from .mfdaq_epoch_channel import ndi_file_type_mfdaq__epoch__channel

# MATLAB compatibility: ``ndi.file.type.mfdaq_epoch_channel(...)`` creates an
# ndi_file_type_mfdaq__epoch__channel, mirroring the MATLAB constructor.
mfdaq_epoch_channel = ndi_file_type_mfdaq__epoch__channel

__all__ = ["ndi_file_type_mfdaq__epoch__channel", "mfdaq_epoch_channel"]
