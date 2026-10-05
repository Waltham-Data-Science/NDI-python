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

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


def _docHasChunkBinSeries(doc: Any) -> bool:
    """True iff DOC's file metadata mentions the ``chunk.bin`` series.

    Named at module scope so it stays testable and so the prefetch
    path stays honest about what "no chunk.bin" means: skip. Checks
    the DID ``files.series_info`` shape first (the current writer),
    and falls back to any ``file_info`` entry whose name starts with
    ``chunk.bin`` (older ingests that wrote each member into
    ``file_info`` directly). Missing or malformed metadata reads
    as "no series", which is safe -- we just don't prefetch for
    that doc.
    """
    props = getattr(doc, "document_properties", None) or {}
    if not isinstance(props, dict):
        return False
    files = props.get("files")
    if not isinstance(files, dict):
        return False

    raw_series = files.get("series_info")
    series_entries: list[dict]
    if isinstance(raw_series, dict):
        series_entries = [raw_series]
    elif isinstance(raw_series, list):
        series_entries = [e for e in raw_series if isinstance(e, dict)]
    else:
        series_entries = []
    for entry in series_entries:
        if str(entry.get("name", "")) == "chunk.bin":
            return True

    raw_file_info = files.get("file_info")
    if isinstance(raw_file_info, list):
        for entry in raw_file_info:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            if name == "chunk.bin" or name.startswith("chunk.bin_"):
                return True
    return False


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

    def startSignedUrlPrefetch(
        self,
        cloud_dataset_id: str,
        *,
        client: Any = None,
    ) -> threading.Thread | None:
        """Prefetch signed-URL scopes for every level document, in background.

        Each level's ``chunk.bin`` file series takes 20-80 s server-side
        to sign, and the user hits that wait the first time they zoom
        into a new level. Kicking off the async signed-URL-set jobs
        for every level while the initial level-0 view is loading
        hides those waits behind a moment the user was already
        watching -- when they later zoom, the URLs are cached.

        Sequential inside one background thread on purpose (see the
        design note in the task that added this): parallelizing across
        scopes would need a lock refactor and 5 levels at ~1 minute
        each still fit inside the initial-render wall time.

        Args:
            cloud_dataset_id: The remote NDI Cloud dataset id. Empty
                means "no cloud context"; the call is a no-op.
            client: Passed to the signer (default signer only).

        Returns:
            The background thread on success, ``None`` when disabled
            or when there is nothing to prefetch. Off with
            ``NDI_LIGHTSHEET_PREFETCH_SIGNED_URLS=0``.
        """
        if os.environ.get("NDI_LIGHTSHEET_PREFETCH_SIGNED_URLS", "1").strip().lower() in (
            "0",
            "false",
            "off",
        ):
            logger.info("signed-URL prefetch disabled via NDI_LIGHTSHEET_PREFETCH_SIGNED_URLS")
            return None
        if not cloud_dataset_id:
            return None

        self.build()

        scopes: list[tuple[str, str, str]] = []
        for doc in self.docs:
            doc_id = getattr(doc, "id", "") or ""
            if not doc_id:
                continue
            if not _docHasChunkBinSeries(doc):
                continue
            scopes.append((cloud_dataset_id, doc_id, "chunk.bin"))

        if not scopes:
            return None

        from ndi.cloud.batch_signed_url import get_default

        return get_default().start_prefetch(scopes, client=client)

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
        import os
        import sys as _sys

        debug = os.environ.get("NDI_LIGHTSHEET_DEBUG", "").strip().lower() in (
            "1",
            "true",
            "on",
            "yes",
        )
        if ctx is None:
            if debug:
                print(
                    "[lightsheet] registerRefreshHint: SKIPPED -- fetcher has "
                    "no _fallback_context (fallback env off, or single-level "
                    "pyramid). Napari will not be auto-nudged when fine "
                    "chunks arrive; the user must trigger a camera event.",
                    file=_sys.stderr,
                    flush=True,
                )
            return
        ctx["refresh_hint_slot"][0] = hint
        if debug:
            print(
                f"[lightsheet] registerRefreshHint: installed "
                f"{'hint' if hint is not None else 'None (no-op)'}; "
                f"future async fine fetches will "
                f"{'nudge napari to re-slice' if hint is not None else 'NOT nudge napari'}.",
                file=_sys.stderr,
                flush=True,
            )

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
