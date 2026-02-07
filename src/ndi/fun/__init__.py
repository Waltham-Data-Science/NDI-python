"""
ndi.fun - Utility functions for NDI.

MATLAB equivalent: +ndi/+fun/

Provides document, epoch, file, data, stimulus, session, and dataset utilities.
"""

from __future__ import annotations

from .utils import (
    channelname2prefixnumber,
    name2variable_name,
    pseudorandomint,
    timestamp,
)

__all__ = [
    'channelname2prefixnumber',
    'name2variable_name',
    'pseudorandomint',
    'timestamp',
]
