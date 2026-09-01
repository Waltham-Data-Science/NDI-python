"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here. That includes the
apps a user adds themselves: naming their package in the
``GUI.Navigator.SessionAppPackages`` preference is the extension path
MATLAB offers, and this port offers it too.

WHAT IS HERE OF MATLAB'S ELEVEN
:class:`~ndi.gui.app.stimulus_response.stimulusResponse` ("Stimulus
Response", under the "Stimulus" submenu). The other ten are still to come;
each depends on further unported subsystems -- ``ndi.cpipeline`` for the
pipeline editor, the sorters' own toolboxes -- and each is its own piece of
work.
"""

from __future__ import annotations

from .session_app import SessionApp, sessionApp
from .stimulus_response import stimulusResponse

__all__ = ["SessionApp", "sessionApp", "stimulusResponse"]
