"""Spatial gene expression documents: the tile binary codec.

Mirrors ``+ndi/+fun/+doc/+gene/`` in NDI-matlab. Kept in its own module
rather than folded into ``doc.py`` on the precedent of ``doc_table.py``:
a cohesive area under ``+fun/+doc/`` large enough to stand alone.

Implements ``tile_format_version`` 1 of ``spatialGeneExpressionTiles``,
specified in
``ndi_common/database_documents/data/spatialGeneExpressionTiles.md``,
which is the authority when this docstring and it disagree.

Layout, all little-endian, field types named by the level document's
``data_type_*`` entries so a level can widen a field without a new
format version::

    n_pixels    uint32
    n_nonzero   uint32
    x           uint16 [n_pixels]      tile-local, this level's pixels
    y           uint16 [n_pixels]
    offset      uint32 [n_pixels + 1]  CSR row pointer over pixels
    gene_index  uint32 [n_nonzero]     row of the geneList's genes.tsv
    count       uint16 [n_nonzero]

CSR over occupied pixels: a pixel's coordinate is stored once rather than
once per transcript, which is why a tiled pyramid is smaller than the GEF
it came from.

INDICES ARE ZERO-BASED throughout -- ``gene_index`` and the tile-local
coordinates alike. That is deliberate and matches NDI-matlab, which also
keeps them zero-based against its own convention: these bytes are written
by one language and read by another, and shifting indices on one side
only is the likeliest way for the two to diverge. It is the bridge's
stated ``indexing_policy``, "0-based for internal data". Conversion to
1-based happens at the point of use, inside :func:`renderTile`.

The format is verified against ``conformance_tile.bin``, the same fixture
NDI-matlab's ``TestTileFormat`` asserts on, so all three implementations
agree on one artifact rather than pairwise with each other.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["readTileFile", "writeTileFile", "renderTile"]

# Named for the document's data_type_* fields. A level that widens one of
# these stays readable by dtype lookup rather than by format version.
_DTYPES: dict[str, Any] = {
    "offset": np.dtype("<u4"),
    "coordinate": np.dtype("<u2"),
    "gene_index": np.dtype("<u4"),
    "count": np.dtype("<u2"),
}


def readTileFile(source: Any) -> dict[str, Any]:
    """Read one ``tile.bin_N`` tile.

    Args:
        source: a path, an open binary file object, or raw ``bytes``.
            The file-object form matters:
            :meth:`ndi.session.database_openbinarydoc` returns an open
            handle rather than a path, unlike MATLAB's, which returns an
            object carrying ``fullpathfilename``. Accepting both keeps
            callers from having to spill a database file to disk first.

    Returns:
        dict with ``n_pixels``, ``n_nonzero`` and the CSR arrays ``x``,
        ``y``, ``offset``, ``gene_index``, ``count``. Every index is
        ZERO-BASED.
    """
    if isinstance(source, (bytes, bytearray)):
        return _unpack(bytes(source))
    if hasattr(source, "read"):
        return _unpack(source.read())
    with open(source, "rb") as fh:
        return _unpack(fh.read())


def writeTileFile(filename: str, x, y, gene_index, count) -> None:
    """Write one tile from flat, pixel-repeated records.

    Records need not arrive sorted or grouped; they are stably sorted on
    the ``(y, x)`` key here, so a caller cannot produce a malformed tile
    by handing them over in the wrong order.

    Args:
        filename: path to write.
        x: tile-local pixel column per record.
        y: tile-local pixel row per record.
        gene_index: ZERO-BASED geneList row per record.
        count: UMI count per record.
    """
    with open(filename, "wb") as fh:
        fh.write(_pack(x, y, gene_index, count))


def renderTile(
    tile: dict[str, Any], gene_rows, h: int, w: int, binSize: int = 1, out=None
) -> np.ndarray:
    """Collapse a tile's gene axis into a dense ``(h, w)`` raster.

    Args:
        tile: as returned by :func:`readTileFile`.
        gene_rows: ZERO-BASED geneList rows to include, or None for every
            gene. A boolean mask of length n_genes is also accepted and is
            the fast path when the selection is large.
        h: tile height in this level's pixels.
        w: tile width in this level's pixels.
        binSize: divide every value by ``binSize ** 2``, turning summed
            counts into counts per base pixel. Binning SUMS, so without
            this a coarse level is ``binSize ** 2`` brighter than a fine
            one and a single contrast range cannot serve a whole
            multiresolution layer. Nothing changes on disk: tiles stay raw
            integer counts and the divisor comes from ``bin_size``.
        out: optional array to accumulate into.

    Returns:
        float32 array of shape ``(h, w)``.
    """
    img = np.zeros((h, w), np.float32) if out is None else out
    if tile["n_pixels"] == 0:
        return img
    gi, cnt, off = tile["gene_index"], tile["count"], tile["offset"]

    if gene_rows is None:
        per_pixel = np.add.reduceat(cnt.astype(np.float32), off[:-1])
    else:
        g = np.asarray(gene_rows)
        # A boolean mask is one indexing op; np.isin re-sorts the
        # selection on every call, once per tile per level.
        keep = g[gi] if g.dtype == bool else np.isin(gi, g)
        if not keep.any():
            return img
        per_pixel = np.add.reduceat(np.where(keep, cnt, 0).astype(np.float32), off[:-1])
    # reduceat on an empty run returns the element at that index rather
    # than zero, so empty pixels have to be zeroed explicitly.
    per_pixel[np.diff(off) == 0] = 0

    if binSize != 1:
        per_pixel = per_pixel * np.float32(1.0 / (binSize * binSize))
    np.add.at(img, (tile["y"].astype(np.int64), tile["x"].astype(np.int64)), per_pixel)
    return img


# -- codec ---------------------------------------------------------------


def _pack(x, y, gene_index, count) -> bytes:
    x = np.asarray(x, np.int64)
    y = np.asarray(y, np.int64)
    gene_index = np.asarray(gene_index, np.int64)
    count = np.asarray(count, np.int64)
    if not (len(x) == len(y) == len(gene_index) == len(count)):
        raise ValueError(
            f"x, y, gene_index and count must be the same length, got "
            f"{len(x)}, {len(y)}, {len(gene_index)}, {len(count)}"
        )

    if len(x) == 0:
        return b"".join(
            [
                np.uint32(0).tobytes(),
                np.uint32(0).tobytes(),
                np.zeros(1, _DTYPES["offset"]).tobytes(),
            ]
        )

    # (y, x) packed into one integer so the sort is a single pass. y in
    # the high half makes the order row-major, matching index_order.
    key = (y << 32) | x
    order = np.argsort(key, kind="stable")
    key, x, y = key[order], x[order], y[order]
    gene_index, count = gene_index[order], count[order]

    new = np.empty(len(key), bool)
    new[0] = True
    np.not_equal(key[1:], key[:-1], out=new[1:])
    starts = np.flatnonzero(new)
    offset = np.append(starts, len(key)).astype(_DTYPES["offset"])

    return b"".join(
        [
            np.uint32(len(starts)).tobytes(),
            np.uint32(len(key)).tobytes(),
            x[starts].astype(_DTYPES["coordinate"]).tobytes(),
            y[starts].astype(_DTYPES["coordinate"]).tobytes(),
            offset.tobytes(),
            gene_index.astype(_DTYPES["gene_index"]).tobytes(),
            count.astype(_DTYPES["count"]).tobytes(),
        ]
    )


def _unpack(raw: bytes) -> dict[str, Any]:
    o = 0
    n_pixels = int(np.frombuffer(raw, _DTYPES["offset"], 1, o)[0])
    o += _DTYPES["offset"].itemsize
    n_nonzero = int(np.frombuffer(raw, _DTYPES["offset"], 1, o)[0])
    o += _DTYPES["offset"].itemsize

    # Validate the whole size BEFORE reading any field. Otherwise a
    # truncated file surfaces as numpy's "buffer is smaller than requested
    # size", which says nothing about which field ran out or what the
    # header claimed.
    expected = (
        2 * _DTYPES["offset"].itemsize
        + 2 * n_pixels * _DTYPES["coordinate"].itemsize
        + (n_pixels + 1) * _DTYPES["offset"].itemsize
        + n_nonzero * _DTYPES["gene_index"].itemsize
        + n_nonzero * _DTYPES["count"].itemsize
    )
    if len(raw) != expected:
        raise ValueError(
            f"tile file has {len(raw)} bytes but its header describes "
            f"{expected} (n_pixels={n_pixels}, n_nonzero={n_nonzero}); "
            f"the file is truncated or not format version 1"
        )

    def take(dt, n):
        nonlocal o
        a = np.frombuffer(raw, dt, n, o)
        o += n * dt.itemsize
        return a

    x = take(_DTYPES["coordinate"], n_pixels)
    y = take(_DTYPES["coordinate"], n_pixels)
    offset = take(_DTYPES["offset"], n_pixels + 1)
    gene_index = take(_DTYPES["gene_index"], n_nonzero)
    count = take(_DTYPES["count"], n_nonzero)
    assert o == len(raw), "size check above should have caught this"
    return {
        "n_pixels": n_pixels,
        "n_nonzero": n_nonzero,
        "x": x,
        "y": y,
        "offset": offset,
        "gene_index": gene_index,
        "count": count,
    }


# =========================================================================
# Document makers
#
# Mirrors +ndi/+fun/+doc/+gene/{makeGeneList,makePyramid,readViewport,
# exportRegion}.m and its private/storeDoc.m.
# =========================================================================

import os
import tempfile
import warnings

from ..document import ndi_document
from ..query import ndi_query

__all__ += ["makeGeneList", "makePyramid", "readViewport", "exportRegion"]


def _blank(document_type: str, **properties):
    """Construct a blank document by type name, subdirectory or not.

    ASYMMETRY, worked around here rather than papered over. MATLAB's
    ``ndi.document`` resolves a bare class name against the whole
    ``database_documents`` tree, so ``ndi.document('geneList')`` finds
    ``data/geneList.json``. NDI-python's ``read_blank_definition`` looks
    only at the top level, so the same call needs ``'data/geneList'``.
    That affects every document under a subdirectory -- ``image``,
    ``generic_file`` and the stimulus family included -- not just these.

    Trying the bare name first means this code reads the same as the
    MATLAB it mirrors, and starts working by the symmetric path the day
    the resolver is fixed, without an edit here.
    """
    try:
        return ndi_document(document_type, **properties)
    except FileNotFoundError:
        return ndi_document(f"data/{document_type}", **properties)


def _store_doc(session, doc, file_names, file_paths):
    """Attach files to a document and add it to the database.

    The single place in this module where a document acquires files and
    enters the database, so a mistake in the document API is one
    correction rather than several.

    Files are ingested, so the originals may be deleted once the database
    has copied them. Pass copies if the caller still needs them.
    """
    if len(file_names) != len(file_paths):
        raise ValueError(
            f"file_names and file_paths must be the same length, got "
            f"{len(file_names)} and {len(file_paths)}"
        )
    for name, path in zip(file_names, file_paths):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"file {path!r} for document entry {name!r} does not exist")
        doc = doc.add_file(name, path)
    session.database_add(doc)
    return doc


def makeGeneList(
    session,
    gene_id,
    gene_name,
    genomeAssembly: str = "",
    annotationSource: str = "",
    geneIdNamespace: str = "",
    geneSymbolNamespace: str = "",
    label: str = "",
):
    """Create a ``geneList`` document from accessions and symbols.

    ``n_genes``, ``gene_name_completeness`` and ``n_duplicate_gene_names``
    are computed here rather than supplied. The last matters: symbols are
    NOT unique in real annotations -- the opossum SAW gene list repeats
    5,531 of them, PAX8 across 89 rows -- so a consumer that keys on
    symbol silently discards most of such a gene. Recording the count lets
    it know not to.

    Args:
        session: an ndi.session or ndi.dataset.
        gene_id: accessions, one per gene row.
        gene_name: symbols, one per gene row; '' where the annotation has
            none.
        genomeAssembly: the assembly the annotation is against. Describes
            the ANNOTATION, not the animal -- the subject's species
            belongs on an animalsubject or openminds_subject document.
        annotationSource: e.g. 'Ensembl 110'.
        geneIdNamespace: e.g. 'Ensembl'.
        geneSymbolNamespace: e.g. 'HGNC'.
        label: free text.

    Returns:
        The stored ndi_document.
    """
    gene_id = [str(g) for g in gene_id]
    gene_name = [str(g) for g in gene_name]
    n = len(gene_id)
    if len(gene_name) != n:
        raise ValueError(
            f"gene_id and gene_name must be the same length, got {n} and " f"{len(gene_name)}"
        )

    named = [g for g in gene_name if g]
    completeness = (len(named) / n) if n else 0.0
    # Symbols carried by more than one row.
    seen: dict[str, int] = {}
    for g in named:
        seen[g] = seen.get(g, 0) + 1
    n_dup = sum(1 for v in seen.values() if v > 1)

    fd, tsv_path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w") as fh:
        fh.write("gene_index\tgene_id\tgene_name\n")
        for i in range(n):
            # gene_index is written explicitly and is ZERO-BASED, matching
            # the tile files and NDI-matlab. A reader should assert it
            # rather than trust that row order survived transport.
            fh.write(f"{i}\t{gene_id[i]}\t{gene_name[i]}\n")

    doc = (
        _blank(
            "geneList",
            geneList={
                "label": label,
                "n_genes": n,
                "genome_assembly": genomeAssembly,
                "gene_id_namespace": geneIdNamespace,
                "gene_symbol_namespace": geneSymbolNamespace,
                "annotation_source": annotationSource,
                "gene_name_completeness": completeness,
                "n_duplicate_gene_names": n_dup,
            },
        )
        + session.newdocument()
    )
    try:
        return _store_doc(session, doc, ["genes.tsv"], [tsv_path])
    finally:
        if os.path.exists(tsv_path):
            os.unlink(tsv_path)


def makePyramid(
    session,
    x,
    y,
    gene_index,
    count,
    gene_list_doc,
    subjectID: str,
    binSizes=(1, 2, 4, 8, 16, 32),
    grid: int = 9,
    basePixelSize=(0.5, 0.5),
    pixelSizeUnits: str = "micrometer",
    label: str = "",
    assay: str = "",
    chipSerial: str = "",
    pipelineVersion: str = "",
    origin=None,
):
    """Bin flat spatial records into a tiled pyramid and store its documents.

    Creates one ``spatialGeneExpressionPyramid`` holding the shared
    identity -- gene list, origin, tile grid, bin sizes -- and one
    ``spatialGeneExpressionTiles`` per bin size depending on it. Levels are
    siblings rather than a chain, so enumerating them is a single query and
    no level orphans another.

    Args:
        session: an ndi.session or ndi.dataset.
        x, y: source coordinates, one per record.
        gene_index: ZERO-BASED geneList row, one per record.
        count: UMI count, one per record.
        gene_list_doc: the geneList these indices are against.
        subjectID: REQUIRED. The pyramid schema declares ``subject_id``
            mustbenotempty, because a section is measured from an animal
            and NDI records that on the measurement. Checked here so the
            failure names the argument rather than surfacing from inside
            database validation.
        binSizes: level ladder, finest first. Dyadic by default: each
            transition compresses the dynamic range of sparse counts by
            the step's AREA factor while leaving the mean unchanged, so
            uniform small ratios zoom most smoothly.
        grid: tile grid, ``grid`` by ``grid`` at EVERY level. Constant
            because nonzeros barely fall with bin size, so every level
            wants comparable tiling and a viewport maps to tile indices
            once, independent of zoom.
        basePixelSize: (x, y) physical size of one base pixel.
        origin: ``(min_x, min_y)`` of the tiled region, or None to take it
            from the data. Prefer the acquisition's own bounding box when
            known: a data-derived origin moves if the gene set changes.

    Returns:
        ``(pyramid_doc, [tiles_doc, ...])``, levels finest first.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    gene_index = np.asarray(gene_index)
    count = np.asarray(count)
    n = len(x)
    if not (len(y) == len(gene_index) == len(count) == n):
        raise ValueError(
            f"x, y, gene_index and count must be the same length, got "
            f"{n}, {len(y)}, {len(gene_index)}, {len(count)}"
        )
    if n == 0:
        raise ValueError("no records were supplied")
    if not subjectID:
        raise ValueError(
            "a subject is required: pass subjectID with the id of a subject "
            "document. The spatialGeneExpressionPyramid schema declares "
            "subject_id mustbenotempty."
        )

    n_genes = int(gene_list_doc.document_properties["geneList"]["n_genes"])
    if int(gene_index.max()) >= n_genes:
        raise ValueError(
            f"largest gene index is {int(gene_index.max())} but the geneList "
            f"has {n_genes} genes; indices are ZERO-BASED"
        )

    if origin is None:
        min_x, min_y = int(x.min()), int(y.min())
    else:
        min_x, min_y = int(origin[0]), int(origin[1])
        if int(x.min()) < min_x or int(y.min()) < min_y:
            raise ValueError(
                f"origin ({min_x}, {min_y}) is larger than the data minimum "
                f"({int(x.min())}, {int(y.min())})"
            )
    extent_x = int(x.max()) - min_x + 1
    extent_y = int(y.max()) - min_y + 1
    bins = sorted(int(b) for b in binSizes)

    pyr_doc = (
        _blank(
            "spatialGeneExpressionPyramid",
            spatialGeneExpressionPyramid={
                "label": label,
                "chip_serial": chipSerial,
                "pipeline_version": pipelineVersion,
                "bin_sizes": bins,
                "base_pixel_size_x": float(basePixelSize[0]),
                "base_pixel_size_y": float(basePixelSize[1]),
                "pixel_size_units": pixelSizeUnits,
                "origin_x": min_x,
                "origin_y": min_y,
                "extent_x": extent_x,
                "extent_y": extent_y,
                "tile_rows": grid,
                "tile_columns": grid,
                "index_order": "row-major",
                "origin_corner": "upper-left",
                "byte_order": "little",
            },
            geneExpression={"assay": assay, "count_type": "raw", "count_units": "UMI"},
        )
        + session.newdocument()
    )
    pyr_doc = pyr_doc.set_dependency_value("geneList_id", gene_list_doc.id)
    pyr_doc = pyr_doc.set_dependency_value("subject_id", subjectID)

    totals_path = _write_gene_totals(gene_index, count, n_genes)
    try:
        pyr_doc = _store_doc(session, pyr_doc, ["gene_totals.tsv"], [totals_path])
    finally:
        if os.path.exists(totals_path):
            os.unlink(totals_path)

    tile_docs = [
        _make_level(
            session,
            x,
            y,
            gene_index,
            count,
            min_x,
            min_y,
            extent_x,
            extent_y,
            b,
            grid,
            n_genes,
            pyr_doc,
            basePixelSize,
            pixelSizeUnits,
            subjectID,
        )
        for b in bins
    ]
    return pyr_doc, tile_docs


