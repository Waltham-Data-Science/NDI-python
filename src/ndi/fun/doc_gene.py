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


def renderTile(tile: dict[str, Any], gene_rows, h: int, w: int,
               binSize: int = 1, out=None) -> np.ndarray:
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
        per_pixel = np.add.reduceat(np.where(keep, cnt, 0).astype(np.float32),
                                    off[:-1])
    # reduceat on an empty run returns the element at that index rather
    # than zero, so empty pixels have to be zeroed explicitly.
    per_pixel[np.diff(off) == 0] = 0

    if binSize != 1:
        per_pixel = per_pixel * np.float32(1.0 / (binSize * binSize))
    np.add.at(img, (tile["y"].astype(np.int64), tile["x"].astype(np.int64)),
              per_pixel)
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
            f"{len(x)}, {len(y)}, {len(gene_index)}, {len(count)}")

    if len(x) == 0:
        return b"".join([np.uint32(0).tobytes(), np.uint32(0).tobytes(),
                         np.zeros(1, _DTYPES["offset"]).tobytes()])

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

    return b"".join([
        np.uint32(len(starts)).tobytes(),
        np.uint32(len(key)).tobytes(),
        x[starts].astype(_DTYPES["coordinate"]).tobytes(),
        y[starts].astype(_DTYPES["coordinate"]).tobytes(),
        offset.tobytes(),
        gene_index.astype(_DTYPES["gene_index"]).tobytes(),
        count.astype(_DTYPES["count"]).tobytes(),
    ])


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
    expected = (2 * _DTYPES["offset"].itemsize
                + 2 * n_pixels * _DTYPES["coordinate"].itemsize
                + (n_pixels + 1) * _DTYPES["offset"].itemsize
                + n_nonzero * _DTYPES["gene_index"].itemsize
                + n_nonzero * _DTYPES["count"].itemsize)
    if len(raw) != expected:
        raise ValueError(
            f"tile file has {len(raw)} bytes but its header describes "
            f"{expected} (n_pixels={n_pixels}, n_nonzero={n_nonzero}); "
            f"the file is truncated or not format version 1")

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
    return dict(n_pixels=n_pixels, n_nonzero=n_nonzero, x=x, y=y,
                offset=offset, gene_index=gene_index, count=count)


# =========================================================================
# Document makers
#
# Mirrors +ndi/+fun/+doc/+gene/{makeGeneList,makePyramid,readViewport,
# exportRegion}.m and its private/storeDoc.m.
# =========================================================================

import os
import tempfile

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
            f"{len(file_names)} and {len(file_paths)}")
    for name, path in zip(file_names, file_paths):
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"file {path!r} for document entry {name!r} does not exist")
        doc = doc.add_file(name, path)
    session.database_add(doc)
    return doc


def makeGeneList(session, gene_id, gene_name, genomeAssembly: str = "",
                 annotationSource: str = "", geneIdNamespace: str = "",
                 geneSymbolNamespace: str = "", label: str = ""):
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
            f"gene_id and gene_name must be the same length, got {n} and "
            f"{len(gene_name)}")

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

    doc = _blank("geneList", geneList={
        "label": label,
        "n_genes": n,
        "genome_assembly": genomeAssembly,
        "gene_id_namespace": geneIdNamespace,
        "gene_symbol_namespace": geneSymbolNamespace,
        "annotation_source": annotationSource,
        "gene_name_completeness": completeness,
        "n_duplicate_gene_names": n_dup,
    }) + session.newdocument()
    try:
        return _store_doc(session, doc, ["genes.tsv"], [tsv_path])
    finally:
        if os.path.exists(tsv_path):
            os.unlink(tsv_path)
