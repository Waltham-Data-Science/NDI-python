"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here --
:class:`~ndi.gui.app.ensemble_maker.ensembleMaker` reaches the navigator's
Apps menu by living in this package and by nothing else. The other ten of
MATLAB's eleven apps -- pyraview, the spike sorters, the exporters -- are
not ported yet, and each is its own piece of work; the Apps menu also
carries whatever a user names in the ``GUI.Navigator.SessionAppPackages``
preference, which is the extension path MATLAB offers.

The apps are IMPORTED here for the convenience of ``from ndi.gui.app import
ensembleMaker``, not for discovery: discovery walks the package's modules
itself and attributes each class to the module that defines it, so an app
that this file never mentioned would be found just the same.
"""

from __future__ import annotations

from .ensemble_maker import ensembleMaker
from .session_app import SessionApp, sessionApp

__all__ = ["SessionApp", "sessionApp", "ensembleMaker"]
