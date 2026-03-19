"""ndi.setup — Lab configuration and session setup utilities.

Python equivalent of MATLAB's ``+ndi/+setup/`` package.

Usage::

    import ndi
    ndi.setup.lab(session, "vhlab")
"""

from .lab import lab

__all__ = ["lab"]
