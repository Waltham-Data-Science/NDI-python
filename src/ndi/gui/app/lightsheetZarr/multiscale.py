"""Compatibility shim: multiscale.py moved to :mod:`ndi.pyramid.multiscale`.

The napari-independent chunk-retrieval and dask-assembly code lives in
:mod:`ndi.pyramid.multiscale` now, so the same loader can serve
matplotlib, Jupyter, batch analyses and a MATLAB comparison harness
alongside the napari viewer. This module re-exports the public API
from its new home so callers that still spell the old path keep
working.

New code should import from :mod:`ndi.pyramid.multiscale` directly.
"""

from __future__ import annotations

from ndi.pyramid.multiscale import *  # noqa: F401,F403
from ndi.pyramid.multiscale import (  # noqa: F401
    _ChunkFetcher,
    _read_chunk_from_fetcher,
    _zero_block,
    layerSpec,
    levelArrays,
    levelDocs,
    levelTable,
    prefetchCoarsestLevel,
    worldTransform,
)
