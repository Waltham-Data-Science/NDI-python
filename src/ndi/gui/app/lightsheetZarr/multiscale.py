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
        try:
            fh = s.database_openbinarydoc(doc, filename)
        except Exception as exc:
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
            return str(path) if path else None
        finally:
            try:
                s.database_closebinarydoc(fh)
            except Exception:
                pass

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
        path = self._fetch(doc, filename)
        if path is not None:
            self._paths[key] = path
        return path

    def forget(self, doc, filename) -> None:
        """Drop a memoised path so the next call fetches it again."""
        self._paths.pop((getattr(doc, "id", str(doc)), filename), None)

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


def levelArrays(
    session: Any,
    pyramid_doc: Any,
    channel: int | None = None,
    reduction: str | None = None,
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
    """
    import dask.array as da
    from dask import delayed

    docs = levelDocs(session, pyramid_doc, reduction=reduction)
    if not docs:
        raise ValueError(
            f"pyramid {pyramid_doc.id!s} has no lightsheetZarrLevel children for "
            f"reduction={reduction!r}."
        )

    _ = channel  # single-channel narrowing lands with the magicgui panels

    fetcher = _ChunkFetcher(session)

    arrays: list[Any] = []
    for doc in docs:
        p = doc.document_properties["lightsheetZarrLevel"]
        shape = tuple(int(v) for v in p["shape"])
        chunks = tuple(int(v) for v in p["chunks"])
        chunk_grid = tuple(int(v) for v in p["chunk_grid"])
        dtype = _numpy_dtype(str(p.get("dtype", "uint16")))
        fill = int(p.get("fill_value", 0))
        codec = str(p.get("codec", "raw"))
        stored = _storedChunkNames(doc)

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
        )
        arrays.append(da.block(nested))

    return arrays, fetcher


def _storedChunkNames(level_doc: Any) -> set[str] | None:
    """Return the set of ``chunk.bin_#`` names attached to a level document.

    Returned as a set for O(1) membership tests during the delayed-block
    grid build. Empty set means "the level document knows it has no
    chunks" and every position resolves to fill_value with no fetch. None
    means "the level document does not expose a file list" (older docs,
    unusual backends) -- the reader then falls back to trying every
    position, matching the pre-file-list behaviour.
    """
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
    fetcher, doc, shape, chunks, chunk_grid, dtype, fill, codec, stored, delayed, da
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
) -> tuple[dict, _ChunkFetcher]:
    """Return ``(spec, fetcher)`` where SPEC is kwargs for ``add_image``.

    ``spec['data']`` is the list of dask arrays from :func:`levelArrays`;
    ``multiscale=True``; ``scale`` and ``translate`` come from
    :func:`worldTransform`; ``name`` defaults to the pyramid's own label.

    ``fetcher`` is the :class:`_ChunkFetcher` backing the delayed reads.
    It is already held alive by the block closures, so the caller doesn't
    strictly need to hold it, but exposing it lets a viewer call
    ``fetcher.warm()`` before the first pan (so the one-off session-open
    cost lands while napari's window is opening) and ``fetcher.close()``
    on teardown.

    If the pyramid's ``axes_order`` contains a ``'c'`` axis, ``spec``
    also fills in ``channel_axis`` (so napari splits the layer into one
    layer per channel) plus per-channel ``colormap`` and ``name``:
    channel names come from the pyramid's ``channel_names`` field
    (comma-separated when present) and fall back to ``Ch1``, ``Ch2``,
    ...; colormaps come from :func:`defaultChannelColors`.
    """
    arrays, fetcher = levelArrays(session, pyramid_doc, channel=channel, reduction=reduction)
    scale, translate = worldTransform(session, pyramid_doc)

    p = pyramid_doc.document_properties["lightsheetZarrPyramid"]
    axes_order = str(p.get("axes_order", "")).lower()
    base_name = name
    if base_name is None:
        base_name = p.get("label") or p.get("pyramid_name") or "lightsheet zarr"

    c_index = axes_order.find("c") if axes_order else -1
    if c_index < 0 or not arrays:
        spec = {
            "data": arrays,
            "multiscale": True,
            "name": base_name,
            "scale": scale or None,
            "translate": translate or None,
        }
        return spec, fetcher

    n_channels = int(arrays[0].shape[c_index])
    names = _channelNames(p, n_channels, base_name)
    colors = defaultChannelColors(n_channels)

    # World transform axes drop the channel axis: napari's `scale` /
    # `translate` on a multiscale image describe the FINEST level in
    # world coordinates, and channel is not a world axis.
    spatial_scale = _dropAxis(scale, c_index) if scale else None
    spatial_trans = _dropAxis(translate, c_index) if translate else None

    spec = {
        "data": arrays,
        "multiscale": True,
        "channel_axis": c_index,
        "name": names,
        "colormap": colors,
        "scale": spatial_scale or None,
        "translate": spatial_trans or None,
    }
    return spec, fetcher


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
