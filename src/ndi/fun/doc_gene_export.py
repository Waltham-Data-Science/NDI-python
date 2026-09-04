"""Reassemble GEF and HDF5 containers from spatial gene expression documents.

The pyramid exists because NDI Cloud can retrieve whole files but cannot
read a byte range out of one, so a viewer needs many small files. That is
the right shape for viewing and the wrong shape for handing to somebody
else's tool: Stereopy, geftools and the rest expect a single ``.gef``.
These functions close that gap, turning a stored pyramid back into a
container an outside tool will accept.

Two exports, deliberately distinct:

* :func:`exportGef` writes a Stereo-seq GEF -- gene-major, with the
  ``/geneExp/binN/{gene,expression}`` pair that SAW produces. Use it when
  the destination is a STOmics tool.
* :func:`exportHdf5` writes a plain HDF5 holding the CSR arrays as stored,
  plus the document properties as attributes. Use it when the destination
  is a script, and losing the document metadata would matter.

Neither is a byte-for-byte reconstruction of the original file. A GEF
carries more than expression -- exon counts, a whole-chip summary raster,
a tissue contour -- and the pyramid stores only what it was given. What
round-trips is the expression: every (pixel, gene, count) record at the
requested bin size, with the coordinate origin restored so positions are
back in source chip units rather than level-relative ones.
"""

from __future__ import annotations

import numpy as np

from .doc_gene import _find_level, exportRegion, readTileFile

__all__ = ["exportGef", "exportHdf5", "readGeneList"]


def readGeneList(session, pyr_doc):
    """The gene dictionary a pyramid is indexed against.

    Args:
        session: an ndi.session or ndi.dataset.
        pyr_doc: a spatialGeneExpressionPyramid document.

    Returns:
        ``(gene_ids, gene_names)``, each a list with one entry per gene
        row, in ZERO-BASED row order.
    """
    from ..query import ndi_query

    gl_id = pyr_doc.dependency_value("geneList_id")
    docs = session.database_search(ndi_query("").isa("geneList"))
    gl = next((d for d in docs if d.id == gl_id), None)
    if gl is None:
        raise ValueError(
            f"the geneList {gl_id} this pyramid depends on is not in this "
            f"session; a pyramid cannot be interpreted without it"
        )
    fh = session.database_openbinarydoc(gl, "genes.tsv")
    try:
        text = fh.read().decode("utf-8")
    finally:
        session.database_closebinarydoc(fh)

    ids, names = [], []
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        f = line.split("\t")
        # The index column is written explicitly and is ZERO-BASED. Assert
        # it rather than trusting that row order survived transport.
        if int(f[0]) != len(ids):
            raise ValueError(
                f"genes.tsv row {len(ids)} declares gene_index {f[0]}; the "
                f"file is out of order or not zero-based"
            )
        ids.append(f[1])
        names.append(f[2] if len(f) > 2 else "")
    return ids, names


def _gather(session, pyr_doc, bin_size):
    """Every stored record of one level, in SOURCE coordinates.

    Returns (x, y, gene_index, count) with the pyramid's origin added
    back, so positions are in chip units rather than level-relative ones.
    """
    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
    tile_doc, lv = _find_level(session, pyr_doc, bin_size)
    th, tw = int(lv["tile_size_y_bins"]), int(lv["tile_size_x_bins"])
    cols = int(p["tile_columns"])
    ox, oy = int(p["origin_x"]), int(p["origin_y"])
    b = int(lv["bin_size"])

    xs, ys, gs, cs = [], [], [], []
    for name in sorted(tile_doc.current_file_list(), key=lambda s: int(s.rsplit("_", 1)[1])):
        t_id = int(name.rsplit("_", 1)[1])
        tr, tc = divmod(t_id, cols)
        fh = session.database_openbinarydoc(tile_doc, name)
        try:
            t = readTileFile(fh)
        finally:
            session.database_closebinarydoc(fh)
        if t["n_pixels"] == 0:
            continue
        n_per = np.diff(t["offset"].astype(np.int64))
        # Level pixel -> source coordinate. The level pixel is the top-left
        # of a bin_size square, so multiplying by b recovers the bin's
        # origin in source units, not its centre; a consumer binning again
        # at the same size gets the same answer.
        gx = (t["x"].astype(np.int64) + tc * tw) * b + ox
        gy = (t["y"].astype(np.int64) + tr * th) * b + oy
        xs.append(np.repeat(gx, n_per))
        ys.append(np.repeat(gy, n_per))
        gs.append(t["gene_index"].astype(np.int64))
        cs.append(t["count"].astype(np.int64))

    if not xs:
        z = np.zeros(0, np.int64)
        return z, z, z, z
    return (np.concatenate(xs), np.concatenate(ys), np.concatenate(gs), np.concatenate(cs))


