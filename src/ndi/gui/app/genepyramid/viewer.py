"""Hand a pyramid to napari. Thin on purpose.

Everything that can be wrong -- the ladder, the scale, the translate --
is computed and tested in :mod:`multiscale`, which imports no napari and
needs no display. What is left here is the call itself.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .multiscale import layerSpec, sourceToWorld, worldTransform

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
    gene_layers=None,
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
        gene_layers: ``(symbol, colormap)`` pairs to open as their own
            additive layers on top of the base image, as
            :func:`~.controls.parseGeneLayers` returns them. A DIFFERENT
            request from *gene_rows*, which filters the base layer to a
            subset and leaves one picture; this adds a layer per gene, so
            the base stays and the genes are comparable against it.
        name: image layer name. Defaults to the pyramid's label, which is
            whatever the ingest recorded -- often the file stem, which
            names the section rather than what is being shown.
        show: call ``napari.run()``. False returns the viewer without
            blocking, which is what a test or a caller composing several
            layers wants.

    Returns:
        The napari Viewer.
    """
    from .progress import closeLaunchWindow, note, stage

    with stage("starting napari"):
        napari = require_napari()

    viewer = napari.Viewer()
    # NAPARI'S OWN THEME IS LEFT ALONE, which means the canvas stays dark.
    # Setting it to "light" did put the docks on a light ground, but it
    # took the CANVAS with it -- and a dark canvas is what imaging data is
    # read against. What was actually wanted was the PANELS on the NDI
    # Cloud palette, and those are styled individually in
    # ndi.gui.app.genepyramid.controls.applyCloudStyle, which does not
    # touch the canvas. Two different surfaces, and only one of them
    # should be white.
    # The image ladder is LAZY: layerSpec resolves tile paths and the
    # level table, and reads no tile bytes. Nothing here is the wait.
    with stage("preparing the image levels (read on demand)"):
        spec = layerSpec(session, pyr_doc, gene_rows, density, name)
    # SPLIT FROM THE LADDER, because only one of these two is lazy and the
    # label used to claim both were. Building the ladder reads nothing.
    # add_image then makes napari's thumbnail, and napari builds that by
    # materialising the WHOLE COARSEST LEVEL -- Image._post_init calls
    # refresh, which reaches _level_materializer and computes the dask
    # array for the thumbnail level. On a real section that is gigabytes
    # of tiles, and on a downloaded dataset it is gigabytes of fetching.
    #
    # It is the longest step of a cold launch and it used to sit behind a
    # label that said "(lazy)", which is why it read as a hang. Naming it
    # does not make it fast; it makes it legible.
    with stage("drawing the overview (reads the whole lowest-resolution level)"):
        image = viewer.add_image(**spec)

    shapes = None
    if outlines is not None:
        keep = [p for p in outlines if len(p)]
        if keep:
            # np.column_stack per polygon rather than list(zip(row, col)):
            # the tuple form built twelve million Python tuples for the
            # opossum section and cost 13.8s, against 1.6s for this.
            with stage(f"placing {len(keep):,} outlines"):
                (sy, sx), _t = worldTransform(session, pyr_doc)
                paths = [np.column_stack([p[:, 1] * sy, p[:, 0] * sx]) for p in keep]
            # shape_type polygon closes the ring itself, which matches the
            # format: writeContourFile does not repeat the first vertex.
            #
            # THIS IS THE SLOW ONE and nothing here can make it fast:
            # napari triangulates every polygon as it takes them.
            note(
                f"drawing {len(keep):,} cell outlines. Each one has to be cut "
                f"into triangles before it can be drawn, which is the long "
                f"part of the launch. Leave out --outlines to skip it."
            )
            with stage("drawing the cell outlines"):
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
        with stage(f"placing {len(cells['x']):,} centroids"):
            row, col = sourceToWorld(session, pyr_doc, cells["x"], cells["y"])
            coords = np.column_stack([row, col])
        with stage("drawing the cell centroids"):
            points = viewer.add_points(
                coords,
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
        with stage("building the control panels"):
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
                gene_layers=gene_layers,
            )

    # The launch window has reported everything it can: the viewer is
    # built and the panels are on it. Leaving it up past this point would
    # make a finished launch look stuck, and it would sit over the picture
    # it exists to get you to.
    closeLaunchWindow()

    if show:
        napari.run()
    return viewer
