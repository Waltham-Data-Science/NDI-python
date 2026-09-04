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

        # Resolve every tile's PATH now, on this thread, and let the blocks
        # read plain files.
        #
        # The blocks must not touch the session. NDI's database is SQLite,
        # whose connections are not usable from another thread, and dask
        # runs blocks on a thread pool by default -- which is also how
        # napari drives multiscale loading. A block that called
        # database_openbinarydoc therefore failed with "ndi_document ... not
        # found", the database returning nothing rather than raising, and
        # only under the threaded scheduler: the synchronous one passed.
        # That is the worst shape a bug can have before a live demo, so the
        # blocks are pure by construction instead.
        #
        # Only metadata is eager. The bytes -- the expensive part -- stay
        # lazy. On a directory-backed session this is path resolution and
        # costs nothing; a cloud-backed session that fetches on open would
        # pay here instead, which is a real limit of this approach and the
        # reason it is written down.
        paths = {}
        for r in range(rows):
            for c in range(cols):
                name = f"tile.bin_{r * cols + c}"
                if name not in stored:
                    continue
                fh = session.database_openbinarydoc(tile_doc, name)
                try:
                    paths[(r, c)] = fh.fullpathfilename
                finally:
                    session.database_closebinarydoc(fh)

        def block(r, c, _paths=paths, _th=th, _tw=tw, _scale=scale):
            path = _paths.get((r, c))
            if path is None:
                return np.zeros((_th, _tw), np.float32)
            return renderTile(readTileFile(path), gene_rows, _th, _tw, binSize=_scale)

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
