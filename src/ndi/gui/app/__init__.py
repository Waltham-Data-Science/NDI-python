"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here.
:class:`~ndi.gui.app.electrode_data_export.ElectrodeDataExport` is the
first of MATLAB's eleven apps to land, and so the first thing NDI's own
scan finds; the rest -- pyraview, the spike sorters, the exporters -- are
each their own piece of work, some of them still waiting on unported
subsystems. A user can extend the menu meanwhile by naming their own
packages in the ``GUI.Navigator.SessionAppPackages`` preference, which is
exactly the extension path MATLAB offers.
"""

from __future__ import annotations

from .electrode_data_export import ElectrodeDataExport
from .session_app import SessionApp, sessionApp

__all__ = ["ElectrodeDataExport", "SessionApp", "sessionApp"]