def _make_level(
    session,
    x,
    y,
    gi,
    c,
    min_x,
    min_y,
    extent_x,
    extent_y,
    b,
    grid,
    n_genes,
    pyr_doc,
    base_pixel_size,
    pixel_size_units,
    subject_id,
):
    """Build and store one resolution level."""
    lw = -(-extent_x // b)  # ceil
    lh = -(-extent_y // b)
    tw = -(-lw // grid)
    th = -(-lh // grid)
    n_tiles = grid * grid

    px = (x - min_x) // b
    py = (y - min_y) // b
    tcol = px // tw
    trow = py // th
    xl = px - tcol * tw
    yl = py - trow * th
    tid = trow * grid + tcol

    # ONE sort, on a TILE-MAJOR key, so tile boundaries fall out of the
    # sorted order with a searchsorted instead of needing a second sort.
    #
    # int64 from the first term. This product reaches ~1e13 on a real
    # section; under NumPy's weak promotion an int32 array times a Python
    # int stays int32, which wraps SILENTLY at 2.15e9. Distinct
    # (pixel, gene) pairs then collide and the dedup below merges them --
    # about 1.7M spurious merges on one measured section, matching the
    # n**2/2**33 collision estimate. Assert rather than trust: no fixture
    # small enough to run quickly can reach the overflow.
    key = ((tid.astype(np.int64) * th + yl) * tw + xl) * n_genes + gi
    if key.dtype != np.int64:
        raise TypeError(f"sort key must be int64, got {key.dtype}")
    span = np.int64(th) * tw * n_genes
    if n_tiles * span >= 2**63:
        raise OverflowError(f"sort key would reach {n_tiles * span:,}, past int64")

    order = np.argsort(key, kind="stable")
    key = key[order]
    xl = xl[order]
    yl = yl[order]
    g = gi[order]
    # int32 is enough: a group sums at most b*b base records.
    cc = c[order].astype(np.int64)

    # Collapse duplicate (pixel, gene) pairs created by binning.
    new = np.empty(len(key), bool)
    new[0] = True
    np.not_equal(key[1:], key[:-1], out=new[1:])
    starts = np.flatnonzero(new)
    cc = np.add.reduceat(cc, starts)
    xl, yl, g, key = xl[starts], yl[starts], g[starts], key[starts]
    cc = np.minimum(cc, 65535)  # data_type_count is uint16

    tid_sorted = key // span
    bounds = np.searchsorted(tid_sorted, np.arange(n_tiles + 1))

    names, paths = [], []
    tmpdir = tempfile.mkdtemp()
    try:
        for t in range(n_tiles):
            lo, hi = int(bounds[t]), int(bounds[t + 1])
            if lo == hi:
                continue  # tiles with no data are not written
            p = os.path.join(tmpdir, f"tile.bin_{t}")
            writeTileFile(p, xl[lo:hi], yl[lo:hi], g[lo:hi], cc[lo:hi])
            names.append(f"tile.bin_{t}")
            paths.append(p)

        doc = (
            _blank(
                "spatialGeneExpressionTiles",
                spatialGeneExpressionTiles={
                    "label": f"bin{b}",
                    "bin_size": b,
                    "pixel_size_x": float(base_pixel_size[0]) * b,
                    "pixel_size_y": float(base_pixel_size[1]) * b,
                    "pixel_size_units": pixel_size_units,
                    "dimension_order": "YXG",
                    "dimension_labels": "height,width,gene",
                    "dimension_size": [lh, lw, n_genes],
                    "dimension_scale": [
                        float(base_pixel_size[1]) * b,
                        float(base_pixel_size[0]) * b,
                        1,
                    ],
                    "dimension_scale_units": "micrometer,micrometer,dimensionless",
                    "tile_size_x_bins": tw,
                    "tile_size_y_bins": th,
                    "n_tiles_stored": len(names),
                    "data_type_gene_index": "uint32",
                    "data_type_count": "uint16",
                    "data_type_offset": "uint32",
                    "data_type_coordinate": "uint16",
                    "tile_compression": "none",
                    "tile_format_version": 1,
                },
            )
            + session.newdocument()
        )
        doc = doc.set_dependency_value("spatialGeneExpressionPyramid_id", pyr_doc.id)
        doc = doc.set_dependency_value("subject_id", subject_id)
        return _store_doc(session, doc, names, paths)
    finally:
        for p in paths:
            if os.path.exists(p):
                os.unlink(p)
        if os.path.isdir(tmpdir):
            os.rmdir(tmpdir)


def _write_gene_totals(gene_index, count, n_genes):
    """Per-gene totals for THIS dataset.

    Deliberately not a column of ``genes.tsv``: that file belongs to the
    geneList, which several datasets may share and which would then
    disagree about totals. Totals are a property of the counts, so they
    live with the pyramid.
    """
    tot = np.bincount(
        np.asarray(gene_index, np.int64),
        weights=np.asarray(count, np.float64),
        minlength=n_genes,
    ).astype(np.int64)
    npx = np.bincount(np.asarray(gene_index, np.int64), minlength=n_genes).astype(np.int64)
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w") as fh:
        fh.write("gene_index\ttotal_counts\tn_records\n")
        for i in range(n_genes):
            fh.write(f"{i}\t{int(tot[i])}\t{int(npx[i])}\n")
    return path


def _find_level(session, pyr_doc, bin_size):
    """The tiles document for one bin size, and its property struct."""
    q = ndi_query("").isa("spatialGeneExpressionTiles") & ndi_query("").depends_on(
        "spatialGeneExpressionPyramid_id", pyr_doc.id
    )
    for d in session.database_search(q):
        lv = d.document_properties["spatialGeneExpressionTiles"]
        if int(lv["bin_size"]) == int(bin_size):
            return d, lv
    raise ValueError(f"this pyramid has no level with bin_size {bin_size}")


def readViewport(session, pyr_doc, bin_size, rect=None, gene_rows=None, density=True):
    """Render a rectangle of one pyramid level.

    Fetches only the tiles that intersect *rect*. Tiles that were never
    written contribute zeros without any read.

    Args:
        session: an ndi.session or ndi.dataset.
        pyr_doc: a spatialGeneExpressionPyramid document.
        bin_size: which level to read; must be one of the pyramid's.
        rect: ``(x0, y0, width, height)`` in pixels OF THAT LEVEL,
            zero-based, relative to the level's upper-left. None reads the
            whole level.
        gene_rows: ZERO-BASED geneList rows to include, or None for all.
        density: divide by ``bin_size ** 2``, giving counts per base
            pixel. Binning SUMS, so without this a coarse level is
            ``bin_size ** 2`` brighter than a fine one and a single
            contrast range cannot serve a whole pyramid.

    Returns:
        ``(img, info)`` -- a float32 array over *rect*, and a dict with
        ``tiles_read``, ``tiles_empty``, ``bin_size``, ``level_size``.
    """
    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
    tile_doc, lv = _find_level(session, pyr_doc, bin_size)

    lh, lw = int(lv["dimension_size"][0]), int(lv["dimension_size"][1])
    th, tw = int(lv["tile_size_y_bins"]), int(lv["tile_size_x_bins"])
    rows, cols = int(p["tile_rows"]), int(p["tile_columns"])

    if rect is None:
        rect = (0, 0, lw, lh)
    x0, y0, w_rect, h_rect = (int(v) for v in rect)
    x1 = min(x0 + w_rect, lw)
    y1 = min(y0 + h_rect, lh)

    img = np.zeros((h_rect, w_rect), np.float32)
    info = {
        "tiles_read": 0,
        "tiles_empty": 0,
        "bin_size": int(bin_size),
        "level_size": (lh, lw),
    }
    stored = set(tile_doc.current_file_list())

    for r in range(y0 // th, min(max(y1 - 1, y0) // th, rows - 1) + 1):
        for c in range(x0 // tw, min(max(x1 - 1, x0) // tw, cols - 1) + 1):
            name = f"tile.bin_{r * cols + c}"
            if name not in stored:
                info["tiles_empty"] += 1
                continue
            fh = session.database_openbinarydoc(tile_doc, name)
            try:
                t = readTileFile(fh)
            finally:
                session.database_closebinarydoc(fh)
            info["tiles_read"] += 1

            t_img = renderTile(t, gene_rows, th, tw, binSize=(bin_size if density else 1))
            # Place this tile's overlap with the requested rectangle.
            tx0, ty0 = c * tw, r * th
            ax0, ax1 = max(x0, tx0), min(x1, tx0 + tw)
            ay0, ay1 = max(y0, ty0), min(y1, ty0 + th)
            if ax1 <= ax0 or ay1 <= ay0:
                continue
            img[ay0 - y0 : ay1 - y0, ax0 - x0 : ax1 - x0] = t_img[
                ay0 - ty0 : ay1 - ty0, ax0 - tx0 : ax1 - tx0
            ]
    return img, info


def exportRegion(session, pyr_doc, bin_size, rect=None):
    """Export a region as a sparse (pixel x gene) matrix of RAW counts.

    Deliberately not normalized: density is a display concern, and an
    export that applied it would be lossy. Use :func:`readViewport` for
    something to look at, this for something to compute on.

    Args:
        rect: as :func:`readViewport`; None exports the whole level.

    Returns:
        ``(M, pixel_xy)`` -- a ``scipy.sparse`` CSR matrix with one row per
        OCCUPIED pixel and one column per gene, and an ``(n_pixels, 2)``
        int array of that pixel's ``(x, y)`` in level coordinates,
        relative to the level origin.
    """
    from scipy import sparse

    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
    tile_doc, lv = _find_level(session, pyr_doc, bin_size)
    lh, lw = int(lv["dimension_size"][0]), int(lv["dimension_size"][1])
    n_genes = int(lv["dimension_size"][2])
    th, tw = int(lv["tile_size_y_bins"]), int(lv["tile_size_x_bins"])
    cols = int(p["tile_columns"])

    if rect is None:
        rect = (0, 0, lw, lh)
    x0, y0, w_rect, h_rect = (int(v) for v in rect)
    x1, y1 = min(x0 + w_rect, lw), min(y0 + h_rect, lh)

    rows_idx, cols_idx, vals, coords = [], [], [], []
    n_px = 0
    for name in sorted(tile_doc.current_file_list()):
        t_id = int(name.rsplit("_", 1)[1])
        tr, tc = divmod(t_id, cols)
        tx0, ty0 = tc * tw, tr * th
        if tx0 >= x1 or tx0 + tw <= x0 or ty0 >= y1 or ty0 + th <= y0:
            continue
        fh = session.database_openbinarydoc(tile_doc, name)
        try:
            t = readTileFile(fh)
        finally:
            session.database_closebinarydoc(fh)
        if t["n_pixels"] == 0:
            continue
        gx = t["x"].astype(np.int64) + tx0
        gy = t["y"].astype(np.int64) + ty0
        keep = (gx >= x0) & (gx < x1) & (gy >= y0) & (gy < y1)
        for i in np.flatnonzero(keep):
            lo, hi = int(t["offset"][i]), int(t["offset"][i + 1])
            if lo == hi:
                continue
            rows_idx.extend([n_px] * (hi - lo))
            cols_idx.extend(t["gene_index"][lo:hi].astype(np.int64).tolist())
            vals.extend(t["count"][lo:hi].astype(np.int64).tolist())
            coords.append((int(gx[i]), int(gy[i])))
            n_px += 1

    M = sparse.csr_matrix((vals, (rows_idx, cols_idx)), shape=(n_px, n_genes), dtype=np.int64)
    return M, np.array(coords, np.int64).reshape(-1, 2)


__all__ += ["levelTable", "chooseLevel", "readViewportBase"]


def levelTable(session, pyr_doc) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The pyramid's level ladder, finest first, plus the frame they share.

    MATLAB equivalent: ``ndi.fun.doc.gene.levelTable``

    A pyramid's ladder is split across two document types: the ladder,
    grid, origin and base pixel size live on the
    ``spatialGeneExpressionPyramid`` document, while each level's pixel
    dimensions, tile size and stored-tile count live on its own
    ``spatialGeneExpressionTiles`` document. Until now only the private
    :func:`_find_level` reached across them, so anything wanting to set up
    a viewer had to re-derive the join. This is that join, once.

    Levels come back finest first, the order a multiscale viewer wants a
    ladder in, so ``levels[0]`` means the finest rather than an arbitrary
    one.

    Args:
        session: an ndi.session or ndi.dataset holding the documents.
        pyr_doc: a spatialGeneExpressionPyramid document.

    Returns:
        ``(levels, frame)``. *levels* is a list of dicts, one per level,
        sorted by ascending ``binSize``, with keys ``binSize``,
        ``levelHeight``, ``levelWidth``, ``tileHeight``, ``tileWidth``,
        ``tileRows``, ``tileColumns``, ``nTilesStored``, ``nTilesGrid``,
        ``pixelSizeX``, ``pixelSizeY``, ``tileDocId``. *frame* carries what
        every level shares: ``originX``, ``originY``, ``extentX``,
        ``extentY``, ``basePixelSizeX``, ``basePixelSizeY``,
        ``pixelSizeUnits``, ``indexOrder``, ``originCorner``.

    Note:
        MATLAB returns one table whose ``Properties.UserData`` carries the
        frame. Python has no table type with attached metadata that a
        caller would expect, so the two halves are returned as a pair
        rather than smuggled onto a DataFrame -- which would also make
        pandas a dependency of reading a document. The field names are the
        MATLAB ones so the two read alike.

    Raises:
        ValueError: if the pyramid has no tiles documents at all.
    """
    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]

    q = ndi_query("").isa("spatialGeneExpressionTiles") & ndi_query("").depends_on(
        "spatialGeneExpressionPyramid_id", pyr_doc.id
    )
    docs = session.database_search(q)
    if not docs:
        raise ValueError(f"pyramid {pyr_doc.id} has no spatialGeneExpressionTiles documents")

    tile_rows = int(p["tile_rows"])
    tile_columns = int(p["tile_columns"])

    levels = []
    for d in docs:
        lv = d.document_properties["spatialGeneExpressionTiles"]
        # dimension_size is [height, width, nGenes] in the document's YXG
        # order; only the first two are geometry.
        levels.append(
            {
                "binSize": int(lv["bin_size"]),
                "levelHeight": int(lv["dimension_size"][0]),
                "levelWidth": int(lv["dimension_size"][1]),
                "tileHeight": int(lv["tile_size_y_bins"]),
                "tileWidth": int(lv["tile_size_x_bins"]),
                "tileRows": tile_rows,
                "tileColumns": tile_columns,
                "nTilesStored": int(lv["n_tiles_stored"]),
                "nTilesGrid": tile_rows * tile_columns,
                "pixelSizeX": float(lv["pixel_size_x"]),
                "pixelSizeY": float(lv["pixel_size_y"]),
                "tileDocId": d.id,
            }
        )

    levels.sort(key=lambda r: r["binSize"])  # finest first

    frame = {
        "originX": float(p["origin_x"]),
        "originY": float(p["origin_y"]),
        "extentX": int(p["extent_x"]),
        "extentY": int(p["extent_y"]),
        "basePixelSizeX": float(p["base_pixel_size_x"]),
        "basePixelSizeY": float(p["base_pixel_size_y"]),
        "pixelSizeUnits": p["pixel_size_units"],
        "indexOrder": p["index_order"],
        "originCorner": p["origin_corner"],
    }
    return levels, frame


def chooseLevel(levels, rect_source, target_pixels) -> tuple[int, dict[str, Any]]:
    """The coarsest level that still resolves a rectangle.

    MATLAB equivalent: ``ndi.fun.doc.gene.chooseLevel``

    Reading a finer level than the display can show costs ``binSize ** 2``
    more tiles for pixels that are then thrown away; reading a coarser one
    loses detail the display could have shown.

    NOT NEEDED FOR NAPARI. napari's multiscale interface takes the whole
    ladder and picks a level itself from the shape ratios, so a napari
    viewer should hand it every level rather than choose one. This is for
    the callers that render a single image: a figure, a thumbnail, an
    export, a tile server.

    Args:
        levels: the list from :func:`levelTable`, finest first.
        rect_source: ``(x0, y0, width, height)`` in SOURCE coordinates --
            the GEF's own x/y frame, the one cell centroids also use.
        target_pixels: how many pixels the longer side should span, at
            least.

    Returns:
        ``(bin_size, info)``. *info* has ``renderedWidth``,
        ``renderedHeight``, ``longSide``, and ``metTarget``, which is False
        when even the finest level falls short. Asking for more detail than
        the data holds is a legitimate request with a definite answer, so
        the finest level is returned rather than raising; a caller that
        scales its display off the result needs to know it happened.

    Raises:
        ValueError: if the rectangle has non-positive width or height.
    """
    w = float(rect_source[2])
    h = float(rect_source[3])
    if w <= 0 or h <= 0:
        raise ValueError(f"rect_source must have positive width and height; got {w} by {h}")

    long_side = [max(w, h) / r["binSize"] for r in levels]

    # levels is finest first, so long_side descends; the LAST entry still
    # meeting the target is the coarsest acceptable level.
    ok = None
    for i, ls in enumerate(long_side):
        if ls >= target_pixels:
            ok = i
    met_target = ok is not None
    if ok is None:
        ok = 0  # finest level; cannot do better

    bin_size = levels[ok]["binSize"]
    info = {
        "renderedWidth": w / bin_size,
        "renderedHeight": h / bin_size,
        "longSide": long_side[ok],
        "metTarget": met_target,
    }
    return bin_size, info


def readViewportBase(session, pyr_doc, bin_size, rect_source=None, gene_rows=None, density=True):
    """Render a rectangle given in SOURCE coordinates.

    MATLAB equivalent: ``ndi.fun.doc.gene.readViewportBase``

    :func:`readViewport` takes its rectangle in the pixels of one level,
    zero-based and relative to that level's upper-left. That is the right
    frame for the tile arithmetic and the wrong frame for a caller, who has
    a rectangle in the source coordinates the data was acquired in -- the
    same frame cell centroids and contours use. The conversion subtracts
    the pyramid origin and divides by the bin size, with the rounding going
    outward so the result never returns less than was asked for.

    Because a level's bins do not generally align with the requested edges,
    what comes back usually covers slightly MORE.
    ``info["rectSourceCovered"]`` reports exactly what, so a caller can
    place the image without re-deriving the rounding.

    Args:
        session: an ndi.session or ndi.dataset.
        pyr_doc: a spatialGeneExpressionPyramid document.
        bin_size: which level to read; must be one of the pyramid's.
        rect_source: ``(x0, y0, width, height)`` in SOURCE coordinates.
            None means the pyramid's whole extent.
        gene_rows: ZERO-BASED geneList rows to include, or None for all.
        density: divide by ``bin_size ** 2``. See :func:`readViewport`.

    Returns:
        ``(img, info)``. *info* is what :func:`readViewport` returns plus
        ``rectLevel``, ``rectSourceCovered``, ``originX`` and ``originY``.

    Raises:
        ValueError: for a malformed or empty rectangle, or an unknown level.
    """
    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]

    if rect_source is None:
        rect_source = (
            float(p["origin_x"]),
            float(p["origin_y"]),
            int(p["extent_x"]),
            int(p["extent_y"]),
        )
    if len(rect_source) != 4:
        raise ValueError(
            f"rect_source must be (x0, y0, width, height) or None; "
            f"got {len(rect_source)} elements"
        )
    if rect_source[2] <= 0 or rect_source[3] <= 0:
        raise ValueError(
            f"rect_source must have positive width and height; "
            f"got {rect_source[2]} by {rect_source[3]}"
        )

    levels, frame = levelTable(session, pyr_doc)
    match = [r for r in levels if r["binSize"] == int(bin_size)]
    if not match:
        raise ValueError(
            f"this pyramid has no level with bin_size {bin_size}; "
            f"it has {[r['binSize'] for r in levels]}"
        )
    lh = match[0]["levelHeight"]
    lw = match[0]["levelWidth"]

    b = int(bin_size)
    bx0 = rect_source[0] - frame["originX"]
    by0 = rect_source[1] - frame["originY"]
    # Low edge floors, high edge ceils, so the result covers the request
    # rather than clipping it.
    lx0 = int(np.floor(bx0 / b))
    ly0 = int(np.floor(by0 / b))
    lx1 = int(np.ceil((bx0 + rect_source[2]) / b))  # exclusive
    ly1 = int(np.ceil((by0 + rect_source[3]) / b))

    # A request wholly outside the pyramid is a legitimate viewport -- a
    # viewer pans off the edge routinely -- but must not become a negative
    # or zero-sized read.
    lx0 = max(lx0, 0)
    ly0 = max(ly0, 0)
    lx1 = min(lx1, lw)
    ly1 = min(ly1, lh)
    w_level = max(lx1 - lx0, 0)
    h_level = max(ly1 - ly0, 0)
    rect_level = (lx0, ly0, w_level, h_level)

    if w_level == 0 or h_level == 0:
        img = np.zeros((h_level, w_level), float)
        info = {
            "tilesRead": 0,
            "tilesEmpty": 0,
            "binSize": b,
            "levelSize": (lh, lw),
        }
    else:
        img, info = readViewport(session, pyr_doc, b, rect_level, gene_rows, density=density)

    info["rectLevel"] = rect_level
    info["rectSourceCovered"] = (
        lx0 * b + frame["originX"],
        ly0 * b + frame["originY"],
        w_level * b,
        h_level * b,
    )
    info["originX"] = frame["originX"]
    info["originY"] = frame["originY"]
    return img, info


__all__ += ["readCells"]

#: cells.tsv columns a reader can rely on; the rest vary by writer.
_CELL_REQUIRED = ("cell_index", "cell_id", "x", "y")


def readCells(session, cells_doc) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the cell table of a spatialGeneExpressionCells document.

    MATLAB equivalent: ``ndi.fun.doc.gene.readCells``

    Columns are taken BY HEADER NAME, not by position. The specification
    names them cell_index, cell_id, x, y, area, dnb_count, total_counts,
    n_genes, but only the first four are required and writers differ on
    the rest: the extraction spike that produced the first opossum cells
    wrote ``dnbCount`` and ``n_genes_by_counts`` where the spec says
    ``dnb_count`` and ``n_genes``. Reading by position would have
    silently mapped one measurement onto another's name.

    CONTOURS ARE NOT READ HERE. ``contours.bin`` holds the boundary
    polygons and needs its own reader; this returns centroids, which is
    what a viewer needs to place cells. ``info["contoursPresent"]`` says
    whether there is more to read.

    What a "cell" is: Stereo-seq CellBin segments NUCLEI from the stain
    image and dilates outward, so a row here is a nucleus plus a margin
    rather than a measured cell body. ``info["segmentationMethod"]``
    records which method produced it.

    Args:
        session: an ndi.session or ndi.dataset holding the document.
        cells_doc: a spatialGeneExpressionCells document.

    Returns:
        ``(columns, info)``. *columns* maps header name to a list or
        array, always including ``cell_index``, ``cell_id``, ``x`` and
        ``y``; x and y are the centroid in SOURCE coordinates, the frame
        a viewer must transform before drawing. *info* carries nCells,
        coordinateUnits, contoursPresent, contourReference and
        segmentationMethod, read from the document rather than assumed.

    Raises:
        ValueError: if cells.tsv has no header or lacks a required column.
    """
    c = cells_doc.document_properties["spatialGeneExpressionCells"]

    fh = session.database_openbinarydoc(cells_doc, "cells.tsv")
    try:
        text = fh.read().decode("utf-8")
    finally:
        session.database_closebinarydoc(fh)

    columns, info = _parse_cells_tsv(text, cells_doc.id)
    info.update(
        {
            "nCells": int(c["n_cells"]),
            "coordinateUnits": c["coordinate_units"],
            "contoursPresent": bool(c["contours_present"]),
            "contourReference": c["contour_reference"],
            "segmentationMethod": c["segmentation_method"],
        }
    )
    n_rows = len(columns["cell_index"])
    if n_rows != int(c["n_cells"]):
        warnings.warn(
            f"cells.tsv holds {n_rows} rows but the document says n_cells "
            f"is {c['n_cells']}. The file is what was read.",
            RuntimeWarning,
            stacklevel=2,
        )
    return columns, info


def _parse_cells_tsv(text: str, where: str = "cells.tsv"):
    """Parse a cells.tsv body. Separate so a directory of extracted cells
    can be read with the same rules as a document's copy."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"cells.tsv in {where} has no header row")

    header = lines[0].split("\t")
    missing = [c for c in _CELL_REQUIRED if c not in header]
    if missing:
        raise ValueError(
            f"cells.tsv is missing required column(s): {', '.join(missing)}. "
            f"It has: {', '.join(header)}"
        )

    cols: dict[str, list] = {h: [] for h in header}
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) < len(header):
            f = f + [""] * (len(header) - len(f))
        for h, v in zip(header, f):
            cols[h].append(v)

    out: dict[str, Any] = {}
    for h, vals in cols.items():
        if h == "cell_id":
            out[h] = vals  # an identifier, never a number
        elif h in ("cell_index",):
            out[h] = np.array([int(float(v)) for v in vals], np.int64)
        else:
            try:
                out[h] = np.array([float(v) if v != "" else np.nan for v in vals])
            except ValueError:
                # Keep the writer's own column rather than dropping it;
                # renaming or discarding a column is how one measurement
                # quietly becomes another.
                out[h] = vals
    return out, {}


__all__ += ["writeContourFile", "readContourFile", "makeCells"]

#: contours.bin defaults; both are document FIELDS so a level can widen
#: without a format version change.
_CONTOUR_VERTEX_TYPE = "int16"
_CONTOUR_OFFSET_TYPE = "uint32"


def writeContourFile(
    filename, polys, vertexType=_CONTOUR_VERTEX_TYPE, offsetType=_CONTOUR_OFFSET_TYPE
) -> dict[str, Any]:
    """Write cell boundary polygons as ``contours.bin``.

    MATLAB equivalent: ``ndi.fun.doc.gene.writeContourFile``

    The contour_format_version 1 layout::

        n_cells           offsetType   1
        n_vertices_total  offsetType   1
        offset            offsetType   n_cells + 1
        vx                vertexType   n_vertices_total
        vy                vertexType   n_vertices_total

    Cell *i* has vertices ``offset[i]:offset[i+1]``. The polygon closes
    implicitly; the first vertex is not repeated, so a caller that closed
    its ring must not pass the duplicate.

    Always writes the RAGGED form even when every cell has the same
    vertex count. The fixed-width form the spec also allows saves
    ``n_cells + 1`` offsets and cannot represent a later ragged edit;
    :func:`readContourFile` accepts both, so other writers' files read.

    Args:
        polys: one entry per cell, each an ``(N, 2)`` array of ``[x, y]``.
            An empty entry is a cell with no contour and is written as
            zero vertices rather than dropped, so row *i* of cells.tsv
            stays row *i* here.

    Raises:
        ValueError: if a polygon is not (N, 2), or if a vertex does not
            fit the stored type. int16 holds +/-32767, ample for
            centroid-relative vertices and NOT ample for absolute source
            coordinates on a chip 20,000 bins across; those would wrap
            silently and put boundaries in the wrong place.
    """
    counts = []
    for i, p in enumerate(polys):
        a = np.asarray(p) if p is not None and len(p) else np.zeros((0, 2))
        if a.size and a.ndim != 2 or (a.size and a.shape[1] != 2):
            raise ValueError(f"polygon {i} must be (N, 2) [x y]; got shape {a.shape}")
        counts.append(a.shape[0] if a.size else 0)

    info_v = np.iinfo(vertexType)
    stacked = [np.asarray(p, float) for p in polys if p is not None and len(p)]
    if stacked:
        allv = np.vstack(stacked)
        bad = np.flatnonzero((allv > info_v.max).any(1) | (allv < info_v.min).any(1))
        if bad.size:
            v = allv[bad[0]]
            raise ValueError(
                f"a vertex ({v[0]:g}, {v[1]:g}) does not fit in {vertexType} "
                f"({info_v.min}..{info_v.max}). Contours stored relative to "
                f"their centroid fit easily; ABSOLUTE source coordinates on a "
                f"chip this size do not, and would wrap silently. Check "
                f"contour_reference."
            )

    offsets = np.concatenate([[0], np.cumsum(counts)]).astype(offsetType)
    total = int(offsets[-1])
    vx = np.zeros(total, vertexType)
    vy = np.zeros(total, vertexType)
    for i, p in enumerate(polys):
        if not counts[i]:
            continue
        a = np.asarray(p)
        vx[offsets[i] : offsets[i + 1]] = a[:, 0]
        vy[offsets[i] : offsets[i + 1]] = a[:, 1]

    ot = np.dtype(offsetType).newbyteorder("<")
    vt = np.dtype(vertexType).newbyteorder("<")
    with open(filename, "wb") as fh:
        fh.write(np.array([len(polys)], ot).tobytes())
        fh.write(np.array([total], ot).tobytes())
        fh.write(offsets.astype(ot).tobytes())
        fh.write(vx.astype(vt).tobytes())
        fh.write(vy.astype(vt).tobytes())

    return {
        "nCells": len(polys),
        "nVerticesTotal": total,
        "vertexType": vertexType,
        "offsetType": offsetType,
        "nVerticesPerCell": 0,
    }


def readContourFile(
    filename,
    nVerticesPerCell: int = 0,
    vertexType=_CONTOUR_VERTEX_TYPE,
    offsetType=_CONTOUR_OFFSET_TYPE,
):
    """Read cell boundary polygons from ``contours.bin``.

    MATLAB equivalent: ``ndi.fun.doc.gene.readContourFile``

    BOTH FORMS ARE ACCEPTED. The ragged form carries an offset array; the
    fixed-width form, which the document signals through a positive
    ``n_vertices_per_cell``, carries none and packs vertex *j* of cell
    *i* at ``i * K + j``. :func:`writeContourFile` emits only the ragged
    form, but a file may come from another writer.

    Args:
        nVerticesPerCell: pass the document's field; 0 means ragged.
        vertexType, offsetType: pass the document's ``data_type_vertex``
            and ``data_type_offset``. They are fields rather than
            constants so a level can widen without a format version bump.

    Returns:
        ``(polys, info)`` -- one ``(N, 2)`` array per cell, and a dict.
    """
    ot = np.dtype(offsetType).newbyteorder("<")
    vt = np.dtype(vertexType).newbyteorder("<")
    raw = open(filename, "rb").read() if isinstance(filename, (str, bytes)) else filename.read()

    pos = 0
    hdr = np.frombuffer(raw, ot, count=2, offset=pos)
    n, total = int(hdr[0]), int(hdr[1])
    pos += 2 * ot.itemsize

    if nVerticesPerCell > 0:
        offsets = np.arange(n + 1, dtype=np.int64) * nVerticesPerCell
        if int(offsets[-1]) != total:
            raise ValueError(
                f"n_vertices_per_cell is {nVerticesPerCell} and there are {n} "
                f"cells, implying {int(offsets[-1])} vertices, but the file "
                f"says {total}"
            )
    else:
        offsets = np.frombuffer(raw, ot, count=n + 1, offset=pos).astype(np.int64)
        pos += (n + 1) * ot.itemsize

    need = 2 * total * vt.itemsize
    if len(raw) - pos < need:
        raise ValueError(
            f"file claims {total} vertices, needing {need} more bytes, but "
            f"only {len(raw) - pos} remain"
        )
    vx = np.frombuffer(raw, vt, count=total, offset=pos)
    vy = np.frombuffer(raw, vt, count=total, offset=pos + total * vt.itemsize)

    polys = [
        np.stack([vx[offsets[i] : offsets[i + 1]], vy[offsets[i] : offsets[i + 1]]], 1)
        for i in range(n)
    ]
    info = {
        "nCells": n,
        "nVerticesTotal": total,
        "vertexType": vertexType,
        "offsetType": offsetType,
        "nVerticesPerCell": nVerticesPerCell,
    }
    return polys, info


def makeCells(
    session,
    cellID,
    x,
    y,
    pyr_doc,
    label: str = "",
    segmentationMethod: str = "",
    segmentationDilation: float = 0,
    coordinateUnits: str = "source",
    subjectID: str = "",
    extra: dict[str, Any] | None = None,
    contours=None,
    contourReference: str = "centroid",
):
    """Create a spatialGeneExpressionCells document.

    MATLAB equivalent: ``ndi.fun.doc.gene.makeCells``

    Writes ``cells.tsv``, optionally ``contours.bin``, and enters the
    document in the database. One row per segmented cell, in the same
    coordinate frame as the pyramid it depends on.

    Args:
        cellID: identifier from the source file, one per cell. Kept as
            TEXT: these are commonly 14-digit numbers that lose precision
            as floats and then no longer match the file they came from.
        x, y: centroids, in the frame named by *coordinateUnits*.
        pyr_doc: the pyramid these cells belong to. A cell table is
            meaningless without the frame it is in, so the dependency is
            required rather than optional.
        segmentationMethod: how cells were segmented, with version. Worth
            stating plainly: Stereo-seq CellBin segments NUCLEI and
            dilates outward, so a "cell" is a nucleus plus a margin, not
            a measured cell body.
        subjectID: optional here, because the pyramid already carries
            one -- unlike :func:`makePyramid`, where it is required.
        extra: further per-cell columns, written after the required four
            with their own names. The spec names area, dnb_count,
            total_counts and n_genes, but writers differ and
            :func:`readCells` matches by header, so a caller's own names
            survive.
        contours: one ``(N, 2)`` vertex array per cell, or None. None
            writes no contours.bin and leaves ``contours_present`` at 0.
        contourReference: whether contour vertices are relative to their
            cell's centroid or absolute. This decides whether they fit in
            int16; :func:`writeContourFile` checks and refuses rather
            than wrapping.

    Returns:
        The stored spatialGeneExpressionCells document.
    """
    cell_id = [str(v) for v in cellID]
    xs = np.asarray(x, float).ravel()
    ys = np.asarray(y, float).ravel()
    n = len(cell_id)
    if len(xs) != n or len(ys) != n:
        raise ValueError(
            f"cellID, x and y must be the same length; got {n}, {len(xs)} and {len(ys)}"
        )
    extra = extra or {}
    for k, v in extra.items():
        if len(v) != n:
            raise ValueError(f"extra column {k!r} has {len(v)} rows but there are {n} cells")
    if contours is not None and len(contours) != n:
        raise ValueError(f"contours has {len(contours)} entries but there are {n} cells")

    # cell_index is the 0-BASED row number and is the key contours.bin and
    # every cellTypeLabels document reference. Written explicitly rather
    # than left implicit, so a reader never infers it from row order.
    fd, tsv_path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w") as fh:
        fh.write("\t".join(["cell_index", "cell_id", "x", "y", *extra.keys()]) + "\n")
        for i in range(n):
            row = [str(i), cell_id[i], f"{xs[i]:g}", f"{ys[i]:g}"]
            row += [
                (f"{v:g}" if isinstance(v, (int, float, np.number)) else str(v))
                for v in (extra[k][i] for k in extra)
            ]
            fh.write("\t".join(row) + "\n")

    file_names, file_paths = ["cells.tsv"], [tsv_path]

    contours_present = 0
    if contours is not None and len(contours):
        fd2, cb_path = tempfile.mkstemp(suffix=".bin")
        os.close(fd2)
        writeContourFile(cb_path, contours)
        file_names.append("contours.bin")
        file_paths.append(cb_path)
        contours_present = 1

    doc = (
        _blank(
            "spatialGeneExpressionCells",
            spatialGeneExpressionCells={
                "label": label,
                "n_cells": n,
                "segmentation_method": segmentationMethod,
                "segmentation_dilation": segmentationDilation,
                "coordinate_units": coordinateUnits,
                "contours_present": contours_present,
                "contour_reference": contourReference,
                "n_vertices_per_cell": 0,
                "data_type_vertex": _CONTOUR_VERTEX_TYPE,
                "data_type_offset": _CONTOUR_OFFSET_TYPE,
                "contour_format_version": 1,
            },
        )
        + session.newdocument()
    )
    doc = doc.set_dependency_value(
        "spatialGeneExpressionPyramid_id", pyr_doc.id, error_if_not_found=False
    )
    if subjectID:
        doc = doc.set_dependency_value("subject_id", subjectID, error_if_not_found=False)

    return _store_doc(session, doc, file_names, file_paths)


__all__ += ["readGEF"]

#: Layouts a Stereo-seq GEF is known to use. Probed in order.
_GEF_ROOTS = ("/geneExp/bin1", "/wholeExp/bin1")
_GEF_EXPR = ("expression", "cellBin")
_GEF_NAME = ("geneName", "geneID", "name", "gene")
_GEF_ID = ("geneID", "gene", "geneName", "name")
_GEF_OFFSET = ("offset", "offsets")
_GEF_COUNT = ("count", "counts")
_GEF_X = ("x", "X")
_GEF_Y = ("y", "Y")
_GEF_CNT = ("count", "MIDCount", "mid_count", "umi")

#: Records read per h5py call on the contiguous fast path.
_GEF_BLOCK = 20_000_000


def _gef_pick(available, candidates, what, where):
    """Return the first candidate present, or say what was looked for."""
    for c in candidates:
        if c in available:
            return c
    raise KeyError(
        f"No {what} field in {where}: looked for "
        f"{{{', '.join(candidates)}}}, found {{{', '.join(available)}}}."
    )


def _gef_str(values):
    """Decode a fixed-width HDF5 string column to a list of str."""
    out = []
    for v in values:
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        out.append(str(v).replace("\x00", "").strip())
    return out


def _gef_extent(handle, root, x, y):
    """Locate the bounding box, nearest-first from ``root`` outward.

    SAW writes minX/maxX/minY/maxY as attributes, but WHERE varies: on the
    bin group, on an ancestor, or on the file root. Probing only the root
    silently yields a 1x1 pyramid on files that put them deeper, and a
    fixture written with them at the root agrees with that bug rather than
    catching it.

    An attribute box that does not CONTAIN the data loses to the data,
    which cannot be wrong about its own extent.
    """
    need = ("minX", "minY", "maxX", "maxY")
    parts = root.strip("/").split("/")
    places = ["/" + "/".join(parts[:i]) for i in range(len(parts), 0, -1)]
    places.append("/")

    have_data = x is not None and len(x)
    if have_data:
        dmin = (int(x.min()), int(y.min()))
        dmax = (int(x.max()), int(y.max()))

    for p in places:
        if p != "/" and p not in handle:
            continue
        attrs = handle[p].attrs if p != "/" else handle.attrs
        if not all(k in attrs for k in need):
            continue
        box = tuple(int(attrs[k]) for k in need)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        if not have_data:
            # Nothing to validate against, and a caller must be able to
            # tell that apart from a box the data agreed with.
            return box, f"attrs at {p} (unvalidated: no records read)"
        if box[0] <= dmin[0] and box[1] <= dmin[1] and box[2] >= dmax[0] and box[3] >= dmax[1]:
            return box, f"attrs at {p}"
    if have_data:
        return (dmin[0], dmin[1], dmax[0], dmax[1]), "data"
    return None, "unknown (no attributes found and no records read)"


def _gef_stat_totals(handle, gene_id):
    """SAW's own per-gene MIDcount from ``/stat/gene``, aligned to our rows.

    A third independent source for a number this project derives twice.
    Aligned by accession rather than by position: assuming the orders match
    would import our own ordering into the check meant to be independent
    of it.
    """
    if "/stat/gene" not in handle:
        return None, "absent (/stat/gene not in this file)"
    st = handle["/stat/gene"][...]
    names = st.dtype.names or ()
    id_f = _gef_pick(names, ("geneID", "gene", "geneName"), "gene id", "/stat/gene")
    c_f = _gef_pick(names, ("MIDcount", "MIDCount", "midcount", "count"), "count", "/stat/gene")
    ids = _gef_str(st[id_f])
    tot = np.asarray(st[c_f], dtype=np.int64)

    n = len(gene_id)
    if len(ids) >= n and ids[:n] == list(gene_id):
        return tot[:n], "row order identical to geneExp"
    lookup = dict(zip(ids, tot))
    out = np.full(n, np.nan)
    hit = 0
    for i, g in enumerate(gene_id):
        if g in lookup:
            out[i] = lookup[g]
            hit += 1
    return out, f"matched {hit}/{n} rows by geneID"


def readGEF(
    filename,
    probeOnly: bool = False,
    maxGenes: int = 0,
    countCeiling: int = 65535,
    root: str = "",
    verbose: bool = False,
):
    """Read a Stereo-seq GEF into the flat records :func:`makePyramid` takes.

    MATLAB equivalent: ``ndi.fun.doc.gene.readGEF``

    Returns one record per (pixel, gene) pair::

        x, y, gene_index, count, gene_id, gene_name, meta = readGEF(path)
        makePyramid(session, x, y, gene_index, count, gl, subjectID="s1")

    Args:
        filename: path to the .gef (an HDF5 file).
        probeOnly: read the gene table, extent and field names but NOT the
            expression records. ``x``, ``y``, ``gene_index`` and ``count``
            come back empty; ``meta["nRecords"]`` is still exact, because
            it is the sum of the gene table's own counts. A real section
            holds ~10^8 records and takes minutes, so a caller that only
            needs to SHOW what is in a file -- an ingest GUI listing genes,
            extent and chip before the user commits -- can ask without
            paying for the data.
        maxGenes: stop after this many genes; 0 reads all.
        countCeiling: counts saturate here rather than wrapping, and
            ``meta["nCountsClamped"]`` reports how many did. The default is
            what the tile format stores; it is an argument so a widened
            level does not need a new reader.
        root: force the HDF5 group, e.g. ``"/geneExp/bin1"``. Default ""
            probes the known layouts.
        verbose: print progress. Off by default because a library called
            from a GUI must not print.

    Returns:
        ``(x, y, gene_index, count, gene_id, gene_name, meta)``. ``x`` and
        ``y`` are int32 source coordinates, ``gene_index`` is a ZERO-BASED
        int32 row of ``gene_id``, ``count`` is uint16. ``meta`` carries
        ``root``, ``exprDataset``, ``fields``, ``nGenesInFile``,
        ``nGenes``, ``nRecords``, ``box``, ``boxSource``, ``resolutionNm``,
        ``chipSerial``, ``nCountsClamped``, ``statTotals``,
        ``statTotalsNote`` and ``readSeconds``.

    Raises:
        KeyError: if no (gene, expression) pair or a required field is
            absent. The message names what was looked for and what is
            there, because a GEF layout that drifts is the expected case.

    NOTHING ABOUT THE LAYOUT IS ASSUMED. Every path and field name is
    probed against a candidate list: records live under ``/geneExp/bin1``
    or ``/wholeExp/bin1``, the expression dataset is ``expression`` or
    ``cellBin``, coordinates are x/y or X/Y, and the count field has four
    spellings. GEF layouts drift between SAW versions.

    COUNTS ARE CLIPPED IN A WIDE TYPE. SAW writes uint8 counts at bin1;
    clipping in the narrow type saturates every value at 255 instead of at
    ``countCeiling``, silently, which is the trap that bit an earlier
    builder under numpy 2.
    """
    import time

    try:
        import h5py
    except ImportError as e:  # pragma: no cover - h5py ships with a core dep
        raise ImportError(
            "h5py is required to read a GEF. Install it with: pip install h5py"
            f"\n(Original error: {e})"
        ) from e

    t0 = time.time()
    roots = (root,) if root else _GEF_ROOTS

    with h5py.File(filename, "r") as f:
        # -- locate the (gene, expression) pair -------------------------
        chosen = expr_name = ""
        for r in roots:
            if r not in f or "gene" not in f[r]:
                continue
            for e in _GEF_EXPR:
                if e in f[r]:
                    chosen, expr_name = r, e
                    break
            if chosen:
                break
        if not chosen:
            raise KeyError(
                f"No (gene, expression) pair under {', '.join(roots)} in {filename}."
            )
        expr_ds = f[chosen][expr_name]
        gene_ds = f[chosen]["gene"]

        # -- gene table (small: tens of thousands of rows) --------------
        genes = gene_ds[...]
        gf = genes.dtype.names or ()
        name_field = _gef_pick(gf, _GEF_NAME, "gene name", f"{chosen}/gene")
        id_field = _gef_pick(gf, _GEF_ID, "gene id", f"{chosen}/gene")
        off_field = _gef_pick(gf, _GEF_OFFSET, "offset", f"{chosen}/gene")
        cnt_field = _gef_pick(gf, _GEF_COUNT, "count", f"{chosen}/gene")

        gene_name = _gef_str(genes[name_field])
        gene_id = _gef_str(genes[id_field])
        offsets = np.asarray(genes[off_field], dtype=np.int64)
        counts = np.asarray(genes[cnt_field], dtype=np.int64)

        n_genes_all = len(counts)
        n_genes = min(maxGenes, n_genes_all) if maxGenes > 0 else n_genes_all
        gene_name = gene_name[:n_genes]
        gene_id = gene_id[:n_genes]

        # -- expression field names, WITHOUT reading any records --------
        # The dtype is metadata, so probeOnly can report the layout it
        # would have used and a real read fails on a bad field name up
        # front rather than after minutes of reading.
        ef = expr_ds.dtype.names or ()
        x_f = _gef_pick(ef, _GEF_X, "x coordinate", expr_name)
        y_f = _gef_pick(ef, _GEF_Y, "y coordinate", expr_name)
        c_f = _gef_pick(ef, _GEF_CNT, "count", expr_name)

        n_records = int(counts[:n_genes].sum())
        meta: dict[str, Any] = {
            "root": chosen,
            "exprDataset": f"{chosen}/{expr_name}",
            "fields": {
                "x": x_f,
                "y": y_f,
                "count": c_f,
                "geneID": id_field,
                "geneName": name_field,
            },
            "nGenesInFile": n_genes_all,
            "nGenes": n_genes,
            "nRecords": n_records,
            "box": None,
            "boxSource": "",
            "resolutionNm": int(f.attrs["resolution"]) if "resolution" in f.attrs else 500,
            "chipSerial": _gef_str([f.attrs["sn"]])[0] if "sn" in f.attrs else "",
            "nCountsClamped": 0,
            "readSeconds": 0.0,
        }
        if verbose:
            print(f"[gef] {filename}")
            print(f"[gef] root={chosen} expr={expr_name}  genes={n_genes} of {n_genes_all}")
            print(f"[gef] expression fields: x={x_f} y={y_f} count={c_f}")

        if probeOnly:
            meta["box"], meta["boxSource"] = _gef_extent(f, chosen, None, None)
            meta["statTotals"], meta["statTotalsNote"] = _gef_stat_totals(f, gene_id)
            meta["readSeconds"] = time.time() - t0
            empty32 = np.zeros(0, np.int32)
            return empty32, empty32, empty32, np.zeros(0, np.uint16), gene_id, gene_name, meta

        # -- expression records -----------------------------------------
        x = np.zeros(n_records, np.int32)
        y = np.zeros(n_records, np.int32)
        count = np.zeros(n_records, np.uint16)
        n_clamped = 0

        # GEF lays records out grouped by gene, so when the offsets are
        # contiguous and ascending the gene of each record follows from the
        # counts alone and the file can be read in a few large blocks.
        # Worth checking rather than assuming: one read per gene is ~26,000
        # calls on a real file and the per-call overhead dominates.
        expected = np.concatenate(([0], np.cumsum(counts[:-1]))) if n_genes_all else offsets
        contiguous = np.array_equal(offsets, expected)
        if verbose:
            print(
                "[gef] gene offsets are contiguous and ascending; reading in blocks"
                if contiguous
                else "[gef] gene offsets are NOT contiguous; one read per gene (slower)"
            )

        if contiguous:
            gene_index = np.repeat(
                np.arange(n_genes, dtype=np.int32), counts[:n_genes]
            )
            written = 0
            while written < n_records:
                n = min(_GEF_BLOCK, n_records - written)
                chunk = expr_ds[written : written + n]
                sl = slice(written, written + n)
                x[sl] = chunk[x_f].astype(np.int32)
                y[sl] = chunk[y_f].astype(np.int32)
                raw = chunk[c_f].astype(np.int64)  # WIDE type before clipping
                n_clamped += int((raw > countCeiling).sum())
                count[sl] = np.minimum(raw, countCeiling).astype(np.uint16)
                written += n
                if verbose:
                    print(f"[gef]   {written:,}/{n_records:,} records  {time.time()-t0:.0f}s")
        else:
            gene_index = np.zeros(n_records, np.int32)
            written = 0
            for i in range(n_genes):
                n = int(counts[i])
                if n == 0:
                    continue
                o = int(offsets[i])
                chunk = expr_ds[o : o + n]
                sl = slice(written, written + n)
                x[sl] = chunk[x_f].astype(np.int32)
                y[sl] = chunk[y_f].astype(np.int32)
                raw = chunk[c_f].astype(np.int64)
                n_clamped += int((raw > countCeiling).sum())
                count[sl] = np.minimum(raw, countCeiling).astype(np.uint16)
                gene_index[sl] = i
                written += n
                if verbose and i and i % 500 == 0:
                    print(f"[gef]   gene {i:,}/{n_genes:,}  {time.time()-t0:.0f}s")

        meta["nCountsClamped"] = n_clamped
        meta["box"], meta["boxSource"] = _gef_extent(f, chosen, x, y)
        meta["statTotals"], meta["statTotalsNote"] = _gef_stat_totals(f, gene_id)
        meta["readSeconds"] = time.time() - t0

        if verbose:
            b = meta["box"]
            print(
                f"[gef] extent {b[2]-b[0]+1} x {b[3]-b[1]+1} source units "
                f"(origin {b[0]},{b[1]}) from {meta['boxSource']}"
            )
            print(f"[gef] max count = {count.max()}, {n_clamped} clamped at {countCeiling}")

        return x, y, gene_index, count, gene_id, gene_name, meta
