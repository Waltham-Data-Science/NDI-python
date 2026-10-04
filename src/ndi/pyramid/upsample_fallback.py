"""Return coarser cached data (upsampled) instead of black for missing tiles.

The classic multiresolution rendering trick: at any screen region, show
the finest cached data on top of the coarsest cached data. Where fine
tiles have not arrived yet, coarser tiles show through -- blurry but
present -- so the user never stares at black holes on a slow link.

Napari's built-in multiscale is supposed to do this itself, but the
slicer we hit does not mark our lazy 3D dask arrays as loaded on time,
so we do the compositing at the READER level: when a fine chunk is not
cached, the delayed function returns an upsampled patch of the covering
coarse-level chunk (that :func:`multiscale.prefetchCoarsestLevel` put
on disk at launch) instead of returning fill_value.

Scope of this first cut:

* Only the COARSEST level is used as the fallback source. Walking
  through intermediate levels would raise sharpness a step at a time
  but the coarsest-level prefetch guarantees it is on disk, and the
  extra decode cost per read is not worth it before we know this
  helps.
* Only the "one coarse chunk fully covers this fine chunk" case
  paints -- if a fine chunk straddles two coarse chunks, we fall
  through to fill_value rather than stitch. Straddling is rare
  because level factors are usually 2^N and chunks align; the empty
  case shows what it always did.
* Nearest-neighbour upsampling via :func:`numpy.kron` on the region
  of interest. Bicubic is prettier but the point is "any pixel beats
  black" not "publication quality".

On by default; opt out with ``NDI_LIGHTSHEET_UPSAMPLE_FALLBACK=0``.
When on, the reader path in :func:`multiscale._build_block_grid`
routes each block through :func:`readChunkWithFallback` instead of
:func:`multiscale._read_chunk_from_fetcher`. Reader also fires an
asynchronous fine-chunk fetch (via ``fetcher.prefetchAsync``) so a
subsequent napari re-slice can find real data. The reader hands a
``refresh_hint`` callable in, and firing it from the fetch completion
tells the caller to nudge napari (debounced) into re-rendering the
layer.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any


def env_on() -> bool:
    """True unless the upsample fallback is explicitly disabled.

    Default flipped to ON in Waltham-Data-Science/NDI-python#320 after
    a user reported multi-minute black stretches during level swaps on
    a home connection: without the fallback, napari has nothing to
    paint for a region until every visible fine-level chunk arrives,
    which for a 1000-tile crop over ~15 MB/s aggregate can be minutes.
    With the fallback on, the coarsest-level tiles (which
    ``prefetchCoarsestLevel`` puts on disk at launch) are upsampled and
    painted immediately -- blurry but present -- and sharpen as the
    fine-level fetches arrive.

    ``NDI_LIGHTSHEET_UPSAMPLE_FALLBACK=0`` (or false/off/no) restores
    the previous opt-in behaviour. Any other value, including empty
    (env var unset), enables the fallback.
    """
    value = os.environ.get("NDI_LIGHTSHEET_UPSAMPLE_FALLBACK", "").strip().lower()
    return value not in ("0", "false", "off", "no")


def _fallback_debug() -> bool:
    """Whether to print per-refresh trace lines to stderr.

    On when either NDI_LIGHTSHEET_DEBUG or NDI_LIGHTSHEET_UPSAMPLE_DEBUG
    is truthy. The regular NDI_LIGHTSHEET_DEBUG channel already carries
    the rest of the launch narration, so a single knob keeps things
    manageable.
    """
    for name in ("NDI_LIGHTSHEET_UPSAMPLE_DEBUG", "NDI_LIGHTSHEET_DEBUG"):
        if os.environ.get(name, "").strip().lower() in ("1", "true", "on", "yes"):
            return True
    return False


class LevelGeometry:
    """Everything needed to place a chunk at level L in world coordinates.

    * ``chunks``: chunk shape (per axis, in this level's pixels).
    * ``chunk_grid``: number of chunks per axis.
    * ``shape``: level shape in pixels.
    * ``voxel_size``: world units per pixel per axis.
    * ``translation``: world coordinate of pixel (0, 0, ..., 0).
    * ``axes_order``: axes string ("czyx", "zyx", ...) -- used to find
      the spatial axes; upsampling ignores channel axes.

    Held as a plain object rather than a dict because the world-bbox
    math looks up the same four fields on the hot path and attribute
    access is a shade faster than repeated ``dict.get``.
    """

    __slots__ = ("chunks", "chunk_grid", "shape", "voxel_size", "translation", "axes_order")

    def __init__(
        self,
        chunks: tuple[int, ...],
        chunk_grid: tuple[int, ...],
        shape: tuple[int, ...],
        voxel_size: list[float],
        translation: list[float],
        axes_order: str,
    ):
        self.chunks = chunks
        self.chunk_grid = chunk_grid
        self.shape = shape
        self.voxel_size = voxel_size
        self.translation = translation
        self.axes_order = axes_order


def levelGeometry(level_props: dict) -> LevelGeometry:
    """Build a :class:`LevelGeometry` from a lightsheetZarrLevel document."""
    chunks = tuple(int(v) for v in level_props["chunks"])
    chunk_grid = tuple(int(v) for v in level_props["chunk_grid"])
    shape = tuple(int(v) for v in level_props["shape"])
    n = len(shape)
    voxel_size = [float(v) for v in level_props.get("voxel_size", [1.0] * n)]
    translation = [float(v) for v in level_props.get("translation", [0.0] * n)]
    axes_order = str(level_props.get("axes_order", "") or "").lower()
    # Pad missing entries so downstream indexing is safe against a
    # partly-filled doc rather than crashing per chunk.
    while len(voxel_size) < n:
        voxel_size.append(1.0)
    while len(translation) < n:
        translation.append(0.0)
    return LevelGeometry(chunks, chunk_grid, shape, voxel_size, translation, axes_order)


def fineChunkWorldBox(
    fine_geom: LevelGeometry,
    fine_chunk_multi_index: tuple[int, ...],
) -> tuple[list[float], list[float]]:
    """World bbox for one chunk of the fine level, per axis.

    Returns ``(starts, ends)`` -- each a list of world coordinates,
    one per axis, in the level's ``axes_order``. Channel axes get
    zero-width bboxes since they carry no world extent; callers strip
    them when converting into coarse pixel coordinates.
    """
    chunks = fine_geom.chunks
    voxel_size = fine_geom.voxel_size
    translation = fine_geom.translation
    n = len(chunks)
    starts: list[float] = []
    ends: list[float] = []
    for i in range(n):
        idx = fine_chunk_multi_index[i]
        p0 = idx * chunks[i]
        p1 = p0 + chunks[i]
        starts.append(translation[i] + p0 * voxel_size[i])
        ends.append(translation[i] + p1 * voxel_size[i])
    return starts, ends


def findCoveringCoarseChunk(
    coarse_geom: LevelGeometry,
    world_starts: list[float],
    world_ends: list[float],
) -> tuple[tuple[int, ...], tuple[slice, ...]] | None:
    """Find a single coarse chunk covering the given world bbox.

    Returns ``(chunk_multi_index, sub_slice_within_chunk)`` -- the
    index of the coarse chunk and the slice, in coarse pixels
    relative to that chunk's origin, that lines up with the fine
    chunk's footprint.

    Returns None when:

    * The fine bbox falls outside the coarse level's world extent.
    * The fine bbox straddles two coarse chunks (v1 does not stitch).
    * A coarse voxel size or chunk size is zero (malformed level).
    """
    chunks = coarse_geom.chunks
    chunk_grid = coarse_geom.chunk_grid
    voxel_size = coarse_geom.voxel_size
    translation = coarse_geom.translation
    n = len(chunks)
    chunk_idx: list[int] = []
    sub_slices: list[slice] = []
    for i in range(n):
        vs = voxel_size[i]
        cs = chunks[i]
        if vs <= 0 or cs <= 0:
            return None
        # World -> pixel in this coarse level.
        p_start = (world_starts[i] - translation[i]) / vs
        p_end = (world_ends[i] - translation[i]) / vs
        # Which coarse chunk holds p_start? Integer floor of p_start / cs.
        c_idx = int(p_start // cs)
        if c_idx < 0 or c_idx >= chunk_grid[i]:
            return None
        chunk_p0 = c_idx * cs
        chunk_p1 = chunk_p0 + cs
        # Straddling case: fine bbox extends past this coarse chunk.
        # v1 punts here.
        if p_end > chunk_p1 + 1e-6:
            return None
        # Sub-slice within this coarse chunk. Round outward so the
        # region contains all of the fine bbox rather than clipping.
        lo = max(0, int(p_start - chunk_p0))
        hi = min(int(cs), int(-(-(p_end - chunk_p0) // 1)))  # ceil trick
        if hi <= lo:
            return None
        chunk_idx.append(c_idx)
        sub_slices.append(slice(lo, hi))
    return tuple(chunk_idx), tuple(sub_slices)


def upsampleToBlock(
    coarse_data,
    sub_slice: tuple[slice, ...],
    block_shape: tuple[int, ...],
):
    """Nearest-neighbour upsample coarse[sub_slice] to block_shape.

    Uses ``numpy.kron`` when the size ratio is an integer along every
    axis (the common power-of-2 pyramid case) and falls back to
    ``numpy.take`` with an index array otherwise. Never allocates
    more than the output block.

    Returns None when the sub-region is empty or shapes are
    incompatible; the caller then falls through to fill_value.
    """
    import numpy as np

    try:
        region = coarse_data[sub_slice]
    except Exception:  # noqa: BLE001 - a bad slice is data-shape drift
        return None
    if region.size == 0:
        return None
    src_shape = region.shape
    if len(src_shape) != len(block_shape):
        return None

    # Integer scaling factor per axis when possible.
    factors = []
    integer_scale = True
    for src, dst in zip(src_shape, block_shape):
        if src == 0:
            return None
        if dst % src == 0:
            factors.append(dst // src)
        else:
            integer_scale = False
            break
    if integer_scale and all(f >= 1 for f in factors):
        # np.kron with ones is the "repeat every voxel n times per
        # axis" primitive; it produces the exact nearest-neighbour
        # upsample without going through pillow or scipy.
        try:
            ones = np.ones(tuple(factors), dtype=region.dtype)
            return np.kron(region, ones)
        except Exception:  # noqa: BLE001
            pass  # Fall through to the index-array path.

    # Non-integer scaling: use nearest-neighbour with an index array
    # per axis. Slower but correct for any src / dst ratio.
    try:
        idx_arrays = []
        for src, dst in zip(src_shape, block_shape):
            if src == 0 or dst == 0:
                return None
            step = src / dst
            idx = np.clip((np.arange(dst) * step).astype(np.int64), 0, src - 1)
            idx_arrays.append(idx)
        result = region
        for axis, idx in enumerate(idx_arrays):
            result = np.take(result, idx, axis=axis)
        return result
    except Exception:  # noqa: BLE001
        return None


#: Counters for how each block resolves. Read from the reader on
#: every call and printed by :func:`fallbackStatsSummary` at shutdown
#: (and in periodic heartbeats under debug), so we can tell whether a
#: viewer session that stays blurry stayed that way because fine
#: chunks never arrived (many HITs are impossible without fetches
#: settling in ``_paths``) or because napari never re-called the
#: reader after they arrived (a lot of MISSes and a lot of
#: PREFETCHED-in-flight, but no HITs later on).
_STATS_LOCK = threading.Lock()
_STATS = {
    "hit_fine": 0,  # chunkPathIfCached found it -> real fine returned
    "fine_decode_failed": 0,  # fine chunk on disk but decode raised (silent-fallback)
    "upsampled": 0,  # fine missing, upsampled from coarse
    "zero_no_coarse_cover": 0,  # no covering coarse chunk in-range
    "zero_coarse_missing": 0,  # covering coarse chunk not on disk
    "zero_upsample_failed": 0,  # upsampler returned None
    "zero_read_fail": 0,  # decode of coarse chunk raised
    "prefetches_queued": 0,  # prefetchAsync calls
    "refresh_hints_fired": 0,  # RefreshHint._fire ran (fine fetch arrived)
}


def fallbackStatsSummary() -> str:
    """One-line summary of what the fallback reader has been doing.

    Useful for diagnosing "the picture stays blurry forever": a
    session with many ``upsampled`` and near-zero ``hit_fine`` means
    either the async prefetches are not landing (network / auth
    breaking silently) or napari is not re-calling the reader after
    they land (refresh hint not triggering a slice compute).
    """
    with _STATS_LOCK:
        parts = [f"{k}={v}" for k, v in _STATS.items() if not k.startswith("_")]
    return "upsample-fallback " + " ".join(parts)


def _bump(key: str, n: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] = _STATS.get(key, 0) + n
        _STATS["_dirty"] = _STATS.get("_dirty", 0) + n


# Expose module-level bump so RefreshHint can log its activity in
# the same stats stream the user already watches.
bump = _bump


def totalReaderActivity() -> int:
    """How many times the fallback reader has returned a block.

    Sum of hit_fine + upsampled + every zero_* bucket. Used by the
    viewer heartbeat to tell "napari actually asked for a slice" from
    "napari has no local-disk fetches so the cloud-only _FetchCounter
    stayed at zero even though the slicer was working all along."
    """
    activity_keys = {"hit_fine", "upsampled", "fine_decode_failed"}
    with _STATS_LOCK:
        return sum(v for k, v in _STATS.items() if k in activity_keys or k.startswith("zero_"))


_HEARTBEAT_STARTED = False
_HEARTBEAT_LOCK = threading.Lock()


def _ensure_debug_heartbeat() -> None:
    """Spin up one daemon thread that dumps fallback stats every ~5 s.

    Only runs when ``_fallback_debug()`` is on. Prints a stats line
    only when something changed since the last tick, so a quiet
    session stays quiet. Starts lazily on the first fallback call so
    there is nothing to clean up at shutdown.
    """
    global _HEARTBEAT_STARTED
    if _HEARTBEAT_STARTED or not _fallback_debug():
        return
    with _HEARTBEAT_LOCK:
        if _HEARTBEAT_STARTED:
            return
        _HEARTBEAT_STARTED = True

        def _loop():
            import time

            last_signature = None
            while True:
                time.sleep(5.0)
                with _STATS_LOCK:
                    dirty = _STATS.get("_dirty", 0)
                    if dirty == 0:
                        continue
                    _STATS["_dirty"] = 0
                    snapshot = {k: v for k, v in _STATS.items() if not k.startswith("_")}
                sig = tuple(sorted(snapshot.items()))
                if sig == last_signature:
                    continue
                last_signature = sig
                parts = " ".join(f"{k}={v}" for k, v in snapshot.items())
                print(
                    f"[lightsheet] upsample-fallback live: {parts}",
                    file=sys.stderr,
                    flush=True,
                )

        t = threading.Thread(target=_loop, name="ndi-lightsheet-fallback-stats", daemon=True)
        t.start()


def readChunkWithFallback(
    fetcher,
    fine_doc,
    fine_filename: str,
    fine_geom: LevelGeometry,
    fine_chunk_multi_index: tuple[int, ...],
    coarse_doc,
    coarse_geom: LevelGeometry,
    stored_coarse_names: set | None,
    chunks_full: tuple[int, ...],
    block_shape: tuple[int, ...],
    dtype,
    fill: int,
    codec: str,
    refresh_hint=None,
):
    """Reader with a coarser-level upsample fallback.

    If ``fine_filename`` is already on disk, decode and return it as
    usual. Otherwise, find the coarse chunk that covers the fine
    chunk's world footprint, upsample the covering sub-region to
    ``block_shape``, and return that -- so napari draws SOMETHING
    for this block right now instead of fill_value.

    Concurrently, kick off a background fetch of the fine chunk so a
    subsequent re-slice can find the real data via ``chunkPathIfCached``.
    When that fetch completes, ``refresh_hint`` (if given) is called
    so the caller can debounce a ``layer.refresh()`` and let napari
    swap the coarse fallback for real fine pixels.

    Never raises for data-side failures; a raised exception here
    would abort the whole slice compute. The block is filled with
    fill_value as a last resort.
    """
    from ndi.pyramid.multiscale import _read_chunk_from_fetcher, _zero_block

    _ensure_debug_heartbeat()

    # Path 1: fine chunk on disk -> normal read.
    fine_path = fetcher.chunkPathIfCached(fine_doc, fine_filename)
    if fine_path is not None:
        try:
            result = _read_chunk_from_fetcher(
                fetcher, fine_doc, fine_filename, chunks_full, block_shape, dtype, fill, codec
            )
            _bump("hit_fine")
            return result
        except Exception as decode_exc:  # noqa: BLE001 - a bad decode is fallback time
            # The fine chunk is on disk but failed to decode: a
            # truncated download, a codec mismatch, or a corrupt
            # blob. Falling through to coarse-upsample keeps the
            # view from going black, but if we don't LOG this, the
            # user sees level-3 pixels forever while the Auto-level
            # picker reports level 0 and no error ever appears --
            # that was the silent-blurry symptom before this change.
            _bump("fine_decode_failed")
            print(
                f"[lightsheet] fine decode failed, upsampling from coarse: "
                f"{fine_filename!r} ({type(decode_exc).__name__}: {decode_exc})",
                file=sys.stderr,
                flush=True,
            )

    # Path 2: fine missing -> upsample coarse if we can, and fetch fine.
    fetcher.prefetchAsync(fine_doc, fine_filename, on_complete=refresh_hint)
    _bump("prefetches_queued")

    world_starts, world_ends = fineChunkWorldBox(fine_geom, fine_chunk_multi_index)
    covering = findCoveringCoarseChunk(coarse_geom, world_starts, world_ends)
    if covering is None:
        _bump("zero_no_coarse_cover")
        return _zero_block(block_shape, dtype, fill)

    coarse_multi, sub_slice = covering
    coarse_filename = _coarse_chunk_filename(coarse_multi, coarse_geom.chunk_grid)
    if stored_coarse_names is not None and coarse_filename not in stored_coarse_names:
        # Coarse chunk was never written -- level is sparse there.
        _bump("zero_no_coarse_cover")
        return _zero_block(block_shape, dtype, fill)

    coarse_path = fetcher.chunkPathIfCached(coarse_doc, coarse_filename)
    if coarse_path is None:
        # Coarse not on disk yet -- prefetch should have covered it, but
        # if we opened during prefetch we may see this. Nothing to
        # upsample from; fill and hope the fine fetch we just queued
        # arrives soon.
        _bump("zero_coarse_missing")
        return _zero_block(block_shape, dtype, fill)

    try:
        coarse_full = _read_chunk_from_fetcher(
            fetcher,
            coarse_doc,
            coarse_filename,
            coarse_geom.chunks,
            coarse_geom.chunks,  # full chunk, no partial-edge trim needed
            dtype,
            fill,
            codec,
        )
    except Exception:  # noqa: BLE001
        _bump("zero_read_fail")
        return _zero_block(block_shape, dtype, fill)

    # Upsample to the fine block's shape. block_shape may be smaller
    # than the nominal chunks on the fine level's edge; the sub_slice
    # was computed against the fine bbox so it already reflects the
    # smaller shape.
    upsampled = upsampleToBlock(coarse_full, sub_slice, block_shape)
    if upsampled is None:
        _bump("zero_upsample_failed")
        return _zero_block(block_shape, dtype, fill)
    _bump("upsampled")
    return upsampled


def _coarse_chunk_filename(multi_index: tuple[int, ...], chunk_grid: tuple[int, ...]) -> str:
    """Recreate the ``chunk.bin_N`` name for a coarse chunk at multi-index.

    Duplicates the linear index math in :func:`multiscale._linear_chunk_index`
    (row-major over reversed axes, 1-based). Kept local so the reader can
    build the name without importing the private helper by name and
    tripping ruff's private-import rule.
    """
    idx = 1
    stride = 1
    for i in range(len(chunk_grid) - 1, -1, -1):
        idx += multi_index[i] * stride
        stride *= chunk_grid[i]
    return f"chunk.bin_{idx:d}"


# RefreshHint and refreshHintFor moved to
# ``ndi.gui.app.lightsheetZarr.refresh_hint`` -- the napari-side
# nudge belongs on the napari side, not in a pyramid-loading
# module that must be importable without Qt for CI. Callers on
# the napari path build their own hint and pass it in as
# ``on_complete`` when they enqueue an async fetch.


# Unit-test hooks. `_pure_helpers` is the set of functions safe to call
# from tests without touching a viewer, a fetcher, or a level document.
__all__ = [
    "env_on",
    "LevelGeometry",
    "levelGeometry",
    "fineChunkWorldBox",
    "findCoveringCoarseChunk",
    "upsampleToBlock",
    "readChunkWithFallback",
]


def _pure_helpers() -> list[Any]:  # pragma: no cover - test discoverability
    return [
        levelGeometry,
        fineChunkWorldBox,
        findCoveringCoarseChunk,
        upsampleToBlock,
    ]
