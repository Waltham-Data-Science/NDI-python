"""ndi.setup.marderlab - Initialize a session with MarderLab DAQ systems.

Python equivalent of MATLAB's ``ndi.setup.marderlab()``. Thin wrapper around
:func:`ndi.setup.lab` that loads the MarderLab DAQ system JSON configs from
``ndi_common/daq_systems/marderlab/``.

MATLAB has a named wrapper for each of six labs; only ``rayolab`` had a
Python counterpart, so ``ndi.setup.marderlab(session)`` -- the call every
MATLAB example for this lab uses -- raised AttributeError.

MATLAB equivalent: ``src/ndi/+ndi/+setup/marderlab.m``

Example::

    import ndi
    session = ndi.session.dir("exp001", "/path/to/session")
    ndi.setup.marderlab(session)
"""

from __future__ import annotations

from .lab import lab


def marderlab(session, force_update: bool = False) -> None:
    """Add the MarderLab DAQ systems to an NDI session.

    Parameters
    ----------
    session : ndi.session.session_base
        The NDI session to add DAQ systems to.
    force_update : bool
        Remove and re-create the MarderLab DAQ systems the session already
        has, rather than leaving them alone -- how a session picks up an
        edited definition. Mirrors MATLAB's ``'forceUpdate'`` option.
    """
    lab(session, "marderlab", force_update=force_update)
