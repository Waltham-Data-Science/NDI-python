"""
ndi.fun.probe.import_.kilosort - import curated Kilosort/Phy spike sorting into NDI.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/

NAMING DIVERGENCE (single, unavoidable): the MATLAB package is
``+ndi/+fun/+probe/+import/+kilosort``. ``import`` is a reserved word in Python,
so the parent subpackage is named ``import_`` and the importable path is
``ndi.fun.probe.import_.kilosort``. Callers reach the entry points as
``ndi.fun.probe.import_.kilosort.session(...)`` and
``ndi.fun.probe.import_.kilosort.probe(...)``, mirroring the MATLAB call form
``ndi.fun.probe.import.kilosort.session(...)``.

Each function lives in its own module (mirroring the one-function-per-file
MATLAB package). The functions are re-exported here so that, like MATLAB, the
package name itself is the callable namespace (``kilosort.session``,
``kilosort.probe``, ...), shadowing the same-named submodules.
"""

from __future__ import annotations

from .getInfo import getInfo
from .labels import labels
from .meanwaveform import meanwaveform
from .probe import probe
from .removeold import removeold
from .session import session
from .waveformdata import waveformdata

__all__ = [
    "session",
    "probe",
    "getInfo",
    "labels",
    "waveformdata",
    "meanwaveform",
    "removeold",
]
