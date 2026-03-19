"""Thin wrapper that re-exports ``ndi.setup.lab`` for backwards compatibility.

Tests should prefer importing from ``ndi.setup`` directly::

    import ndi
    ndi.setup.lab(session, "vhlab")
"""

from ndi.setup.lab import lab as setup_lab_daq_systems

__all__ = ["setup_lab_daq_systems"]
