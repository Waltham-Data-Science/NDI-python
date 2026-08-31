"""
ndi.fun - Utility functions for NDI.

MATLAB equivalent: +ndi/+fun/

Provides document, epoch, file, data, stimulus, session, dataset,
and probe utilities.
"""

from __future__ import annotations

from . import (
    calc,  # noqa: F401 — make ndi.fun.calc accessible
    file,  # noqa: F401 — make ndi.fun.file accessible
    probe,  # noqa: F401 — make ndi.fun.probe accessible
    stimulus,  # noqa: F401 — make ndi.fun.stimulus accessible
    text,  # noqa: F401 — make ndi.fun.text accessible
)
from .plot import plot_extracellular_spikeshapes
from .text import parse_text, parseText
from .utils import (
    channelname2prefixnumber,
    name2variable_name,
    name2variableName,
    pseudorandomint,
    timestamp,
)

__all__ = [
    "channelname2prefixnumber",
    "plot_extracellular_spikeshapes",
    "name2variableName",
    "name2variable_name",
    "parseText",
    "parse_text",
    "probe",
    "pseudorandomint",
    "timestamp",
]
