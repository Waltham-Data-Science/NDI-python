"""
ndi.epoch - ndi_epoch_epoch management classes.

This module provides classes for managing epochs (recording periods)
in neuroscience experiments.

Classes:
    ndi_epoch_epoch: Immutable data class representing a single epoch
    ndi_epoch_epochset: Abstract base class for epoch management
    ndi_epoch_epochprobemap: Mapping between probes and devices for an epoch
"""

from .epoch import ndi_epoch_epoch
from .epochprobemap import ndi_epoch_epochprobemap, build_devicestring, parse_devicestring
from .epochprobemap_daqsystem import ndi_epoch_epochprobemap__daqsystem
from .epochset import ndi_epoch_epochset
from .functions import epochrange, findepochnode

__all__ = [
    "ndi_epoch_epoch",
    "ndi_epoch_epochset",
    "ndi_epoch_epochprobemap",
    "ndi_epoch_epochprobemap__daqsystem",
    "build_devicestring",
    "epochrange",
    "findepochnode",
    "parse_devicestring",
]
