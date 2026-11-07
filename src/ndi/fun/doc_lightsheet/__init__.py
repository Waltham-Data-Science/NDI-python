"""ndi.fun.doc_lightsheet - lightsheet OME-Zarr document helpers.

Mirrors ``+ndi/+fun/+doc/+lightsheet/`` in NDI-matlab, one module per MATLAB
function or class (the layout of ``ndr.format.omezarr``). See
``ndi_matlab_python_bridge.yaml`` next to this file for each entry's status.
The builders are ``fromSPIM`` (SmartSPIM All_Channels slices), ``fromOMEZarr``
(an OME-Zarr store) and the ``makePyramid`` they share; any of them can write
to a local session or stream to NDI Cloud through ``ndi.cloud``'s SessionWriter.

The napari viewer these documents feed lives in
:mod:`ndi.gui.app.lightsheetZarr`.
"""

from .BuildProfile import BuildProfile, ndi_fun_doc_lightsheet_BuildProfile
from .chooseLevel import chooseLevel
from .chooseTileShape import chooseTileShape
from .dtypeName import dtypeName
from .fromOMEZarr import fromOMEZarr
from .fromSPIM import fromSPIM
from .levelTable import levelTable
from .makePyramid import makePyramid
from .makeSourceFile import makeSourceFile
from .reduceBlocks import reduceBlocks
from .view import view
from .viewCommand import viewCommand

__all__ = [
    "BuildProfile",
    "ndi_fun_doc_lightsheet_BuildProfile",
    "chooseLevel",
    "chooseTileShape",
    "dtypeName",
    "fromOMEZarr",
    "fromSPIM",
    "levelTable",
    "makePyramid",
    "makeSourceFile",
    "reduceBlocks",
    "view",
    "viewCommand",
]
