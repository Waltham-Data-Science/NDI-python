"""Turn a pyramid document into what a multiscale viewer needs.

No napari import: everything here is testable headlessly, which is the
whole reason the package is split this way.

WHAT A MULTISCALE VIEWER NEEDS, and why each piece is easy to get wrong:

    the ladder     one array per level, finest first, each lazy so that
                   opening a 4.9 GB pyramid reads nothing until something
                   is drawn.
    scale          the size of one FINEST-level bin in world units.
                   napari applies the layer's scale to level 0 and derives
                   the coarser levels from the shape ratios, so passing a
                   per-level scale is not how it works.
    translate      where the finest level's first bin sits in the world.
                   This is the pyramid origin, and forgetting it puts the
                   whole section somewhere plausible and wrong -- which
                   looks fine until you overlay cells and they miss.

WORLD FRAME. Axes are (row, column) = (y, x), napari's order, and the
unit is whatever ``pixel_size_units`` the pyramid records (micrometer for
Stereo-seq). Source coordinates are converted, not preserved: the frame
cell centroids arrive in is source units, so a caller overlaying them
must apply the same transform, and :func:`worldTransform` returns it
rather than leaving each caller to rebuild it.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np

from ....fun.doc_gene import levelTable, readTileFile, renderTile

__all__ = ["levelArrays", "layerSpec", "worldTransform", "sourceToWorld"]


def _require_dask():
    try:
        import dask
        import dask.array as da
    except ImportError as e:  # pragma: no cover - exercised by absence
        raise ImportError(
            "dask is required to build a lazy pyramid ladder. Install it "
            f"with:  pip install 'ndi[napari]'\n(Original error: {e})"
        ) from e
    return dask, da


class _TileFetcher:
    """Fetches tile bytes on threads that own their own session handle.

    PASSING THE SESSION INTO A BLOCK IS NOT THE PROBLEM. The object crosses
    a thread boundary fine. Its SQLite connection does not: NDI's database
    belongs to the thread that opened it, and dask runs blocks on a thread
    pool -- which is also how napari drives multiscale loading. A lock does
    not help, because the obstacle is thread IDENTITY, not concurrency.

    What makes that dangerous rather than merely broken is the shape of the
    failure. Raw sqlite3 raises ProgrammingError naming both thread ids,
    which would be an easy fix. But did's read path catches it and returns
    None, and session_base reads None as "no such document" -- so the error
    is ``ndi_document <id> not found`` for a document that is present, and
    only under the threaded scheduler. The synchronous one passes.

    SO WHY NOT A SESSION PER DASK WORKER? Because opening a real session
    takes SECONDS, not milliseconds, and napari's pool is sized to the
    machine. That would put a session build in front of the first tile
    each pool thread touches. Instead this is a small server: dedicated
    threads own a session each, every fetch is a request to one of them,
    and the cost is paid ``workers`` times for the life of the viewer.

    ``workers`` DEFAULTS TO 1 -- one session, opened once, exactly as if a
    separate process held it. Raising it buys overlap, since a cloud fetch
    is latency rather than CPU and two outstanding requests take about as
    long as one; it costs another whole session per worker, which is the
    expensive thing here. Raise it only if panning is visibly
    fetch-bound, and call ``warm()`` either way.

    A SEPARATE PROCESS would be the same architecture with an IPC hop
    added. It is not obviously worth it: what crosses the boundary is a
    PATH, not tile bytes, and the fetch is I/O so the GIL is released
    anyway. The reason to reach for one is if a cloud-backed session turns
    out to share global state that per-session isolation does not fix --
    untested here, and the seam for it is this class alone: swap the
    executor and ``levelArrays`` does not change.
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

        Only a path-backed session is reopened. Anything holding a live
        client or credentials is left alone rather than duplicated on a
        guess: reopening one could re-authenticate per thread, which is
        worse than the serialization it would buy.
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
                    thread_name_prefix="ndi-tile",
                    initializer=self._initThread,
                )
        return self._pool

    def warm(self) -> None:
        """Build the session handles now, off the calling thread.

        Optional, and worth calling right after the viewer window appears:
        it moves the one-off session cost into the moment the user is
        looking at an empty canvas rather than into the first pan.
        """
        pool = self._ensurePool()
        if pool is None:
            return
        for f in [pool.submit(lambda: None) for _ in range(self._workers)]:
            f.result()

    def _resolve(self, doc, filename) -> str:
        s = getattr(self._local, "session", None) or self._session
        fh = s.database_openbinarydoc(doc, filename)
        try:
            return fh.fullpathfilename
        finally:
            s.database_closebinarydoc(fh)

    def tilePath(self, doc, filename) -> str:
        """Resolve one binary file to a local path, fetching it if remote.

        The handle is closed before the path is returned, and the file
        outlives the handle -- which is what lets the caller read it with a
        plain file reader, as the eager version did.

        A RESOLVED PATH IS REMEMBERED, and this is worth more than saving a
        round trip. DID names a cached file by its immutable uid, so the
        path for a tile cannot change meaning: the file is either still
        there or gone, never different. Once it is known, a hit is one
        stat() -- which any thread may do, because the filesystem has no
        opinion about which thread opened the session. So a re-render after
        a gene toggle or a band change never reaches the fetch threads at
        all, where before every block went through the queue to be told
        what it already knew.

        The file CAN disappear, which is why the memo is checked rather
        than trusted, and why a read that fails behind a passing check
        falls back to fetching once more (see _readable).
        """
        key = (getattr(doc, "id", str(doc)), filename)
        known = self._paths.get(key)
        if known is not None and os.path.exists(known):
            return known
        path = self._fetch(doc, filename)
        # A plain dict assignment; the GIL makes it atomic, and two threads
        # racing the same tile resolve it to the same path anyway.
        self._paths[key] = path
        return path

    def forget(self, doc, filename) -> None:
        """Drop a memoised path, so the next call fetches it again.

        For the narrow race the memo cannot rule out: the file passed
        os.path.exists and was evicted before it could be read.
        """
        self._paths.pop((getattr(doc, "id", str(doc)), filename), None)

    def _fetch(self, doc, filename) -> str:
        if threading.get_ident() == self._owner:
            return self._resolve(doc, filename)
        pool = self._ensurePool()
        if pool is None:
            # No way to build a second handle for this session type. There
            # is nothing safe to do from here, so say what is wrong rather
            # than letting did turn it into "document not found".
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


