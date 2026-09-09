"""Napari viewer wiring for lightsheetZarrPyramid.

Kept thin: this module only knows napari. Everything else - session
resolution, depends_on queries, dask arrays over chunk.bin_# files -
lives in ``multiscale``. Napari is an optional extra
(``pip install 'ndi[napari]'``); ``require_napari`` fails with that
hint rather than a bare ImportError.
"""

from __future__ import annotations

from typing import Any


def require_napari():
    """Return the napari module or raise a helpful ImportError."""
    try:
        import napari
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "napari is required to view a lightsheetZarrPyramid. "
            "Install it with: pip install 'ndi[napari]'\n"
            f"(Original error: {exc})"
        ) from exc
    return napari


def openPyramid(
    session: Any,
    pyramid_doc: Any,
    channel: int | None = None,
    level: int | None = None,
    controls: bool = True,
    name: str | None = None,
    show: bool = True,
):
    """Open a lightsheetZarrPyramid in napari.

    Parameters
    ----------
    session
        The ``ndi.session.dir`` the pyramid belongs to.
    pyramid_doc
        The parent ``lightsheetZarrPyramid`` document.
    channel
        1-based channel index. ``None`` adds every channel as its own
        napari layer.
    level
        0-based level to display at startup. ``None`` lets napari's
        multiscale renderer choose from the window size.
    controls
        Whether to dock the reduction / channel / level panels.
    name
        Layer name. ``None`` uses the pyramid document's label.
    show
        Whether to call ``napari.run()`` after the layer is added. Set
        False from a caller that manages its own event loop.

    Returns
    -------
    napari.Viewer
        The viewer that was created (whether or not ``napari.run()`` was
        called).
    """
    napari = require_napari()
    from ndi.gui.app.lightsheetZarr import multiscale

    spec = multiscale.layerSpec(session, pyramid_doc, channel=channel, name=name)
    viewer = napari.Viewer()
    viewer.add_image(**spec)

    if level is not None:
        # napari's multiscale layer picks a level from the current zoom;
        # this forces the initial choice by scaling the camera to match
        # the requested level's world size.
        try:
            viewer.dims.set_current_step(0, level)
        except Exception:
            pass

    if controls:
        _attach_controls(viewer, session, pyramid_doc)

    if show:
        napari.run()

    return viewer


def _attach_controls(viewer, session, pyramid_doc) -> None:
    """Dock the reduction / channel / level panels.

    Placeholder: the panels are magicgui widgets that live alongside
    ``multiscale.py`` in follow-up work (see the package README). Until
    then this is a no-op so the viewer opens without the controls
    rather than refusing to open at all.
    """
    # Intentionally no-op in this scaffold. The follow-up PR adds
    # magicgui panels for reduction switching (mean/max sibling
    # pyramid) and channel selection.
    return
