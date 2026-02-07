"""
ndi.file - File navigation and management for NDI.

This module provides classes for navigating and organizing data files
into epochs for neuroscience experiments.

Classes:
    FileNavigator: Base class for finding and organizing epoch files
    EpochDir: Directory-based epoch navigation

Example:
    >>> from ndi.file import FileNavigator
    >>> nav = FileNavigator(session, '*.rhd')
    >>> epochfiles = nav.getepochfiles(1)
"""

from . import type as filetype
from .navigator import FileNavigator
from .navigator.epochdir import EpochDirNavigator

__all__ = [
    "FileNavigator",
    "EpochDirNavigator",
    "filetype",
]
