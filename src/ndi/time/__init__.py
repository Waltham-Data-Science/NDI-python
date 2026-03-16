"""
ndi.time - Time synchronization module for NDI framework.

This module provides classes for managing time synchronization across
epochs and devices in neuroscience data.

Classes:
    ndi_time_clocktype: Enumeration of clock types (UTC, dev_local_time, etc.)
    ndi_time_timemapping: Polynomial time transformation
    ndi_time_timereference: Time specification relative to a clock
    ndi_time_syncrule: Abstract base for synchronization rules
    ndi_time_syncgraph: Graph-based time conversion

Submodules:
    syncrule: Concrete ndi_time_syncrule implementations (ndi_time_syncrule_filematch, ndi_time_syncrule_filefind)

Example:
    >>> from ndi.time import ndi_time_clocktype, ndi_time_timemapping, ndi_time_syncgraph
    >>> from ndi.time.syncrule import ndi_time_syncrule_filematch
    >>>
    >>> # Create a sync graph
    >>> sg = ndi_time_syncgraph(session)
    >>> sg.add_rule(ndi_time_syncrule_filematch())
    >>>
    >>> # Convert time between epochs
    >>> t_out, ref_out, msg = sg.time_convert(
    ...     timeref_in, t_in, referent_out, ndi_time_clocktype.UTC
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
    ndi_time_clocktype,
)
from .syncgraph import ndi_time_epochnode, ndi_time_graphinfo, ndi_time_syncgraph
from .syncrule_base import ndi_time_syncrule
from .timemapping import ndi_time_timemapping
from .timereference import ndi_time_timereference, ndi_time_timereference__struct

__all__ = [
    # Clock types
    "ndi_time_clocktype",
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
    "ndi_time_timemapping",
    # Time reference
    "ndi_time_timereference",
    "ndi_time_timereference__struct",
    # Sync rule
    "ndi_time_syncrule",
    # Sync graph
    "ndi_time_syncgraph",
    "ndi_time_epochnode",
    "ndi_time_graphinfo",
    # Submodule
    "syncrule",
]
