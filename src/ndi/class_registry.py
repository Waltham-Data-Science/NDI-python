"""Unified NDI class registry for cross-language document compatibility.

Maps NDI class identifier strings (e.g. ``"ndi.probe.timeseries.mfdaq"``)
to their Python implementation classes.  This registry is used in two
directions:

* **Object → ndi_document**: each Python class exposes an ``NDI_*_CLASS``
  constant or ``ndi_element_class()`` method that returns its
  identifier, which gets written into the document.
* **ndi_document → Object**: :func:`get_class` looks up the Python class
  for a given identifier string so the object can be reconstructed.

The identifiers intentionally mirror the MATLAB class hierarchy to
ensure cross-language database compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Lazily populated on first access to avoid circular imports.
_REGISTRY: dict[str, type] | None = None


def _build_registry() -> dict[str, type]:
    """Build the class registry by importing all known NDI classes."""
    from .daq.reader.mfdaq.blackrock import ndi_daq_reader_mfdaq_blackrock
    from .daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2
    from .daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan
    from .daq.reader.mfdaq.spikegadgets import ndi_daq_reader_mfdaq_spikegadgets
    from .daq.system import ndi_daq_system
    from .element import ndi_element
    from .file.navigator import ndi_file_navigator
    from .file.navigator.epochdir import ndi_file_navigator_epochdir
    from .probe import ndi_probe
    from .probe.timeseries import ndi_probe_timeseries
    from .probe.timeseries_mfdaq import ndi_probe_timeseries_mfdaq
    from .probe.timeseries_stimulator import ndi_probe_timeseries_stimulator
    from .setup.daq.reader.mfdaq.stimulus.nielsenvisintan import (
        ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisintan,
    )
    from .setup.daq.reader.mfdaq.stimulus.vhlabvisspike2 import (
        ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2,
    )

    registry: dict[str, type] = {}

    # Elements / probes (keyed by ndi_element_class() return value)
    for cls in (
        ndi_element,
        ndi_probe,
        ndi_probe_timeseries,
        ndi_probe_timeseries_mfdaq,
        ndi_probe_timeseries_stimulator,
    ):
        registry[cls().ndi_element_class()] = cls

    # DAQ readers (keyed by NDI_DAQREADER_CLASS constant)
    for cls in (
        ndi_daq_reader_mfdaq_intan,
        ndi_daq_reader_mfdaq_blackrock,
        ndi_daq_reader_mfdaq_cedspike2,
        ndi_daq_reader_mfdaq_spikegadgets,
        ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2,
        ndi_setup_daq_reader_mfdaq_stimulus_nielsenvisintan,
    ):
        registry[cls.NDI_DAQREADER_CLASS] = cls

    # DAQ system
    registry[ndi_daq_system.NDI_DAQSYSTEM_CLASS] = ndi_daq_system

    # File navigators
    registry[ndi_file_navigator.NDI_FILENAVIGATOR_CLASS] = ndi_file_navigator
    registry[ndi_file_navigator_epochdir.NDI_FILENAVIGATOR_CLASS] = ndi_file_navigator_epochdir

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