def worldTransform(session, pyr_doc) -> tuple[tuple[float, float], tuple[float, float]]:
    """The ``(scale, translate)`` that place a pyramid in world coordinates.

    Both are ``(row, column)`` = ``(y, x)``, napari's axis order.

    scale is the size of one FINEST-level bin, because napari applies the
    layer scale to level 0 and infers the rest from shape ratios.
    translate is where that level's first bin sits, which is the pyramid
    origin converted to world units.

    Returns:
        ``((scale_y, scale_x), (translate_y, translate_x))``.
    """
    _levels, frame = levelTable(session, pyr_doc)
    sy = float(frame["basePixelSizeY"])
    sx = float(frame["basePixelSizeX"])
    return (sy, sx), (float(frame["originY"]) * sy, float(frame["originX"]) * sx)


def sourceToWorld(session, pyr_doc, x, y):
    """Convert SOURCE coordinates to the world frame the ladder is placed in.

    Cell centroids and contours arrive in source units. Anything overlaid
    on the pyramid has to go through the same transform the image layer
    got, or it lands somewhere plausible and wrong.

    Args:
        x, y: source coordinates, array-like.

    Returns:
        ``(row, column)`` arrays in world units -- note the swap: source
        x is the COLUMN axis and source y is the ROW axis.
    """
    (sy, sx), _t = worldTransform(session, pyr_doc)
    # The origin is NOT subtracted. The layer's translate already carries
    # it, so subtracting here would apply it twice.
    return np.asarray(y, float) * sy, np.asarray(x, float) * sx


