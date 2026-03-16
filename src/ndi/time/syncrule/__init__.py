"""
ndi.time.syncrule - Synchronization rule implementations.

This module provides concrete implementations of ndi_time_syncrule for
different synchronization strategies.
"""

from .common_triggers_overlapping_epochs import ndi_time_syncrule_commonTriggersOverlappingEpochs
from .filefind import ndi_time_syncrule_filefind
from .filematch import ndi_time_syncrule_filematch
from .random_pulses import ndi_time_syncrule_randomPulses

__all__ = [
    "ndi_time_syncrule_commonTriggersOverlappingEpochs",
    "ndi_time_syncrule_filefind",
    "ndi_time_syncrule_filematch",
    "ndi_time_syncrule_randomPulses",
]
