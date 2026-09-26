"""Dask multiscale over a lightsheetZarrPyramid stored as file_series.

The reader here is the load-bearing piece that the ``napariViewLightsheet``
console script and any programmatic viewer both drive. It:

* Enumerates ``lightsheetZarrLevel`` documents whose ``depends_on``
  ``lightsheetZarrPyramid_id`` matches the parent pyramid, optionally
  filtered to a single reduction.
* Presents each level as a lazy ``dask.array.Array`` backed by the
  level's ``chunk.bin_#`` file series.
* Composes them into a napari-consumable multiscale layer spec, with
  per-level ``scale`` and ``translate`` filled in from the level
  documents.

A reader that wants reduction ``R`` keeps levels with
``reduction_function in {'none', R}`` (the shared raw level 0 plus the
reduced tail), sorted by ``level`` ascending. Callers that want the
whole ladder pass ``reduction=None`` (the default) and get every level.

Chunk bytes go through the standard NDI cloud-cache path
``session.database_openbinarydoc(level_doc, "chunk.bin_#") ->
.fullpathfilename`` (same idiom as genepyramid.multiscale). That keeps
lightsheet reads on the same HIPAA-compliant cloud API that the rest of
the session uses; no separate zarr store or external URL is opened.

Napari itself is NOT imported here - the module returns plain dask
arrays and a dict for ``add_image(**spec)`` so a headless caller can
build the ladder without a display. ``napari`` and ``dask`` are
optional install extras (``pip install 'ndi[napari]'``).
"""

from __future__ import annotations

import os
import threading
from typing import Any

# ---------------------------------------------------------------------------
# depends_on / doc discovery


def levelDocs(session: Any, pyramid_doc: Any, reduction: str | None = None) -> list[Any]:
    """Return the ``lightsheetZarrLevel`` documents of a pyramid, finest-first.

    Uses the standard NDI query surface: query for the class and filter
    by the ``lightsheetZarrPyramid_id`` dependency slot. When
    ``reduction`` is given, keeps only levels with ``reduction_function``
    in ``{'none', reduction}`` -- the shared raw level(s) plus the
    requested reduction. ``reduction=None`` returns every level.
    """
    from ndi.query import ndi_query

    q = ndi_query("").isa("lightsheetZarrLevel") & ndi_query("").depends_on(
        "lightsheetZarrPyramid_id", pyramid_doc.id
    )
    docs = list(session.database_search(q))
    if reduction is not None:
        keep = {"none", reduction}
        docs = [
            d
            for d in docs
            if d.document_properties["lightsheetZarrLevel"].get("reduction_function", "none")
            in keep
        ]
    docs.sort(key=lambda d: int(d.document_properties["lightsheetZarrLevel"]["level"]))
    return docs


