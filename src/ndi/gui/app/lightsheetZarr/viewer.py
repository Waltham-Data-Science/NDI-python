"""Napari viewer wiring for lightsheetZarrPyramid.

Kept thin: this module only knows napari. Everything else - session
resolution, depends_on queries, dask arrays over chunk.bin_# files -
lives in ``multiscale``. Napari is an optional extra
(``pip install 'ndi[napari]'``); ``require_napari`` fails with that
hint rather than a bare ImportError.

Progress -- both the stderr channel and the Qt launch window -- lives
in :mod:`.progress` and is on by default; ``NDI_LIGHTSHEET_QUIET=1``
silences it, ``NDI_LIGHTSHEET_PROGRESS`` picks the mode, and
``NDI_LIGHTSHEET_DEBUG`` forces the stderr channel on top of a GUI.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any


class _FetchCounter:
    """Thread-safe observer for ``ndi.cloud.filehandler.watchFetches``.

    Prints a running count of chunk fetches to stderr, throttled to
    at most one line every ``interval`` seconds. Fires on every
    start/done event, so a user watching the terminal always sees
    activity within half a second of a chunk cascade starting -- the
    "silent hang" is what we're trying to avoid.

    Also prints an idle heartbeat every ``idle_interval`` seconds
    when there is no activity, so a user waiting on background load
    can tell the difference between "no fetches" and "still fetching
    slowly". The heartbeat is a separate thread that wakes on a
    condition variable, so it costs no CPU while activity is high.
    """

    def __init__(
        self,
        out=sys.stderr,
        interval: float = 0.5,
        idle_interval: float = 5.0,
    ):
        self._lock = threading.Lock()
        self._out = out
        self._interval = interval
        self._idle_interval = idle_interval
        self._started = 0
        self._done = 0
        self._last_activity = time.monotonic()
        self._last_print = 0.0
        self._stop = threading.Event()
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            name="ndi-lightsheet-heartbeat",
            daemon=True,
        )
        self._heartbeat.start()

    def __call__(self, event, uri, done, total):
        with self._lock:
            if event == "start":
                self._started += 1
                self._last_activity = time.monotonic()
            elif event == "done":
                self._done += 1
                self._last_activity = time.monotonic()
            elif event == "chunk":
                self._last_activity = time.monotonic()
            self._maybe_print(force=(event == "done" and self._done == self._started))

    def _maybe_print(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_print < self._interval:
            return
        self._last_print = now
        in_flight = self._started - self._done
        print(
            f"[lightsheet] tiles: {self._done} loaded / {self._started} requested "
            f"(in flight: {in_flight})",
            file=self._out,
            flush=True,
        )

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._idle_interval):
            with self._lock:
                idle = time.monotonic() - self._last_activity
                if self._started == 0:
                    print(
                        "[lightsheet] no tiles requested yet by napari; "
                        "waiting for first slice ...",
                        file=self._out,
                        flush=True,
                    )
                elif self._done < self._started and idle >= self._idle_interval:
                    self._maybe_print(force=True)

    def stop(self) -> None:
        self._stop.set()


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


def _enable_async_slicing(napari_module) -> None:
    """Turn on napari's async slicing so first-frame chunk fetches don't
    block the paint thread.

    A Ctrl+C traceback on a real cloud pyramid showed vispy's paintGL
    calling into napari's _project_thick_slice, which does
    np.asarray(data[slices]) -- a synchronous dask.compute() on the
    main thread. On a lazy cloud-backed multiscale layer that fires
    hundreds of HTTPS fetches before the window can repaint. With
    async slicing, napari schedules the slice compute on a worker
    thread and the paint thread returns immediately.

    Napari 0.5+ moved the toggle from the NAPARI_ASYNC env var to a
    settings property, so set it programmatically. Best-effort: on a
    napari version that has no such setting the call is a silent
    no-op and the caller gets whatever the default policy is.
    """
    import os

    os.environ.setdefault("NAPARI_ASYNC", "1")  # napari 0.4 fallback
    try:
        settings = napari_module.settings.get_settings()
        experimental = getattr(settings, "experimental", None)
        if experimental is not None and hasattr(experimental, "async_"):
            experimental.async_ = True
    except Exception:  # noqa: BLE001 - a setting that isn't there isn't fatal
        pass


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
    # Build the launch window BEFORE napari is imported: napari's own
    # QApplication then reuses ours, and Qt is up to draw the progress
    # bar while Python's import cost for napari lands. progress._mode
    # picks GUI on macOS/Windows and where a display is set.
    from . import progress

    progress.note("opening lightsheet pyramid ...")

    napari = require_napari()
    _enable_async_slicing(napari)

    from ndi.cloud.filehandler import watchFetches
    from ndi.gui.app.lightsheetZarr import multiscale

    with progress.stage("preparing on-demand image levels"):
        spec, fetcher = multiscale.layerSpec(
            session, pyramid_doc, channel=channel, name=name, reduction=reduction
        )

    # Warm the worker pool now, off the main thread. The one-off
    # session-open cost then overlaps with napari.Viewer()'s Qt startup
    # rather than serialising against the first fetch.
    with progress.stage("connecting to image store"):
        try:
            fetcher.warm()
        except Exception:
            pass

    with progress.stage("opening image viewer"):
        viewer = napari.Viewer()

    with progress.stage("attaching image to viewer"):
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

    # Print which multiscale level napari picks. Async slicing chooses
    # at paint time based on viewbox size and zoom; without this the
    # user is guessing whether it's level 0 (121k tiles) or level 3
    # (252 tiles) that is going through the fetcher. Best-effort:
    # older napari versions may not expose the event under the same
    # name, in which case the listener installs silently or not at
    # all and we lose only the extra line.
    _subscribe_level_change(viewer)

    # Launch window is closed BEFORE napari.run() because napari's
    # event loop blocks the main thread and our Qt window can't
    # repaint during it -- a frozen progress bar next to napari looks
    # worse than none. The stderr counter takes over as the "is
    # anything happening" indicator.
    progress.closeLaunchWindow()
    progress.note("viewer running -- watching tile fetches on stderr")

    counter = _FetchCounter()

    if show:
        try:
            with watchFetches(counter):
                napari.run()
        finally:
            counter.stop()
            fetcher.close()

    return viewer


def _subscribe_level_change(viewer) -> None:
    """Print a line to stderr each time napari picks a different level.

    Multiscale layers fire an event when they promote or demote to a
    coarser/finer level; napari's exact event name has moved between
    versions, so this walks a small set of known names and attaches
    to the first that exists. On a viewer whose layers don't expose
    any of them, this is a silent no-op.
    """
    for layer in getattr(viewer, "layers", []):
        events = getattr(layer, "events", None)
        if events is None:
            continue
        for name in ("data_level", "corner_pixels", "_data_level"):
            emitter = getattr(events, name, None)
            if emitter is None:
                continue
            emitter.connect(lambda e, lyr=layer, key=name: _report_level(lyr, key))
            break


def _report_level(layer, event_name: str) -> None:
    level = getattr(layer, "data_level", None)
    if level is None:
        level = getattr(layer, "_data_level", None)
    lname = getattr(layer, "name", "?")
    print(
        f"[lightsheet] napari picked level {level} for layer {lname!r} " f"(event={event_name})",
        file=sys.stderr,
        flush=True,
    )


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
