"""
ndi.time.syncrule - Synchronization rule implementations.

This module provides concrete implementations of SyncRule for
different synchronization strategies.
"""

from .common_triggers_overlapping_epochs import CommonTriggersOverlappingEpochs
from .filefind import FileFind
from .filematch import FileMatch
from .random_pulses import RandomPulses

__all__ = [
    "CommonTriggersOverlappingEpochs",
    "FileFind",
    "FileMatch",
    "RandomPulses",
]
