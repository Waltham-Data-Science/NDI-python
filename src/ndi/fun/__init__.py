"""
ndi.fun - Utility functions for NDI.

MATLAB equivalent: +ndi/+fun/

Provides document, epoch, file, data, stimulus, session, dataset,
and probe utilities.
"""

from __future__ import annotations

from . import (
    file,  # noqa: F401 — make ndi.fun.file accessible
    probe,  # noqa: F401 — make ndi.fun.probe accessible
    stimulus,  # noqa: F401 — make ndi.fun.stimulus accessible
)
from .utils import (
    channelname2prefixnumber,
    name2variable_name,
    name2variableName,
    pseudorandomint,
    timestamp,
)

__all__ = [
    "channelname2prefixnumber",
    "name2variableName",
    "name2variable_name",
    "probe",
    "pseudorandomint",
    "timestamp",
]
