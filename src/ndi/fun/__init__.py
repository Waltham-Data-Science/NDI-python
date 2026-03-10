"""
ndi.fun - Utility functions for NDI.

MATLAB equivalent: +ndi/+fun/

Provides document, epoch, file, data, stimulus, session, dataset,
and probe utilities.
"""

from __future__ import annotations

from . import probe  # noqa: F401 — make ndi.fun.probe accessible
from .utils import (
    channelname2prefixnumber,
    name2variable_name,
    pseudorandomint,
    timestamp,
)

__all__ = [
    "channelname2prefixnumber",
    "name2variable_name",
    "probe",
    "pseudorandomint",
    "timestamp",
]
