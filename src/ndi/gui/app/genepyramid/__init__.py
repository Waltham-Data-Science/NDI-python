"""ndi.gui.app.genepyramid - view a spatial gene expression pyramid.

PYTHON-ONLY. napari has no MATLAB counterpart, so unlike most of this
package there is nothing here to mirror. MATLAB reads the same documents
through ``ndi.fun.doc.gene``; what differs is only the surface that draws
them.

The package is split so that the part which can be WRONG is testable
without a display:

    multiscale.py   pyramid document -> a list of lazy dask arrays, plus
                    the scale and translate that place them in world
                    coordinates. No napari import. Every coordinate
                    decision lives here and is unit tested.
    viewer.py       hands that to napari. Thin on purpose.

That split is the point. Registering a non-dyadic ladder in world
coordinates is the part that goes quietly wrong -- an off-by-one in the
origin puts every level somewhere plausible and wrong -- and it is
exactly the part a headless test can pin down. Opening a window is not.

Nothing here imports napari at module level, so a machine without it
still imports ndi.gui.app and still discovers the other apps.
"""

from __future__ import annotations

__all__ = ["levelArrays", "layerSpec", "worldTransform"]


def __getattr__(name):
    # Deferred so that importing ndi.gui.app does not pull in dask.
    if name in __all__:
        from . import multiscale

        return getattr(multiscale, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
