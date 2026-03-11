"""
ndi.epoch - Epoch management classes.

This module provides classes for managing epochs (recording periods)
in neuroscience experiments.

Classes:
    Epoch: Immutable data class representing a single epoch
    EpochSet: Abstract base class for epoch management
    EpochProbeMap: Mapping between probes and devices for an epoch
"""

from .epoch import Epoch
from .epochprobemap import EpochProbeMap, build_devicestring, parse_devicestring
from .epochprobemap_daqsystem import EpochProbeMapDAQSystem
from .epochset import EpochSet
from .functions import epochrange, findepochnode

__all__ = [
    "Epoch",
    "EpochSet",
    "EpochProbeMap",
    "EpochProbeMapDAQSystem",
    "build_devicestring",
    "epochrange",
    "findepochnode",
    "parse_devicestring",
]
