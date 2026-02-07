"""
ndi.time - Time synchronization module for NDI framework.

This module provides classes for managing time synchronization across
epochs and devices in neuroscience data.

Classes:
    ClockType: Enumeration of clock types (UTC, dev_local_time, etc.)
    TimeMapping: Polynomial time transformation
    TimeReference: Time specification relative to a clock
    SyncRule: Abstract base for synchronization rules
    SyncGraph: Graph-based time conversion

Submodules:
    syncrule: Concrete SyncRule implementations (FileMatch, FileFind)

Example:
    >>> from ndi.time import ClockType, TimeMapping, SyncGraph
    >>> from ndi.time.syncrule import FileMatch
    >>>
    >>> # Create a sync graph
    >>> sg = SyncGraph(session)
    >>> sg.add_rule(FileMatch())
    >>>
    >>> # Convert time between epochs
    >>> t_out, ref_out, msg = sg.time_convert(
    ...     timeref_in, t_in, referent_out, ClockType.UTC
    ... )
"""

# Import syncrule implementations
from . import syncrule
from .clocktype import (
    APPROX_DEV_GLOBAL_TIME,
    APPROX_EXP_GLOBAL_TIME,
    APPROX_UTC,
    DEV_GLOBAL_TIME,
    DEV_LOCAL_TIME,
    EXP_GLOBAL_TIME,
    INHERITED,
    NO_TIME,
    UTC,
    ClockType,
)
from .syncgraph import EpochNode, GraphInfo, SyncGraph
from .syncrule_base import SyncRule
from .timemapping import TimeMapping
from .timereference import TimeReference, TimeReferenceStruct

__all__ = [
    # Clock types
    "ClockType",
    "UTC",
    "APPROX_UTC",
    "EXP_GLOBAL_TIME",
    "APPROX_EXP_GLOBAL_TIME",
    "DEV_GLOBAL_TIME",
    "APPROX_DEV_GLOBAL_TIME",
    "DEV_LOCAL_TIME",
    "NO_TIME",
    "INHERITED",
    # Time mapping
    "TimeMapping",
    # Time reference
    "TimeReference",
    "TimeReferenceStruct",
    # Sync rule
    "SyncRule",
    # Sync graph
    "SyncGraph",
    "EpochNode",
    "GraphInfo",
    # Submodule
    "syncrule",
]
