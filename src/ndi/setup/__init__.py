"""ndi.setup - Lab configuration and session setup utilities.

Python equivalent of MATLAB's ``+ndi/+setup/`` package.

Usage::

    import ndi
    ndi.setup.lab(session, "vhlab")
    ndi.setup.lab(session, "vhlab", force_update=True)
    ndi.setup.rayolab(session)
    ndi.setup.sync.add_sync_rules(session, "vhlab")
"""

from . import sync
from .lab import lab
from .rayolab import rayolab

__all__ = ["lab", "rayolab", "sync"]