def levelArrays(session, pyr_doc, gene_rows=None, density: bool = True) -> list[Any]:
    """One lazy dask array per pyramid level, finest first.

    Blocks are tiles. A tile that was never written contributes zeros
    without touching the filesystem, so an empty corner of the section
    costs nothing. Nothing is read until something is drawn.

    Args:
        session: an ndi.session or ndi.dataset.
        pyr_doc: a spatialGeneExpressionPyramid document.
        gene_rows: ZERO-BASED geneList rows to include, or None for all.
        density: divide each level by ``binSize ** 2``, giving counts per
            base pixel. Binning SUMS, so without this a coarse level is
            ``binSize ** 2`` brighter than a fine one and one contrast
            range cannot serve the whole ladder -- which a multiscale
            viewer needs, since it switches levels as you zoom and the
            brightness would jump at each switch.

    Returns:
        A list of dask arrays, finest first.
    """
    dask, da = _require_dask()
    levels, _frame = levelTable(session, pyr_doc)
    fetcher = _TileFetcher(session)

    from ....fun.doc_gene import _find_level

    out = []
    for lv in levels:
        b = lv["binSize"]
        th, tw = lv["tileHeight"], lv["tileWidth"]
        rows, cols = lv["tileRows"], lv["tileColumns"]
        lh, lw = lv["levelHeight"], lv["levelWidth"]

        tile_doc, _props = _find_level(session, pyr_doc, b)
        stored = set(tile_doc.current_file_list())
        scale = b if density else 1

        # NOTHING IS FETCHED HERE. current_file_list() says which tiles
        # exist, which is document metadata already in hand, and the block
        # opens its own tile when dask asks for it. The eager version
        # resolved every tile of every level up front, which on a
        # directory-backed session is free path resolution but on a
        # cloud-backed one DOWNLOADS THE WHOLE PYRAMID before anything is
        # drawn -- database_openbinarydoc retrieves a remote file, so
        # "resolve the path" and "fetch the bytes" are the same call.
        # The block being lazy never helped, because the cost was already
        # paid by the time dask chose its blocks.
        def block(
            r,
            c,
            _fetch=fetcher,
            _doc=tile_doc,
            _cols=cols,
            _stored=stored,
            _th=th,
            _tw=tw,
            _scale=scale,
        ):
            name = f"tile.bin_{r * _cols + c}"
            if name not in _stored:
                return np.zeros((_th, _tw), np.float32)  # missing tile costs nothing
            try:
                tile = readTileFile(_fetch.tilePath(_doc, name))
            except OSError:
                # The memoised path passed os.path.exists and then went
                # away -- a cache eviction between the check and the read.
                # Narrow, but the whole point of memoising is that this is
                # the only way it can be wrong, so it is handled rather
                # than left to surface as a corrupt-looking tile.
                _fetch.forget(_doc, name)
                tile = readTileFile(_fetch.tilePath(_doc, name))
            return renderTile(tile, gene_rows, _th, _tw, binSize=_scale)

        grid = [
            [
                da.from_delayed(dask.delayed(block)(r, c), shape=(th, tw), dtype=np.float32)
                for c in range(cols)
            ]
            for r in range(rows)
        ]
        # Crop to the level's TRUE size. The assembled grid is
        # rows*th by cols*tw, which overshoots whenever the level does not
        # divide evenly by the grid. Leaving the padding on makes a level
        # cover more ground than the extent it claims, so the levels of one
        # pyramid disagree about their own field of view and a viewer
        # registering them by shape ratio misaligns them -- worse at coarse
        # levels, where the rounding is proportionally larger.
        out.append(da.block(grid)[:lh, :lw])

    return out


def layerSpec(
    session, pyr_doc, gene_rows=None, density: bool = True, name: str | None = None
) -> dict[str, Any]:
    """Everything ``napari.Viewer.add_image`` needs, as keyword arguments.

    Returned rather than applied, so the placement can be asserted in a
    headless test and so a caller can override any of it before drawing.

    Args:
        name: layer name; defaults to the pyramid's label, or "genes".

    Returns:
        A dict with ``data``, ``multiscale``, ``scale``, ``translate``,
        ``name`` and ``rgb``.
    """
    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
    scale, translate = worldTransform(session, pyr_doc)
    return {
        "data": levelArrays(session, pyr_doc, gene_rows, density),
        "multiscale": True,
        "scale": scale,
        "translate": translate,
        "name": name or (p.get("label") or "genes"),
        "rgb": False,
    }
