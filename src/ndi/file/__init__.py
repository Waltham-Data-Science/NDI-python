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
from .navigator import ndi_file_navigator
from .navigator.epochdir import ndi_file_navigator_epochdir
from .pfilemirror import pfilemirror as _pfilemirror_func

# MATLAB compatibility: ``ndi.file.navigator(session, patterns)`` creates a
# ndi_file_navigator, mirroring the MATLAB constructor ``ndi.file.navigator``.
navigator = ndi_file_navigator

# MATLAB compatibility: ``ndi.file.navigator_epochdir(session, patterns)``
# creates an ndi_file_navigator_epochdir, mirroring ``ndi.file.navigator_epochdir``.
navigator_epochdir = ndi_file_navigator_epochdir

# MATLAB compatibility: ``ndi.file.pfilemirror(src, dest)`` calls the
# directory-mirror utility, mirroring ``ndi.file.pfilemirror``.
pfilemirror = _pfilemirror_func

__all__ = [
    "ndi_file_navigator",
    "ndi_file_navigator_epochdir",
    "filetype",
    "navigator",
    "navigator_epochdir",
    "pfilemirror",
]
