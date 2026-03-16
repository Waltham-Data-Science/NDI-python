"""Unified NDI class registry for cross-language document compatibility.

Maps NDI class identifier strings (e.g. ``"ndi.probe.timeseries.mfdaq"``)
to their Python implementation classes.  This registry is used in two
directions:

* **Object → Document**: each Python class exposes an ``NDI_*_CLASS``
  constant or ``ndi_element_class()`` method that returns its
  identifier, which gets written into the document.
* **Document → Object**: :func:`get_class` looks up the Python class
  for a given identifier string so the object can be reconstructed.

The identifiers intentionally mirror the MATLAB class hierarchy to
ensure cross-language database compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Lazily populated on first access to avoid circular imports.
_REGISTRY: dict[str, type] | None = None


def _build_registry() -> dict[str, type]:
    """Build the class registry by importing all known NDI classes."""
    from .daq.reader.mfdaq.blackrock import BlackrockReader
    from .daq.reader.mfdaq.cedspike2 import CEDSpike2Reader
    from .daq.reader.mfdaq.intan import IntanReader
    from .daq.reader.mfdaq.spikegadgets import SpikeGadgetsReader
    from .daq.system import DAQSystem
    from .element import Element
    from .file.navigator import FileNavigator
    from .probe import Probe
    from .probe.timeseries import ProbeTimeseries
    from .probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ
    from .probe.timeseries_stimulator import ProbeTimeseriesStimulator

    registry: dict[str, type] = {}

    # Elements / probes (keyed by ndi_element_class() return value)
    for cls in (Element, Probe, ProbeTimeseries, ProbeTimeseriesMFDAQ, ProbeTimeseriesStimulator):
        registry[cls().ndi_element_class()] = cls

    # DAQ readers (keyed by NDI_DAQREADER_CLASS constant)
    for cls in (IntanReader, BlackrockReader, CEDSpike2Reader, SpikeGadgetsReader):
        registry[cls.NDI_DAQREADER_CLASS] = cls

    # DAQ system
    registry[DAQSystem.NDI_DAQSYSTEM_CLASS] = DAQSystem

    # File navigator
    registry[FileNavigator.NDI_FILENAVIGATOR_CLASS] = FileNavigator

    return registry


def get_class(ndi_class_name: str) -> type | None:
    """Look up the Python class for an NDI class identifier.

    Args:
        ndi_class_name: The NDI class identifier string,
            e.g. ``"ndi.probe.timeseries.mfdaq"`` or
            ``"ndi.daq.reader.mfdaq.intan"``.

    Returns:
        The corresponding Python class, or ``None`` if not found.
    """
    global _REGISTRY  # noqa: PLW0603
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY.get(ndi_class_name)


def get_all() -> dict[str, type]:
    """Return a copy of the full registry (mainly for debugging)."""
    global _REGISTRY  # noqa: PLW0603
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return dict(_REGISTRY)
