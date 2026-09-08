"""ndi.setup.yangyangwang - Initialize a session with YangYangWang DAQ systems.

Python equivalent of MATLAB's ``ndi.setup.yangyangwang()``. Thin wrapper around
:func:`ndi.setup.lab` that loads the YangYangWang DAQ system JSON configs from
``ndi_common/daq_systems/yangyangwang/``.

MATLAB has a named wrapper for each of six labs; only ``rayolab`` had a
Python counterpart, so ``ndi.setup.yangyangwang(session)`` -- the call every
MATLAB example for this lab uses -- raised AttributeError.

MATLAB equivalent: ``src/ndi/+ndi/+setup/yangyangwang.m``

Example::

    import ndi
    session = ndi.session.dir("exp001", "/path/to/session")
    ndi.setup.yangyangwang(session)
"""

from __future__ import annotations

from .lab import lab


def yangyangwang(session, force_update: bool = False) -> None:
    """Add the YangYangWang DAQ systems to an NDI session.

    Parameters
    ----------
    session : ndi.session.session_base
        The NDI session to add DAQ systems to.
    force_update : bool
        Remove and re-create the YangYangWang DAQ systems the session already
        has, rather than leaving them alone -- how a session picks up an
        edited definition. Mirrors MATLAB's ``'forceUpdate'`` option.
    """
    lab(session, "yangyangwang", force_update=force_update)
