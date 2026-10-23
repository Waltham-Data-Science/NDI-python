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

import heapq
import itertools
import os
import threading
import time
from typing import Any

from ndi.cloud.batch_signed_url import BatchScopeUnreachable


class StaleChunkRead(Exception):
    """A blocking chunk read was released because the view moved on.

    napari computes slices on ONE thread, so a slice for a view the user
    has already zoomed past holds up the slice for where they stopped
    until every one of its tiles has arrived. When the viewer reports
    (:meth:`_ChunkFetcher.setView`) that a waiting chunk is no longer in
    view, the read raises this instead of waiting. The fetch itself is
    NOT cancelled: it stays queued at low priority and lands in the
    local cache, so zooming back costs nothing.

    Raised, not answered with fill_value: napari's opportunistic dask
    cache would keep a fill block under the chunk's task key, and the
    region would stay blank after the real data arrived.
    """


# Returned by _ChunkFetcher._resolveDirect when the session-free path cannot
# answer (no manifest on disk yet, no cloud location, not a series member) and
# the caller should go through the session's database_openbinarydoc instead.
_FALLBACK = object()


class _Job:
    """One queued or running chunk fetch, shared by everyone waiting on it."""

    __slots__ = ("key", "doc", "filename", "started", "done", "path", "exc", "callbacks")

    def __init__(self, key, doc, filename):
        self.key = key
        self.doc = doc
        self.filename = filename
        self.started = False
        self.done = threading.Event()
        self.path: str | None = None
        self.exc: BaseException | None = None
        self.callbacks: list = []


class _TileTiming:
    """Where each tile's time goes, printed as one line per burst of reads.

    Every chunk napari reads passes through :func:`_read_chunk_from_fetcher`,
    which reports four phases here: finding the chunk's local path (a memo
    hit, or a trip through the fetcher queue -- which also covers a disk
    lookup or a cloud download), reading the bytes, decoding them, and the
    whole tile. Once a burst of reads goes quiet, or every few seconds
    during a long one, one ``[lightsheet] tiles:`` line goes to stderr.

    ``span`` is the wall time from the first tile starting to the last one
    finishing. If span is much larger than the per-tile times can explain,
    the time is going somewhere other than our reader (dask scheduling,
    napari). ``NDI_LIGHTSHEET_TIMING=0`` turns the lines off.
    """

    _QUIET_S = 0.5  # a burst ends after this long with no tile finishing
    _MAX_S = 5.0  # a long burst still reports this often

    def __init__(self, fetcher):
        self._fetcher = fetcher
        self._lock = threading.Lock()
        self._on = os.environ.get("NDI_LIGHTSHEET_TIMING", "1").strip().lower() not in (
            "0",
            "false",
            "off",
        )
        self._reset()
        self._timer = None

    def _reset(self):
        self.n = 0
        self.memo = 0
        self.queued = 0
        self.queued_s = 0.0
        self.queued_max = 0.0
        self.missing = 0
        self.read_s = 0.0
        self.read_bytes = 0
        self.decode_s = 0.0
        self.tile_s = 0.0
        self.tile_max = 0.0
        self.first = None
        self.last = None
        self.worker_base = self._workerCounts()

    def _workerCounts(self):
        f = self._fetcher
        return (
            getattr(f, "_direct_hits", 0),
            getattr(f, "_direct_fetches", 0),
            getattr(f, "_fallbacks", 0),
            getattr(f, "_stale_released", 0),
        )

    def record(self, t0, memo_hit, path_s, found, read_s, nbytes, decode_s):
        if not self._on:
            return
        now = time.monotonic()
        with self._lock:
            if self.first is None:
                self.first = t0
            self.last = now
            self.n += 1
            if memo_hit:
                self.memo += 1
            else:
                self.queued += 1
                self.queued_s += path_s
                self.queued_max = max(self.queued_max, path_s)
            if not found:
                self.missing += 1
            self.read_s += read_s
            self.read_bytes += nbytes
            self.decode_s += decode_s
            tile = now - t0
            self.tile_s += tile
            self.tile_max = max(self.tile_max, tile)
            if now - self.first >= self._MAX_S:
                line = self._lineLocked()
            else:
                line = None
                self._armLocked()
        if line:
            _printTiming(line)

    def _armLocked(self):
        # One quiet-period timer at a time; it re-checks on firing.
        if self._timer is None:
            self._timer = threading.Timer(self._QUIET_S, self._quiet)
            self._timer.daemon = True
            self._timer.start()

    def _quiet(self):
        with self._lock:
            self._timer = None
            if self.n == 0:
                return
            if time.monotonic() - self.last < self._QUIET_S:
                self._armLocked()
                return
            line = self._lineLocked()
        _printTiming(line)

    def _lineLocked(self) -> str:
        n = self.n
        hits, fetches, fallbacks, stale = (
            a - b for a, b in zip(self._workerCounts(), self.worker_base)
        )
        span = self.last - self.first
        mb = self.read_bytes / 1e6
        rate = f", {mb / self.read_s:.0f} MB/s" if self.read_s > 0 else ""
        q_mean = 1000.0 * self.queued_s / self.queued if self.queued else 0.0
        line = (
            f"tiles: {n} in {span:.2f}s span | "
            f"path: {self.memo} memo, {self.queued} via queue "
            f"(mean {q_mean:.1f}ms, max {1000.0 * self.queued_max:.0f}ms; "
            f"workers did {hits} disk hits, {fetches} cloud fetches, "
            f"{fallbacks} via session, {stale} stale) | "
            f"read {1000.0 * self.read_s / n:.1f}ms/tile ({mb:.1f} MB{rate}) | "
            f"decode {1000.0 * self.decode_s / n:.1f}ms/tile | "
            f"tile mean {1000.0 * self.tile_s / n:.1f}ms, max {1000.0 * self.tile_max:.0f}ms"
            + (f" | {self.missing} not found" if self.missing else "")
        )
        self._reset()
        return line


