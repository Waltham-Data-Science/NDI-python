"""ndi.fun.doc.lightsheet.makePyramid -- one pyramid parent and its deduped levels.

MATLAB counterpart: ``+ndi/+fun/+doc/+lightsheet/makePyramid.m``.

Given the multiscales entries :func:`ndr.format.omezarr.listPyramids` reports
(or that :func:`fromSPIM` plans) and one reduction label per entry, writes ONE
``lightsheetZarrPyramid`` document (the source volume) and one
``lightsheetZarrLevel`` per UNIQUE level path across all entries. Two entries
naming the same path (level 0 shared by the mean and max ladders) share one
level document, whose ``reduction_function`` is ``'none'``.

With ``materializeChunks`` each level's voxels are read, cut into the level's
chunk shape (``chooseTileShape``, isotropic in world space, near
``tileBudgetBytes``), zero-padded at the edges, written C-order (Zarr v2 byte
order), optionally Blosc-Zstd compressed, and attached as the file series
``chunk.bin`` (members ``chunk.bin_1`` ... ``chunk.bin_N``, one-based, C-order
over the chunk grid). The bytes and the documents are the same as MATLAB's, so
a pyramid built by either language reads in both viewers.

Where the bytes come from (``levelSources``, a dict from level path to a
source dict) is MATLAB's: ``{'kind': 'omezarr'}`` (the default, read from
``sourceZarrPath``), ``{'kind': 'smartspim', 'slicePaths', 'dtype'}`` (2-D
TIFF slices, axes t,c,z,y,x), ``{'kind': 'reduce', 'fromPath', 'factor',
'reduction'}`` (block-reduce a level written earlier in this call) and
``{'kind': 'reduceSmartspim', 'slicePaths', 'sourceDtype', 'fromShape',
'factor', 'reduction'}`` (block-reduce the slices themselves).

STREAMING. A target with ``streamMembers`` (an
:class:`ndi.cloud.session_writer` SessionWriter) is sent each level as it is
built: the level is declared with every chunk's uid, each super-block's
chunks are streamed as they are written, a level later levels reduce from is
retained locally until they are done, level 1 of each ladder is FOLDED into
level 0 (built from the same reads of the slices), twin levels (the max
ladder's level beside the mean's) are built from one read, and a build can
RESUME (``resume``: adopt what the cloud has and build only missing chunks).

LANGUAGE DIFFERENCES. MATLAB compresses on a parpool and reads slices on
parfeval workers; here both are thread pools (Blosc and the TIFF decoders
release the GIL). ``numWorkers=-1`` means "as many as this computer has
cores" (MATLAB: "the parpool already open, else serial"); 0 or 1 is serial.
Regions are 0-based half-open internally; chunk numbers stay one-based, as
the documents record them.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np

__all__ = ["makePyramid"]


# ---------------------------------------------------------------------------
# small helpers shared with fromSPIM / fromOMEZarr
# ---------------------------------------------------------------------------


def _dtypeName(dtype: Any, form: str) -> str:
    from ndi.fun.doc_lightsheet.dtypeName import dtypeName

    return dtypeName(dtype, form)


def _np_dtype(dtype: Any) -> np.dtype:
    """A voxel type, in any spelling dtypeName reads, as a little-endian numpy dtype."""
    return np.dtype(_dtypeName(dtype, "zarr")).newbyteorder("<")


def _reduce(arr: np.ndarray, factor, reduction: str, dtype: Any) -> np.ndarray:
    from ndi.fun.doc_lightsheet.reduceBlocks import reduceBlocks

    out = reduceBlocks(arr, [int(f) for f in factor], reduction, _dtypeName(dtype, "matlab"))
    return np.asarray(out, dtype=_np_dtype(dtype))


def _row(x: Any) -> list[float]:
    if x is None:
        return []
    return [float(v) for v in np.asarray(x, dtype=float).ravel()]


def _int_row(x: Any) -> list[int]:
    return [int(v) for v in np.asarray(x).ravel()]


def _joinAxisNames(axes: list[dict]) -> str:
    return "".join(str(a.get("name", "")) for a in axes or [])


def _collectAxisUnits(axes: list[dict]) -> list[str]:
    return [str(a.get("unit", "") or "") for a in axes or []]


def _channelCount(shape: list[int], axesOrder: str) -> int:
    k = axesOrder.find("c")
    if k < 0 or len(shape) <= k:
        return 1
    return int(shape[k])


def _clampChunksToShape(chunks: Any, shape: list[int]) -> list[int]:
    chunks = np.asarray(chunks, dtype=float).ravel()
    shape = np.asarray(shape, dtype=float).ravel()
    if chunks.size != shape.size:
        raise ValueError(
            f"Explicit chunks length {chunks.size} does not match level shape length "
            f"{shape.size}."
        )
    if np.any(chunks < 1) or np.any(chunks != np.floor(chunks)):
        raise ValueError("Explicit chunks must be positive integers.")
    return _int_row(np.minimum(chunks, shape))


def _elementSizeBytes(dtype: Any) -> int:
    try:
        return int(_np_dtype(dtype).itemsize)
    except Exception:  # noqa: BLE001 -- MATLAB falls back to 2
        return 2


def _codecParamsJSON(codec: str, clevel: int) -> str:
    if codec == "blosc-zstd":
        return f'{{"cname":"zstd","clevel":{int(clevel)},"shuffle":1,"blocksize":0}}'
    return "{}"


def _chunkWeight(source: dict | None) -> int:
    """Work of one output chunk, in level-0 chunks (a chunk reduced straight
    from the slices reads prod(factor) chunks' worth of them)."""
    if (
        isinstance(source, dict)
        and source.get("kind") == "reduceSmartspim"
        and not source.get("folded", False)
    ):
        return int(np.prod(source["factor"]))
    return 1


def _readAmplification(source: dict, typesize: int) -> float:
    a = 1.0
    if source.get("kind") in ("reduce", "reduceSmartspim"):
        a = float(np.prod(source["factor"]))
        if source.get("reduction") == "mean":
            a *= max(1.0, 4.0 / typesize)
    return a


def _reducedFrom(levelSources: dict, p: str) -> str:
    src = levelSources.get(p)
    if src and src.get("kind") == "reduce":
        return str(src["fromPath"])
    return ""


def _resumedLevel(resume: dict, levelIndex: int, reductionFn: str) -> Any:
    for d in resume.get("levelDocs", []) or []:
        lp = d.document_properties["lightsheetZarrLevel"]
        if int(lp["level"]) == levelIndex and str(lp["reduction_function"]) == reductionFn:
            return d
    return None


def _reportProgress(fcn: Callable | None, done: float, total: float, text: str) -> None:
    """Call the progress callback; a broken bar must not stop a build, but a
    job's pause request (ndi.job) must."""
    if fcn is None:
        return
    frac = 0.0
    if total > 0:
        frac = max(0.0, min(1.0, float(done) / float(total)))
    try:
        fcn(frac, str(text))
    except Exception as exc:  # noqa: BLE001
        from ndi.job.job import _JobPaused

        if isinstance(exc, _JobPaused):
            raise


def _say(text: str) -> None:
    print(f"[makePyramid] {text}", flush=True)


def _resolvePoolSize(numWorkers: int) -> int:
    if numWorkers in (0, 1):
        return 1
    if numWorkers < 0:
        return max(1, os.cpu_count() or 1)
    return int(numWorkers)


def _sessionTiming(stream: dict | None) -> dict[str, float]:
    t = {"urls": 0.0, "stage": 0.0, "send": 0.0, "verify": 0.0}
    if stream is None:
        return t
    timing = getattr(stream["session"], "timing", None)
    if timing is None:
        return t
    for k in t:
        v = timing.get(k) if isinstance(timing, dict) else getattr(timing, k, None)
        if v is not None:
            t[k] = float(v)
    return t


def _addFileSeries(doc: Any, name: str, paths: list[str], indices: list[int]) -> Any:
    """DID's addFileSeries on an ndi_document (Python ndi_document wraps no series API)."""
    from did.document import Document

    from ndi.document import ndi_document

    dd = Document(doc.document_properties)
    dd.add_file_series(name, list(paths), indices=[int(i) for i in indices])
    return ndi_document(dd.document_properties)


def _cleanupTmp(d: str) -> None:
    if d and os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# chunk geometry (0-based, half-open regions; chunk ids one-based, C order)
# ---------------------------------------------------------------------------


def _allChunkIndices(grid: list[int]) -> np.ndarray:
    """Rows are the 0-based chunk coordinates in C order (last axis fastest)."""
    return np.array(list(np.ndindex(*[int(g) for g in grid])), dtype=np.int64).reshape(
        -1, len(grid)
    )


def _strides(grid) -> np.ndarray:
    nd = len(grid)
    s = np.ones(nd, dtype=np.int64)
    for a in range(nd - 2, -1, -1):
        s[a] = s[a + 1] * int(grid[a + 1])
    return s


def _round_half_away(x: np.ndarray) -> np.ndarray:
    return np.floor(np.asarray(x, dtype=float) + 0.5).astype(np.int64)


def _block(idxs, lo, hi) -> dict:
    lo = np.asarray(lo, dtype=np.int64).reshape(len(idxs), -1)
    hi = np.asarray(hi, dtype=np.int64).reshape(len(idxs), -1)
    return {
        "idxs": np.asarray(idxs, dtype=np.int64),
        "lo": lo,
        "hi": hi,
        "loBBox": lo.min(axis=0),
        "hiBBox": hi.max(axis=0),
    }


def _planSuperBlocks(chunks, grid, shape, budgetChunks: int) -> list[dict]:
    """Group a level's chunks into super-blocks of WHOLE rows along x (up to the
    budget, within one plane), or equal parts of a row longer than twice it."""
    order = _allChunkIndices(grid)
    nChunks = order.shape[0]
    nd = len(grid)
    nx = int(grid[-1])
    ny = int(grid[-2]) if nd >= 2 else 1
    groups: list[np.ndarray] = []
    if nx <= 2 * budgetChunks:
        rowsPerBlock = max(1, budgetChunks // nx)
        nRows = nChunks // nx
        r = 1
        while r <= nRows:
            planeEnd = math.ceil(r / ny) * ny
            last = min(r + rowsPerBlock - 1, planeEnd, nRows)
            groups.append(np.arange((r - 1) * nx, last * nx))
            r = last + 1
    else:
        k = math.ceil(nx / budgetChunks)
        edges = _round_half_away(np.linspace(0, nx, k + 1))
        for r in range(nChunks // nx):
            for seg in range(k):
                groups.append(r * nx + np.arange(edges[seg], edges[seg + 1]))
    chunks = np.asarray(chunks, dtype=np.int64)
    shape = np.asarray(shape, dtype=np.int64)
    blocks = []
    for g in groups:
        lo = order[g] * chunks
        hi = np.minimum(lo + chunks, shape)
        blocks.append(_block(g + 1, lo, hi))
    return blocks


def _chunksIn(lo, hi, c, grid, shape) -> dict:
    """The chunks of region [lo, hi) (which starts on a chunk boundary)."""
    lo = np.asarray(lo, dtype=np.int64)
    hi = np.asarray(hi, dtype=np.int64)
    c = np.asarray(c, dtype=np.int64)
    cLo = lo // c
    cHi = -(-hi // c)
    coords = (
        np.array(list(np.ndindex(*[int(n) for n in (cHi - cLo)])), dtype=np.int64).reshape(
            -1, lo.size
        )
        + cLo
    )
    ids = coords @ _strides(grid) + 1
    order = np.argsort(ids, kind="stable")
    ids = ids[order]
    coords = coords[order]
    loRows = coords * c
    hiRows = np.minimum(loRows + c, np.asarray(shape, dtype=np.int64))
    out = _block(ids, loRows, hiRows)
    out["loBBox"], out["hiBBox"] = lo, hi
    return out


def _planFoldCells(shape0, c0, c1, shape1, f, budgetBytes: float, typesize: int) -> list[dict]:
    """Regions of level 0 holding whole level-0 chunks (C0) and whole chunks of a
    level reduced from it by F (C1): L = lcm(C0, C1*F) per axis, grouped along x
    up to the budget. Each cell has its level-0 chunks and, in 'L1', the reduced
    level's chunks in that level's coordinates."""
    shape0 = np.asarray(shape0, dtype=np.int64)
    shape1 = np.asarray(shape1, dtype=np.int64)
    c0 = np.asarray(c0, dtype=np.int64)
    c1 = np.asarray(c1, dtype=np.int64)
    f = np.asarray(f, dtype=np.int64)
    nd = shape0.size
    L = np.array([math.lcm(int(c0[a]), int(c1[a] * f[a])) for a in range(nd)], dtype=np.int64)
    nCell = -(-shape0 // L)
    cellBytes = int(np.prod(np.minimum(L, shape0))) * typesize
    gx = max(1, min(int(nCell[-1]), int(budgetBytes // max(cellBytes, 1))))
    nCell[-1] = -(-nCell[-1] // gx)
    span = np.ones(nd, dtype=np.int64)
    span[-1] = gx
    grid0 = -(-shape0 // c0)
    grid1 = -(-shape1 // c1)
    cells = []
    for cc in np.ndindex(*[int(n) for n in nCell]):
        cc = np.asarray(cc, dtype=np.int64)
        lo0 = cc * L * span
        hi0 = np.minimum(lo0 + L * span, shape0)
        cell = _chunksIn(lo0, hi0, c0, grid0, shape0)
        lo1 = lo0 // f
        hi1 = np.minimum(-(-hi0 // f), shape1)
        cell["L1"] = _chunksIn(lo1, hi1, c1, grid1, shape1)
        cells.append(cell)
    return cells


def _splitAlongZ(lo, hi, nParts: int, align: int = 1) -> list[tuple[np.ndarray, np.ndarray]]:
    """Region [lo, hi) as up to nParts slabs along axis 2 (z of t,c,z,y,x), each
    starting a multiple of ALIGN voxels from lo."""
    lo = np.asarray(lo, dtype=np.int64)
    hi = np.asarray(hi, dtype=np.int64)
    if lo.size < 3 or nParts <= 1:
        return [(lo, hi)]
    n_len = int(hi[2] - lo[2])
    nBlocks = -(-n_len // align)
    n = min(nParts, nBlocks)
    edges = lo[2] + np.minimum(_round_half_away(np.linspace(0, nBlocks, n + 1)) * align, n_len)
    out = []
    for k in range(n):
        a, b = lo.copy(), hi.copy()
        a[2], b[2] = edges[k], edges[k + 1]
        out.append((a, b))
    return out


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------


def _readSliceWindow(path: str, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    """Rows y0:y1, columns x0:x1 of one 2-D TIFF slice, decoding only the strips
    that cover it where tifffile can."""
    import tifffile

    try:
        import zarr

        store = tifffile.imread(path, aszarr=True)
        try:
            z = zarr.open(store, mode="r")
            if hasattr(z, "shape") and len(z.shape) == 2:
                return np.asarray(z[y0:y1, x0:x1])
        finally:
            store.close()
    except Exception:  # noqa: BLE001 -- fall back to reading the whole slice
        pass
    return np.asarray(tifffile.imread(path))[y0:y1, x0:x1]


def _readSliceRetrying(path: str, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    """A slice window, retried for up to 30 minutes (waits 2 s growing to 60 s):
    slices often live on a file server that can drop out for a few minutes."""
    t0 = time.monotonic()
    wait = 2.0
    while True:
        try:
            return _readSliceWindow(path, y0, y1, x0, x1)
        except Exception as exc:  # noqa: BLE001
            gone = os.path.isdir(os.path.dirname(path)) and not os.path.isfile(path)
            if gone or time.monotonic() - t0 + wait > 1800:
                raise
            _say(f"Could not read {path} ({exc}); trying again in {wait:.0f} s.")
            time.sleep(wait)
            wait = min(60.0, 2 * wait)


def _readSmartSpimRegion(slicePaths, dtype, lo, hi) -> np.ndarray:
    """Region [lo, hi) of axes t,c,z,y,x from slicePaths[c][z]."""
    dt = _np_dtype(dtype)
    out = np.zeros(tuple(int(v) for v in (hi - lo)), dtype=dt)
    for c in range(int(lo[1]), int(hi[1])):
        for z in range(int(lo[2]), int(hi[2])):
            tile = _readSliceRetrying(
                slicePaths[c][z], int(lo[3]), int(hi[3]), int(lo[4]), int(hi[4])
            )
            out[0, c - lo[1], z - lo[2], :, :] = tile.astype(dt, copy=False)
    return out


def _sourceRegionOfReduction(lo, hi, f, fromShape):
    f = np.asarray(f, dtype=np.int64)
    return lo * f, np.minimum(hi * f, np.asarray(fromShape, dtype=np.int64))


def _readStoredChunk(path: str, chunks, codec: str, dtype) -> np.ndarray:
    with open(path, "rb") as fh:
        raw = fh.read()
    if codec == "blosc-zstd":
        from numcodecs import Blosc

        raw = Blosc().decode(raw)
    dt = _np_dtype(dtype)
    return np.frombuffer(raw, dtype=dt, count=int(np.prod(chunks))).reshape(
        tuple(int(c) for c in chunks)
    )


def _readStoredLevelRegion(source: dict, lo, hi) -> np.ndarray:
    chunks = np.asarray(source["fromChunks"], dtype=np.int64)
    grid = source["fromGrid"]
    out = np.zeros(tuple(int(v) for v in (hi - lo)), dtype=_np_dtype(source["fromDtype"]))
    cLo = lo // chunks
    cHi = (hi - 1) // chunks
    strides = _strides(grid)
    for off in np.ndindex(*[int(n) for n in (cHi - cLo + 1)]):
        c = cLo + np.asarray(off, dtype=np.int64)
        tile = _readStoredChunk(
            source["chunkPaths"][int(c @ strides)],
            chunks,
            source["fromCodec"],
            source["fromDtype"],
        )
        tLo = c * chunks
        oLo = np.maximum(tLo, lo)
        oHi = np.minimum(tLo + chunks, hi)
        dst = tuple(slice(int(a - l0), int(b - l0)) for a, b, l0 in zip(oLo, oHi, lo))
        src = tuple(slice(int(a - t0), int(b - t0)) for a, b, t0 in zip(oLo, oHi, tLo))
        out[dst] = tile[src]
    return out


def _readSuperBlockRegion(source: dict, lo, hi) -> np.ndarray:
    kind = source["kind"]
    if kind == "omezarr":
        from ndr.format.omezarr.readArray import readArray

        region = np.vstack([lo + 1, hi]).astype(float)  # 1-based inclusive
        return np.asarray(
            readArray(
                source["zarrPath"], source["pyramidName"], int(source["kInEntry"]), Region=region
            )
        )
    if kind == "smartspim":
        return _readSmartSpimRegion(source["slicePaths"], source["dtype"], lo, hi)
    if kind == "reduce":
        sLo, sHi = _sourceRegionOfReduction(lo, hi, source["factor"], source["fromShape"])
        src = _readStoredLevelRegion(source, sLo, sHi)
        return _reduce(src, source["factor"], source["reduction"], source["dtype"])
    if kind == "reduceSmartspim":
        sLo, sHi = _sourceRegionOfReduction(lo, hi, source["factor"], source["fromShape"])
        src = _readSmartSpimRegion(source["slicePaths"], source["sourceDtype"], sLo, sHi)
        return _reduce(src, source["factor"], source["reduction"], source["dtype"])
    raise ValueError(f"Unknown level source kind '{kind}'.")


def _readTiles(src: dict, lo, hi) -> list[np.ndarray]:
    """The region(s) one read serves: one tile, a twin pair, or a fold group."""
    kind = src["kind"]
    if kind == "reduceSmartspimPair":
        sLo, sHi = _sourceRegionOfReduction(lo, hi, src["factor"], src["fromShape"])
        raw = _readSmartSpimRegion(src["slicePaths"], src["sourceDtype"], sLo, sHi)
        return [_reduce(raw, src["factor"], r, d) for r, d in zip(src["reductions"], src["dtypes"])]
    if kind == "smartspimFold":
        raw = _readSmartSpimRegion(src["slicePaths"], src["dtype"], lo, hi)
        return [raw] + [
            _reduce(raw, src["factor"], r, d) for r, d in zip(src["reductions"], src["dtypes"])
        ]
    return [_readSuperBlockRegion(src, lo, hi)]


class _Read:
    """A region read as slabs along z on the reader pool (or here, in turn)."""

    def __init__(self, pool: ThreadPoolExecutor | None, src: dict, lo, hi, nParts, align=1):
        self.parts: list[Future | list[np.ndarray]] = []
        for a, b in _splitAlongZ(lo, hi, nParts, align):
            if pool is None:
                self.parts.append(_readTiles(src, a, b))
            else:
                self.parts.append(pool.submit(_readTiles, src, a, b))

    def result(self) -> list[np.ndarray]:
        parts = [p.result() if isinstance(p, Future) else p for p in self.parts]
        if len(parts) == 1:
            return parts[0]
        return [np.concatenate([p[i] for p in parts], axis=2) for i in range(len(parts[0]))]


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------


def _padEncodeAndWrite(tile: np.ndarray, chunks, codec: str, clevel: int, tmpRoot: str, idx):
    """Pad a tile to the chunk shape with zeros, encode it C-order, write chunk_<idx>.bin."""
    chunks = tuple(int(c) for c in chunks)
    if tile.shape != chunks:
        padded = np.zeros(chunks, dtype=tile.dtype)
        padded[tuple(slice(0, s) for s in tile.shape)] = tile
        tile = padded
    tile = np.ascontiguousarray(tile, dtype=tile.dtype.newbyteorder("<"))
    if codec == "raw":
        payload = tile.tobytes(order="C")
    elif codec == "blosc-zstd":
        from numcodecs import Blosc

        payload = Blosc(
            cname="zstd", clevel=int(clevel), shuffle=Blosc.SHUFFLE, blocksize=0
        ).encode(tile)
    else:
        raise ValueError(f"Unknown codec {codec}.")
    path = os.path.join(tmpRoot, f"chunk_{int(idx)}.bin")
    with open(path, "wb") as fh:
        fh.write(payload)
    return path


def _encodeBlock(bigTile, sb, sel, chunks, codec, clevel, tmpRoot, pool):
    """Cut the chunks SEL picks out of a super-block's region and encode each to
    a file in tmpRoot. Returns (paths, one-based ids, timings)."""
    t = {"assemble": 0.0, "compress": 0.0, "workerBusy": 0.0, "mbOut": 0.0}
    rows = np.flatnonzero(sel)
    if rows.size == 0:
        return [], [], t
    t0 = time.monotonic()
    jobs = []
    for r in rows:
        src = tuple(
            slice(int(a - b0), int(b - b0))
            for a, b, b0 in zip(sb["lo"][r], sb["hi"][r], sb["loBBox"])
        )
        jobs.append((int(sb["idxs"][r]), bigTile[src]))
    t["assemble"] = time.monotonic() - t0

    def one(job):
        c0 = time.monotonic()
        p = _padEncodeAndWrite(job[1], chunks, codec, clevel, tmpRoot, job[0])
        return p, time.monotonic() - c0

    t0 = time.monotonic()
    if pool is not None and len(jobs) > 1:
        results = list(pool.map(one, jobs))
    else:
        results = [one(j) for j in jobs]
    t["compress"] = time.monotonic() - t0
    paths = [r[0] for r in results]
    t["workerBusy"] = sum(r[1] for r in results)
    t["mbOut"] = sum(os.path.getsize(p) for p in paths) / 2**20
    return paths, [j[0] for j in jobs], t


def _addTimes(a: dict, b: dict) -> None:
    for k in ("assemble", "compress", "workerBusy", "mbOut"):
        a[k] += b[k]


def _appendDebugLog(path, levelLabel, s, n, done, total, bboxMB) -> None:
    if not path:
        return
    try:
        rss = float("nan")
        try:
            with open("/proc/self/statm") as fh:
                rss = int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
        except OSError:
            pass
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {levelLabel} | sb={s}/{n} | "
            f"chunks={done:g}/{total:g} | rss_MB={rss:.0f} | bbox_MB={bboxMB:.0f}"
        )
        with open(path, "a") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 -- instrumentation never stops a build
        pass


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------


class _Build:
    """State of one makePyramid call (MATLAB's nested-function workspace)."""

    def __init__(self, session, pyramids, perEntryReduction, o: dict):
        self.session = session
        self.pyramids = pyramids
        self.o = o
        self.levelSources: dict = o["levelSources"] or {}
        self.pathOrder: list[str] = []
        self.pathReductions: dict[str, list[str]] = {}
        self.representative: dict[str, tuple[int, int]] = {}
        for i, entry in enumerate(pyramids):
            for k, level in enumerate(entry["levels"]):
                p = str(level["path"])
                if p not in self.pathReductions:
                    self.pathOrder.append(p)
                    self.pathReductions[p] = [perEntryReduction[i]]
                    self.representative[p] = (i, k)
                elif perEntryReduction[i] not in self.pathReductions[p]:
                    self.pathReductions[p].append(perEntryReduction[i])
        self.levelChunks: list[list[int]] = []
        self.levelGrids: list[list[int]] = []
        self.compressPool: ThreadPoolExecutor | None = None
        self.readPool: ThreadPoolExecutor | None = None
        self.poolSize = 1

    def levelMeta(self, path: str):
        i, k = self.representative[path]
        entry = self.pyramids[i]
        reds = self.pathReductions[path]
        return entry, entry["levels"][k], ("none" if len(reds) > 1 else reds[0])

    def foldCandidates(self, done: list[bool]) -> list[int]:
        o, po = self.o, self.pathOrder
        zero = self.levelSources.get(po[0])
        if not zero or zero.get("kind") != "smartspim":
            return []
        _, lvl0, _ = self.levelMeta(po[0])
        shape0 = _int_row(lvl0["shape"])
        factor = chunks = None
        qs = []
        for k in range(1, len(po)):
            src = self.levelSources.get(po[k])
            if done[k] or not src:
                continue
            if (
                src.get("kind") != "reduceSmartspim"
                or src["slicePaths"] != zero["slicePaths"]
                or _int_row(src["fromShape"]) != shape0
            ):
                continue
            f = _int_row(src["factor"])
            if factor is None:
                factor, chunks = f, self.levelChunks[k]
                L = [math.lcm(self.levelChunks[0][a], chunks[a] * f[a]) for a in range(len(f))]
                if np.prod(np.minimum(L, shape0)) * _elementSizeBytes(zero["dtype"]) > 8 * 2**30:
                    return []
            elif f != factor or self.levelChunks[k] != chunks:
                continue
            qs.append(k)
        del o
        return qs

    def findTwin(self, i: int, built: list[bool]) -> int:
        po = self.pathOrder
        mine = self.levelSources.get(po[i])
        for k in range(i + 1, len(po)):
            other = self.levelSources.get(po[k])
            if built[k] or not other:
                continue
            if (
                other.get("kind") == "reduceSmartspim"
                and other["reduction"] != mine["reduction"]
                and _int_row(other["factor"]) == _int_row(mine["factor"])
                and _int_row(other["fromShape"]) == _int_row(mine["fromShape"])
                and other["slicePaths"] == mine["slicePaths"]
                and self.levelChunks[k] == self.levelChunks[i]
                and self.levelGrids[k] == self.levelGrids[i]
            ):
                return k
        return -1

    def resolveLevelSource(self, p: str, entry, level, docByPath: dict) -> dict:
        o = self.o
        source = dict(self.levelSources.get(p) or {"kind": "omezarr"})
        kind = source["kind"]
        if kind == "omezarr":
            if not o["sourceZarrPath"]:
                raise ValueError(f"Level {p} has no levelSources entry and no sourceZarrPath.")
            paths = [str(L["path"]) for L in entry["levels"]]
            if p not in paths:
                raise ValueError(f"level path {p} not found in pyramid {entry['name']}.")
            return {
                "kind": "omezarr",
                "zarrPath": str(o["sourceZarrPath"]),
                "pyramidName": str(entry["name"]),
                "kInEntry": paths.index(p) + 1,
            }
        if kind == "smartspim":
            source["dtype"] = _dtypeName(source["dtype"], "matlab")
            return source
        if kind == "reduceSmartspim":
            source["dtype"] = _dtypeName(level["dtype"], "matlab")
            source["sourceDtype"] = _dtypeName(source["sourceDtype"], "matlab")
            source["factor"] = _int_row(source["factor"])
            source["fromShape"] = _int_row(source["fromShape"])
            return source
        if kind == "reduce":
            if source["fromPath"] not in docByPath:
                raise ValueError(
                    f"Level {p} reduces level {source['fromPath']}, which has not been "
                    "written yet. List finer levels first."
                )
            frm = docByPath[source["fromPath"]]
            fp = frm.document_properties["lightsheetZarrLevel"]
            nFrom = int(np.prod(fp["chunk_grid"]))
            paths = []
            # Each stored chunk resolved to its file once, here on this thread
            # (the database belongs to it); the readers then read plain files.
            for i in range(1, nFrom + 1):
                fh = self.session.database_openbinarydoc(frm, f"chunk.bin_{i}")
                paths.append(str(getattr(fh, "name", "")))
                self.session.database_closebinarydoc(fh)
            source.update(
                fromShape=_int_row(fp["shape"]),
                fromChunks=_int_row(fp["chunks"]),
                fromGrid=_int_row(fp["chunk_grid"]),
                fromCodec=str(fp["codec"]),
                fromDtype=_dtypeName(fp["dtype"], "matlab"),
                chunkPaths=paths,
                dtype=_dtypeName(level["dtype"], "matlab"),
                factor=_int_row(source["factor"]),
            )
            return source
        raise ValueError(f"Unknown level source kind '{kind}' for level {p}.")

    def newStream(self, p: str, levelIndex: int, reductionFn: str, readers: dict) -> dict:
        s = {"session": self.session, "retain": readers.get(p, 0) > 0, "existing": None}
        if self.o["resume"]:
            s["existing"] = _resumedLevel(self.o["resume"], levelIndex, reductionFn)
        return s


def _prepareLevel(
    b: _Build,
    pyramidDoc,
    entry,
    level,
    levelIndex,
    reductionFn,
    chunks,
    grid,
    doneChunks,
    source,
    stream,
):
    """The level's document, declared to a streaming target (or adopted, with the
    chunks it still lacks in stream['only']). complete=True: nothing left."""
    o = b.o
    nChunksStored = int(np.prod(grid)) if o["materializeChunks"] else 0
    pre = "lightsheetZarrLevel."
    levelDoc = b.session.newdocument(
        "lightsheetZarrLevel",
        **{
            pre + "label": f"{entry['name']} level {levelIndex} ({reductionFn})",
            pre + "level": int(levelIndex),
            pre + "reduction_function": reductionFn,
            pre + "axes_order": _joinAxisNames(entry["axes"]),
            pre + "shape": _int_row(level["shape"]),
            pre + "chunks": [int(c) for c in chunks],
            pre + "chunk_grid": [int(g) for g in grid],
            pre + "n_chunks_stored": nChunksStored,
            pre + "chunk_index_origin": 1,
            pre + "chunk_order": "C",
            pre + "dtype": _dtypeName(level["dtype"], "zarr"),
            pre + "fill_value": 0,
            pre + "byte_order": "little",
            pre + "codec": o["codec"],
            pre + "codec_params": _codecParamsJSON(o["codec"], o["clevel"]),
            pre + "voxel_size": _row(level["scale"]),
            pre + "voxel_size_units": "micrometer",
            pre + "translation": _row(level["translation"]),
        },
    )
    levelDoc = levelDoc.set_dependency_value("lightsheetZarrPyramid_id", pyramidDoc.id)
    levelDoc = levelDoc.set_dependency_value("subject_id", o["subjectID"])
    if o["sourceFileID"]:
        levelDoc = levelDoc.set_dependency_value("source_file_id", o["sourceFileID"])

    tmpRoot = ""
    complete = False
    if stream is not None:
        tmpRoot = tempfile.mkdtemp(prefix="ndi_lightsheet_")
        nChunks = int(np.prod(grid))
        if stream["existing"] is not None:
            levelDoc = stream["existing"]
            b.session.adopt(levelDoc)
            stream["only"] = [int(i) for i in b.session.missingMembers(levelDoc, "chunk.bin")]
            if not stream["only"]:
                doneChunks += nChunks * _chunkWeight(source)
                _cleanupTmp(tmpRoot)
                return levelDoc, stream, doneChunks, True, ""
            _say(f"Resuming: {len(stream['only'])} of {nChunks} chunks still to send.")
            doneChunks += (nChunks - len(stream["only"])) * _chunkWeight(source)
        else:
            planned = [os.path.join(tmpRoot, f"chunk_{i}.bin") for i in range(1, nChunks + 1)]
            levelDoc = _addFileSeries(levelDoc, "chunk.bin", planned, list(range(1, nChunks + 1)))
            b.session.declare(levelDoc)
            stream["only"] = []
        stream["levelDoc"] = levelDoc
        stream["tmpRoot"] = tmpRoot
    return levelDoc, stream, doneChunks, complete, tmpRoot


def _keepOnly(blocks: list[dict], onlyMine: list[int], onlyTwin: list[int] | None) -> list[dict]:
    """Keep the chunks still to send (either level's, with a twin), dropping empty blocks."""
    kept = []
    for sb in blocks:
        ids = sb["idxs"]
        mine = np.isin(ids, onlyMine) if onlyMine else np.ones(ids.size, bool)
        if onlyTwin is None:
            theirs = np.zeros(ids.size, bool)
        else:
            theirs = np.isin(ids, onlyTwin) if onlyTwin else np.ones(ids.size, bool)
        keep = mine | theirs
        if not keep.any():
            continue
        nb = _block(ids[keep], sb["lo"][keep], sb["hi"][keep])
        nb["mine"], nb["theirs"] = mine[keep], theirs[keep]
        kept.append(nb)
    return kept


def _attachChunkFiles(
    b: _Build,
    levelDoc,
    source,
    level,
    chunks,
    grid,
    doneChunks,
    totalChunks,
    levelLabel,
    stream,
    twin,
    fold,
):
    o = b.o
    shape = _int_row(level["shape"])
    if len(shape) < len(chunks):
        shape += [1] * (len(chunks) - len(shape))
    tmpRoot = (
        stream["tmpRoot"] if stream is not None else tempfile.mkdtemp(prefix="ndi_lightsheet_")
    )
    nChunks = int(np.prod(grid))
    typesize = _elementSizeBytes(level["dtype"])
    seriesLocations: list[str] = [""] * nChunks

    poolSize = b.poolSize
    chunkBytes = int(np.prod(chunks)) * typesize
    amplification = _readAmplification(source, typesize)
    prefetchBytes = float(o["prefetchBytes"]) / amplification
    budget = min(max(poolSize, int(prefetchBytes // max(chunkBytes, 1))), nChunks)

    if fold:
        doneChunks = _buildFolded(
            b,
            source,
            shape,
            chunks,
            typesize,
            stream,
            fold,
            4 * prefetchBytes,
            doneChunks,
            totalChunks,
            levelLabel,
            tmpRoot,
        )
        o["profiler"].endLevel(levelLabel)
        return levelDoc, tmpRoot, doneChunks

    blocks = _planSuperBlocks(chunks, grid, shape, budget)
    hasTwin = twin is not None
    blocks = _keepOnly(
        blocks,
        stream["only"] if stream is not None else [],
        (twin["stream"]["only"] if hasTwin else None),
    )
    readSource = source
    if hasTwin:
        readSource = {
            "kind": "reduceSmartspimPair",
            "slicePaths": source["slicePaths"],
            "sourceDtype": source["sourceDtype"],
            "fromShape": source["fromShape"],
            "factor": source["factor"],
            "reductions": [source["reduction"], twin["source"]["reduction"]],
            "dtypes": [source["dtype"], twin["source"]["dtype"]],
        }
    slices = source["kind"] in ("smartspim", "reduceSmartspim")
    nReaders = max(1, o["readWorkers"]) if slices else 1
    useAsync = o["asyncPrefetch"] and poolSize > 1 and len(blocks) > 1
    readPool = b.readPool if (useAsync or (slices and b.readPool is not None)) else None

    def start(sb):
        if readPool is not None:
            return _Read(readPool, readSource, sb["loBBox"], sb["hiBBox"], nReaders)
        if o["splitReadsWithoutPool"] and slices:
            return _Read(None, readSource, sb["loBBox"], sb["hiBBox"], o["readWorkers"])
        return _Read(None, readSource, sb["loBBox"], sb["hiBBox"], 1)

    nextRead = start(blocks[0]) if (useAsync and blocks) else None
    for s, sb in enumerate(blocks, start=1):
        tBlock = time.monotonic()
        t0 = time.monotonic()
        if useAsync:
            tiles = nextRead.result()
            if s < len(blocks):
                nextRead = start(blocks[s])
        else:
            tiles = start(sb).result()
        tReadWait = time.monotonic() - t0

        mPaths, mIdxs, tm = _encodeBlock(
            tiles[0], sb, sb["mine"], chunks, o["codec"], o["clevel"], tmpRoot, b.compressPool
        )
        tPaths, tIdxs = [], []
        if hasTwin:
            tPaths, tIdxs, tt = _encodeBlock(
                tiles[1],
                sb,
                sb["theirs"],
                chunks,
                o["codec"],
                o["clevel"],
                twin["stream"]["tmpRoot"],
                b.compressPool,
            )
            _addTimes(tm, tt)
        del tiles
        for j, i in enumerate(mIdxs):
            seriesLocations[i - 1] = mPaths[j]
        t0 = time.monotonic()
        before = _sessionTiming(stream)
        if stream is not None and mIdxs:
            stream["session"].streamMembers(
                stream["levelDoc"], "chunk.bin", mIdxs, mPaths, stream["retain"]
            )
        if hasTwin and tIdxs:
            twin["stream"]["session"].streamMembers(
                twin["stream"]["levelDoc"], "chunk.bin", tIdxs, tPaths, twin["stream"]["retain"]
            )
        tUpload = time.monotonic() - t0
        after = _sessionTiming(stream)
        nDone = len(mIdxs) + len(tIdxs)
        doneChunks += nDone * _chunkWeight(source)
        t0 = time.monotonic()
        _reportProgress(
            o["progressFcn"],
            doneChunks,
            totalChunks,
            f"{levelLabel}: super-block {s}/{len(blocks)}, chunk {int(sb['idxs'][-1])}/{nChunks}",
        )
        tProgress = time.monotonic() - t0
        bboxMB = float(np.prod(sb["hiBBox"] - sb["loBBox"])) * typesize / 2**20
        o["profiler"].add(
            _profileRow(
                levelLabel,
                s,
                len(blocks),
                nDone,
                max(1, min(poolSize, max(len(mIdxs), len(tIdxs)))),
                bboxMB * amplification,
                nDone * chunkBytes / 2**20,
                tm,
                tReadWait,
                tUpload,
                before,
                after,
                tProgress,
                time.monotonic() - tBlock,
            )
        )
        _appendDebugLog(o["debugLog"], levelLabel, s, len(blocks), doneChunks, totalChunks, bboxMB)

    if stream is None:
        levelDoc = _addFileSeries(
            levelDoc, "chunk.bin", seriesLocations, list(range(1, nChunks + 1))
        )
    o["profiler"].endLevel(levelLabel)
    return levelDoc, tmpRoot, doneChunks


def _profileRow(
    level,
    s,
    n,
    chunks,
    workers,
    mbRead,
    mbChunks,
    tm,
    readWait,
    upload,
    before,
    after,
    progress,
    total,
) -> dict:
    return {
        "level": level, "superblock": s, "nSuperBlocks": n, "chunks": chunks,
        "workers": workers, "mbRead": mbRead, "mbChunks": mbChunks, "mbOut": tm["mbOut"],
        "readWait": readWait, "assemble": tm["assemble"], "compress": tm["compress"],
        "workerBusy": tm["workerBusy"], "upload": upload,
        "urls": after["urls"] - before["urls"], "stage": after["stage"] - before["stage"],
        "send": after["send"] - before["send"], "verify": after["verify"] - before["verify"],
        "progress": progress, "total": total,
    }  # fmt: skip


def _buildFolded(
    b: _Build,
    source,
    shape,
    chunks,
    typesize,
    stream,
    fold,
    budgetBytes,
    doneChunks,
    totalChunks,
    levelLabel,
    tmpRoot,
):
    """Level 0 and the FOLDED levels (level 1 of each ladder, block-reduced straight
    from the same slices) from ONE read of the slices per region."""
    o = b.o
    f = _int_row(fold[0]["source"]["factor"])
    cells = _planFoldCells(
        shape, chunks, fold[0]["chunks"], fold[0]["shape"], f, budgetBytes, typesize
    )
    kept = []
    for c in cells:
        only = stream["only"]
        c["mine"] = np.isin(c["idxs"], only) if only else np.ones(c["idxs"].size, bool)
        c["sel"] = []
        for fk in fold:
            fo = fk["stream"]["only"]
            ids = c["L1"]["idxs"]
            c["sel"].append(np.isin(ids, fo) if fo else np.ones(ids.size, bool))
        if c["mine"].any() or any(s.any() for s in c["sel"]):
            kept.append(c)
    cells = kept
    _say(
        f"{len(cells)} read(s) of the slices, each giving level 0 and {len(fold)} reduced "
        "level(s)."
    )
    readSource = {
        "kind": "smartspimFold",
        "slicePaths": source["slicePaths"],
        "dtype": source["dtype"],
        "factor": f,
        "reductions": [x["source"]["reduction"] for x in fold],
        "dtypes": [x["source"]["dtype"] for x in fold],
    }
    nReaders = max(1, o["readWorkers"])
    useAsync = o["asyncPrefetch"] and b.poolSize > 1 and len(cells) > 1

    def start(cb):
        if useAsync and b.readPool is not None:
            return _Read(b.readPool, readSource, cb["loBBox"], cb["hiBBox"], nReaders, f[2])
        if o["splitReadsWithoutPool"]:
            return _Read(None, readSource, cb["loBBox"], cb["hiBBox"], o["readWorkers"], f[2])
        return _Read(None, readSource, cb["loBBox"], cb["hiBBox"], 1)

    nextRead = start(cells[0]) if (useAsync and cells) else None
    for s, cb in enumerate(cells, start=1):
        tBlock = time.monotonic()
        t0 = time.monotonic()
        if useAsync:
            tiles = nextRead.result()
            if s < len(cells):
                nextRead = start(cells[s])
        else:
            tiles = start(cb).result()
        tReadWait = time.monotonic() - t0
        p0, i0, tm = _encodeBlock(
            tiles[0], cb, cb["mine"], chunks, o["codec"], o["clevel"], tmpRoot, b.compressPool
        )
        pk, ik = [], []
        for k, fk in enumerate(fold):
            p, i, tk = _encodeBlock(
                tiles[1 + k],
                cb["L1"],
                cb["sel"][k],
                fk["chunks"],
                o["codec"],
                o["clevel"],
                fk["stream"]["tmpRoot"],
                b.compressPool,
            )
            pk.append(p)
            ik.append(i)
            _addTimes(tm, tk)
        del tiles
        t0 = time.monotonic()
        before = _sessionTiming(stream)
        if i0:
            stream["session"].streamMembers(
                stream["levelDoc"], "chunk.bin", i0, p0, stream["retain"]
            )
        for k, fk in enumerate(fold):
            if ik[k]:
                fk["stream"]["session"].streamMembers(
                    fk["stream"]["levelDoc"], "chunk.bin", ik[k], pk[k], fk["stream"]["retain"]
                )
        tUpload = time.monotonic() - t0
        after = _sessionTiming(stream)
        nDone = len(i0) + sum(len(i) for i in ik)
        doneChunks += nDone  # folded chunks cost no read of their own
        t0 = time.monotonic()
        _reportProgress(
            o["progressFcn"],
            doneChunks,
            totalChunks,
            f"{levelLabel}: read {s}/{len(cells)} of the slices",
        )
        tProgress = time.monotonic() - t0
        bboxMB = float(np.prod(cb["hiBBox"] - cb["loBBox"])) * typesize / 2**20
        o["profiler"].add(
            _profileRow(
                levelLabel,
                s,
                len(cells),
                nDone,
                max(1, min(b.poolSize, len(i0))),
                bboxMB,
                len(i0) * int(np.prod(chunks)) * typesize / 2**20,
                tm,
                tReadWait,
                tUpload,
                before,
                after,
                tProgress,
                time.monotonic() - tBlock,
            )
        )
        _appendDebugLog(o["debugLog"], levelLabel, s, len(cells), doneChunks, totalChunks, bboxMB)
    return doneChunks


def _makeOneLevel(
    b: _Build,
    pyramidDoc,
    entry,
    level,
    levelIndex,
    reductionFn,
    chunks,
    grid,
    doneChunks,
    totalChunks,
    source,
    stream,
    twin,
    fold,
):
    """Declare (or adopt) one level and build its chunks, with any twin or folded
    levels built from the same reads. Returns (levelDoc, doneChunks, twinDoc, foldDocs)."""
    o = b.o
    twinDoc = None
    foldDocs: list[Any] = [None] * len(fold)
    tmps: list[str] = []
    try:
        levelDoc, stream, doneChunks, complete, tmpRoot = _prepareLevel(
            b,
            pyramidDoc,
            entry,
            level,
            levelIndex,
            reductionFn,
            chunks,
            grid,
            doneChunks,
            source,
            stream,
        )
        tmps.append(tmpRoot)
        if complete:
            return levelDoc, doneChunks, None, foldDocs
        keep = []
        for k, fk in enumerate(fold):
            fDoc, fStream, doneChunks, fComplete, fTmp = _prepareLevel(
                b,
                pyramidDoc,
                fk["entry"],
                fk["level"],
                fk["levelIndex"],
                fk["reductionFn"],
                fk["chunks"],
                fk["grid"],
                doneChunks,
                fk["source"],
                fk["stream"],
            )
            foldDocs[k] = fDoc
            if not fComplete:
                fk["stream"] = fStream
                tmps.append(fTmp)
                keep.append(k)
        foldAt = keep
        fold = [fold[k] for k in keep]
        if fold:
            twin = None
        if twin is not None:
            tDoc, tStream, doneChunks, tComplete, tTmp = _prepareLevel(
                b,
                pyramidDoc,
                twin["entry"],
                twin["level"],
                twin["levelIndex"],
                twin["reductionFn"],
                chunks,
                grid,
                doneChunks,
                twin["source"],
                twin["stream"],
            )
            if tComplete:
                twinDoc = tDoc
                twin = None
            else:
                twin["stream"] = tStream
                twin["levelDoc"] = tDoc
                tmps.append(tTmp)
        if o["materializeChunks"]:
            label = f"Level {levelIndex} ({reductionFn})"
            if twin is not None:
                label = f"Level {levelIndex} ({reductionFn}+{twin['reductionFn']})"
            if fold:
                label = (
                    f"Level {levelIndex} ({reductionFn}) + level {fold[0]['levelIndex']} "
                    f"({', '.join(x['reductionFn'] for x in fold)})"
                )
            levelDoc, tmpRoot, doneChunks = _attachChunkFiles(
                b,
                levelDoc,
                source,
                level,
                chunks,
                grid,
                doneChunks,
                totalChunks,
                label,
                stream,
                twin,
                fold,
            )
            tmps.append(tmpRoot)
            for k, fk in zip(foldAt, fold):
                foldDocs[k] = fk["stream"]["levelDoc"]
            if twin is not None:
                twinDoc = twin["levelDoc"]
        if stream is None:
            b.session.database_add(levelDoc)
        return levelDoc, doneChunks, twinDoc, foldDocs
    finally:
        for t in tmps:
            _cleanupTmp(t)


def makePyramid(
    session: Any,
    pyramids: list[dict],
    perEntryReduction: list[str],
    *,
    subjectID: str,
    elementID: str = "",
    sourceFileID: str = "",
    pipelineVersion: str = "",
    label: str = "",
    tileBudgetBytes: float = 32 * 2**20,
    chunks: Any = None,
    materializeChunks: bool = False,
    sourceZarrPath: str = "",
    codec: str = "raw",
    clevel: int = 5,
    progressFcn: Callable[[float, str], Any] | None = None,
    numWorkers: int = -1,
    prefetchBytes: float = 512 * 2**20,
    asyncPrefetch: bool = True,
    debugLog: str = "",
    profileLog: str = "",
    readWorkers: int = 8,
    splitReadsWithoutPool: bool = False,
    foldLevel1: bool = True,
    profileEverySeconds: float = 600,
    levelSources: dict[str, dict] | None = None,
    channelNames: str = "",
    resume: dict | None = None,
) -> tuple[Any, list[Any], bool]:
    """Write one lightsheetZarrPyramid and one lightsheetZarrLevel per unique level path.

    Returns ``(pyramidDoc, levelDocs, sharedLevel0)``: the pyramid document,
    the level documents in level-path order (finest first), and whether level
    0 is shared by more than one entry. See the module docstring for the
    options; they are MATLAB's name-value options, with the same names and
    defaults (``numWorkers=-1`` here means one worker per core).
    """
    from ndi.fun.doc_lightsheet.BuildProfile import BuildProfile
    from ndi.fun.doc_lightsheet.chooseTileShape import chooseTileShape

    if codec not in ("raw", "blosc-zstd"):
        raise ValueError(f"codec must be 'raw' or 'blosc-zstd'; got {codec!r}.")
    if not 1 <= int(clevel) <= 9:
        raise ValueError("clevel must be an integer from 1 to 9.")
    if numWorkers < -1:
        raise ValueError("numWorkers must be -1, 0 or a positive integer.")
    levelSources = dict(levelSources or {})
    if materializeChunks and not sourceZarrPath and not levelSources:
        raise ValueError(
            "materializeChunks=True requires sourceZarrPath (or levelSources) so chunks can "
            "be read from a source."
        )
    if len(pyramids) != len(perEntryReduction):
        raise ValueError(
            f"perEntryReduction ({len(perEntryReduction)}) must have one entry per pyramid "
            f"({len(pyramids)})."
        )
    o: dict[str, Any] = {
        "subjectID": subjectID,
        "elementID": elementID,
        "sourceFileID": sourceFileID,
        "pipelineVersion": pipelineVersion,
        "label": label,
        "tileBudgetBytes": tileBudgetBytes,
        "chunks": chunks,
        "materializeChunks": materializeChunks,
        "sourceZarrPath": sourceZarrPath,
        "codec": codec,
        "clevel": int(clevel),
        "progressFcn": progressFcn,
        "numWorkers": numWorkers,
        "prefetchBytes": prefetchBytes,
        "asyncPrefetch": asyncPrefetch,
        "debugLog": debugLog,
        "profileLog": profileLog,
        "readWorkers": int(readWorkers),
        "splitReadsWithoutPool": splitReadsWithoutPool,
        "foldLevel1": foldLevel1,
        "levelSources": levelSources,
        "channelNames": channelNames,
        "resume": resume,
    }
    b = _Build(session, pyramids, list(perEntryReduction), o)
    po = b.pathOrder

    first = pyramids[0]
    firstLevel = first["levels"][0]
    axesOrder = _joinAxisNames(first["axes"])
    label = label or str(first.get("name", ""))

    streaming = materializeChunks and hasattr(session, "streamMembers")
    resuming = bool(resume)
    if resuming and not streaming:
        raise ValueError(
            "Only a streamed build (to a target such as ndi.cloud SessionWriter) can resume."
        )
    docLabel = f"{label} (uploading)" if streaming else label
    pre = "lightsheetZarrPyramid."
    pyramidDoc = session.newdocument(
        "lightsheetZarrPyramid",
        **{
            pre + "label": docLabel,
            pre + "pyramid_name": str(first.get("name", "")),
            pre + "pyramid_type": str(first.get("type", "")),
            pre + "axes_order": axesOrder,
            pre + "axes_units": ",".join(_collectAxisUnits(first["axes"])),
            pre + "channel_names": channelNames,
            pre + "n_channels": _channelCount(_int_row(firstLevel["shape"]), axesOrder),
            pre + "shape_level0": _int_row(firstLevel["shape"]),
            pre + "voxel_size_level0": _row(firstLevel["scale"]),
            pre + "voxel_size_units": "micrometer",
            pre + "translation_level0": _row(firstLevel["translation"]),
            pre + "dtype": _dtypeName(firstLevel["dtype"], "zarr"),
            pre + "pipeline_version": pipelineVersion,
            pre + "byte_order": "little",
        },
    )
    pyramidDoc = pyramidDoc.set_dependency_value("subject_id", subjectID)
    if elementID:
        pyramidDoc = pyramidDoc.set_dependency_value("element_id", elementID)
    if sourceFileID:
        pyramidDoc = pyramidDoc.set_dependency_value("source_file_id", sourceFileID)
    if resuming:
        pyramidDoc = resume["pyramidDoc"]
        session.adopt(pyramidDoc)
    else:
        session.database_add(pyramidDoc)

    # Plan every level's chunk shape and grid; progress counts WORK (a chunk
    # reduced straight from the slices counts prod(factor)).
    totalChunks = 0
    nChunksAll = 0
    for p in po:
        entry, level, _ = b.levelMeta(p)
        if chunks is None or np.asarray(chunks).size == 0:
            c = _int_row(
                chooseTileShape(
                    _int_row(level["shape"]),
                    _joinAxisNames(entry["axes"]),
                    _row(level["scale"]),
                    _dtypeName(level["dtype"], "matlab"),
                    tileBudgetBytes,
                )
            )
        else:
            c = _clampChunksToShape(chunks, _int_row(level["shape"]))
        g = [-(-int(s) // int(k)) for s, k in zip(_int_row(level["shape"]), c)]
        b.levelChunks.append(c)
        b.levelGrids.append(g)
        if materializeChunks:
            totalChunks += int(np.prod(g)) * _chunkWeight(levelSources.get(p))
            nChunksAll += int(np.prod(g))
    if streaming and foldLevel1 and materializeChunks:
        for fk in b.foldCandidates([False] * len(po)):
            totalChunks -= int(np.prod(b.levelGrids[fk])) * (_chunkWeight(levelSources[po[fk]]) - 1)

    b.poolSize = _resolvePoolSize(numWorkers) if materializeChunks else 1
    if materializeChunks:
        asyncStr = "on (read overlaps compress)" if asyncPrefetch and b.poolSize > 1 else "off"
        _say(
            f"Parallel workers: {b.poolSize}. Prefetch budget: {prefetchBytes / 2**20:.0f} MB "
            f"per read. Async prefetch: {asyncStr}. Total chunks: {nChunksAll} across "
            f"{len(po)} level path(s). Codec: {codec}."
        )
    o["profiler"] = BuildProfile(profileLog, profileEverySeconds)

    levelDocs: list[Any] = [None] * len(po)
    docByPath: dict[str, Any] = {}
    sharedLevel0 = False
    doneChunks = 0
    readers: dict[str, int] = {}
    for p in po:
        frm = _reducedFrom(levelSources, p)
        if frm:
            readers[frm] = readers.get(frm, 0) + 1
    built = [False] * len(po)

    if b.poolSize > 1:
        b.compressPool = ThreadPoolExecutor(b.poolSize, thread_name_prefix="ndi-compress")
        b.readPool = ThreadPoolExecutor(max(1, readWorkers) + 1, thread_name_prefix="ndi-read")
    try:
        for idx, p in enumerate(po):
            if built[idx]:
                continue
            entry, level, reductionFn = b.levelMeta(p)
            if len(b.pathReductions[p]) > 1 and idx == 0:
                sharedLevel0 = True
            if materializeChunks:
                _say(
                    f"Level {idx + 1}/{len(po)} ({entry['name']}, {reductionFn}): shape="
                    f"{_int_row(level['shape'])}, chunks={b.levelChunks[idx]}, "
                    f"{int(np.prod(b.levelGrids[idx]))} chunks to write."
                )
            _reportProgress(
                progressFcn,
                doneChunks,
                totalChunks,
                f"Level {idx + 1}/{len(po)} ({entry['name']}, {reductionFn}): starting",
            )
            source = b.resolveLevelSource(p, entry, level, docByPath) if materializeChunks else None
            stream = b.newStream(p, idx, reductionFn, readers) if streaming else None

            fold: list[dict] = []
            if streaming and foldLevel1 and source and source["kind"] == "smartspim":
                for fq in b.foldCandidates(built):
                    fEntry, fLevel, fRed = b.levelMeta(po[fq])
                    fSource = b.resolveLevelSource(po[fq], fEntry, fLevel, docByPath)
                    fSource["folded"] = True
                    fold.append({
                        "entry": fEntry, "level": fLevel, "levelIndex": fq,
                        "reductionFn": fRed, "source": fSource,
                        "stream": b.newStream(po[fq], fq, fRed, readers),
                        "chunks": b.levelChunks[fq], "grid": b.levelGrids[fq],
                        "shape": _int_row(fLevel["shape"]), "q": fq,
                    })  # fmt: skip
                    _say(
                        f"Level {fq + 1}/{len(po)} ({fEntry['name']}, {fRed}) is built during "
                        "this level, from the same reads of the slices."
                    )
            twin = None
            q = -1
            if streaming and source and source["kind"] == "reduceSmartspim":
                q = b.findTwin(idx, built)
            if q >= 0:
                tEntry, tLevel, tRed = b.levelMeta(po[q])
                twin = {
                    "entry": tEntry, "level": tLevel, "levelIndex": q, "reductionFn": tRed,
                    "source": b.resolveLevelSource(po[q], tEntry, tLevel, docByPath),
                    "stream": b.newStream(po[q], q, tRed, readers),
                }  # fmt: skip
                _say(
                    f"Level {q + 1}/{len(po)} ({tEntry['name']}, {tRed}) is built with it, from "
                    "the same reads of the slices."
                )
            levelDocs[idx], doneChunks, twinDoc, foldDocs = _makeOneLevel(
                b,
                pyramidDoc,
                entry,
                level,
                idx,
                reductionFn,
                b.levelChunks[idx],
                b.levelGrids[idx],
                doneChunks,
                totalChunks,
                source,
                stream,
                twin,
                fold,
            )
            docByPath[p] = levelDocs[idx]
            for fk, fDoc in zip(fold, foldDocs):
                if fDoc is not None:
                    levelDocs[fk["q"]] = fDoc
                    docByPath[po[fk["q"]]] = fDoc
                    built[fk["q"]] = True
            if twinDoc is not None:
                levelDocs[q] = twinDoc
                docByPath[po[q]] = twinDoc
                built[q] = True
            frm = _reducedFrom(levelSources, p)
            if streaming and frm:
                readers[frm] -= 1
                if readers[frm] == 0:
                    session.releaseMembers(docByPath[frm])
    finally:
        for pool in (b.compressPool, b.readPool):
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)

    if streaming:
        pyramidDoc = pyramidDoc.setproperties(**{"lightsheetZarrPyramid.label": label})
        session.replaceOnCommit(pyramidDoc)
    o["profiler"].finish()
    _reportProgress(progressFcn, max(doneChunks, totalChunks), max(totalChunks, 1), "Done.")
    return pyramidDoc, levelDocs, sharedLevel0
