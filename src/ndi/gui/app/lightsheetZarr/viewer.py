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

import os
import sys
import threading
import time
from typing import Any


class _NapariStatusReporter:
    """Push a tile-loading status message into napari's status bar.

    Called from the fetch counter's main-thread-safe surfaces. Napari's
    status bar is a Qt widget, so a background thread calling
    ``viewer.status = ...`` would need main-thread dispatch; the
    counter's ``_maybe_print`` runs on whichever thread fired the
    fetch event. Rather than adding QThread machinery here, we keep
    a reference to the viewer and to the last string, and only
    push on the main thread via a QTimer.singleShot(0, ...).
    """

    def __init__(self, viewer):
        self._viewer = viewer

    def push(self, message: str) -> None:
        # QTimer.singleShot is thread-safe; the callback runs on the
        # Qt main thread, which is what viewer.status expects.
        try:
            from qtpy.QtCore import QTimer
        except ImportError:
            return
        v = self._viewer
        QTimer.singleShot(0, lambda: setattr(v, "status", message))


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
        status_reporter=None,
    ):
        self._lock = threading.Lock()
        self._out = out
        self._interval = interval
        self._idle_interval = idle_interval
        self._status_reporter = status_reporter
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

    def set_status_reporter(self, reporter) -> None:
        """Attach a reporter to update napari's status bar.

        Called from openPyramid after napari.Viewer() exists, since
        the reporter needs a viewer to write to. The counter itself
        is built earlier so it can observe fetches during layerSpec
        and add_image.
        """
        with self._lock:
            self._status_reporter = reporter

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
        stderr_line = (
            f"[lightsheet] tiles: {self._done} loaded / {self._started} requested "
            f"(in flight: {in_flight}){last}"
        )
        print(stderr_line, file=self._out, flush=True)
        if self._status_reporter is not None:
            status_msg = (
                f"lightsheet: {self._done}/{self._started} tiles"
                + (f" ({in_flight} in flight)" if in_flight else "")
                + (f" | last {self._last_duration:.2f}s" if self._last_duration else "")
            )
            self._status_reporter.push(status_msg)

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
    """Configure napari's slicing mode.

    Default is async (background slice compute, non-blocking paint),
    which is what we want on a cloud-backed multiscale layer -- a Ctrl+C
    on the sync path showed vispy's paintGL blocked in
    _project_thick_slice -> dask.compute for the whole coarsest level.

    Overridable via ``NDI_LIGHTSHEET_ASYNC``:
      "1" or unset -- async slicing on (default)
      "0"          -- async slicing off; napari falls back to synchronous
                       slicing on the main thread. Useful when the async
                       task manager is not dispatching (napari 0.5+
                       Python 3.13 has been seen to hang here). Our
                       contrast_limits pin prevents the "auto-sample
                       the coarsest level" trap that the sync path hit
                       originally, so sync is a reasonable second
                       choice: add_image blocks until the first slice
                       is on screen, then subsequent paints only
                       recompute on pan/zoom.

    Best-effort under try/except: on a napari version that has neither
    NAPARI_ASYNC nor an experimental.async_ setting, the caller gets
    whatever the default policy is.
    """
    import os

    async_on = os.environ.get("NDI_LIGHTSHEET_ASYNC", "1").strip() != "0"
    os.environ.setdefault("NAPARI_ASYNC", "1" if async_on else "0")
    try:
        settings = napari_module.settings.get_settings()
        experimental = getattr(settings, "experimental", None)
        if experimental is not None and hasattr(experimental, "async_"):
            experimental.async_ = async_on
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
        specs, fetcher = multiscale.layerSpec(
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

    # Now that a viewer exists, wire the counter to napari's status
    # bar so users see tile progress inside the viewer window rather
    # than having to watch the terminal.
    counter.set_status_reporter(_NapariStatusReporter(viewer))

    # Extract per-layer level lists BEFORE add_image; the "_ndi_"
    # prefix is our marker for kwargs napari does not understand.
    layer_levels: list[list[Any]] = []
    layer_scales: list[list[list[float] | None]] = []
    for spec in specs:
        layer_levels.append(spec.pop("_ndi_level_arrays", []))
        layer_scales.append(spec.pop("_ndi_level_scales", []))

    added_layers: list[Any] = []
    with progress.stage("attaching image to viewer"):
        for spec in specs:
            added_layers.append(viewer.add_image(**spec))

    # Debug: after add_image, print what napari actually has. A silent
    # session where the reader never fires could be a layer that failed
    # to register, a layer that is invisible, or a layer whose shape /
    # dtype napari refused to slice against. Under debug we make each
    # visible.
    if os.environ.get("NDI_LIGHTSHEET_DEBUG"):
        try:
            print(
                f"[lightsheet] viewer.layers has {len(viewer.layers)} layer(s) after add_image",
                file=sys.stderr,
                flush=True,
            )
            for i, layer in enumerate(viewer.layers):
                data_attr = getattr(layer, "data", None)
                multiscale_attr = getattr(layer, "multiscale", None)
                visible = getattr(layer, "visible", None)
                loaded_attr = getattr(layer, "loaded", None)
                data_type = type(data_attr).__name__
                # napari 0.5 wraps multiscale data in a MultiScaleData
                # (or similar) that isn't a python list; probe len()
                # and index [0] rather than isinstance-checking. Both
                # tuple and list satisfy this path too.
                n_levels = 0
                first_shape = "?"
                first_dtype = "?"
                try:
                    n_levels = len(data_attr)
                except (TypeError, AttributeError):
                    n_levels = 0
                if n_levels:
                    try:
                        first = data_attr[0]
                        first_shape = getattr(first, "shape", "?")
                        first_dtype = getattr(first, "dtype", "?")
                    except (TypeError, IndexError, KeyError):
                        pass
                else:
                    # Single-array data attribute.
                    n_levels = 1
                    first_shape = getattr(data_attr, "shape", "?")
                    first_dtype = getattr(data_attr, "dtype", "?")
                print(
                    f"[lightsheet]   layer {i}: name={layer.name!r} "
                    f"visible={visible} loaded={loaded_attr} "
                    f"multiscale={multiscale_attr} "
                    f"data_type={data_type} n_levels={n_levels} "
                    f"shape={first_shape} dtype={first_dtype}",
                    file=sys.stderr,
                    flush=True,
                )
            print(
                f"[lightsheet] viewer.dims: ndim={viewer.dims.ndim} "
                f"current_step={list(viewer.dims.current_step)}",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[lightsheet] layer inspect failed: {exc}", file=sys.stderr, flush=True)

    # Guarantee the initial frame is drawn at the coarsest level rather
    # than at whatever camera state napari happened to open with. On a
    # multiscale layer, reset_view fits the whole data extent to the
    # viewport, and napari's level picker then chooses the level whose
    # shape best fits the (much smaller) viewport -- the coarsest one,
    # for a lightsheet layer that is thousands of pixels on a side.
    # Without this the first paint can pick a finer level than the
    # viewport can display, needlessly fetching thousands of tiles for
    # a first frame the user will scroll away from immediately.
    try:
        viewer.reset_view()
    except Exception:
        pass  # older napari, best-effort

    # Earlier revisions of this file force-called layer.refresh() here
    # under debug as a probe: with async slicing the probe was needed
    # to confirm the slicer would ever reach our reader. But refresh()
    # on a sync-slicing napari (NDI_LIGHTSHEET_ASYNC=0) runs the whole
    # slice compute on the main thread and blocks Qt's event loop for
    # the duration -- macOS then marks the app "Not Responding" and
    # the window never comes up. The probe has served its purpose:
    # chunkPath tracing has confirmed napari's own paint reaches the
    # reader. No forced refresh here.

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
        picker, picker_labels = _attach_level_selector(
            viewer, added_layers, layer_levels, layer_scales
        )
        # Zoom-driven level swap uses the picker as its handle so the
        # dock widget always shows the level napari is drawing and
        # the manual and automatic paths share one code path.
        _attach_zoom_level_swap(viewer, picker, picker_labels, layer_scales)

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
    """Print a line to stderr each time napari picks a different level,
    and when a layer's slice-loading indicator changes.

    Multiscale layers fire an event when they promote or demote to a
    coarser/finer level; napari's exact event name has moved between
    versions, so this walks a small set of known names and attaches
    to the first that exists. On a viewer whose layers don't expose
    any of them, that half is a silent no-op.

    Also connects to ``layer.events.loaded`` when present: napari's
    per-layer channel-panel spinner is driven by that event, and users
    watching the spinner want a log line pinning the moment it stops.
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

        loaded_emitter = getattr(events, "loaded", None)
        if loaded_emitter is not None:
            loaded_emitter.connect(lambda e, lyr=layer: _report_loaded(lyr))


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


def _report_loaded(layer) -> None:
    """Fire when napari flips the layer's ``loaded`` flag.

    The channel-list panel spinner is driven by ``layer.loaded``:
    False means "napari is waiting for a slice", True means "the
    slice arrived". A stuck-on-False means napari never finished
    slicing. Printing both edges pins the moment the spinner starts
    and stops to a wall-clock timestamp in the log.
    """
    loaded = getattr(layer, "loaded", None)
    lname = getattr(layer, "name", "?")
    print(
        f"[lightsheet] layer {lname!r} loaded={loaded}",
        file=sys.stderr,
        flush=True,
    )


def _attach_level_selector(viewer, layers, per_layer_levels, per_layer_scales):
    """Dock a "Resolution" selector that swaps each layer's level.

    Swaps ``layer.data`` AND ``layer.scale`` together so world
    coordinates stay locked when the pixel dimensions change. No new
    fetches happen on swap -- the graphs are pre-built during
    layerSpec -- only napari-side re-slicing at the new pixel size.

    Returns ``(picker_widget, labels)`` so callers -- notably the
    auto-level watcher -- can drive the same picker programmatically
    and keep the visible choice, the layer data, and the layer scale
    in sync.

    Prints a wall-clock timeline to stderr:

      level selector: request level 2 at t=+41.3s
      level selector: layer 'mean Ch1' data swapped at t=+41.3s
      level selector: request completed in 0.05s

    Napari's own re-slice and paint happen after this returns; the
    "completed" line pins the moment WE were done handing napari the
    new data, not the moment the picture updates. Fetches that follow
    then show up in the fetch counter's own tile-by-tile lines, so
    the user can read the whole sequence back.

    Returns ``(None, [])`` when magicgui isn't installed or when
    nothing has levels to switch between.
    """
    if not layers or not per_layer_levels:
        return None, []
    max_levels = max((len(lst) for lst in per_layer_levels), default=0)
    if max_levels < 2:
        return None, []  # Nothing to switch between.

    try:
        from magicgui import magicgui
    except ImportError:  # pragma: no cover - optional at import
        print(
            "[lightsheet] magicgui not installed; level selector unavailable "
            "(pip install magicgui)",
            file=sys.stderr,
            flush=True,
        )
        return None, []

    labels = [f"level {i}" for i in range(max_levels)]
    default_label = labels[-1]  # coarsest
    session_start = time.monotonic()

    @magicgui(
        auto_call=True,
        level={"choices": labels, "label": "Resolution"},
    )
    def _picker(level: str = default_label):
        idx = labels.index(level)
        t0 = time.monotonic()
        elapsed_start = t0 - session_start
        print(
            f"[lightsheet] level selector: request {level} at t=+{elapsed_start:.1f}s",
            file=sys.stderr,
            flush=True,
        )
        for layer, arrays, scales in zip(layers, per_layer_levels, per_layer_scales):
            if not arrays or idx >= len(arrays):
                continue
            layer.data = arrays[idx]
            # scale MUST update alongside data or napari places the
            # new pixels at the previous level's world position, and
            # the picture jumps to a different spatial location.
            if scales and idx < len(scales) and scales[idx]:
                try:
                    layer.scale = scales[idx]
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[lightsheet]   scale swap on {layer.name!r} failed: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
            print(
                f"[lightsheet]   layer {layer.name!r} data/scale swapped "
                f"at t=+{time.monotonic() - session_start:.1f}s",
                file=sys.stderr,
                flush=True,
            )
        print(
            f"[lightsheet] level selector: request completed in "
            f"{time.monotonic() - t0:.2f}s (napari now re-slicing)",
            file=sys.stderr,
            flush=True,
        )

    try:
        viewer.window.add_dock_widget(_picker, area="right", name="Resolution")
    except Exception as exc:  # noqa: BLE001
        print(
            f"[lightsheet] could not dock level selector: {exc}",
            file=sys.stderr,
            flush=True,
        )
    return _picker, labels


def _attach_zoom_level_swap(viewer, picker, labels, per_layer_scales) -> None:
    """Auto-select a pyramid level based on the camera's current zoom.

    A level is worth spending bandwidth on only when its pixels are
    finer than the screen can display. Napari's camera exposes ``zoom``
    as screen pixels per world unit, so a screen pixel is
    ``1 / zoom`` world units wide -- and any level whose voxel size is
    MUCH smaller than that number is over-detailed: we would fetch
    tiles just to average them down to one screen pixel each.

    Picking rule: the coarsest level whose Y/X voxel size is smaller
    than the current world-per-screen-pixel (with a 1.5x oversample
    safety margin, so a slightly under-Nyquist level still qualifies).
    When the user zooms right in past level 0, level 0 is the finest
    thing we have and stays selected.

    Debounced 400ms so a smooth pinch or wheel-zoom does not thrash
    through every level on the way through. The visible "Resolution"
    picker is updated via ``picker.level.value = <label>`` -- magicgui
    then fires the picker's own callback, so the data/scale swap and
    the log line are exactly the same as a manual click. That is the
    point of routing through the picker rather than swapping directly:
    one code path for both, and the widget always shows the level
    napari is actually drawing.

    Silent no-op when ``NDI_LIGHTSHEET_AUTOLEVEL=0`` is set, when
    no picker exists, or when no level knows its voxel size.
    """
    if picker is None or not labels:
        return
    if os.environ.get("NDI_LIGHTSHEET_AUTOLEVEL", "1").strip().lower() in ("0", "false", "off"):
        print(
            "[lightsheet] auto-level: disabled via NDI_LIGHTSHEET_AUTOLEVEL",
            file=sys.stderr,
            flush=True,
        )
        return
    if not per_layer_scales:
        return

    # All layers cover the same volume, so any layer's per-level
    # scale list answers the "how big is a voxel at level i" question.
    # Pick the first non-empty one; skip missing entries within it.
    scales = None
    for candidate in per_layer_scales:
        if candidate:
            scales = candidate
            break
    if scales is None:
        return

    # Voxel size at each level, in world units per pixel on the tighter
    # of the two display axes (Y and X). Missing entries fall back to
    # +inf so they never win the "coarsest that still qualifies" search.
    level_yx_voxels: list[float] = []
    for s in scales:
        if s is None or len(s) < 2:
            level_yx_voxels.append(float("inf"))
            continue
        try:
            level_yx_voxels.append(min(float(s[-2]), float(s[-1])))
        except (TypeError, ValueError):
            level_yx_voxels.append(float("inf"))

    if not any(v != float("inf") for v in level_yx_voxels):
        print(
            "[lightsheet] auto-level: no per-level voxel sizes available; disabled",
            file=sys.stderr,
            flush=True,
        )
        return

    try:
        from qtpy.QtCore import QTimer
    except ImportError:  # pragma: no cover - Qt is required for napari
        return

    session_start = time.monotonic()
    # The picker was created with the coarsest level as its default.
    # Track that so we do not repeatedly set the same value and log
    # an auto-level line for a no-op.
    last_choice = {"idx": len(labels) - 1}

    def choose_level() -> None:
        try:
            zoom = float(viewer.camera.zoom)
        except Exception:  # noqa: BLE001 - camera could be gone during shutdown
            return
        if zoom <= 0:
            return
        world_per_pixel = 1.0 / zoom
        # Oversample factor: fetch one level finer than strict Nyquist
        # so the image on screen has a little headroom. 1.5 means a
        # level whose voxel is up to 1.5x the screen-pixel size still
        # qualifies as "the finest one worth fetching".
        threshold = world_per_pixel * 1.5

        # Walk coarsest -> finest looking for the first level whose
        # voxel size is smaller than the threshold. Levels are ordered
        # finest (index 0) to coarsest (index N-1), so we iterate
        # in reverse to find the coarsest that satisfies the rule.
        target_idx = 0
        for i in range(len(level_yx_voxels) - 1, -1, -1):
            if level_yx_voxels[i] <= threshold:
                target_idx = i
                break

        if target_idx == last_choice["idx"]:
            return
        last_choice["idx"] = target_idx
        elapsed = time.monotonic() - session_start
        print(
            f"[lightsheet] auto-level: zoom={zoom:.4f} px/world, "
            f"world/px={world_per_pixel:.3f}, pick level {target_idx} "
            f"(voxel {level_yx_voxels[target_idx]:.3f}) "
            f"at t=+{elapsed:.1f}s",
            file=sys.stderr,
            flush=True,
        )
        # Set the picker's value; magicgui's auto_call fires the
        # picker function, which does the actual data/scale swap
        # and prints its own log line.
        try:
            picker.level.value = labels[target_idx]
        except Exception as exc:  # noqa: BLE001
            print(
                f"[lightsheet] auto-level: could not set picker level: {exc}",
                file=sys.stderr,
                flush=True,
            )

    debouncer = QTimer()
    debouncer.setSingleShot(True)
    debouncer.setInterval(400)
    debouncer.timeout.connect(choose_level)

    def on_zoom_event(_event=None) -> None:
        # Restart the countdown on every zoom event; a settling
        # camera fires many events in rapid succession and only the
        # final resting zoom is worth acting on.
        try:
            debouncer.start()
        except Exception:  # noqa: BLE001 - Qt event loop may be shutting down
            pass

    try:
        viewer.camera.events.zoom.connect(on_zoom_event)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[lightsheet] auto-level: could not attach zoom listener: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return

    # Prime with an initial choice after napari has drawn its first
    # frame -- the camera's zoom is only meaningful once the viewer
    # has fitted its initial view to the layer extents.
    QTimer.singleShot(750, choose_level)


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
