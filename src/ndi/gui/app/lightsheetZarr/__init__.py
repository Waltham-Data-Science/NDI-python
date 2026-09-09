"""ndi.gui.app.lightsheetZarr - napari view of a lightsheetZarrPyramid.

Sibling of ``ndi.gui.app.genepyramid``. Keeps import cost off headless
callers (`napari` and `dask` are lazy) by re-exporting through
``__getattr__``. Consumers should either use the console script
``napariViewLightsheet`` (declared in ``pyproject.toml`` `[project.scripts]`)
or ``ndi.gui.app.lightsheetZarr.viewer.openPyramid``.
"""

from __future__ import annotations

__all__ = ["levelArrays", "layerSpec", "worldTransform"]


def __getattr__(name):
    if name in {"levelArrays", "layerSpec", "worldTransform"}:
        from ndi.gui.app.lightsheetZarr import multiscale
        return getattr(multiscale, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
