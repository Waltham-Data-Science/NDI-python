"""ndi.gui.app - GUI apps that operate on a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/``

The package holds the :class:`~ndi.gui.app.session_app.SessionApp`
interface and the apps that adopt it. An app declares a ``Name``, takes a
session in its constructor, and is thereby offered in the navigator's
per-session "Apps" menu -- no registration step, and no list of apps
anywhere for it to be added to.

The package is also one of the two scanned by default (with ``ndi.app``),
so an app dropped in here is discovered by being here. All eleven of
MATLAB's apps have landed -- ``ElectrodeDataExport``, ``ElectrodeMap``,
``ensembleMaker``, ``katzExporter``, ``kiasort``, ``pipelineEditor``,
``pyraview``, ``spikeSorterImporter``, ``stimulusDecoder``,
``stimulusResponse`` and ``vhNDISpikeSorter`` -- and each reaches the Apps
menu by living in this package and by nothing else. Several close loops
with each other: the importer creates the spiking-neuron elements the
ensemble maker builds ensembles from, the two stimulus apps are the
stimulus pipeline's halves (one writes what was shown, the other measures
how an element answered), and the electrode map assigns the geometry the
data export writes into a sorter's channel map.

Three of the eleven wrap something Python cannot reach yet:
``vhNDISpikeSorter`` (needs the vhlab-library-matlab MATLAB library),
``kiasort`` (KIASORT is a MATLAB toolbox; its import side IS ported --
see :mod:`ndi.fun.probe.import_.kiasort`), and ``pipelineEditor``
(``ndi.cpipeline`` is not ported). Each is an availability check that
opens either way and explains itself when the tool is absent, so the port
is honest about the absence rather than hiding it -- and a lab that grows
a Python drop-in of any of the three gets a working button with no change
here.

A user can extend the menu by naming their own packages in the
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
from .katz_exporter import katzExporter
from .kiasort import kiasort
from .pipeline_editor import pipelineEditor
from .session_app import SessionApp, sessionApp
from .spike_sorter_importer import spikeSorterImporter
from .stimulus_decoder import stimulusDecoder
from .stimulus_response import stimulusResponse
from .vh_ndi_spike_sorter import vhNDISpikeSorter

__all__ = [
    "ElectrodeDataExport",
    "ElectrodeMap",
    "SessionApp",
    "ensembleMaker",
    "katzExporter",
    "kiasort",
    "pipelineEditor",
    "sessionApp",
    "spikeSorterImporter",
    "stimulusDecoder",
    "stimulusResponse",
    "vhNDISpikeSorter",
]
