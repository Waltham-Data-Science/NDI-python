"""Shared core for ROI-based .gef ingest: records -> N per-ROI pyramids.

Mirrors ``+ndi/+fun/+doc/+gene/private/buildROIpyramids.m`` from NDI-matlab
PR #1150. Python has no ``+private/`` convention; a leading underscore on the
module name is the equivalent.

This module exists so :func:`ndi.fun.doc_gene.fromGEFbyROI` and
:func:`ndi.fun.doc_gene.fromGEFinteractive` share the per-polygon loop:
both read a GEF, hand the records plus a list of (subject, polygon) pairs
to :func:`build_roi_pyramids`, and get back one pyramid per polygon with
shared geneList / sourceFile documents and a per-polygon
spatialGeneExpressionROI provenance sidecar.

Not part of the public API; callers go through :mod:`ndi.fun.doc_gene`.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
from matplotlib.path import Path as _MplPath


def _doc_id(doc) -> str:
    """Id of a document, with None/empty string passing through as ''."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    try:
        return doc.id
    except AttributeError:
        return ""


def _tick(fcn, frac: float, txt: str) -> None:
    """Silent when no handle, so every phase can report uniformly."""
    if fcn is None:
        return
    fcn(float(frac), txt)


def _sub_progress(fcn, lo: float, hi: float):
    """Re-scale a [0, 1] progress handle onto the ``[lo, hi]`` slice."""
    if fcn is None:
        return None

    def sub(frac, txt):
        fcn(lo + (hi - lo) * frac, txt)

    return sub


def _points_in_polygon(x, y, poly_x, poly_y) -> np.ndarray:
    """Which (x, y) points lie inside the polygon drawn by (poly_x, poly_y).

    MATLAB equivalent: ``inpolygon``. ``matplotlib.path.Path.contains_points``
    runs the same ray-cast under a C-accelerated loop, so a hemisphere's
    ~1e8 records costs seconds rather than the minutes a pure-Python
    ``inpolygon`` would need. shapely would also work and brings a heavier
    dependency; matplotlib is already in the NDI dep set.
    """
    pts = np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
    verts = np.column_stack([np.asarray(poly_x, dtype=float), np.asarray(poly_y, dtype=float)])
    return _MplPath(verts).contains_points(pts)


