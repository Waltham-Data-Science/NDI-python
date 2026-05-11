"""ndi.setup - Lab configuration and session setup utilities.

Python equivalent of MATLAB's ``+ndi/+setup/`` package.

Usage::

    import ndi
    ndi.setup.lab(session, "vhlab")
    ndi.setup.rayolab(session)
"""

from .lab import lab
from .rayolab import rayolab

__all__ = ["lab", "rayolab"]
