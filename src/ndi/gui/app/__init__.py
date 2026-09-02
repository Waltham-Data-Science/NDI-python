"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here. Five of MATLAB's
eleven have landed --
:class:`~ndi.gui.app.electrode_data_export.ElectrodeDataExport`,
:class:`~ndi.gui.app.ensemble_maker.ensembleMaker`,
:class:`~ndi.gui.app.spike_sorter_importer.spikeSorterImporter`,
:class:`~ndi.gui.app.stimulus_decoder.stimulusDecoder` and
:class:`~ndi.gui.app.stimulus_response.stimulusResponse` -- and each
reaches the Apps menu by living in this package and by nothing else. Two
pairs of them close a loop: the importer creates the spiking-neuron
elements that the ensemble maker builds ensembles from, and the two
stimulus apps are the stimulus pipeline's two halves -- one writes what
was shown, the other measures how an element answered it. The remaining
six -- pyraview, the other spike sorters, the other exporters -- are each
their own piece of work, some still waiting on unported subsystems
(``ndi.cpipeline`` for the pipeline editor, the sorters' own toolboxes). A
user can extend the menu meanwhile by naming their own packages in the
``GUI.Navigator.SessionAppPackages`` preference, which is exactly the
extension path MATLAB offers.

The apps are IMPORTED here for the convenience of ``from ndi.gui.app import
ensembleMaker``, not for discovery: discovery walks the package's modules
itself and attributes each class to the module that defines it, so an app
that this file never mentioned would be found just the same.
"""

from __future__ import annotations

from .electrode_data_export import ElectrodeDataExport
from .electrode_map import ElectrodeMap
from .ensemble_maker import ensembleMaker
from .session_app import SessionApp, sessionApp
from .spike_sorter_importer import spikeSorterImporter
from .stimulus_decoder import stimulusDecoder
from .stimulus_response import stimulusResponse

__all__ = [
    "ElectrodeDataExport",
    "ElectrodeMap",
    "SessionApp",
    "ensembleMaker",
    "sessionApp",
    "spikeSorterImporter",
    "stimulusDecoder",
    "stimulusResponse",
]
