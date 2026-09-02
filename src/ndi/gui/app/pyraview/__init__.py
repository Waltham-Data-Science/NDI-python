"""ndi.gui.app.pyraview - the NDI signal viewer, and the pieces it is built from.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/pyraview.m`` (the app) and
``src/ndi/+ndi/+gui/+app/+pyraview/`` (its helpers). MATLAB has a class and a
package of the same name side by side; Python cannot, so the package holds
both and the app class is re-exported here under MATLAB's name -- which makes
``ndi.gui.app.pyraview.pyraview`` the class and
``ndi.gui.app.pyraview.filter_data`` the helper, the same two call paths
MATLAB offers.

THE OTHER pyraview
There are two things called pyraview and they are not the same. This package
is the NDI viewer. ``import pyraview`` -- no dots -- is the separate VH-Lab
library (https://github.com/VH-Lab/Pyraview) that builds and reads the
multi-resolution pyramids the viewer draws: a C++ core with MATLAB and Python
bindings. Inside this package that name always means the library, since
Python 3 resolves it absolutely; ``ndi_install.py`` clones and builds it.

Nothing here imports the library at module level, so a machine without it
still imports ndi.gui.app and still discovers the other apps. The two
functions that genuinely need it -- :func:`get_data.get_data` for reading a
pyramid and :func:`make_pyraview_doc.make_pyraview_doc` for building one --
import it where they use it.
"""

from __future__ import annotations

from . import (
    filter_data,
    get_data,
    load_spiking_neurons,
    make_pyraview_doc,
    mappings,
    transform_plot_data,
    transform_spike_data,
)

__all__ = [
    "filter_data",
    "get_data",
    "load_spiking_neurons",
    "make_pyraview_doc",
    "mappings",
    "transform_plot_data",
    "transform_spike_data",
]
