"""ndi.setup.angeluccilab - Initialize a session with AngelucciLab DAQ systems.

Python equivalent of MATLAB's ``ndi.setup.angeluccilab()``. Thin wrapper around
:func:`ndi.setup.lab` that loads the AngelucciLab DAQ system JSON configs from
``ndi_common/daq_systems/angeluccilab/``.

MATLAB has a named wrapper for each of six labs; only ``rayolab`` had a
Python counterpart, so ``ndi.setup.angeluccilab(session)`` -- the call every
MATLAB example for this lab uses -- raised AttributeError.

MATLAB equivalent: ``src/ndi/+ndi/+setup/angeluccilab.m``

Example::

    import ndi
    session = ndi.session.dir("exp001", "/path/to/session")
    ndi.setup.angeluccilab(session)
"""

from __future__ import annotations

from .lab import lab


def angeluccilab(session, force_update: bool = False) -> None:
    """Add the AngelucciLab DAQ systems to an NDI session.

    Parameters
    ----------
    session : ndi.session.session_base
        The NDI session to add DAQ systems to.
    force_update : bool
        Remove and re-create the AngelucciLab DAQ systems the session already
        has, rather than leaving them alone -- how a session picks up an
        edited definition. Mirrors MATLAB's ``'forceUpdate'`` option.
    """
    lab(session, "angeluccilab", force_update=force_update)
