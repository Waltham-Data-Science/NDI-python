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
        show: call ``napari.run()``. False returns the viewer without
            blocking, which is what a test or a caller composing several
            layers wants.

    Returns:
        The napari Viewer.
    """
    napari = require_napari()

    viewer = napari.Viewer()
    viewer.add_image(**layerSpec(session, pyr_doc, gene_rows, density))

    if cells is not None:
        row, col = sourceToWorld(session, pyr_doc, cells["x"], cells["y"])
        viewer.add_points(
            list(zip(row, col)),
            name="cell centroids",
            size=cells.get("size", 8),
            face_color=cells.get("face_color", "red"),
            border_width=0,
        )

    if show:
        napari.run()
    return viewer
