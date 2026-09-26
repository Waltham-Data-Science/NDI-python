"""ImagePyramidLoader: napari-independent facade over the retrieval layer.

The loader is the ONE class a caller talks to when they want the data
out of a ``lightsheetZarrPyramid`` document: build lazy dask arrays
per level, resolve chunks through the NDI cloud API, pre-fetch the
coarsest level at launch, hand over stats.

Napari consumes it through
:mod:`ndi.gui.app.lightsheetZarr.viewer`; matplotlib, Jupyter,
headless batch analyses, and a sibling ``+ndi/+pyramid/`` namespace
in NDI-matlab consume it the same way. That is the point of the
facade: retrieval logic testable without a display, plus one place
to reach for when tuning cache behaviour or measuring performance.

Design so far is intentionally thin: it delegates to
:func:`multiscale.layerSpec`, :func:`multiscale.prefetchCoarsestLevel`
and :meth:`_ChunkFetcher.stats_summary` rather than reimplementing
their bodies. That keeps the diff small during the move -- the
loader adds a single entry point and a lifecycle contract without
rewriting anything that already works. Future commits can grow the
loader into a richer object (chunk-level prefetch priorities, per-
layer stat splits, matplotlib helpers) without touching viewer.py.
"""

from __future__ import annotations

import threading
from typing import Any


class ImagePyramidLoader:
    """A lightsheetZarrPyramid, ready to be read.

    Construction is cheap -- it captures the arguments but does no
    network I/O until :meth:`build` is called (implicitly on the
    first access to :attr:`specs`, :attr:`fetcher` or :attr:`docs`).
    That lets a caller construct the loader in one place and pass
    it around without paying for the dask graphs, and it lets tests
    verify construction without a working NDI session.

    Attributes:
        session: The NDI session the pyramid lives in.
        pyramid_doc: The ``lightsheetZarrPyramid`` document.
        reduction: Optional reduction filter ("mean", "max", ...);
            None keeps every level.
        workers: Optional override for the fetcher pool size; None
            uses :func:`multiscale._default_workers`.
    """

    def __init__(
        self,
        session: Any,
        pyramid_doc: Any,
        *,
        reduction: str | None = None,
        workers: int | None = None,
        name: str | None = None,
        channel: int | None = None,
    ):
        self.session = session
        self.pyramid_doc = pyramid_doc
        self.reduction = reduction
        self.workers = workers
        self.name = name
        self.channel = channel
        self._specs: list[dict] | None = None
        self._fetcher = None
        self._docs: list | None = None
        self._build_lock = threading.Lock()

    # ------------------------------------------------------------------ build

    def build(self) -> None:
        """Build the lazy dask arrays and the fetcher. Idempotent.

        First call reads the pyramid's level documents and constructs
        one lazy dask array per level per channel through
        :func:`multiscale.layerSpec`. Later calls are a no-op.

        Raises whatever ``layerSpec`` raises when the pyramid has no
        levels for the chosen reduction; callers that want to probe
        for that condition should catch and inspect.
        """
        with self._build_lock:
            if self._specs is not None:
                return
            from ndi.pyramid.multiscale import layerSpec

            self._specs, self._fetcher = layerSpec(
                self.session,
                self.pyramid_doc,
                channel=self.channel,
                name=self.name,
                reduction=self.reduction,
                workers=self.workers,
            )

    # ------------------------------------------------------------------ views

    @property
    def specs(self) -> list[dict]:
        """One napari-consumable spec per output layer (usually per channel).

        A caller with a viewer does
        ``for spec in loader.specs: viewer.add_image(**spec)``. The
        specs carry extra keys (``_ndi_level_arrays``,
        ``_ndi_level_scales``) that napari does not understand; the
        caller pops those out and hands them to the level selector.
        """
        self.build()
        return self._specs  # type: ignore[return-value]

    @property
    def fetcher(self):
        """The shared chunk fetcher.

        Callers use this to attach cache-warming, to install the
        napari refresh hint into the upsample-fallback context, and
        to read per-fetch timing at shutdown.
        """
        self.build()
        return self._fetcher

    @property
    def docs(self) -> list:
        """The level documents, sorted finest-first.

        Cached so :meth:`build` and downstream consumers see the
        same ordering.
        """
        if self._docs is None:
            from ndi.pyramid.multiscale import levelDocs

            self._docs = levelDocs(self.session, self.pyramid_doc, reduction=self.reduction)
        return self._docs

    @property
    def numLevels(self) -> int:
        """How many levels the pyramid has for the chosen reduction."""
        return len(self.docs)

    # ------------------------------------------------------------------ prefetch

    def startPrefetch(self, level: int = -1) -> threading.Thread | None:
        """Kick off a background prefetch of every stored chunk on one level.

        Default is the coarsest level (``level=-1``), the level the
        upsample-fallback reader draws from when a fine chunk is
        still en route. Returns the background thread so a caller
        can join it in tests; napari callers just fire and forget.

        Off with the env var used by
        :func:`multiscale.prefetchCoarsestLevel`
        (``NDI_LIGHTSHEET_PREFETCH_COARSEST=0``).
        """
        from ndi.pyramid.multiscale import prefetchCoarsestLevel

        self.build()
        if level not in (-1, self.numLevels - 1):
            # Only the coarsest is supported in v1; anything else
            # falls back to no-op. The future arbitrary-level
            # prefetch lives here.
            return None
        return prefetchCoarsestLevel(
            self.session,
            self.pyramid_doc,
            self._fetcher,
            reduction=self.reduction,
        )

    # ------------------------------------------------------------------ hooks

    def registerRefreshHint(self, hint) -> None:
        """Install a ``on_complete`` callback for async fine-chunk fetches.

        The pyramid loader itself never calls napari. When the
        upsample-fallback reader queues an async fetch of a fine
        chunk, the fetch's completion fires ``hint(local_path)``.
        For napari the hint debounces ``layer.refresh()``; for a
        matplotlib caller it could redraw a figure; for a headless
        test it could set an event for the test to wait on.

        No-op when the fallback context does not exist (feature off
        or single-level pyramid).
        """
        self.build()
        fetcher = self._fetcher
        ctx = getattr(fetcher, "_fallback_context", None)
        if ctx is None:
            return
        ctx["refresh_hint_slot"][0] = hint

    # ------------------------------------------------------------------ stats

    def stats(self) -> dict:
        """Snapshot of fetcher + fallback stats.

        Return value is a dict with:

        * ``fetcher``: one-line summary from
          :meth:`_ChunkFetcher.stats_summary` (cache hits, cloud
          fetches, mean / max per-fetch time).
        * ``fallback``: :func:`fallbackStatsSummary` output, only
          when the upsample fallback is opted in.

        Missing keys mean "the feature was not built"; callers
        format each present entry however they like.
        """
        out: dict[str, str] = {}
        if self._fetcher is not None:
            try:
                out["fetcher"] = self._fetcher.stats_summary()
            except Exception:  # noqa: BLE001 - a bad stat is not fatal
                pass
        from ndi.pyramid.upsample_fallback import env_on, fallbackStatsSummary

        if env_on():
            try:
                out["fallback"] = fallbackStatsSummary()
            except Exception:  # noqa: BLE001
                pass
        return out

    # ------------------------------------------------------------------ shutdown

    def close(self) -> None:
        """Shut down the fetcher pool. Safe to call multiple times."""
        if self._fetcher is not None:
            try:
                self._fetcher.close()
            except Exception:  # noqa: BLE001
                pass
