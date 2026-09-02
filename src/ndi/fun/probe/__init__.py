"""
ndi.fun.probe - ndi_probe utility functions.

MATLAB equivalent: +ndi/+fun/+probe/

Provides :mod:`~ndi.fun.probe.export` (writing a probe's data in the flat
int16 format spike sorters read), :mod:`~ndi.fun.probe.geometry` (a probe's
electrode geometry and the channel maps built from it),
:func:`~ndi.fun.probe.channel_count.channelCount`, and
:func:`~ndi.fun.probe.location.location`.
"""

from __future__ import annotations

from . import export, geometry  # noqa: F401 — ndi.fun.probe.export / .geometry
from .channel_count import channel_count, channelCount
from .export_binary import export_all_binary, export_binary
from .location import location

__all__ = [
    "channelCount",
    "channel_count",
    "export",
    "export_all_binary",
    "export_binary",
    "geometry",
    "location",
]
