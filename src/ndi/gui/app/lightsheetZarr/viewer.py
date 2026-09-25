"""Napari viewer wiring for lightsheetZarrPyramid.

Kept thin: this module only knows napari. Everything else - session
resolution, depends_on queries, dask arrays over chunk.bin_# files -
lives in ``multiscale``. Napari is an optional extra
(``pip install 'ndi[napari]'``); ``require_napari`` fails with that
hint rather than a bare ImportError.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any


class _FetchCounter:
    """Thread-safe observer for ``ndi.cloud.filehandler.watchFetches``.

    Aggregates start/done events into a single "N/M fetched, X in flight"
    status line, throttled to a print every ~0.5 s so a wall of concurrent
    chunk fetches from :class:`_ChunkFetcher`'s worker pool doesn't drown
    the terminal.
    """

    def __init__(self, out=sys.stderr, interval: float = 0.5):
        self._lock = threading.Lock()
        self._out = out
        self._interval = interval
        self._started = 0
        self._done = 0
        self._bytes = 0
        self._last_print = 0.0

    def __call__(self, event, uri, done, total):
        with self._lock:
            if event == "start":
                self._started += 1
            elif event == "done":
                self._done += 1
            elif event == "chunk" and isinstance(done, int):
                self._bytes = max(self._bytes, done)
            now = time.monotonic()
            if event in ("start", "done") and now - self._last_print >= self._interval:
                self._last_print = now
                in_flight = self._started - self._done
                print(
                    f"[lightsheet] fetched {self._done}/{self._started} "
                    f"(in flight: {in_flight})",
                    file=self._out,
                    flush=True,
                )


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
    from ndi.cloud.filehandler import watchFetches
    from ndi.gui.app.lightsheetZarr import multiscale

    verbose = bool(os.environ.get("NDI_LIGHTSHEET_DEBUG"))

    if verbose:
        print("[lightsheet] building lazy multiscale ladder ...", file=sys.stderr, flush=True)
    spec, fetcher = multiscale.layerSpec(
        session, pyramid_doc, channel=channel, name=name, reduction=reduction
    )

    if verbose:
        print(
            f"[lightsheet] ladder ready ({len(spec['data'])} levels); "
            "opening napari and streaming initial chunks ...",
            file=sys.stderr,
            flush=True,
        )

    # Build the fetcher's session handles now, off the main thread, so
    # the one-off session-open cost lands while napari's window is coming
    # up rather than at the first pan.
    try:
        fetcher.warm()
    except Exception:
        pass  # warm is best-effort; a fetch that needs it will still work

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

    # Watch fetches for the LIFETIME of the viewer. add_image only
    # builds the layer -- the actual cascade of chunk fetches happens
    # inside napari's Qt event loop as it renders, so an observer that
    # only wraps add_image is torn down before any fetch begins.
    counter = _FetchCounter() if verbose else None

    if show:
        try:
            if counter is not None:
                with watchFetches(counter):
                    napari.run()
            else:
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
