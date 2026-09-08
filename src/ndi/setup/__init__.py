"""ndi.setup - Lab configuration and session setup utilities.

Python equivalent of MATLAB's ``+ndi/+setup/`` package.

Usage::

    import ndi
    ndi.setup.lab(session, "vhlab")
    ndi.setup.rayolab(session)
"""

from . import sync
from .angeluccilab import angeluccilab
from .dbkatzlab import dbkatzlab
from .lab import lab
from .lab_names import lab_names, labNames
from .marderlab import marderlab
from .rayolab import rayolab
from .vhlab import vhlab
from .yangyangwang import yangyangwang

#: The six labs MATLAB gives a named wrapper. Every lab under
#: ndi_common/daq_systems is reachable through lab(session, name); these are
#: the ones with a function of their own, and five of the six had no Python
#: counterpart at all.
LAB_WRAPPERS = (
    "angeluccilab",
    "dbkatzlab",
    "marderlab",
    "rayolab",
    "vhlab",
    "yangyangwang",
)

__all__ = [
    "LAB_WRAPPERS",
    "angeluccilab",
    "dbkatzlab",
    "lab",
    "labNames",
    "lab_names",
    "marderlab",
    "rayolab",
    "sync",
    "vhlab",
    "yangyangwang",
]
