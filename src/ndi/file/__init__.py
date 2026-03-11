"""
ndi.file - File navigation and management for NDI.

This module provides classes for navigating and organizing data files
into epochs for neuroscience experiments.

MATLAB equivalents:
    ndi.file.navigator           -> ndi.file.navigator (constructor)
    ndi.file.navigator_epochdir  -> ndi.file.navigator_epochdir (constructor)
    ndi.file.pfilemirror         -> ndi.file.pfilemirror (function)
    ndi.file.type.mfdaq_epoch_channel -> ndi.file.type.mfdaq_epoch_channel

Example:
    >>> nav = ndi.file.navigator(session, '*.rhd')
    >>> epochfiles = nav.getepochfiles(1)
"""

from . import type as filetype
from .navigator import FileNavigator
from .navigator.epochdir import EpochDirNavigator
from .pfilemirror import pfilemirror as _pfilemirror_func

# MATLAB compatibility: ``ndi.file.navigator(session, patterns)`` creates a
# FileNavigator, mirroring the MATLAB constructor ``ndi.file.navigator``.
navigator = FileNavigator

# MATLAB compatibility: ``ndi.file.navigator_epochdir(session, patterns)``
# creates an EpochDirNavigator, mirroring ``ndi.file.navigator_epochdir``.
navigator_epochdir = EpochDirNavigator

# MATLAB compatibility: ``ndi.file.pfilemirror(src, dest)`` calls the
# directory-mirror utility, mirroring ``ndi.file.pfilemirror``.
pfilemirror = _pfilemirror_func

__all__ = [
    "FileNavigator",
    "EpochDirNavigator",
    "filetype",
    "navigator",
    "navigator_epochdir",
    "pfilemirror",
]