def build_roi_pyramids(
    session,
    x,
    y,
    gene_index,
    count,
    gene_id,
    gene_name,
    meta: dict[str, Any],
    gef_path: str,
    subjects: list[str],
    polygons: list,
    options: dict[str, Any],
):
    """Already-read records plus (subject, polygon) pairs -> N pyramids.

    MATLAB equivalent: ``+ndi/+fun/+doc/+gene/private/buildROIpyramids``.

    Takes GEF records already in memory and builds one
    ``spatialGeneExpressionPyramid`` per polygon, each tagged with its
    subject. The geneList and the sourceFile documents are SHARED across
    all ROIs: every pyramid built here came from the same .gef and the
    same gene annotation, so the dependent documents point at a single
    geneList and (when ``options['recordSource']`` is True) a single
    sourceFile.

    The geometry is recorded next to each pyramid as a
    ``spatialGeneExpressionROI`` document so a V2 importer can lift it
    back without asking the scientist to redraw.

    Args:
        session: an ndi.session or ndi.dataset.
        x, y, gene_index, count, gene_id, gene_name, meta: the output of
            ``ndr.format.stereoseq.readGEF``, held once by the caller.
        gef_path: path to the .gef, used only to describe the source
            file.
        subjects: list of subject ids, one per polygon, each a nonempty
            string.
        polygons: list of ``(M, 2)`` arrays, one per subject, in GEF
            pixel coordinates (column 0 is x, column 1 is y, M>=3).
        options: dict with the same fields fromGEFbyROI exposes
            (binSizes, grid, basePixelSize, etc.). Not a Pydantic
            model because this is a private, named-argument-pass-through
            path; makePyramid validates each on its way in.

    Returns:
        ``(pyr_docs, tile_docs_list, gene_list_doc, source_doc, info)``.

        - ``pyr_docs``: list of pyramid documents; ``None`` for an
          empty-polygon ROI.
        - ``tile_docs_list``: list of tile-document lists; ``None`` for
          an empty-polygon ROI.
        - ``gene_list_doc``: the single shared geneList.
        - ``source_doc``: the shared sourceFile document, or ``None``
          when ``recordSource`` is False.
        - ``info``: dict with ``meta``, ``sourceDoc``, ``notes``,
          ``nKeepPerROI`` (1xN count of records in each polygon), and
          ``roiDocs`` (list of spatialGeneExpressionROI documents).

    Raises:
        ValueError: on empty subject/polygon lists, length mismatches, a
            polygon of the wrong shape, or an empty subject id.
    """
    # Local import to keep the module loadable without the heavier
    # document stack; those imports only matter at call time.
    from .doc_gene import makeGeneList, makePyramid, makeROI, makeSourceFile, readNotes

    n = len(subjects)
    if len(polygons) != n:
        raise ValueError(
            f"subjects and polygons must be the same length, got {n} and {len(polygons)}."
        )
    if n == 0:
        raise ValueError("At least one (subject, polygon) pair is required.")

    # -- resolve the chip and the base pixel size, same as fromGEF ------
    chip_serial = options.get("chipSerial", "") or ""
    if not chip_serial:
        meta_cs = (
            meta.get("chipSerial", "")
            if isinstance(meta, dict)
            else getattr(meta, "chipSerial", "")
        )
        chip_serial = meta_cs or ""
    base_pixel_size = options.get("basePixelSize")
    if base_pixel_size is None:
        meta_res = (
            meta.get("resolutionNm", None)
            if isinstance(meta, dict)
            else getattr(meta, "resolutionNm", None)
        )
        if meta_res is not None:
            # resolutionNm is NANOMETRES and basePixelSize is micrometres;
            # SAW's usual 500 nm -> 0.5 um.
            base_pixel_size = (float(meta_res) / 1000.0, float(meta_res) / 1000.0)
        else:
            base_pixel_size = (0.5, 0.5)
    else:
        base_pixel_size = tuple(float(v) for v in base_pixel_size)

    progress_fcn = options.get("progressFcn")

    # -- shared documents -----------------------------------------------
    _tick(progress_fcn, 0.55, "Building the gene list...")
    gene_list_doc = makeGeneList(
        session,
        gene_id,
        gene_name,
        genomeAssembly=options.get("genomeAssembly", "") or "",
        annotationSource=options.get("annotationSource", "") or "",
        geneIdNamespace=options.get("geneIdNamespace", "") or "",
        geneSymbolNamespace=options.get("geneSymbolNamespace", "") or "",
        label=options.get("label", "") or "",
    )

    source_doc = None
    source_file_id = ""
    if options.get("recordSource", True):
        _tick(progress_fcn, 0.60, "Describing the source file...")
        source_doc = makeSourceFile(session, gef_path, checksum=options.get("checksum", True))
        session.database_add(source_doc)
        source_file_id = source_doc.id

    # -- per-ROI pyramids -----------------------------------------------
    # Progress plan: 0.00-0.55 is the caller's readGEF, 0.55-0.65 is the
    # shared docs above, 0.65-1.00 is the N pyramids divided evenly.
    pyr_docs: list = [None] * n
    tile_docs_list: list = [None] * n
    roi_docs: list = [None] * n
    n_keep_per_roi = [0] * n
    pyramid_span = 1.0 - 0.65
    pyramid_per_roi = pyramid_span / n

    # Double once, for the inpolygon pass only; the records go to
    # makePyramid in the type the reader gave them. Promoting them for
    # the whole build would cost 32 bytes a record where 14 does.
    x_arr = np.asarray(x)
    y_arr = np.asarray(y)
    gene_index_arr = np.asarray(gene_index)
    count_arr = np.asarray(count)
    xd = x_arr.astype(np.float64, copy=False)
    yd = y_arr.astype(np.float64, copy=False)

    for k in range(n):
        poly = np.asarray(polygons[k], dtype=float)
        if poly.ndim != 2 or poly.shape[1] != 2:
            raise ValueError(
                f"Polygon {k} must be numeric Mx2 with M>=3; " f"got shape {poly.shape}."
            )
        if poly.shape[0] < 3:
            raise ValueError(f"Polygon {k} must have at least 3 vertices; got {poly.shape[0]}.")
        sub_val = subjects[k]
        if not isinstance(sub_val, str) or not sub_val:
            raise ValueError(
                f"Subject {k} is empty or not a string; every polygon needs a "
                f"nonempty subject id."
            )
        subject_id = sub_val

        poly_x = poly[:, 0]
        poly_y = poly[:, 1]

        # bbox prefilter cuts inpolygon's query set by (bbox area /
        # extent area) for free: on a hemisphere split into three
        # pieces that is a ~3x speedup. A separate boolean-to-index step
        # keeps keep_idx in records-space so the subsequent indexing
        # into x/y/gene_index/count stays type-preserving.
        bb_mask = (
            (xd >= poly_x.min())
            & (xd <= poly_x.max())
            & (yd >= poly_y.min())
            & (yd <= poly_y.max())
        )
        bb_idx = np.flatnonzero(bb_mask)
        if bb_idx.size == 0:
            keep_idx = bb_idx
        else:
            in_poly = _points_in_polygon(xd[bb_idx], yd[bb_idx], poly_x, poly_y)
            keep_idx = bb_idx[in_poly]
        n_keep_per_roi[k] = int(keep_idx.size)

        _tick(
            progress_fcn,
            0.65 + k * pyramid_per_roi,
            f"Pyramid {k + 1} of {n} ({n_keep_per_roi[k]} records)...",
        )

        if n_keep_per_roi[k] == 0:
            warnings.warn(
                f"Polygon {k} (subject {subject_id}) contained no records; "
                f"no pyramid was built. The ROI document is still recorded.",
                RuntimeWarning,
                stacklevel=2,
            )
            # Record the geometry anyway. The pyramid dependency stays
            # unset (the ROI schema allows that, per the MATLAB code
            # comment; see the known-upstream-issue note in the bridge
            # decision_log for makeROI).
            roi_docs[k] = makeROI(
                session,
                None,
                poly,
                sourceFileID=source_file_id,
                label=options.get("label", "") or "",
                nRecordsIn=0,
            )
            continue

        sub = _sub_progress(
            progress_fcn,
            0.65 + k * pyramid_per_roi,
            0.65 + (k + 1) * pyramid_per_roi,
        )

        pyr_doc, tile_docs = makePyramid(
            session,
            x_arr[keep_idx],
            y_arr[keep_idx],
            gene_index_arr[keep_idx],
            count_arr[keep_idx],
            gene_list_doc,
            subjectID=subject_id,
            binSizes=options.get("binSizes", (1, 2, 4, 8, 16, 32)),
            grid=options.get("grid"),
            tileBudgetBytes=options.get("tileBudgetBytes", 50 * 2**20),
            gridRange=options.get("gridRange", (3, 64)),
            basePixelSize=base_pixel_size,
            pixelSizeUnits=options.get("pixelSizeUnits", "micrometer"),
            label=options.get("label", "") or "",
            assay=options.get("assay", "Stereo-seq") or "Stereo-seq",
            chipSerial=chip_serial,
            pipelineVersion=options.get("pipelineVersion", "") or "",
            origin=options.get("origin"),
            sourceFileID=source_file_id,
            progressFcn=sub,
        )
        pyr_docs[k] = pyr_doc
        tile_docs_list[k] = tile_docs

        # Provenance sidecar: keep the drawn polygon on record next to
        # the pyramid it carved out.
        roi_docs[k] = makeROI(
            session,
            pyr_doc,
            poly,
            sourceFileID=source_file_id,
            label=options.get("label", "") or "",
            nRecordsIn=n_keep_per_roi[k],
        )

    _tick(progress_fcn, 1.0, "Done.")

    info = {
        "meta": meta,
        "sourceDoc": source_doc,
        "notes": readNotes(meta, gene_id),
        "nKeepPerROI": list(n_keep_per_roi),
        "roiDocs": roi_docs,
    }
    return pyr_docs, tile_docs_list, gene_list_doc, source_doc, info