def _printTiming(line: str) -> None:
    import sys
    from datetime import datetime

    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{stamp} [lightsheet] {line}", file=sys.stderr, flush=True)


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

    This class is the middle ground: dedicated fetcher threads resolve
    chunks off the caller's thread. Delayed tasks call ``chunkPath(doc, name)``
    from whichever thread they run on; the fetcher dispatches through its
    pool and returns the resolved local path. Resolved paths are memoised
    per (doc_id, filename) so a re-render never reaches the fetch threads
    again -- a cached hit is one ``os.path.exists`` from any thread.

    SESSION-FREE MEMBER RESOLUTION. A chunk is a file series member, and
    resolving one needs no database at all: the level document is already
    in memory, its manifest names each member's uid, and DID's
    ``cached_path_for_uid`` finds a member on disk with no SQL (it is
    documented as safe from any thread). A member that is not on disk is
    fetched through NDI's cloud handler -- the same
    ``download_file_from_cloud`` DID itself would call, with the same
    context -- and lands in DID's file cache under its uid, exactly where
    ``open_doc`` would have put it. So workers are plain threads, and a
    worker only opens a session of its own (lazily, on first need) when a
    chunk has to go the long way: the manifest is not on disk yet, or the
    document records no cloud location. ``NDI_LIGHTSHEET_DIRECT=0`` turns
    the session-free path off.

    ``workers`` defaults to 1 here; the viewer passes
    :func:`_default_workers`. Cloud fetches are latency-bound, so many
    workers buy overlap, and with session-free resolution an extra worker
    costs one idle thread.
    """

    def __init__(self, session, workers: int = 1, max_workers: int | None = None):
        self._session = session
        self._owner = threading.get_ident()
        self._reopen = self._reopener(session)
        # max_workers threads are started; at most `workers` of them fetch
        # at once. The limit can change while the viewer runs (setWorkers):
        # threads past it just wait, so lowering it never interrupts a
        # fetch and raising it takes effect on the next job.
        self._limit = max(1, int(workers))
        self._workers = max(self._limit, int(max_workers or 0))
        self._running = 0
        self._local = threading.local()
        self._lock = threading.Lock()
        self._paths: dict[tuple[str, str], str] = {}
        # Work queue. A heap of (tier, -seq, job): tier 0 is a chunk in
        # the current view (see setView), tier 1 everything else, and
        # within a tier the NEWEST request goes first -- the user is
        # looking at what they asked for last, not at the levels they
        # zoomed through on the way. One _Job per chunk key, shared by
        # every waiter and callback, so a chunk is never fetched twice.
        # A re-request pushes a fresh entry; stale heap entries for a
        # started job are skipped on pop.
        self._cv = threading.Condition()
        self._heap: list = []
        self._jobs: dict[tuple[str, str], _Job] = {}
        self._seq = itertools.count()
        self._threads: list[threading.Thread] = []
        self._threads_ready = 0
        self._closed = False
        # The current view's chunk keys, set from the viewer's main-
        # thread poll. None means unknown: nothing is prioritised and
        # no read is ever released as stale.
        self._view_keys: frozenset | None = None
        self._view_time = 0.0
        # Chunks of these docs are never released as stale: napari's
        # auto-contrast samples the coarsest level at launch, whatever
        # the view is.
        self._never_stale_docs: set[str] = set()
        self._stale_released = 0
        # Per-fetch timing bucketed by outcome. Set by _resolve on every
        # call, including memo hits, so a caller can tell whether a
        # slow tile is "cloud is slow" vs "local cache lookup is slow"
        # vs "memo miss forces a re-fetch".
        self._stats_lock = threading.Lock()
        self._resolve_times_cache: list[float] = []
        self._resolve_times_fetch: list[float] = []
        self._resolve_none: int = 0
        # Systemic failure of the batch signed-URL path. Once one background
        # prefetch surfaces a BatchScopeUnreachable, every chunk in the
        # affected scope will fail identically -- and returning fill_value
        # for all of them would silently render the whole canvas as zeros,
        # exactly the pattern the loader was written to prevent. We hold
        # the first raise here so subsequent lookups (chunkPathIfCached,
        # chunkPath) can surface it instead of hiding behind the fallback.
        # See Waltham-Data-Science/NDI-python#322 and the strict-mode
        # rationale in ndi.cloud.batch_signed_url.BatchScopeUnreachable.
        self._unreachable_exc: BatchScopeUnreachable | None = None
        # Session-free member resolution (see the class docstring). The
        # file directory is read once, here, on the owner thread; the
        # per-document and per-series caches hold only in-memory data
        # and manifest uid lists.
        self._direct = os.environ.get("NDI_LIGHTSHEET_DIRECT", "1").strip().lower() not in (
            "0",
            "false",
            "off",
        )
        self._file_dir = self._fileDir(session)
        self._did_docs: dict[str, Any] = {}
        self._series: dict[tuple[str, str], tuple] = {}
        self._direct_hits = 0
        self._direct_fetches = 0
        self._fallbacks = 0
        self.timing = _TileTiming(self)

    @staticmethod
    def _fileDir(session) -> str | None:
        """DID's per-database file directory, or None if not reachable.

        A session exposes its database directly; a dataset holds one
        through its inner session.
        """
        for holder in (session, getattr(session, "_session", None)):
            database = getattr(holder, "database", None) if holder is not None else None
            try:
                path = database.binary_path if database is not None else None
            except Exception:  # noqa: BLE001 - not DID-backed
                path = None
            if path:
                return str(path)
        return None

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

    def _ensureWorkers(self) -> bool:
        """Start the fetcher threads once. False when the session cannot
        be reopened for another thread (then everything runs inline)."""
        if self._reopen is None and not self._direct:
            return False
        with self._cv:
            if self._threads or self._closed:
                return not self._closed
            for i in range(self._workers):
                t = threading.Thread(
                    target=self._workerLoop,
                    name=f"ndi-lightsheet_{i}",
                    daemon=True,
                )
                self._threads.append(t)
                t.start()
        return True

    def _workerLoop(self) -> None:
        # No session here: most chunks resolve without one, and a worker
        # that needs one opens it on first use (_threadSession).
        with self._cv:
            self._threads_ready += 1
            self._cv.notify_all()
        while True:
            with self._cv:
                job = None
                while job is None:
                    while (not self._heap or self._running >= self._limit) and not self._closed:
                        self._cv.wait()
                    if self._closed:
                        return
                    tier, nseq, cand = heapq.heappop(self._heap)
                    if cand.started:
                        continue
                    if tier == 0 and (self._view_keys is None or cand.key not in self._view_keys):
                        # Was in view when queued, is not any more.
                        heapq.heappush(self._heap, (1, nseq, cand))
                        continue
                    cand.started = True
                    self._running += 1
                    job = cand
            self._run(job)

    def _run(self, job: _Job) -> None:
        """Resolve one job on this thread and settle everyone waiting."""
        path = None
        try:
            path = self._resolve(job.doc, job.filename)
        except BatchScopeUnreachable as exc:
            # Systemic scope failure. Remember it so the next
            # chunkPathIfCached / chunkPath surfaces it instead of
            # letting the upsample fallback quietly return a canvas
            # full of zeros.
            with self._lock:
                if self._unreachable_exc is None:
                    self._unreachable_exc = exc
            job.exc = exc
        except BaseException as exc:  # noqa: BLE001 - handed to the waiter
            job.exc = exc
        if path is not None:
            with self._lock:
                self._paths[job.key] = path
        with self._cv:
            self._jobs.pop(job.key, None)
            callbacks, job.callbacks = job.callbacks, []
            self._running -= 1
            self._cv.notify_all()
        job.path = path
        job.done.set()
        for cb in callbacks:
            try:
                cb(path)
            except Exception:  # noqa: BLE001 - a bad callback is not fatal
                pass

    def _enqueue(self, doc, filename, on_complete=None) -> _Job:
        """Queue a fetch (or bump an already-queued one to newest)."""
        key = (getattr(doc, "id", str(doc)), filename)
        with self._cv:
            job = self._jobs.get(key)
            if job is None:
                job = _Job(key, doc, filename)
                self._jobs[key] = job
            if on_complete is not None:
                job.callbacks.append(on_complete)
            if not job.started:
                tier = 0 if self._view_keys is not None and key in self._view_keys else 1
                heapq.heappush(self._heap, (tier, -next(self._seq), job))
                self._cv.notify()
        return job

    @property
    def workerLimit(self) -> int:
        """How many chunks may be fetched at once right now."""
        return self._limit

    @property
    def maxWorkers(self) -> int:
        """The most :meth:`setWorkers` will allow: the threads started."""
        return self._workers

    def setWorkers(self, n: int) -> int:
        """Change how many chunks are fetched at once; returns the new limit.

        Clamped to 1..:attr:`maxWorkers`. Takes effect immediately for
        queued work; fetches already running finish undisturbed.
        """
        with self._cv:
            self._limit = max(1, min(int(n), self._workers))
            self._cv.notify_all()
            return self._limit

    def warm(self) -> None:
        """Build the session handles now, off the calling thread.

        Optional; worth calling right after ``napari.Viewer()`` so the
        one-off session-open cost lands while the user is staring at an
        empty canvas rather than at the first pan.
        """
        if not self._ensureWorkers():
            return
        with self._cv:
            while self._threads_ready < self._workers and not self._closed:
                self._cv.wait()

    def setView(self, keys, never_stale_doc_ids=None) -> None:
        """Tell the fetcher which chunks the current view needs.

        KEYS maps ``(doc_id, filename)`` to the level document (None:
        the view is unknown). Chunks in view jump the queue -- and are
        queued now if nobody has asked yet, so they are already on the
        way while napari is still finishing an older slice. A blocking
        read for a chunk that has dropped OUT of view is released with
        :class:`StaleChunkRead`; its fetch stays queued at low priority.
        """
        with self._cv:
            if never_stale_doc_ids is not None:
                self._never_stale_docs = set(never_stale_doc_ids)
            if keys is None:
                self._view_keys = None
                self._cv.notify_all()
                return
            self._view_keys = frozenset(keys)
            self._view_time = time.monotonic()
            # Re-rank what is queued: anything now in view to tier 0.
            for key in self._view_keys:
                job = self._jobs.get(key)
                if job is not None and not job.started:
                    heapq.heappush(self._heap, (0, -next(self._seq), job))
            self._cv.notify_all()
        # Queue what the view needs and nobody has asked for yet.
        if not self._threads and not self._ensureWorkers():
            return
        for key, doc in keys.items():
            known = self._paths.get(key)
            if known is not None and os.path.exists(known):
                continue
            self._enqueue(doc, key[1])

    def _isStale(self, job: _Job, since: float) -> bool:
        view = self._view_keys
        return (
            view is not None
            and self._view_time > since
            and job.key not in view
            and job.key[0] not in self._never_stale_docs
        )

    def staleReleased(self) -> int:
        """How many blocking reads were released as stale so far."""
        return self._stale_released

    def _threadSession(self):
        """The session this thread may use, opening one on first need.

        The owner thread uses the caller's session. A worker reopens its
        own the first time a chunk cannot be resolved session-free. A
        session that cannot be reopened (no path) is used as-is, as before:
        that is the directory-less case the inline fallback serves.
        """
        if threading.get_ident() == self._owner or self._reopen is None:
            return self._session
        s = getattr(self._local, "session", None)
        if s is None:
            s = self._reopen()
            self._local.session = s
        return s

    def _resolve(self, doc, filename) -> str | None:
        import time as _time

        t0 = _time.monotonic()
        if self._direct:
            try:
                direct = self._resolveDirect(doc, filename)
            except BatchScopeUnreachable:
                with self._stats_lock:
                    self._resolve_none += 1
                raise
            except Exception as exc:  # noqa: BLE001 - same contract as below
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
            if direct is not _FALLBACK:
                self._recordResolve(filename, _time.monotonic() - t0, direct)
                return direct
            with self._stats_lock:
                self._fallbacks += 1
        try:
            s = self._threadSession()
            fh = s.database_openbinarydoc(doc, filename)
        except BatchScopeUnreachable:
            # A systemic failure of the batch signed-URL path is not a
            # transient blip we can paper over with fill_value: every
            # chunk in the scope will fail identically, and swallowing
            # this one turns the whole canvas into silent zeros -- the
            # exact "silent fetch failure" pattern this loader was
            # written to prevent. Propagate so callers (viewer, dask
            # compute, integration test) see the actual cause. See
            # Waltham-Data-Science/NDI-python#322 and the strict-mode
            # rationale on BatchScopeUnreachable itself.
            with self._stats_lock:
                self._resolve_none += 1
            raise
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
            path = str(path) if path else None
            self._recordResolve(filename, _time.monotonic() - t0, path)
            return path
        finally:
            try:
                s.database_closebinarydoc(fh)
            except Exception:
                pass

    def _recordResolve(self, filename, dt: float, path) -> None:
        """Bucket one resolve's time; under debug, say what a fetch cost.

        database_openbinarydoc and the session-free path both have two
        happy paths: a local hit (microseconds) and a cloud fetch (tens of
        ms to seconds). 50 ms is comfortably above local disk latency and
        well under any credible cloud round trip; a threshold keeps the
        classifier independent of either path's internals.
        """
        with self._stats_lock:
            if dt < 0.05:
                self._resolve_times_cache.append(dt)
            else:
                self._resolve_times_fetch.append(dt)
        if dt >= 0.05 and os.environ.get("NDI_LIGHTSHEET_DEBUG"):
            import sys

            from ndi.cloud.filehandler import lastFetchTiming

            t = lastFetchTiming()
            if t:
                size = t.get("bytes", 0) or 0
                xfer = t.get("transfer_s", 0.0) or 0.0
                rate = f", {size / xfer / 1e6:.1f} MB/s" if xfer > 0 and size else ""
                detail = (
                    f"sign {t.get('sign_s', 0.0):.2f}s "
                    f"({'batch' if t.get('batch') else 'per-file'}), "
                    f"transfer {xfer:.2f}s, {size / 1e6:.2f} MB{rate}"
                )
            else:
                detail = "no cloud timing recorded"
            print(
                f"[lightsheet] fetched {filename} in {dt:.2f}s: {detail} "
                f"(thread {threading.current_thread().name})",
                file=sys.stderr,
                flush=True,
            )

    # ------------------------------------------------------------ direct path

    def _resolveDirect(self, doc, filename):
        """Resolve a series member with no database, or return _FALLBACK.

        Local first, through DID's ``cached_path_for_uid`` (global file
        cache, then this database's file directory -- the order
        ``open_doc`` uses). A member that is not on disk is fetched through
        the cloud handler into DID's file cache. Returns the local path,
        None for a member the manifest records as absent (sparse; what
        ``open_doc`` reports as NoSuchMember), or _FALLBACK when this path
        cannot answer and the session must.
        """
        from did.file import cached_path_for_uid

        found = self._seriesFor(doc, filename)
        if found is None:
            return _FALLBACK
        stem, index, uids, manifest_location, doc_id = found
        if index > len(uids) or not uids[index - 1]:
            return None
        member_uid = str(uids[index - 1])
        roots = [self._file_dir] if self._file_dir else []
        local = cached_path_for_uid(member_uid, additional_roots=roots)
        if local:
            with self._stats_lock:
                self._direct_hits += 1
            return str(local)
        if not manifest_location:
            return _FALLBACK
        path = self._fetchMember(doc_id, filename, stem, member_uid, manifest_location)
        with self._stats_lock:
            self._direct_fetches += 1
        return path

    def _seriesFor(self, doc, filename):
        """(stem, index, member uids, manifest ndic location, doc id), or None.

        Reads only the document in memory and the manifest on disk. The
        manifest's uid list is read once per (document, series) and kept;
        a manifest that is not on disk yet is not remembered as missing,
        so once the session path has fetched it the next call finds it.
        """
        try:
            from did.document import Document as DIDDocument
            from did.file import cached_path_for_uid, read_series_manifest
        except ImportError:
            return None
        doc_id = getattr(doc, "id", None)
        if not doc_id:
            return None
        did_doc = self._did_docs.get(doc_id)
        if did_doc is None:
            props = getattr(doc, "document_properties", None)
            if not isinstance(props, dict):
                return None
            did_doc = DIDDocument(props)
            self._did_docs[doc_id] = did_doc
        stem, index = did_doc.series_member_of(filename)
        if not stem or index is None or index < 1:
            return None
        entry = self._series.get((doc_id, stem))
        if entry is None:
            roots = [self._file_dir] if self._file_dir else []
            manifest_path = None
            for uid in did_doc.file_uids(stem):
                manifest_path = cached_path_for_uid(uid, additional_roots=roots)
                if manifest_path:
                    break
            if not manifest_path:
                return None
            try:
                uids = [
                    str(u) if u else "" for u in read_series_manifest(manifest_path).get("uids", [])
                ]
            except Exception:  # noqa: BLE001 - let the session path report it
                return None
            entry = (uids, _ndicLocation(did_doc.document_properties, stem))
            self._series[(doc_id, stem)] = entry
        uids, location = entry
        return stem, index, uids, location, doc_id

    def _fetchMember(self, doc_id, filename, stem, member_uid, manifest_location) -> str:
        """Fetch one member through the cloud handler into DID's file cache.

        The same call DID's ``open_doc`` makes -- the manifest's location
        as the source and the member in the context, so the handler fetches
        the member's own object through the batch signed-URL cache -- into
        a unique scratch file in DID's temp folder, then moved into the
        global file cache under the member's uid. A cache that cannot take
        it (unwritable, or a uid of the wrong width) leaves the file in
        this database's file directory instead; either way
        ``cached_path_for_uid`` finds it next time, in this process or the
        next, and so does DID.
        """
        import tempfile

        from did.common import PathConstants

        from ndi.cloud.filehandler import download_file_from_cloud

        temp_dir = PathConstants().temppath
        os.makedirs(temp_dir, exist_ok=True)
        fd, scratch = tempfile.mkstemp(dir=temp_dir, prefix=f"{member_uid}.", suffix=".part")
        os.close(fd)
        os.remove(scratch)
        try:
            download_file_from_cloud(
                scratch,
                manifest_location,
                {
                    "documentId": doc_id,
                    "filename": filename,
                    "seriesName": stem,
                    "uid": member_uid,
                    "mode": "open",
                },
            )
            if not os.path.isfile(scratch):
                raise FileNotFoundError(
                    f"the cloud handler produced no file for {filename} (uid {member_uid})"
                )
            return self._keepFetched(scratch, member_uid)
        except BaseException:
            try:
                os.remove(scratch)
            except OSError:
                pass
            raise

    def _keepFetched(self, scratch: str, member_uid: str) -> str:
        """Move a fetched member to where cached_path_for_uid will find it."""
        import struct

        try:
            from did.common import get_cache

            cache = get_cache()
            if len(member_uid) == cache.file_name_characters:
                if cache.is_file(member_uid):
                    existing = cache.full_path(member_uid)
                    if os.path.isfile(existing):
                        # Another fetch of the same uid won the race; same bytes.
                        os.remove(scratch)
                        return existing
                    cache.remove_file(member_uid)
                cache.add_file(scratch, member_uid)
                if os.path.exists(scratch):
                    os.remove(scratch)
                return cache.full_path(member_uid)
        except (OSError, ValueError, struct.error):
            pass
        if self._file_dir:
            os.makedirs(self._file_dir, exist_ok=True)
            dest = os.path.join(self._file_dir, member_uid)
            os.replace(scratch, dest)
            return dest
        return scratch

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
            n_fallback = self._fallbacks
        return (
            f"resolves: {n_cache} cache-hits (mean {mean_cache_ms:.1f}ms), "
            f"{n_fetch} cloud-fetches (mean {mean_fetch_s:.2f}s, max "
            f"{max_fetch_s:.2f}s), {n_none} failures, "
            f"{self._stale_released} stale reads released, "
            f"{n_fallback} via a session ({self._limit} of {self._workers} workers)"
        )

    def reset_stats(self) -> None:
        with self._stats_lock:
            self._resolve_times_cache.clear()
            self._resolve_times_fetch.clear()
            self._resolve_none = 0
            self._direct_hits = 0
            self._direct_fetches = 0
            self._fallbacks = 0

    def chunkPath(self, doc, filename) -> str | None:
        """Resolve one chunk file to a local path, fetching it if remote.

        None when the chunk was never materialised (sparse) or when the
        underlying fetch raised.

        Memoised: once a path is known, subsequent lookups are one
        ``os.path.exists`` from any thread. Files can be evicted, so a
        stale hit that fails on read should be dropped with :meth:`forget`.
        """
        if self._unreachable_exc is not None:
            raise self._unreachable_exc
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

        Raises :class:`BatchScopeUnreachable` if a prior background
        prefetch established that the batch signed-URL path is dead
        for this fetcher. The upsample fallback would otherwise
        quietly return a zero block for every chunk in the affected
        scope; surfacing the exception here forces the actual cause
        out through ``.compute()``.
        """
        if self._unreachable_exc is not None:
            raise self._unreachable_exc
        key = (getattr(doc, "id", str(doc)), filename)
        known = self._paths.get(key)
        if known is not None and os.path.exists(known):
            return known
        return None

    def prefetchAsync(self, doc, filename, on_complete=None) -> None:
        """Kick off a background fetch of one chunk. Never blocks.

        The upsample-fallback reader returns coarse-upsampled data
        immediately for a chunk that is not on disk; this asks the
        fetcher threads to go fetch the real thing so a later re-slice
        can find it via :meth:`chunkPathIfCached`. On completion (or
        failure), ``on_complete`` is called with the resolved path
        or None -- callers use that to trigger a napari refresh so
        the user is not stuck looking at blurred data forever.

        De-duplicates by memo key: the same (doc, filename) already
        queued or already cached does not fetch a second time.
        Errors are absorbed; the reader will retry on the next
        re-slice and eventually get real data or a permanent
        fallback.
        """
        key = (getattr(doc, "id", str(doc)), filename)
        known = self._paths.get(key)
        if known is not None and os.path.exists(known):
            # Already cached -- fire the completion callback
            # synchronously so the caller can react uniformly whether
            # the answer was cheap or expensive.
            if on_complete is not None:
                try:
                    on_complete(known)
                except Exception:  # noqa: BLE001
                    pass
            return
        if not self._ensureWorkers():
            # No workers means this session cannot be reopened, and
            # the fetcher is single-threaded. Fall back to a blocking
            # resolve on the caller's thread -- it is the rare
            # directory-backed case and does not need async.
            try:
                path = self._resolve(doc, filename)
            except Exception:  # noqa: BLE001
                path = None
            if path is not None:
                with self._lock:
                    self._paths[key] = path
            if on_complete is not None:
                try:
                    on_complete(path)
                except Exception:  # noqa: BLE001
                    pass
            return
        self._enqueue(doc, filename, on_complete=on_complete)

    def _fetch(self, doc, filename) -> str | None:
        if threading.get_ident() == self._owner:
            return self._resolve(doc, filename)
        if not self._ensureWorkers():
            raise RuntimeError(
                f"Cannot fetch {filename!r} from thread "
                f"{threading.current_thread().name}: this session cannot be "
                f"reopened for another thread, and NDI's database may only "
                f"be used from the thread that opened it. Compute the ladder "
                f"with dask's synchronous scheduler, or pass a session that "
                f"exposes a path."
            )
        since = time.monotonic()
        job = self._enqueue(doc, filename)
        # Wait, but keep checking whether the view has moved on: a
        # slice for a view the user zoomed past must not hold up the
        # slice for where they stopped (napari slices on one thread).
        while not job.done.wait(0.1):
            if self._isStale(job, since):
                with self._lock:
                    self._stale_released += 1
                raise StaleChunkRead(f"{filename} left the view before it arrived")
        if job.exc is not None:
            raise job.exc
        return job.path

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._heap.clear()
            self._cv.notify_all()


