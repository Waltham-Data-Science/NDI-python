"""Compatibility shim: upsample_fallback moved to :mod:`ndi.pyramid`.

The pure geometry + reader lives in :mod:`ndi.pyramid.upsample_fallback`
so it can be tested and reused without napari. The Qt-side
``RefreshHint`` moved to :mod:`ndi.gui.app.lightsheetZarr.refresh_hint`.

This module re-exports both so callers that spelled the old path
keep working. New code should import from the new homes directly.
"""

from __future__ import annotations

from ndi.gui.app.lightsheetZarr.refresh_hint import RefreshHint, refreshHintFor  # noqa: F401
from ndi.pyramid.upsample_fallback import *  # noqa: F401,F403
from ndi.pyramid.upsample_fallback import (  # noqa: F401
    LevelGeometry,
    _fallback_debug,
    env_on,
    fallbackStatsSummary,
    findCoveringCoarseChunk,
    fineChunkWorldBox,
    levelGeometry,
    readChunkWithFallback,
    upsampleToBlock,
)