def exportGef(session, pyr_doc, bin_size, filename, resolution_nm=None):
    """Write a Stereo-seq GEF from a stored pyramid level.

    Produces the ``/geneExp/bin{N}/{gene,expression}`` pair SAW writes:
    ``expression`` is a compound array of (x, y, count) grouped by gene,
    and ``gene`` is the index into it, one row per gene with its offset
    and count. Coordinates are in source chip units.

    Args:
        session: an ndi.session or ndi.dataset.
        pyr_doc: a spatialGeneExpressionPyramid document.
        bin_size: which level to export.
        filename: path to write.
        resolution_nm: DNB pitch in nanometres for the file's
            ``resolution`` attribute. None derives it from the pyramid's
            ``base_pixel_size_x``, which is in micrometres.

    Returns:
        A dict describing what was written.
    """
    import h5py

    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
    ids, names = readGeneList(session, pyr_doc)
    x, y, g, c = _gather(session, pyr_doc, bin_size)

    # GEF is GENE-MAJOR: records grouped by gene, with an offset table.
    order = np.argsort(g, kind="stable")
    x, y, g, c = x[order], y[order], g[order], c[order]
    n_genes = len(ids)
    per_gene = np.bincount(g, minlength=n_genes).astype(np.uint32)
    offsets = np.concatenate([[0], np.cumsum(per_gene)[:-1]]).astype(np.uint32)

    if resolution_nm is None:
        resolution_nm = int(round(float(p["base_pixel_size_x"]) * 1000))

    expr_dt = np.dtype([("x", "<i4"), ("y", "<i4"), ("count", "<u2")])
    gene_dt = np.dtype(
        [("geneID", "S64"), ("geneName", "S64"), ("offset", "<u4"), ("count", "<u4")]
    )

    with h5py.File(filename, "w") as f:
        grp = f.create_group(f"/geneExp/bin{int(bin_size)}")
        expr = np.empty(len(x), expr_dt)
        expr["x"], expr["y"], expr["count"] = x, y, np.minimum(c, 65535)
        grp.create_dataset("expression", data=expr)

        gene = np.empty(n_genes, gene_dt)
        gene["geneID"] = [s.encode("utf-8")[:64] for s in ids]
        gene["geneName"] = [s.encode("utf-8")[:64] for s in names]
        gene["offset"], gene["count"] = offsets, per_gene
        grp.create_dataset("gene", data=gene)

        # Attributes on the BIN GROUP, not only the file root. Readers
        # differ about where they look, and a reader that probes only the
        # root and finds nothing silently derives a 1x1 extent -- which is
        # how the bounding box was first got wrong in this project.
        for target in (grp, f):
            target.attrs["minX"] = int(p["origin_x"])
            target.attrs["minY"] = int(p["origin_y"])
            target.attrs["maxX"] = int(p["origin_x"]) + int(p["extent_x"]) - 1
            target.attrs["maxY"] = int(p["origin_y"]) + int(p["extent_y"]) - 1
            target.attrs["resolution"] = int(resolution_nm)
        f.attrs["omicsType"] = "Transcriptomics"
        f.attrs["sn"] = str(p.get("chip_serial", ""))
        f.attrs["ndi_pyramid_id"] = str(pyr_doc.id)
        f.attrs["ndi_note"] = (
            "Reassembled from an NDI spatialGeneExpressionPyramid. Expression "
            "round-trips; exon counts, the whole-chip summary raster and the "
            "tissue contour of an original GEF are not represented."
        )

    return {
        "filename": str(filename),
        "bin_size": int(bin_size),
        "n_records": int(len(x)),
        "n_genes": n_genes,
        "total_counts": int(c.sum()),
        "resolution_nm": int(resolution_nm),
    }


def exportHdf5(session, pyr_doc, bin_size, filename, genes=None):
    """Write a plain HDF5 of one level as a sparse (pixel x gene) matrix.

    Unlike :func:`exportGef` this keeps the document metadata, so the file
    is self-describing for a script that has no NDI session. Use it when
    the destination is analysis code rather than a STOmics tool.

    Args:
        genes: ZERO-BASED gene rows to include, or None for all.

    Returns:
        A dict describing what was written.
    """
    import h5py

    p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
    _, lv = _find_level(session, pyr_doc, bin_size)
    ids, names = readGeneList(session, pyr_doc)
    M, pixel_xy = exportRegion(session, pyr_doc, bin_size)

    if genes is not None:
        genes = np.asarray(genes, np.int64)
        M = M[:, genes]
        ids = [ids[i] for i in genes]
        names = [names[i] for i in genes]

    ox, oy = int(p["origin_x"]), int(p["origin_y"])
    b = int(lv["bin_size"])

    with h5py.File(filename, "w") as f:
        d = f.create_group("data")
        # CSR as stored, so a reader can reconstruct without densifying.
        d.create_dataset("indptr", data=M.indptr)
        d.create_dataset("indices", data=M.indices)
        d.create_dataset("counts", data=M.data)
        d.attrs["shape"] = np.array(M.shape, np.int64)
        d.attrs["layout"] = "csr: rows are occupied pixels, columns are genes"

        px = f.create_group("pixel")
        px.create_dataset("x_level", data=pixel_xy[:, 0])
        px.create_dataset("y_level", data=pixel_xy[:, 1])
        # Both frames, because which one a consumer wants depends on
        # whether it is comparing against the chip or against this level,
        # and deriving one from the other silently gets the origin wrong.
        px.create_dataset("x_source", data=pixel_xy[:, 0] * b + ox)
        px.create_dataset("y_source", data=pixel_xy[:, 1] * b + oy)

        gg = f.create_group("gene")
        gg.create_dataset("gene_id", data=np.array(ids, dtype="S64"))
        gg.create_dataset("gene_name", data=np.array(names, dtype="S64"))
        gg.attrs["index_base"] = 0

        for k, v in p.items():
            f.attrs[f"pyramid_{k}"] = v if not isinstance(v, list) else np.array(v)
        for k, v in lv.items():
            if k == "tiles":
                continue
            f.attrs[f"level_{k}"] = v if not isinstance(v, list) else np.array(v)
        f.attrs["ndi_pyramid_id"] = str(pyr_doc.id)

    return {
        "filename": str(filename),
        "bin_size": int(bin_size),
        "n_pixels": int(M.shape[0]),
        "n_genes": int(M.shape[1]),
        "total_counts": int(M.sum()),
    }
