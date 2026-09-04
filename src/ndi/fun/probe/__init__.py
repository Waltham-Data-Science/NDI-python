"""
ndi.fun.probe - ndi_probe utility functions.

MATLAB equivalent: +ndi/+fun/+probe/

Provides :mod:`~ndi.fun.probe.export` (writing a probe's data in the flat
int16 format spike sorters read), :mod:`~ndi.fun.probe.import_` (reading a
curated sort back in, as ``import_.kilosort``),
:mod:`~ndi.fun.probe.geometry` (a probe's electrode geometry and the channel
maps built from it),
:func:`~ndi.fun.probe.extracellular_info.extracellularInfo` (the neurons an
import has already put in the database),
:func:`~ndi.fun.probe.channel_count.channelCount`,
:func:`~ndi.fun.probe.plot_probe_geometry.plotProbeGeometry` (drawing one),
and :func:`~ndi.fun.probe.location.location`.
"""

from __future__ import annotations

from . import export, geometry, import_  # noqa: F401 — ndi.fun.probe.export / .geometry
from .channel_count import channel_count, channelCount
from .export_binary import export_all_binary, export_binary
from .extracellular_info import extracellular_info, extracellularInfo
from .location import location
from .plot_probe_geometry import plot_probe_geometry, plotProbeGeometry

__all__ = [
    "channelCount",
    "channel_count",
    "export",
    "export_all_binary",
    "export_binary",
    "extracellularInfo",
    "extracellular_info",
    "geometry",
    "import_",
    "location",
    "plotProbeGeometry",
    "plot_probe_geometry",
]
