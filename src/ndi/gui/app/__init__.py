"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here. MATLAB's eleven
apps -- pyraview, the spike sorters, the exporters -- are not ported yet;
each depends on further unported subsystems, and each is its own piece of
work. Until one lands, the Apps menu is populated only by apps in the
packages a user names in the ``GUI.Navigator.SessionAppPackages``
preference, which is exactly the extension path MATLAB offers.
"""

from __future__ import annotations

from .session_app import SessionApp, sessionApp

__all__ = ["SessionApp", "sessionApp"]
