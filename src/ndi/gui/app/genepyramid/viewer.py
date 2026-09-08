"""Hand a pyramid to napari. Thin on purpose.

Everything that can be wrong -- the ladder, the scale, the translate --
is computed and tested in :mod:`multiscale`, which imports no napari and
needs no display. What is left here is the call itself.
"""

from __future__ import annotations

from typing import Any

from .multiscale import layerSpec, sourceToWorld

__all__ = ["require_napari", "openPyramid"]


def require_napari():
    """Return the napari module, or say what to install.

    napari stays an EXTRA rather than a runtime dependency, for the same
    reason PySide6 does: a headless install -- a pipeline, a container, an
    analysis box with no display -- should not pull in Qt and OpenGL. The
    failure mode for a missing toolkit is then a sentence rather than a
    traceback.
    """
    try:
        import napari
    except ImportError as e:
        raise ImportError(
            "napari is required to view a gene pyramid. Install it with:  "
            f"pip install 'ndi[napari]'\n(Original error: {e})"
        ) from e
    return napari


def openPyramid(
    session,
    pyr_doc,
    gene_rows=None,
    density: bool = True,
    cells: dict[str, Any] | None = None,
    outlines=None,
    cells_doc=None,
    controls: bool = True,
    labelings=None,
    name: str | None = None,
    show: bool = True,
):
    """Open a spatial gene expression pyramid in napari.

    Args:
        session: an ndi.session or ndi.dataset.
        pyr_doc: a spatialGeneExpressionPyramid document.
        gene_rows: ZERO-BASED geneList rows to show, or None for all.
        density: counts per base pixel rather than per bin, so one
            contrast range serves the whole ladder. See
            :func:`~.multiscale.levelArrays`.
        cells: optional ``{"x": ..., "y": ...}`` in SOURCE coordinates,
            added as a Points layer. Routed through
            :func:`~.multiscale.sourceToWorld` rather than passed
            straight in, because the image layer carries the origin in
            its translate and centroids that skip that transform land
            somewhere plausible and wrong.
        outlines: optional list of ``(N, 2)`` ``[x, y]`` vertex arrays in
            SOURCE coordinates, as :func:`~ndi.fun.doc_gene.readContours`
            returns them, drawn as a Shapes layer. Routed through
            :func:`~.multiscale.sourceToWorld` for the same reason
            centroids are. Empty polygons are dropped: napari treats a
            zero-vertex shape as malformed rather than as nothing.
        cells_doc: the spatialGeneExpressionCells document the overlay
            came from. Only needed for the cell-type panel, which reads
            the cellTypeLabels documents that depend on it -- the cells
            themselves arrive as plain arrays and carry no way back to
            their own document.
        labelings: label names to show in the cell-type panel, or None to
            let it decide. Two labelings that say the same thing about the
            section -- a subclass call transferred onto the clustering it
            was transferred onto -- are otherwise drawn twice, so by
            default the panel keeps one and says so. Naming them here
            overrides that entirely.
        controls: dock the gene, display and cell-type panels. Without
            them the gene selection and the density choice are fixed at
            launch, since this viewer holds no other state. Skipped with
            a note when Qt is unavailable -- they are conveniences and
            their absence must not stop the picture.
        name: image layer name. Defaults to the pyramid's label, which is
            whatever the ingest recorded -- often the file stem, which
            names the section rather than what is being shown.
        show: call ``napari.run()``. False returns the viewer without
            blocking, which is what a test or a caller composing several
            layers wants.

    Returns:
        The napari Viewer.
    """
    napari = require_napari()

    viewer = napari.Viewer()
    image = viewer.add_image(**layerSpec(session, pyr_doc, gene_rows, density, name))

    shapes = None
    if outlines is not None:
        keep = [p for p in outlines if len(p)]
        if keep:
            paths = []
            for p in keep:
                row, col = sourceToWorld(session, pyr_doc, p[:, 0], p[:, 1])
                paths.append(list(zip(row, col)))
            # shape_type polygon closes the ring itself, which matches the
            # format: writeContourFile does not repeat the first vertex.
            shapes = viewer.add_shapes(
                paths,
                shape_type="polygon",
                name="cell outlines",
                face_color="transparent",
                edge_color="cyan",
                edge_width=1,
            )

    points = None
    if cells is not None:
        row, col = sourceToWorld(session, pyr_doc, cells["x"], cells["y"])
        points = viewer.add_points(
            list(zip(row, col)),
            name="cell centroids",
            size=cells.get("size", 8),
            face_color=cells.get("face_color", "red"),
            border_width=0,
        )

    if controls:
        from .controls import addAllPanels

        # Remembered on the layer so the display panel can rebuild the
        # ladder with the SAME gene selection when it switches between
        # density and counts; recomputing with all genes would silently
        # widen what is being shown.
        image._ndi_gene_rows = gene_rows
        addAllPanels(
            viewer,
            session,
            pyr_doc,
            image,
            density,
            cells_doc=cells_doc,
            points_layer=points,
            shapes_layer=shapes,
            labelings=labelings,
        )

    if show:
        napari.run()
    return viewer