def levelTable(session: Any, pyramid_doc: Any, reduction: str | None = None) -> list[dict]:
    """One row per level: level, reduction_function, shape, chunks, voxel_size, id.

    Metadata-only. Used by ``napariViewLightsheet --report`` and by
    ``chooseLevel``-style callers that must not read chunk bytes.
    When ``reduction`` is given, the returned rows are the ladder the
    named reduction would read.
    """
    rows: list[dict] = []
    for doc in levelDocs(session, pyramid_doc, reduction=reduction):
        p = doc.document_properties["lightsheetZarrLevel"]
        rows.append(
            {
                "level": int(p["level"]),
                "reduction_function": p.get("reduction_function", "none"),
                "shape": list(p["shape"]),
                "chunks": list(p["chunks"]),
                "voxel_size": list(p.get("voxel_size", [])),
                "translation": list(p.get("translation", [])),
                "dtype": p.get("dtype", ""),
                "id": doc.id,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# world transform


def worldTransform(session: Any, pyramid_doc: Any) -> tuple[list[float], list[float]]:
    """Return ``(scale_level0, translation_level0)`` for a napari layer.

    Follows napari's rule that ``scale``/``translate`` on a multiscale
    layer describe the FINEST level; coarser levels are then placed at
    ``scale * 2**level`` (or whatever the level document's own
    ``voxel_size`` says, when it does not agree with a power-of-two
    ladder).
    """
    _ = session  # signature parity with genepyramid; kept for a future world-frame lookup
    p = pyramid_doc.document_properties["lightsheetZarrPyramid"]
    scale = [float(v) for v in p.get("voxel_size_level0", [])]
    translation = [float(v) for v in p.get("translation_level0", [])]
    if not translation and scale:
        translation = [0.0] * len(scale)
    return scale, translation


# ---------------------------------------------------------------------------
# multiscale arrays


class _ChunkFetcher:
    """Fetches chunk paths on threads that own their own session handle.

    Same shape as genepyramid._TileFetcher (see that file for the reasoning
    -- worth reading in full if this is touched). Recap:

    DID's SQLiteDB is thread-owned: only the thread that opened a session
    may call ``database_openbinarydoc`` on it. Dask's default (threaded)
    scheduler runs delayed tasks on a pool. If a task reaches into the
    caller's session, DID's read path catches sqlite's cross-thread error
    and returns None -- and session_base then raises
    ``ndi_document <id> not found`` for a document that is present. Only
    the synchronous scheduler passes.

    Resolving every chunk on the main thread AVOIDS that trap and works
    for a directory-backed session (path resolution is free), but on a
    cloud-backed session ``database_openbinarydoc`` DOWNLOADS THE FILE --
    resolving is fetching. Eager resolution of every chunk of every level
    then downloads the whole pyramid before napari draws a pixel.

    This class is the middle ground: dedicated fetcher threads each own
    their own re-opened session. Delayed tasks call ``chunkPath(doc, name)``
    from whichever thread they run on; the fetcher dispatches through its
    pool and returns the resolved local path. Resolved paths are memoised
    per (doc_id, filename) so a re-render never reaches the fetch threads
    again -- a cached hit is one ``os.path.exists`` from any thread.

    ``workers`` DEFAULTS TO 1: one session opened once, exactly as if a
    separate process held it. Cloud fetches are latency-bound, so raising
    it buys overlap; it also costs another whole session per worker.
    """

    def __init__(self, session, workers: int = 1):
        self._session = session
        self._owner = threading.get_ident()
        self._reopen = self._reopener(session)
        self._workers = max(1, int(workers))
        self._local = threading.local()
        self._pool = None
        self._lock = threading.Lock()
        self._paths: dict[tuple[str, str], str] = {}
        # Async prefetch bookkeeping. When the upsample-fallback reader
        # kicks off a background fetch, this maps the chunk key to the
        # list of on_complete callbacks that fire when the pool worker
        # finishes. Sharing the map de-duplicates: the same chunk
        # requested twice enqueues one task and both callers are
        # notified when it lands.
        self._in_flight: dict[tuple[str, str], list] = {}
        # Per-fetch timing bucketed by outcome. Set by _resolve on every
        # call, including memo hits, so a caller can tell whether a
        # slow tile is "cloud is slow" vs "local cache lookup is slow"
        # vs "memo miss forces a re-fetch".
        self._stats_lock = threading.Lock()
        self._resolve_times_cache: list[float] = []
        self._resolve_times_fetch: list[float] = []
        self._resolve_none: int = 0

    @staticmethod
    def _reopener(session):
        """How to build another handle on the same data, or None if unknown.

        Only a path-backed session is reopened; anything holding a live
        client or credentials is left alone rather than duplicated on a
        guess (per-thread reauth would be worse than the serialisation it
        buys).
        """
        path = getattr(session, "path", None)
        if path is None:
            return None
        cls = type(session)
        return lambda: cls(path)

    def _initThread(self):
        self._local.session = self._reopen()

    def _ensurePool(self):
        if self._pool is not None or self._reopen is None:
            return self._pool
        with self._lock:
            if self._pool is None:
                from concurrent.futures import ThreadPoolExecutor

                self._pool = ThreadPoolExecutor(
                    max_workers=self._workers,
                    thread_name_prefix="ndi-lightsheet",
                    initializer=self._initThread,
                )
        return self._pool

    def warm(self) -> None:
        """Build the session handles now, off the calling thread.

        Optional; worth calling right after ``napari.Viewer()`` so the
        one-off session-open cost lands while the user is staring at an
        empty canvas rather than at the first pan.
        """
        pool = self._ensurePool()
        if pool is None:
            return
        for f in [pool.submit(lambda: None) for _ in range(self._workers)]:
            f.result()

    def _resolve(self, doc, filename) -> str | None:
        s = getattr(self._local, "session", None) or self._session
        import time as _time

        t0 = _time.monotonic()
        try:
            fh = s.database_openbinarydoc(doc, filename)
        except Exception as exc:
            with self._stats_lock:
                self._resolve_none += 1
            if os.environ.get("NDI_LIGHTSHEET_DEBUG"):
                import sys

                print(
                    f"[lightsheet] chunk fetch failed for {filename}: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            return None
        try:
            path = getattr(fh, "fullpathfilename", None)
            dt = _time.monotonic() - t0
            # database_openbinarydoc has two happy paths: a local-cache
            # hit (near instant, microseconds; no cloud roundtrip) and
            # a cloud fetch (tens of ms to seconds). Split the buckets
            # so a summary later can say how many of each we saw and
            # what each one costs.
            #
            # 50 ms is comfortably above local disk latency and well
            # under any credible cloud RTT; picking a threshold rather
            # than routing on internal state keeps the classifier
            # independent of DID's evolving fast paths.
            with self._stats_lock:
                if dt < 0.05:
                    self._resolve_times_cache.append(dt)
                else:
                    self._resolve_times_fetch.append(dt)
            return str(path) if path else None
        finally:
            try:
                s.database_closebinarydoc(fh)
            except Exception:
                pass

    def stats_summary(self) -> str:
        """One-line summary of resolve timings for the last session.

        Formats as:

          resolves: N cache-hits (mean X.Xms), M cloud-fetches (mean X.Xs),
          F failures.

        Reset by :meth:`reset_stats`; the object stays alive across a
        viewer session and prints once from ``openPyramid`` on shutdown.
        """
        with self._stats_lock:
            n_cache = len(self._resolve_times_cache)
            n_fetch = len(self._resolve_times_fetch)
            n_none = self._resolve_none
            mean_cache_ms = 1000.0 * (sum(self._resolve_times_cache) / n_cache if n_cache else 0.0)
            mean_fetch_s = sum(self._resolve_times_fetch) / n_fetch if n_fetch else 0.0
            max_fetch_s = max(self._resolve_times_fetch) if n_fetch else 0.0
        return (
            f"resolves: {n_cache} cache-hits (mean {mean_cache_ms:.1f}ms), "
            f"{n_fetch} cloud-fetches (mean {mean_fetch_s:.2f}s, max "
            f"{max_fetch_s:.2f}s), {n_none} failures"
        )

    def reset_stats(self) -> None:
        with self._stats_lock:
            self._resolve_times_cache.clear()
            self._resolve_times_fetch.clear()
            self._resolve_none = 0

    def chunkPath(self, doc, filename) -> str | None:
        """Resolve one chunk file to a local path, fetching it if remote.

        None when the chunk was never materialised (sparse) or when the
        underlying fetch raised.

        Memoised: once a path is known, subsequent lookups are one
        ``os.path.exists`` from any thread. Files can be evicted, so a
        stale hit that fails on read should be dropped with :meth:`forget`.
        """
        key = (getattr(doc, "id", str(doc)), filename)
        known = self._paths.get(key)
        if known is not None and os.path.exists(known):
            return known
        # Loud trace under debug so we can see whether napari is
        # actually reaching this reader at all -- a session that draws
        # nothing and produces no observer events could mean either
        # "napari never asked for a slice" or "napari asked but our
        # dask blocks didn't run". Print unconditionally under debug
        # so the two cases are distinguishable.
        if os.environ.get("NDI_LIGHTSHEET_DEBUG"):
            import sys
            import threading as _th

            print(
                f"[lightsheet] chunkPath: {filename} (thread " f"{_th.current_thread().name})",
                file=sys.stderr,
                flush=True,
            )
        path = self._fetch(doc, filename)
        if path is not None:
            self._paths[key] = path
        return path

    def forget(self, doc, filename) -> None:
        """Drop a memoised path so the next call fetches it again."""
        self._paths.pop((getattr(doc, "id", str(doc)), filename), None)

    def chunkPathIfCached(self, doc, filename) -> str | None:
        """Return a local path IFF the chunk is already on disk, else None.

        Never fetches -- reads only the memoisation table and the
        filesystem, so this is safe to call from every dask task on
        the critical read path. The upsample-fallback reader uses
        this to decide "return real fine data" vs "fall back to
        upsampled coarse data" WITHOUT waiting on a cloud round
        trip. A miss means "we do not have it now"; whether we ever
        will is a separate question the async prefetch answers.
        """
        key = (getattr(doc, "id", str(doc)), filename)
        known = self._paths.get(key)
        if known is not None and os.path.exists(known):
            return known
        return None

    def prefetchAsync(self, doc, filename, on_complete=None) -> None:
        """Kick off a background fetch of one chunk. Never blocks.

        The upsample-fallback reader returns coarse-upsampled data
        immediately for a chunk that is not on disk; this asks the
        pool to go fetch the real thing so a later re-slice can
        find it via :meth:`chunkPathIfCached`. On completion (or
        failure), ``on_complete`` is called with the resolved path
        or None -- callers use that to trigger a napari refresh so
        the user is not stuck looking at blurred data forever.

        De-duplicates by memo key: the same (doc, filename) already
        in flight or already cached does not enqueue a second task.
        Errors are absorbed; the reader will retry on the next
        re-slice and eventually get real data or a permanent
        fallback.
        """
        key = (getattr(doc, "id", str(doc)), filename)
        with self._lock:
            if key in self._paths and os.path.exists(self._paths[key]):
                # Already cached -- no need to enqueue. Fire the
                # completion callback synchronously so the caller
                # can react uniformly whether the answer was cheap
                # or expensive.
                if on_complete is not None:
                    try:
                        on_complete(self._paths[key])
                    except Exception:  # noqa: BLE001
                        pass
                return
            if key in self._in_flight:
                if on_complete is not None:
                    self._in_flight[key].append(on_complete)
                return
            self._in_flight[key] = [on_complete] if on_complete is not None else []

        pool = self._ensurePool()
        if pool is None:
            # No pool means this session cannot be reopened, and
            # the fetcher is single-threaded. Fall back to a
            # blocking resolve on the caller's thread -- it is the
            # rare directory-backed case and does not need async.
            path = self._resolve(doc, filename)
            self._settle_in_flight(key, path)
            return

        def _run():
            try:
                path = self._resolve(doc, filename)
            except Exception:  # noqa: BLE001
                path = None
            if path is not None:
                with self._lock:
                    self._paths[key] = path
            self._settle_in_flight(key, path)

        pool.submit(_run)

    def _settle_in_flight(self, key, path) -> None:
        """Drain and call every pending completion callback for one key."""
        with self._lock:
            callbacks = self._in_flight.pop(key, [])
        for cb in callbacks:
            try:
                cb(path)
            except Exception:  # noqa: BLE001 - a bad callback is not fatal
                pass

    def _fetch(self, doc, filename) -> str | None:
        if threading.get_ident() == self._owner:
            return self._resolve(doc, filename)
        pool = self._ensurePool()
        if pool is None:
            raise RuntimeError(
                f"Cannot fetch {filename!r} from thread "
                f"{threading.current_thread().name}: this session cannot be "
                f"reopened for another thread, and NDI's database may only "
                f"be used from the thread that opened it. Compute the ladder "
                f"with dask's synchronous scheduler, or pass a session that "
                f"exposes a path."
            )
        return pool.submit(self._resolve, doc, filename).result()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None


def _default_workers() -> int:
    """Chunk-fetcher worker count. Env override for the cloud-latency case."""
    try:
        n = int(os.environ.get("NDI_LIGHTSHEET_WORKERS", "8"))
    except ValueError:
        return 8
    return max(1, n)


def levelArrays(
    session: Any,
    pyramid_doc: Any,
    channel: int | None = None,
    reduction: str | None = None,
    workers: int | None = None,
) -> tuple[list[Any], _ChunkFetcher]:
    """One lazy dask array per level, plus the fetcher backing them.

    Each array reads its chunks from the level document's ``chunk.bin_#``
    file series through the NDI cloud cache; a missing chunk resolves to
    the level's ``fill_value`` without any network call.

    The returned :class:`_ChunkFetcher` owns the dedicated fetcher threads
    that back the delayed tasks. It stays alive because the block closures
    hold a reference to it, so the caller does not strictly need to keep
    it -- but returning it lets a viewer call ``.warm()`` before the first
    pan and ``.close()`` on teardown.

    ``channel`` (1-based) narrows the returned arrays to a single channel
    along the pyramid's ``c`` axis; ``None`` returns every channel as its
    own axis.

    ``reduction`` filters the ladder to ``reduction_function`` in
    ``{'none', reduction}``; ``None`` returns every level.

    ``workers`` sets how many parallel fetcher threads the returned
    ``_ChunkFetcher`` runs. Defaults to the ``NDI_LIGHTSHEET_WORKERS``
    env var or 8; cloud reads are latency-bound so a higher count buys
    real overlap on the first-frame cascade.

    Per-level progress goes through :mod:`.progress` so a Qt launch
    window (when Qt is available) and the stderr channel share one
    label per step.
    """
    import dask.array as da
    from dask import delayed

    from . import progress

    docs = levelDocs(session, pyramid_doc, reduction=reduction)
    if not docs:
        raise ValueError(
            f"pyramid {pyramid_doc.id!s} has no lightsheetZarrLevel children for "
            f"reduction={reduction!r}."
        )

    _ = channel  # single-channel narrowing lands with the magicgui panels

    fetcher = _ChunkFetcher(session, workers=workers if workers is not None else _default_workers())

    # Upsample-fallback context: build once from the coarsest level's
    # document so every fine-level delayed task can look up covering
    # coarse chunks without re-reading the doc. Only material when the
    # NDI_LIGHTSHEET_UPSAMPLE_FALLBACK env var is on. The context also
    # rides on the fetcher itself so viewer.py can install a napari
    # refresh hint AFTER the arrays exist (the viewer does not, at
    # this point).
    fallback_context = _prepFallbackContext(docs)
    fetcher._fallback_context = fallback_context  # type: ignore[attr-defined]

    arrays: list[Any] = []
    for i, doc in enumerate(docs):
        p = doc.document_properties["lightsheetZarrLevel"]
        shape = tuple(int(v) for v in p["shape"])
        chunks = tuple(int(v) for v in p["chunks"])
        chunk_grid = tuple(int(v) for v in p["chunk_grid"])
        dtype = _numpy_dtype(str(p.get("dtype", "uint16")))
        fill = int(p.get("fill_value", 0))
        codec = str(p.get("codec", "raw"))
        stored = _storedChunkNames(doc)
        _assertStoredMatchesLevel(doc, p, stored)

        n_blocks = 1
        for g in chunk_grid:
            n_blocks *= g

        # The coarsest level is its own fallback; wrapping its reader
        # would recurse into itself for missing chunks. Only levels
        # ABOVE the coarsest get the fallback treatment.
        fallback_reader = None
        if fallback_context is not None and i < len(docs) - 1:
            fallback_reader = _makeFallbackReader(p, fallback_context)

        with progress.stage(f"preparing level {i} ({n_blocks:,} tiles, shape={list(shape)})"):
            nested = _build_block_grid(
                fetcher,
                doc,
                shape,
                chunks,
                chunk_grid,
                dtype,
                fill,
                codec,
                stored,
                delayed,
                da,
                fallback_reader=fallback_reader,
            )
            arrays.append(da.block(nested))

    return arrays, fetcher


def _prepFallbackContext(docs: list) -> dict | None:
    """Assemble the coarse-level context the upsample fallback needs.

    Returns a dict with the coarsest level's document, its geometry,
    and its stored-chunk name set -- or None when the env var is off
    or the pyramid has only one level (no fine level to fall back
    from). The dict also carries a one-element list ``refresh_hint_slot``
    that the viewer later populates with a debounced
    :class:`RefreshHint`; the fallback reader reads slot[0] at
    delayed-task time, so a hint installed after ``levelArrays``
    returns is still picked up by every subsequent slice.
    """
    from . import upsample_fallback

    if not upsample_fallback.env_on():
        return None
    if len(docs) < 2:
        return None
    coarse_doc = docs[-1]
    coarse_props = coarse_doc.document_properties["lightsheetZarrLevel"]
    coarse_geom = upsample_fallback.levelGeometry(coarse_props)
    coarse_stored = _storedChunkNames(coarse_doc)
    return {
        "coarse_doc": coarse_doc,
        "coarse_geom": coarse_geom,
        "coarse_stored": coarse_stored,
        "refresh_hint_slot": [None],
    }


def _makeFallbackReader(fine_props: dict, ctx: dict):
    """Return a closure over the fallback context for one fine level.

    The closure has the signature ``_build_block_grid`` expects for
    ``fallback_reader``: ``(fetcher, doc, filename, indices, chunks,
    block_shape, dtype, fill, codec)``. It reads the current refresh
    hint from ``ctx["refresh_hint_slot"][0]`` per call, so a hint
    installed after this closure was built still fires.
    """
    from . import upsample_fallback

    fine_geom = upsample_fallback.levelGeometry(fine_props)
    coarse_doc = ctx["coarse_doc"]
    coarse_geom = ctx["coarse_geom"]
    coarse_stored = ctx["coarse_stored"]
    slot = ctx["refresh_hint_slot"]

    def reader(fetcher, doc, filename, indices, chunks_full, block_shape, dtype, fill, codec):
        return upsample_fallback.readChunkWithFallback(
            fetcher,
            doc,
            filename,
            fine_geom,
            tuple(indices),
            coarse_doc,
            coarse_geom,
            coarse_stored,
            chunks_full,
            block_shape,
            dtype,
            fill,
            codec,
            refresh_hint=slot[0],
        )

    return reader


def prefetchCoarsestLevel(
    session: Any,
    pyramid_doc: Any,
    fetcher,
    *,
    reduction: str | None = None,
) -> threading.Thread | None:
    """Fetch every stored chunk of the coarsest pyramid level in the background.

    This is the launch-time complement of the upsample fallback that
    (in a follow-up) fills fine-level gaps by resampling coarser
    cached data: without at least one level fully on disk, the
    fallback still has holes. The coarsest level is the natural
    choice -- it is the smallest (252 tiles here, not 121,440) and
    stretched-up coarse pixels look better than black rectangles.

    Runs off the main thread so napari can paint before this
    finishes. The fetcher's worker pool serves the requests, and
    :meth:`_ChunkFetcher.chunkPath` is memoised -- a chunk that
    napari already fetched during the launch cascade is one
    ``os.path.exists`` here, not a repeat network round trip.

    Off with ``NDI_LIGHTSHEET_PREFETCH_COARSEST=0`` for the case
    where a caller wants to keep the pool fully available to napari's
    own foreground fetches. Skipped when the coarsest level records
    no stored chunks -- a directory-backed session that already has
    everything, or an empty test fixture.

    Returns the background thread (already started) or None when
    nothing to do or the knob is off. Callers do not need to join
    it: it is daemonised so a viewer exit does not wait.
    """
    if os.environ.get("NDI_LIGHTSHEET_PREFETCH_COARSEST", "1").strip().lower() in (
        "0",
        "false",
        "off",
    ):
        return None

    docs = levelDocs(session, pyramid_doc, reduction=reduction)
    if not docs:
        return None
    coarsest = docs[-1]  # levelDocs is finest-first, so coarsest is last.
    stored = _storedChunkNames(coarsest)
    if not stored:
        return None

    # Materialise the chunk name list up front so the log line
    # reports a stable denominator; a set's iteration order would
    # otherwise change what "10/252" refers to across ticks.
    names = sorted(stored)
    total = len(names)

    # Import here so the module still imports cleanly on a system
    # without the progress module ready (tests import multiscale
    # without progress's Qt path being importable).
    from . import progress

    def _do_prefetch() -> None:
        import time as _time

        t0 = _time.monotonic()
        completed = 0
        skipped_errors = 0
        # Serial through the fetcher: each chunkPath submits ONE task
        # to the pool and blocks on its return. That leaves the other
        # (workers - 1) pool threads for napari's own foreground
        # fetches instead of drowning them under a 252-deep queue.
        for i, name in enumerate(names, 1):
            try:
                fetcher.chunkPath(coarsest, name)
            except Exception:  # noqa: BLE001 - a stale prefetch is not fatal
                skipped_errors += 1
            completed = i
            if i == total or i % 25 == 0:
                dt = _time.monotonic() - t0
                rate = i / dt if dt > 0 else 0.0
                progress.note(
                    f"prefetch coarsest level: {i}/{total} tiles "
                    f"({dt:.1f}s, {rate:.1f} tiles/s)"
                )
        dt = _time.monotonic() - t0
        tail = f", {skipped_errors} skipped on errors" if skipped_errors else ""
        progress.note(
            f"prefetch coarsest level: DONE {completed}/{total} tiles " f"in {dt:.1f}s{tail}"
        )

    thread = threading.Thread(
        target=_do_prefetch,
        name="ndi-lightsheet-prefetch",
        daemon=True,
    )
    thread.start()
    progress.note(f"prefetch coarsest level: kicked off {total} tiles in background")
    return thread


def _assertStoredMatchesLevel(level_doc: Any, level_props: dict, stored: set[str] | None) -> None:
    """Raise if the resolved chunk name set can't cover the level's writes.

    A level document records ``n_chunks_stored`` -- how many
    ``chunk.bin_#`` members the writer actually wrote. When the reader
    resolves an empty stored set (or a set clearly smaller than what the
    writer claims), the level document lays its chunks out somewhere the
    reader doesn't look, and rendering would fall through to fill_value
    for every position -- a solid fill_value canvas, no error. That is
    exactly the failure mode that hid the file_series switch: the reader
    kept filtering ``file_info`` for ``chunk.bin_#`` after the writer
    moved the members to ``files.series_info``, produced an empty set,
    and drew black without a peep. Fail loudly here so a similar drift
    in the future is caught at open time, not by staring at a blank
    viewer.

    A ``None`` stored set means "no file list on this document"; the
    reader then attempts every position, which is fine on a raw-only
    fixture but not something a level with recorded writes should hit.
    Treat that as a mismatch too.
    """
    try:
        n_stored = int(level_props.get("n_chunks_stored", 0) or 0)
    except (TypeError, ValueError):
        n_stored = 0
    if n_stored <= 0:
        return
    if stored is None or len(stored) < n_stored:
        doc_id = getattr(level_doc, "id", None) or "<unknown>"
        label = str(level_props.get("label", "") or "")
        found = 0 if stored is None else len(stored)
        raise RuntimeError(
            f"lightsheetZarrLevel {doc_id} (label={label!r}) claims "
            f"n_chunks_stored={n_stored} but the reader resolved {found} "
            f"chunk file(s) on the document. The reader looks at "
            f"files.series_info first (chunk.bin as a DID file series) "
            f"and falls back to files.file_info entries matching "
            f"'chunk.bin_#'; neither carried enough members here. Either "
            f"the writer stored the chunks under a different layout the "
            f"reader has not learned yet, or the document lost its files "
            f"between ingest and read. Investigate the level document's "
            f"files.series_info / file_info before opening the pyramid; "
            f"opening it now would render a solid fill_value canvas "
            f"instead of the actual volume."
        )


def _storedChunkNames(level_doc: Any) -> set[str] | None:
    """Return the set of ``chunk.bin_#`` names attached to a level document.

    Returned as a set for O(1) membership tests during the delayed-block
    grid build. Empty set means "the level document knows it has no
    chunks" and every position resolves to fill_value with no fetch. None
    means "the level document does not expose a file list" (older docs,
    unusual backends) -- the reader then falls back to trying every
    position, matching the pre-file-list behaviour.

    ``chunk.bin`` is a DID file series: the level document's
    ``file_info`` names only the series manifest (``chunk.bin``); its
    members ``chunk.bin_1..N`` are recorded on ``files.series_info``.
    Read the series record first and, if present, return the set of
    member names it enumerates. Fall back to filtering ``file_info``
    for direct ``chunk.bin_#`` entries so pre-series documents still
    resolve chunks (older ingests wrote each member into ``file_info``
    directly).
    """
    props = getattr(level_doc, "document_properties", None) or {}
    files = props.get("files") if isinstance(props, dict) else None
    if isinstance(files, dict):
        raw_series = files.get("series_info")
        if isinstance(raw_series, dict):
            series_entries: list[dict] = [raw_series]
        elif isinstance(raw_series, list):
            series_entries = [e for e in raw_series if isinstance(e, dict)]
        else:
            series_entries = []
        for entry in series_entries:
            if str(entry.get("name", "")) != "chunk.bin":
                continue
            names_from_series = _seriesMemberNames("chunk.bin", entry)
            if names_from_series is not None:
                return names_from_series

    try:
        names = level_doc.current_file_list()
    except Exception:
        return None
    if names is None:
        return None
    out: set[str] = set()
    for name in names:
        s = str(name)
        if s.startswith("chunk.bin_"):
            out.add(s)
    return out


def _seriesMemberNames(base: str, series_entry: dict) -> set[str] | None:
    """Expand one series' record into ``base_<index>`` member names.

    Prefers the entry's ``ingest_locations`` (each carries an explicit
    ``index``), which is the sparse-aware shape DID materialises when a
    series is added; falls back to a dense 1..count listing when only
    the count is recorded, matching how a freshly-added series looks
    before any location bookkeeping runs.
    """
    ingest = series_entry.get("ingest_locations")
    if isinstance(ingest, list) and ingest:
        out: set[str] = set()
        for loc in ingest:
            if not isinstance(loc, dict):
                continue
            try:
                idx = int(loc.get("index", 0))
            except (TypeError, ValueError):
                continue
            if idx >= 1:
                out.add(f"{base}_{idx:d}")
        if out:
            return out

    try:
        count = int(series_entry.get("count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return set()
    return {f"{base}_{i:d}" for i in range(1, count + 1)}


def _numpy_dtype(s: str):
    """Turn a Zarr / MATLAB dtype string into a numpy dtype."""
    import numpy as np

    s = s.strip().lower()
    if s and s[0] in "<>|=":
        endian = s[0]
        rest = s[1:]
    else:
        endian = "<"
        rest = s
    aliases = {
        "u1": "u1",
        "u2": "u2",
        "u4": "u4",
        "u8": "u8",
        "i1": "i1",
        "i2": "i2",
        "i4": "i4",
        "i8": "i8",
        "f2": "f2",
        "f4": "f4",
        "f8": "f8",
        "uint8": "u1",
        "uint16": "u2",
        "uint32": "u4",
        "uint64": "u8",
        "int8": "i1",
        "int16": "i2",
        "int32": "i4",
        "int64": "i8",
        "float16": "f2",
        "float32": "f4",
        "float64": "f8",
        "half": "f2",
        "single": "f4",
        "double": "f8",
    }
    code = aliases.get(rest, rest)
    return np.dtype(f"{endian}{code}")


def _linear_chunk_index(indices: tuple, chunk_grid: tuple) -> int:
    """C-order linear index from a per-axis 0-based tuple, returned 1-based."""
    linear = 0
    n = len(chunk_grid)
    for a, idx0 in enumerate(indices):
        stride = 1
        for b in range(a + 1, n):
            stride *= chunk_grid[b]
        linear += idx0 * stride
    return linear + 1


def _build_block_grid(
    fetcher,
    doc,
    shape,
    chunks,
    chunk_grid,
    dtype,
    fill,
    codec,
    stored,
    delayed,
    da,
    *,
    fallback_reader=None,
):
    """Recursively build a nested list of dask blocks matching chunk_grid.

    Chunk paths are resolved LAZILY, inside each delayed task, through
    the shared :class:`_ChunkFetcher`. That is what makes the reader
    stream on a cloud-backed session: nothing is fetched until dask asks
    for a specific block, and each block goes through fetcher threads
    that own their own session handle (dodging DID's thread-owned
    SQLite connection).

    STORED (a set of ``chunk.bin_#`` names, or None) short-circuits the
    fetcher for chunks the level document doesn't list. On a sparse
    volume, empty tiles are one hash lookup and a ``np.full`` -- no
    network call at all. None means the level document has no file
    list, and the reader falls back to attempting every position.

    ``fallback_reader`` swaps the delayed body from
    :func:`_read_chunk_from_fetcher` to a wrapper that shows
    coarser-level data (upsampled) when the fine chunk is not on disk
    yet, so unfinished tiles do not draw as black holes. Its signature
    is ``(fetcher, doc, filename, indices_tuple, chunks, block_shape,
    dtype, fill, codec)``; ``indices_tuple`` is the fine chunk's
    per-axis 0-based multi-index, which the wrapper needs to compute
    the covering coarse region.
    """

    def one_block(indices: tuple):
        idx_1 = _linear_chunk_index(indices, chunk_grid)
        # Edge blocks are smaller along one or more axes.
        block_shape = tuple(
            min(chunks[a], shape[a] - indices[a] * chunks[a]) for a in range(len(indices))
        )
        name = f"chunk.bin_{idx_1:d}"
        # Short-circuit missing chunks BEFORE they reach a dask task, so
        # sparse regions don't even schedule work.
        if stored is not None and name not in stored:
            d = delayed(_zero_block)(block_shape, dtype, fill)
        elif fallback_reader is not None:
            d = delayed(fallback_reader)(
                fetcher, doc, name, indices, chunks, block_shape, dtype, fill, codec
            )
        else:
            d = delayed(_read_chunk_from_fetcher)(
                fetcher, doc, name, chunks, block_shape, dtype, fill, codec
            )
        return da.from_delayed(d, shape=block_shape, dtype=dtype)

    def recurse(prefix: list) -> list:
        axis = len(prefix)
        if axis == len(chunk_grid):
            return one_block(tuple(prefix))
        return [recurse(prefix + [i]) for i in range(chunk_grid[axis])]

    return recurse([])


def _zero_block(block_shape, dtype, fill):
    """A missing-chunk block: fill_value at the true edge-block shape."""
    import numpy as np

    return np.full(block_shape, fill, dtype=dtype)


def _read_chunk_from_fetcher(fetcher, doc, filename, chunks_full, block_shape, dtype, fill, codec):
    """Resolve a chunk file through the fetcher, then decode + trim.

    Runs inside a dask delayed task and therefore may execute on any
    worker thread. All NDI database access goes through ``fetcher``,
    which owns its own thread(s) with their own session handle -- so
    the delayed body itself never touches the caller's session.

    A resolved path that has been evicted from the local cache between
    the memo check and the read is retried once with :meth:`forget`; a
    persistent miss falls through to fill_value rather than raising, so
    a torn cache never poisons the whole canvas.
    """
    import numpy as np

    path = fetcher.chunkPath(doc, filename)
    n_expected = int(np.prod(chunks_full)) * dtype.itemsize
    if path is None:
        return np.full(block_shape, fill, dtype=dtype)
    try:
        raw = _readAll(path)
    except OSError:
        fetcher.forget(doc, filename)
        path = fetcher.chunkPath(doc, filename)
        if path is None:
            return np.full(block_shape, fill, dtype=dtype)
        try:
            raw = _readAll(path)
        except OSError:
            return np.full(block_shape, fill, dtype=dtype)

    if codec == "blosc-zstd":
        from numcodecs import Blosc

        raw = Blosc().decode(raw)

    if len(raw) < n_expected:
        raw = raw + b"\x00" * (n_expected - len(raw))
    arr = np.frombuffer(raw[:n_expected], dtype=dtype).reshape(chunks_full)
    if block_shape != chunks_full:
        arr = arr[tuple(slice(0, s) for s in block_shape)]
    return arr


def _readAll(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# Colorblind-friendly default palette for napari image layers, one
# colour per channel. Green/magenta first is the standard biology
# "safe pair" -- distinguishable under every common form of colour
# blindness -- and the rest extend the palette while keeping every
# adjacent pair distinguishable. Higher indices are assumed to be
# less common; the palette is padded with 'gray' if a fixture ever
# ships more than seven channels.
DEFAULT_CHANNEL_PALETTE: tuple[str, ...] = (
    "green",
    "magenta",
    "cyan",
    "yellow",
    "blue",
    "red",
    "gray",
)


def _defaultContrastLimits(pyramid_props: dict, dtype) -> tuple[float, float]:
    """The ``contrast_limits`` napari should open the layer with.

    Prefers the pyramid document's declared ``value_range`` (a pair of
    numbers written when the pyramid was built and typically covering
    the observed dynamic range); falls back to the dtype's full range
    for integer types and (0, 1) for float. Never samples the data,
    because sampling is what this function exists to avoid.
    """
    import numpy as np

    declared = pyramid_props.get("value_range")
    if isinstance(declared, (list, tuple)) and len(declared) == 2:
        try:
            lo, hi = float(declared[0]), float(declared[1])
            if hi > lo:
                return (lo, hi)
        except (TypeError, ValueError):
            pass

    d = np.dtype(dtype)
    if np.issubdtype(d, np.integer):
        info = np.iinfo(d)
        return (float(info.min), float(info.max))
    return (0.0, 1.0)


def defaultChannelColors(n_channels: int) -> list[str]:
    """Return the first ``n_channels`` napari colormap names from the
    default palette. Any request beyond the palette length is padded
    with the last colour ('gray')."""
    palette = list(DEFAULT_CHANNEL_PALETTE)
    if n_channels <= len(palette):
        return palette[:n_channels]
    return palette + [palette[-1]] * (n_channels - len(palette))


def layerSpec(
    session: Any,
    pyramid_doc: Any,
    channel: int | None = None,
    name: str | None = None,
    reduction: str | None = None,
    workers: int | None = None,
) -> tuple[list[dict], _ChunkFetcher]:
    """Return ``(specs, fetcher)`` where SPECS is a list of ``add_image``
    kwargs -- one per channel (or one total when the pyramid has no
    channel axis).

    Each ``spec['data']`` is a list of dask arrays (one per multiscale
    level), 3D (Z, Y, X) with the channel dimension stripped. Napari
    treats each list as a multiscale ladder for that channel's layer.

    Why one layer per channel, built ourselves, instead of a single
    ``add_image(channel_axis=...)`` call? Napari 0.5's channel_axis
    interacts badly with a list-of-multiscale-arrays: it splits the
    outer list along the channel axis of the FIRST array, drops
    multiscale on each per-channel layer, and registers a single-
    level layer at the finest resolution. The caller's log then shows
    ``n_levels=1 shape=[Z, Y, X]`` even though ``multiscale=True`` is
    on, and napari asks for a viewport-sized handful of level-0
    chunks -- an all-fill_value corner of a 121k-tile volume, which
    auto-contrasts to zero. Splitting the channel axis ourselves and
    passing per-channel multiscale lists side-steps that bug.

    ``fetcher`` is the :class:`_ChunkFetcher` backing the delayed
    reads. It is already held alive by the block closures, so the
    caller doesn't strictly need to hold it, but exposing it lets a
    viewer call ``fetcher.warm()`` before the first pan (so the
    one-off session-open cost lands while napari's window is
    opening) and ``fetcher.close()`` on teardown.

    Channel names come from the pyramid's ``channel_names`` field
    (comma-separated when present) and fall back to ``Ch1``, ``Ch2``,
    ...; colormaps come from :func:`defaultChannelColors`.
    """
    arrays, fetcher = levelArrays(
        session, pyramid_doc, channel=channel, reduction=reduction, workers=workers
    )
    scale, translate = worldTransform(session, pyramid_doc)

    p = pyramid_doc.document_properties["lightsheetZarrPyramid"]
    axes_order = str(p.get("axes_order", "")).lower()
    base_name = name
    if base_name is None:
        base_name = p.get("label") or p.get("pyramid_name") or "lightsheet zarr"

    # Contrast limits: default is None (let napari auto-detect by
    # sampling the coarsest level). Napari's genepyramid viewer works
    # under exactly this policy -- the auto-detect on a small 2D
    # coarsest level is the "drawing the overview" stage its progress
    # bar names. For lightsheet 3D the same policy reads ~a few
    # hundred coarsest-level tiles, most of which are locally cached
    # after ingest.
    #
    # NDI_LIGHTSHEET_CONTRAST_LIMITS=pin restores the previous
    # behaviour: pin contrast to the pyramid's value_range or the
    # dtype full range so napari does no sampling at all. That path
    # was added when we thought the auto-detect was the hang; it
    # turned out to also short-circuit napari's slice-then-loaded
    # transition on a multiscale layer (loaded stayed False forever,
    # channel spinner stuck on). Pinning is now the diagnostic knob,
    # not the default.
    if arrays and _env_true("NDI_LIGHTSHEET_CONTRAST_LIMITS"):
        contrast_limits = _defaultContrastLimits(p, arrays[0].dtype)
    else:
        contrast_limits = None

    c_index = axes_order.find("c") if axes_order else -1
    if c_index < 0 or not arrays:
        spec = {
            "data": arrays,
            "multiscale": True,
            "name": base_name,
            "scale": scale or None,
            "translate": translate or None,
            "contrast_limits": contrast_limits,
        }
        return [spec], fetcher

    n_channels = int(arrays[0].shape[c_index])
    names = _channelNames(p, n_channels, base_name)
    colors = defaultChannelColors(n_channels)

    # World transform axes drop the channel axis: napari's `scale` /
    # `translate` on a multiscale image describe the FINEST level in
    # world coordinates, and channel is not a world axis.
    spatial_scale = _dropAxis(scale, c_index) if scale else None
    spatial_trans = _dropAxis(translate, c_index) if translate else None

    # Build one multiscale spec per channel by slicing each level
    # array on c_index. dask.take is lazy: no fetches happen here,
    # only a graph rewrite that says "block[c] instead of block[all]".
    import dask.array as da

    # Default is single-level (only the coarsest, as a plain non-
    # multiscale layer). Napari 0.5's multiscale slicer has been
    # observed to never mark layer.loaded=True on a lazy cloud-backed
    # 3D multiscale pyramid: the channel-list spinner spins forever
    # and nothing draws. Single-level takes the multiscale slicer out
    # of the loop entirely; the layer draws, then a magicgui panel
    # lets the user swap between levels manually (see
    # :func:`_attach_level_selector` in viewer.py).
    #
    # NDI_LIGHTSHEET_MULTISCALE=1 opts back into the multiscale path
    # for anyone testing whether the napari-side bug has been fixed
    # or for a data shape that does not hit it.
    single_level = not _env_true("NDI_LIGHTSHEET_MULTISCALE")

    # Build per-channel arrays once; each is a list of one 3D lazy
    # dask array per level. The level dropdown swaps between the
    # elements at runtime.
    per_channel_levels: list[list[Any]] = []
    for c in range(n_channels):
        per_channel_levels.append([da.take(a, indices=c, axis=c_index) for a in arrays])

    # Per-level scales, so that the level dropdown can update
    # layer.scale and keep world coordinates locked when it swaps
    # data. Each level document records its own voxel_size (finest to
    # coarsest); we drop the channel entry so it matches the 3D
    # per-channel array shape napari sees.
    level_docs_ordered = levelDocs(session, pyramid_doc, reduction=reduction)
    per_level_scale: list[list[float] | None] = []
    for doc in level_docs_ordered:
        lvl_props = doc.document_properties["lightsheetZarrLevel"]
        vs = lvl_props.get("voxel_size")
        if isinstance(vs, list) and len(vs) > c_index:
            per_level_scale.append(_dropAxis([float(v) for v in vs], c_index))
        else:
            per_level_scale.append(None)

    # Additive blending across channels: napari's default is
    # "translucent" so a later channel simply covers the earlier one,
    # which for two-channel fluorescence gives a magenta or green
    # canvas but never the overlaid picture the user actually wants.
    # "additive" makes colors sum; this is how fluorescence viewers
    # composite channels everywhere else.
    blending = "additive" if n_channels > 1 else "translucent"

    specs: list[dict] = []
    for c in range(n_channels):
        if single_level:
            # Coarsest level only, as a plain (non-multiscale) layer.
            # Initial scale is the coarsest level's own voxel size,
            # not the finest -- otherwise napari places the coarsest
            # pixels at level-0 world coordinates and the image
            # jumps as the user swaps levels.
            coarsest_scale = per_level_scale[-1] or spatial_scale
            specs.append(
                {
                    "data": per_channel_levels[c][-1],
                    "multiscale": False,
                    "name": names[c],
                    "colormap": colors[c],
                    "blending": blending,
                    "contrast_limits": contrast_limits,
                    "scale": coarsest_scale or None,
                    "translate": spatial_trans or None,
                    # Kept on the spec so openPyramid can attach the
                    # level selector without recomputing arrays. Not
                    # a napari.add_image kwarg; caller pops before
                    # calling add_image.
                    "_ndi_level_arrays": per_channel_levels[c],
                    "_ndi_level_scales": per_level_scale,
                }
            )
        else:
            specs.append(
                {
                    "_ndi_level_scales": per_level_scale,
                    "data": per_channel_levels[c],
                    "multiscale": True,
                    "name": names[c],
                    "colormap": colors[c],
                    "blending": blending,
                    "contrast_limits": contrast_limits,
                    "scale": spatial_scale or None,
                    "translate": spatial_trans or None,
                    "_ndi_level_arrays": per_channel_levels[c],
                }
            )
    return specs, fetcher


def _env_true(name: str) -> bool:
    val = os.environ.get(name, "").strip().lower()
    return val not in ("", "0", "false", "no")


def _channelNames(pyramid_props: dict, n_channels: int, base_name: str) -> list[str]:
    """Split the pyramid doc's comma-separated channel_names field into a
    list. Missing / short / empty entries fall back to 'Ch1', 'Ch2', ...
    Each returned name is prefixed with the layer's base_name so the
    napari layer panel disambiguates two pyramids opened side by side.
    """
    raw = str(pyramid_props.get("channel_names", "") or "").strip()
    if raw:
        parts = [s.strip() for s in raw.split(",")]
    else:
        parts = []
    out: list[str] = []
    for i in range(n_channels):
        label = parts[i] if i < len(parts) and parts[i] else f"Ch{i + 1}"
        out.append(f"{base_name} {label}" if base_name else label)
    return out


def _dropAxis(values: list, axis_index: int) -> list:
    """Return VALUES with the entry at AXIS_INDEX removed. Silent no-op
    when the list is empty or the index is out of range so the caller
    can defend against a partially-populated pyramid document."""
    if not values or axis_index < 0 or axis_index >= len(values):
        return list(values) if values else []
    out = list(values)
    del out[axis_index]
    return out


# All chunk fetching now goes through _ChunkFetcher.chunkPath, which
# owns its own thread(s) with re-opened session handles. The old
# _fetch_chunk (main-thread eager resolver) is gone.
