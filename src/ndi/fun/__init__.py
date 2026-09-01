"""
ndi.fun - Utility functions for NDI.

MATLAB equivalent: +ndi/+fun/

Provides document, epoch, file, data, stimulus, session, dataset,
and probe utilities.
"""

from __future__ import annotations

from . import (
    calc,  # noqa: F401 — make ndi.fun.calc accessible
    ensemble,  # noqa: F401 — make ndi.fun.ensemble accessible
    export,  # noqa: F401 — make ndi.fun.export accessible
    file,  # noqa: F401 — make ndi.fun.file accessible
    probe,  # noqa: F401 — make ndi.fun.probe accessible
    stimulus,  # noqa: F401 — make ndi.fun.stimulus accessible
)
from .plot import plot_extracellular_spikeshapes
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
    "probe",
    "pseudorandomint",
    "timestamp",
]
