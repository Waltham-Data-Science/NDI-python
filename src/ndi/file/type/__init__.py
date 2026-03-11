"""
ndi.file.type - File type classes for NDI.

Contains dataclasses describing channel metadata for various file types.

MATLAB equivalents:
    ndi.file.type.mfdaq_epoch_channel -> ndi.file.type.mfdaq_epoch_channel
"""

from .mfdaq_epoch_channel import MFDAQEpochChannel

# MATLAB compatibility: ``ndi.file.type.mfdaq_epoch_channel(...)`` creates an
# MFDAQEpochChannel, mirroring the MATLAB constructor.
mfdaq_epoch_channel = MFDAQEpochChannel

__all__ = ["MFDAQEpochChannel", "mfdaq_epoch_channel"]