_DEFAULT_WORKERS = 16

#: Threads started per fetcher, so the viewer can raise the limit live.
MAX_WORKERS = 64

#: The choices the viewer offers for tiles in flight.
WORKER_CHOICES = (8, 16, 32, 64)


def _default_workers() -> int:
    """Chunks fetched at once at launch; ``NDI_LIGHTSHEET_WORKERS`` overrides.

    16 by default. A cloud tile is seconds of waiting on the network and
    almost no CPU, so overlap pays -- until the line is full: on a
    100 Mb/s connection 32 tiles of a few MB each just share the same
    bandwidth and every one arrives later. The viewer can change it live
    (:meth:`_ChunkFetcher.setWorkers`).
    """
    try:
        n = int(os.environ.get("NDI_LIGHTSHEET_WORKERS", str(_DEFAULT_WORKERS)))
    except ValueError:
        return _DEFAULT_WORKERS
    return max(1, n)


def configureDaskPool(workers: int) -> int:
    """Size dask's thread pool for I/O-bound chunk reads; returns its size.

    napari computes slices through dask's threaded scheduler, whose pool
    defaults to one thread per CPU -- right for computation, wrong here:
    each chunk read mostly waits on the network, so the pool, not the
    fetcher, caps how many tiles are in flight. This sets the pool to at
    least ``workers`` threads (never fewer than the CPU count), process
    wide, so napari's reads can keep every fetcher worker busy.
    """
    from concurrent.futures import ThreadPoolExecutor

    import dask

    n = max(os.cpu_count() or 4, int(workers))
    dask.config.set(pool=ThreadPoolExecutor(n, thread_name_prefix="ndi-dask"))
    return n


