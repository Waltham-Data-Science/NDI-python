"""
ndi.file.type - File type classes for NDI.

Contains dataclasses describing channel metadata for various file types.
"""

from .mfdaq_epoch_channel import MFDAQEpochChannel

__all__ = ['MFDAQEpochChannel']
