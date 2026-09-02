"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here. A user extends the
menu the same way, by naming their own package in the
``GUI.Navigator.SessionAppPackages`` preference -- exactly the extension
path MATLAB offers.

WHAT IS HERE OF MATLAB'S ELEVEN
:class:`~ndi.gui.app.electrode_data_export.ElectrodeDataExport` ("Electrode
Data Export", at the top level) and
:class:`~ndi.gui.app.stimulus_response.stimulusResponse` ("Stimulus
Response", under the "Stimulus" submenu). The other nine -- pyraview, the
spike sorters, the remaining exporters -- are each their own piece of work,
some still waiting on unported subsystems (``ndi.cpipeline`` for the
pipeline editor, the sorters' own toolboxes).
"""

from __future__ import annotations

from .electrode_data_export import ElectrodeDataExport
from .session_app import SessionApp, sessionApp
from .stimulus_response import stimulusResponse

__all__ = ["ElectrodeDataExport", "SessionApp", "sessionApp", "stimulusResponse"]
