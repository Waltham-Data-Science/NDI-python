"""ndi.setup.rayolab - Initialize a session with RayoLab DAQ systems.

Python equivalent of MATLAB's ``ndi.setup.rayolab()``. Thin wrapper around
:func:`ndi.setup.lab` that loads the RayoLab DAQ system JSON configs from
``ndi_common/daq_systems/rayolab/``.

The RayoLab setup currently includes two DAQ systems:

- ``rayo_intanSeries`` -- raw Intan RHD acquisition, grouped by filename
  prefix via ``ndi.file.navigator.rhd_series``, read with
  ``ndi.daq.reader.mfdaq.ndr`` (the NDR ``intan`` reader).
- ``rayo_stim`` -- the RayoLab stimulator, paired with the
  :class:`~ndi.daq.metadatareader.ndi_daq_metadatareader_RayoLabStims`
  metadata reader (which always returns ``stimid = 1``).

MATLAB equivalent: ``src/ndi/+ndi/+setup/rayolab.m``

Example::

    import ndi
    session = ndi.session.dir("exp001", "/path/to/session")
    ndi.setup.rayolab(session)
"""

from __future__ import annotations

from .lab import lab


def rayolab(session) -> None:
    """Add the RayoLab DAQ systems to an NDI session.

    Parameters
    ----------
    session : ndi.session.session_base
        The NDI session to add DAQ systems to.
    """
    lab(session, "rayolab")
