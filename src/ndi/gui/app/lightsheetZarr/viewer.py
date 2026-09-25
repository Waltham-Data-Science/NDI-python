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

    Prints a running count of tile fetches to stderr and tracks per-fetch
    timing / byte counts so a user can decide whether the current chunk
    size is right for their link. The tuning question we want to answer
    is "are tiles latency-bound or bandwidth-bound?" -- if each 4 MB
    fetch takes 0.5 s of TLS handshake plus 20 ms of actual transfer,
    bigger chunks win; if 4 MB streams in 200 ms and the connection is
    already saturated, they don't.

    Three channels of output, all on stderr:

    * Per-fetch (throttled): every ``interval`` seconds during a
      cascade, one summary line -- "tiles: D loaded / S requested (in
      flight: X); last fetch Ys, Z MB". Fires on start and done so
      activity is visible within half a second.
    * Heartbeat: every ``idle_interval`` seconds when no lines have
      printed, either "no tiles requested yet by napari" (before the
      first fetch) or the current counter (during a slow cascade). A
      daemon thread wakes on a condition variable so it costs no CPU
      while activity is high.
    * Aggregate on stop: one closing summary -- fetches, total MB,
      wall clock, mean and max per-fetch time, effective MB/s. Emitted
      when :meth:`stop` is called (after napari.run() returns) so a
      viewer session ends with the numbers a user needs to pick a
      chunk size.
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
        self._pending_starts: dict[str, float] = {}
        self._pending_bytes: dict[str, int] = {}
        self._durations: list[float] = []
        self._byte_sizes: list[int] = []
        self._last_duration: float | None = None
        self._last_bytes: int | None = None
        self._session_start = time.monotonic()
        self._stop = threading.Event()
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            name="ndi-lightsheet-heartbeat",
            daemon=True,
        )
        self._heartbeat.start()

    def __call__(self, event, uri, done, total):
        with self._lock:
            now = time.monotonic()
            if event == "start":
                self._started += 1
                self._pending_starts[uri] = now
                self._pending_bytes[uri] = 0
                self._last_activity = now
            elif event == "chunk":
                if isinstance(done, int):
                    self._pending_bytes[uri] = max(self._pending_bytes.get(uri, 0), done)
                self._last_activity = now
            elif event == "done":
                self._done += 1
                self._last_activity = now
                t_start = self._pending_starts.pop(uri, None)
                nbytes = self._pending_bytes.pop(uri, 0)
                if t_start is not None:
                    dt = now - t_start
                    self._durations.append(dt)
                    self._byte_sizes.append(nbytes)
                    self._last_duration = dt
                    self._last_bytes = nbytes
            self._maybe_print(force=(event == "done" and self._done == self._started))

    def _maybe_print(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_print < self._interval:
            return
        self._last_print = now
        in_flight = self._started - self._done
        last = ""
        if self._last_duration is not None:
            mb = (self._last_bytes or 0) / (1024.0 * 1024.0)
            last = f"; last fetch {self._last_duration:.2f}s, {mb:.1f} MB"
        print(
            f"[lightsheet] tiles: {self._done} loaded / {self._started} requested "
            f"(in flight: {in_flight}){last}",
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
        with self._lock:
            wall = time.monotonic() - self._session_start
            if not self._durations:
                # Zero fetches is a diagnostic all on its own -- with a
                # multiscale layer active this means napari is either
                # drawing only fill_value chunks (short-circuited before
                # any HTTPS) or its async slicer never scheduled a
                # slice. Whichever it is, silence would hide it.
                started = self._started
                in_flight = self._started - self._done
                print(
                    f"[lightsheet] fetch summary: 0 tiles fetched in {wall:.1f}s "
                    f"(started={started}, in_flight={in_flight}). "
                    "napari either drew only sparse/fill regions, or the async "
                    "slicer never dispatched -- try dragging the Z slider or "
                    "zooming in to force a slice compute.",
                    file=self._out,
                    flush=True,
                )
                return
            n = len(self._durations)
            total_bytes = sum(self._byte_sizes)
            mean_dt = sum(self._durations) / n
            max_dt = max(self._durations)
            min_dt = min(self._durations)
            mean_mb = (total_bytes / n) / (1024.0 * 1024.0)
            total_mb = total_bytes / (1024.0 * 1024.0)
            throughput = (total_bytes / wall) / (1024.0 * 1024.0) if wall > 0 else 0.0
            print(
                f"[lightsheet] fetch summary: {n} tiles, {total_mb:.1f} MB total, "
                f"{wall:.1f}s wall, mean {mean_dt:.2f}s/tile ({mean_mb:.1f} MB), "
                f"min {min_dt:.2f}s, max {max_dt:.2f}s, throughput {throughput:.1f} MB/s",
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

    # Install the loud fetch counter FIRST, before any stage. Every
    # cloud fetch that happens between here and napari.run()'s exit
    # then flows through the same observer. Nested watchFetches inside
    # progress.stage's cloudFetches temporarily override for byte
    # updates but the counter's outer scope resumes on stage exit,
    # so start/done counts still add up across stages.
    counter = _FetchCounter()
    fetch_watch = watchFetches(counter)
    fetch_watch.__enter__()

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

    if show:
        try:
            napari.run()
        finally:
            counter.stop()
            fetch_watch.__exit__(None, None, None)
            # Fetcher stats: cache-hit vs cloud-fetch split.
            # Complements the counter (which only sees cloud fetches
            # through watchFetches) with the local-cache hits it can't
            # see. Together they give the full picture of what happened
            # under this viewer session.
            print(f"[lightsheet] {fetcher.stats_summary()}", file=sys.stderr, flush=True)
            fetcher.close()
    else:
        # Not showing napari means the caller ran their own event loop
        # or is scripting the viewer; drop the observer so the caller
        # doesn't inherit our counter as ambient state.
        fetch_watch.__exit__(None, None, None)

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