def _ndicLocation(props: dict, name: str) -> str:
    """The ``ndic://`` location recorded for file ``name``, or ""."""
    from ndi.cloud.filehandler import NDIC_SCHEME

    files = props.get("files") if isinstance(props, dict) else None
    if not isinstance(files, dict):
        return ""
    file_info = files.get("file_info")
    infos = file_info if isinstance(file_info, list) else [file_info] if file_info else []
    for info in infos:
        if not isinstance(info, dict) or str(info.get("name", "")).lower() != name.lower():
            continue
        locations = info.get("locations")
        locs = locations if isinstance(locations, list) else [locations] if locations else []
        for loc in locs:
            where = loc.get("location", "") if isinstance(loc, dict) else ""
            if str(where).startswith(NDIC_SCHEME):
                return str(where)
    return ""


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

    from ndi.gui.app.lightsheetZarr import progress

    docs = levelDocs(session, pyramid_doc, reduction=reduction)
    if not docs:
        raise ValueError(
            f"pyramid {pyramid_doc.id!s} has no lightsheetZarrLevel children for "
            f"reduction={reduction!r}."
        )

    _ = channel  # single-channel narrowing lands with the magicgui panels

    limit = workers if workers is not None else _default_workers()
    fetcher = _ChunkFetcher(session, workers=limit, max_workers=max(limit, MAX_WORKERS))

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
    # Per-level chunk geometry, finest first (same order as ARRAYS).
    # The viewer reads this to work out which chunks the current view
    # needs, so it can say "37 of 120 tiles" rather than only how many
    # are in flight. Rides on the fetcher like the fallback context.
    level_meta: list[dict] = []
    fetcher._level_meta = level_meta  # type: ignore[attr-defined]
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

        level_meta.append(
            {
                "doc": doc,
                "axes": str(p.get("axes_order", "")).lower(),
                "chunks": chunks,
                "chunk_grid": chunk_grid,
                "stored": stored,
            }
        )

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
            arrays.append(
                _build_level_array(
                    fetcher,
                    doc,
                    shape,
                    chunks,
                    chunk_grid,
                    dtype,
                    fill,
                    codec,
                    stored,
                    da,
                    fallback_reader=fallback_reader,
                )
            )

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

    The closure has the signature ``_build_level_array`` expects for
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
    from ndi.gui.app.lightsheetZarr import progress

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


