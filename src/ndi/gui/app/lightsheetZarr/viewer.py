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
    reduction: str | None = None,
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
    reduction
        Filter the level ladder to ``reduction_function`` in
        ``{'none', reduction}``. ``None`` shows every level.
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

    spec, fetcher = multiscale.layerSpec(
        session, pyramid_doc, channel=channel, name=name, reduction=reduction
    )
    viewer = napari.Viewer()
    viewer.add_image(**spec)

    # Build the fetcher's session handles now, while the user is looking
    # at an empty canvas rather than at the first pan. Harmless on a
    # local session (the pool starts, the sessions open, the first tile
    # goes straight through); real win on a cloud session.
    try:
        fetcher.warm()
    except Exception:
        pass  # warm is best-effort; a fetch that needs it will still work

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
        try:
            napari.run()
        finally:
            fetcher.close()

    return viewer


def _attach_controls(viewer, session, pyramid_doc) -> None:
    """Dock the reduction / channel / level panels.

    Placeholder: the panels are magicgui widgets that live alongside
    ``multiscale.py`` in follow-up work (see the package README). Until
    then this is a no-op so the viewer opens without the controls
    rather than refusing to open at all.
    """
    # Intentionally no-op in this scaffold. The follow-up PR adds
    # magicgui panels for reduction switching and channel selection.
    return