def _build_level_array(
    fetcher,
    doc,
    shape,
    chunks,
    chunk_grid,
    dtype,
    fill,
    codec,
    stored,
    da,
    *,
    fallback_reader=None,
):
    """One lazy dask array for a level, one block per chunk file.

    The whole level is ONE graph layer (``da.map_blocks`` with no input
    arrays; each block learns its chunk position from ``block_info``).
    An earlier version built one ``from_delayed`` array per chunk and
    joined them with ``da.block``: every chunk became its own graph
    layer, and dask walks every layer each time a slice is computed. A
    view of 16 cached chunks then cost ~1.4 s on a 16k-chunk level and
    ~26 s on a 131k-chunk one, against ~15 ms to read the 16 files --
    the cost grew with the size of the level, not of the view. A single
    layer costs only for the blocks a slice touches, and the level is
    built in microseconds rather than seconds.

    Chunk paths are resolved LAZILY, inside each block, through the
    shared :class:`_ChunkFetcher`. That is what makes the reader stream
    on a cloud-backed session: nothing is fetched until dask asks for a
    specific block, and each block goes through fetcher threads that own
    their own session handle (dodging DID's thread-owned SQLite
    connection).

    STORED (a set of ``chunk.bin_#`` names, or None) short-circuits the
    fetcher for chunks the level document doesn't list. On a sparse
    volume, empty tiles are one hash lookup and a ``np.full`` -- no
    network call at all. None means the level document has no file
    list, and the reader falls back to attempting every position.

    ``fallback_reader`` swaps the block body from
    :func:`_read_chunk_from_fetcher` to a wrapper that shows
    coarser-level data (upsampled) when the fine chunk is not on disk
    yet, so unfinished tiles do not draw as black holes. Its signature
    is ``(fetcher, doc, filename, indices_tuple, chunks, block_shape,
    dtype, fill, codec)``; ``indices_tuple`` is the fine chunk's
    per-axis 0-based multi-index, which the wrapper needs to compute
    the covering coarse region.
    """
    import numpy as np
    from dask.base import tokenize

    chunks = tuple(int(c) for c in chunks)
    chunk_grid = tuple(int(g) for g in chunk_grid)
    block_chunks = tuple(
        tuple(min(chunks[a], shape[a] - i * chunks[a]) for i in range(chunk_grid[a]))
        for a in range(len(chunk_grid))
    )

    def read_block(block_info=None):
        info = block_info[None]
        indices = tuple(int(i) for i in info["chunk-location"])
        block_shape = tuple(int(n) for n in info["chunk-shape"])
        name = f"chunk.bin_{_linear_chunk_index(indices, chunk_grid):d}"
        if stored is not None and name not in stored:
            return _zero_block(block_shape, dtype, fill)
        if fallback_reader is not None:
            return fallback_reader(
                fetcher, doc, name, indices, chunks, block_shape, dtype, fill, codec
            )
        return _read_chunk_from_fetcher(fetcher, doc, name, chunks, block_shape, dtype, fill, codec)

    # An explicit name: tokenizing the closure would hash the fetcher.
    # id(fetcher) keeps two viewers on the same level from sharing keys.
    token = tokenize(
        getattr(doc, "id", str(doc)), shape, chunks, str(dtype), fill, codec, id(fetcher)
    )
    return da.map_blocks(
        read_block,
        chunks=block_chunks,
        dtype=dtype,
        meta=np.empty((0,) * len(block_chunks), dtype=dtype),
        name=f"ndi-lightsheet-level-{token}",
    )


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

    t0 = time.monotonic()
    key = (getattr(doc, "id", str(doc)), filename)
    paths = getattr(fetcher, "_paths", None)
    memo_hit = paths is not None and key in paths
    path = fetcher.chunkPath(doc, filename)
    t_path = time.monotonic()
    n_expected = int(np.prod(chunks_full)) * dtype.itemsize
    timing = getattr(fetcher, "timing", None)
    if path is None:
        if timing is not None:
            timing.record(t0, memo_hit, t_path - t0, False, 0.0, 0, 0.0)
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
    t_read = time.monotonic()
    nbytes = len(raw)

    if codec == "blosc-zstd":
        from numcodecs import Blosc

        raw = Blosc().decode(raw)

    if len(raw) < n_expected:
        raw = raw + b"\x00" * (n_expected - len(raw))
    arr = np.frombuffer(raw[:n_expected], dtype=dtype).reshape(chunks_full)
    if block_shape != chunks_full:
        arr = arr[tuple(slice(0, s) for s in block_shape)]
    if timing is not None:
        timing.record(
            t0, memo_hit, t_path - t0, True, t_read - t_path, nbytes, time.monotonic() - t_read
        )
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

    # Default is multiscale: user A/B preferred this over single-level
    # because the transition between levels is smoother -- single-level
    # swaps layer.data under napari, which shows up as a short black
    # frame on every level change, while a native multiscale layer
    # just picks a finer level and refines. Both modes have been
    # observed to hit the same napari slicer wedge on this dataset
    # (vispy "QBasicTimer destroyed dispatcher" spam, no tile
    # requests), so single-level is not actually safer -- it just
    # looks janker when it does paint.
    #
    # NDI_LIGHTSHEET_SINGLE_LEVEL=1 opts back into the earlier
    # single-level + Resolution-picker mode for anyone who wants
    # the manual swap flow (or is debugging the multiscale slicer
    # bug on a different dataset shape).
    # NDI_LIGHTSHEET_ASYNC=0 is the escape hatch when the slicer
    # wedges: it blocks add_image until the first slice is on
    # screen, bypassing napari's async slicer entirely.
    single_level = _env_true("NDI_LIGHTSHEET_SINGLE_LEVEL")

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
