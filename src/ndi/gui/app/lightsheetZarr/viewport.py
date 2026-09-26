"""Viewport-scoped layer data: only feed napari the chunks it can show.

Napari's slicer is given each layer's full spatial extent and asks for
whatever tiles overlap the current Z slice, regardless of what the
canvas is actually showing. On a 4376x3695 slice at level 1 that is
tens of thousands of tiles for a view that displays a few hundred
pixels of the brain. The wait is over cloud bandwidth, not compute.

This module cuts that down by re-cropping each layer's ``data`` to
the world rectangle currently visible, on every pan / zoom / Z-slice
change (debounced). The manoeuvre is:

* Compute the world bbox from ``viewer.camera.center`` and ``.zoom``
  plus the canvas size in pixels (screen pixels / zoom = world width).
* Convert the world bbox to a data-index bbox using each layer's own
  ``scale`` and ``translate`` -- the two together map data index to
  world coordinate.
* Quantise the bbox to the underlying dask array's chunk grid, with
  a generous margin, so that panning within a chunk does not rebuild
  the graph and every pan lands on a chunk boundary rather than
  cutting one.
* Slice the layer's FULL-LEVEL dask array to that bbox and hand the
  cropped view to napari as ``layer.data``. Update ``layer.translate``
  by ``[y0 * scale_y, x0 * scale_x]`` so the world position of every
  drawn pixel is unchanged -- the crop is invisible on screen.

The full-level arrays (one per level per channel) come from the same
lists that :func:`ndi.gui.app.lightsheetZarr.viewer._attach_level_selector`
uses, so this module and the Resolution picker share one source of
truth. When the auto-level watcher swaps to a different level, this
module refreshes the crop against the new level.

Off by default -- opt in with ``NDI_LIGHTSHEET_VIEWPORT_CLIP=1``.
The Resolution picker's manual and auto-level paths still work when
this is enabled, but both routes go through ``ViewportClip.refresh``
so the layer's data always matches the current level AND the current
viewport.

Not a substitute for a real tile-level filter (that would let napari
keep the same array reference and just tell it "these chunks are
zero"); it is the least-invasive first cut that stops the fetch-storm
on a level-1 view. A tile-level filter would live at the
``_ChunkFetcher.chunkPath`` boundary once the chunk-index-to-bbox map
is available at the reader level. See
``multiscale._ChunkFetcher`` and the follow-up note in the bridge
YAML.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any


def _env_true(name: str) -> bool:
    """Env-var truth test used across the lightsheetZarr package."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "on", "yes")


def attach_viewport_clip(
    viewer,
    layers,
    per_layer_levels: list[list[Any]],
    per_layer_scales: list[list[list[float] | None]],
    picker=None,
    labels: list[str] | None = None,
) -> ViewportClip | None:
    """Wire viewport-scoped cropping onto the given layers.

    Returns the :class:`ViewportClip` handle so a caller can call
    ``.refresh()`` on it in response to a manual level change (the
    Resolution picker's own callback is wrapped from here, so a
    manual click DOES already refresh -- the returned handle is
    mainly for tests and for future hooks).

    Silent no-op and returns None when ``NDI_LIGHTSHEET_VIEWPORT_CLIP``
    is not set, when the viewer doesn't expose the pieces we need,
    or when nothing has levels to crop.
    """
    if not _env_true("NDI_LIGHTSHEET_VIEWPORT_CLIP"):
        return None
    if not layers or not per_layer_levels:
        return None

    try:
        clip = ViewportClip(viewer, layers, per_layer_levels, per_layer_scales, picker, labels)
    except _ViewportUnsupported as exc:
        print(
            f"[lightsheet] viewport clip: unavailable ({exc}); "
            f"falling back to full-slice fetches",
            file=sys.stderr,
            flush=True,
        )
        return None

    clip.start()
    print(
        "[lightsheet] viewport clip: on (NDI_LIGHTSHEET_VIEWPORT_CLIP=1)",
        file=sys.stderr,
        flush=True,
    )
    return clip


class _ViewportUnsupported(RuntimeError):
    """Raised when the current viewer / napari version lacks the pieces
    ``ViewportClip`` needs. Reported once as a note, not a traceback."""


class ViewportClip:
    """Keep every layer's ``data`` cropped to the visible world rectangle.

    Owns:

    * The full-resolution arrays for every level of every layer -- the
      lists the level selector picks from. Cropping never destroys
      these; a new crop is a fresh slice.
    * The per-layer current level index, updated when the Resolution
      picker changes.
    * The Qt debouncer that coalesces rapid camera events into one
      refresh at rest.

    The public surface is one method, :meth:`refresh`, which reads the
    current camera and level and mutates ``layer.data`` and
    ``layer.translate`` accordingly.
    """

    #: Debounce (ms) for camera events. Long enough that a pinch-zoom
    #: settling through many small updates rebuilds the graph once,
    #: short enough that a click-to-pan feels responsive.
    DEBOUNCE_MS: int = 300

    #: Extra chunks kept outside the visible rectangle so a small pan
    #: does not immediately re-crop. Grows the fetch a little in each
    #: direction; small numbers pay off in less thrash.
    CHUNK_MARGIN: int = 1

    def __init__(
        self,
        viewer,
        layers,
        per_layer_levels,
        per_layer_scales,
        picker=None,
        labels=None,
    ):
        self._viewer = viewer
        self._layers = list(layers)
        self._per_layer_levels = per_layer_levels
        self._per_layer_scales = per_layer_scales
        self._picker = picker
        self._labels = list(labels) if labels else None
        self._lock = threading.Lock()

        # Everything from here down probes napari's / Qt's API in ways
        # that can differ across versions; funnel every "napari does
        # not expose this" into one exception the caller reports once.
        try:
            from qtpy.QtCore import QTimer
        except ImportError as exc:  # pragma: no cover - Qt is required
            raise _ViewportUnsupported(f"qtpy not importable ({exc})") from exc
        if not hasattr(viewer, "camera"):
            raise _ViewportUnsupported("viewer has no .camera")
        if not hasattr(viewer.camera, "events"):
            raise _ViewportUnsupported("viewer.camera has no .events")

        self._QTimer = QTimer

        # Per-layer current level index. Start at whatever level the
        # layer currently holds -- the picker's default is coarsest,
        # and add_image was called with the coarsest layer.data, so
        # index N-1 is the safe starting assumption when we cannot
        # find a matching level below.
        self._current_level: list[int] = []
        for layer, levels in zip(self._layers, self._per_layer_levels):
            idx = len(levels) - 1  # default: coarsest
            current_data = getattr(layer, "data", None)
            for i, arr in enumerate(levels):
                if arr is current_data:
                    idx = i
                    break
            self._current_level.append(idx)

        # Remember original layer.translate for each layer as world
        # anchor: layer.translate = original_translate + crop_offset.
        # When we swap crops, we recompute translate against this
        # anchor rather than accumulating drift on each refresh.
        self._base_translate: list[list[float]] = []
        for layer in self._layers:
            t = getattr(layer, "translate", None)
            try:
                self._base_translate.append([float(v) for v in list(t)] if t is not None else [])
            except (TypeError, ValueError):
                self._base_translate.append([])

        # Last-applied crop, per layer, so a redundant refresh (same
        # bbox at the same level) is a no-op. Prevents re-triggering
        # napari re-slice for a pan of one screen pixel.
        self._last_crop: list[tuple[int, int, int, int, int] | None] = [None] * len(self._layers)

        self._debouncer = self._QTimer()
        self._debouncer.setSingleShot(True)
        self._debouncer.setInterval(self.DEBOUNCE_MS)
        self._debouncer.timeout.connect(self.refresh)

        self._session_start = time.monotonic()

    # ------------------------------------------------------------------ start

    def start(self) -> None:
        """Connect camera / dims / picker listeners and do a first crop.

        Missing an emitter is not fatal; we connect to what exists and
        report which pieces were unavailable. A viewer that grows the
        rest later still gets partial coverage without a re-attach.
        """
        camera = self._viewer.camera
        connected = []

        for name in ("zoom", "center", "angles"):
            emitter = getattr(camera.events, name, None)
            if emitter is None:
                continue
            emitter.connect(self._on_camera_event)
            connected.append(f"camera.{name}")

        dims = getattr(self._viewer, "dims", None)
        if dims is not None and hasattr(dims, "events"):
            step = getattr(dims.events, "current_step", None)
            if step is not None:
                step.connect(self._on_dims_event)
                connected.append("dims.current_step")

        # Wrap the picker's called_function so an auto-level or manual
        # click ends by refreshing the crop against the new level.
        # magicgui's called_function returns the picker's actual
        # callable; wrapping it means we do not fight the picker for
        # who owns layer.data.
        if self._picker is not None and self._labels is not None:
            self._wrap_picker()

        # First crop as soon as napari has fitted its initial view --
        # the camera's zoom is only meaningful once the viewer has
        # sized itself to the layer extents.
        self._QTimer.singleShot(500, self.refresh)

        print(
            f"[lightsheet] viewport clip: listening on {', '.join(connected) or '(nothing)'}",
            file=sys.stderr,
            flush=True,
        )

    def _wrap_picker(self) -> None:
        """Hook the picker so a level change also refreshes the crop."""
        picker = self._picker
        labels = self._labels
        try:
            called = picker.called  # magicgui emits `called` after the callback
        except AttributeError:
            return

        def _after_picker(_result=None) -> None:
            # magicgui's `.called` emit gives us the return value; we
            # only need to know a swap happened. Re-read the picker's
            # current label to get the new level index and update our
            # per-layer tracking, then refresh.
            try:
                label = picker.level.value
                idx = labels.index(label)
            except Exception:  # noqa: BLE001
                return
            with self._lock:
                for i in range(len(self._current_level)):
                    self._current_level[i] = idx
            # Refresh directly (no debounce): the user explicitly
            # asked for this level and expects an immediate re-crop.
            self.refresh()

        try:
            called.connect(_after_picker)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[lightsheet] viewport clip: could not hook picker: {exc}",
                file=sys.stderr,
                flush=True,
            )

    # ------------------------------------------------------------------ events

    def _on_camera_event(self, _event=None) -> None:
        try:
            self._debouncer.start()
        except Exception:  # noqa: BLE001 - Qt loop may be shutting down
            pass

    def _on_dims_event(self, _event=None) -> None:
        # A Z slider move can be as consequential as a zoom (different
        # slab, different chunks) -- debounce it the same way.
        try:
            self._debouncer.start()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ crop

    def refresh(self) -> None:
        """Recompute and apply the viewport crop for every layer."""
        world_bbox = self._world_viewport()
        if world_bbox is None:
            return

        with self._lock:
            for layer_idx, layer in enumerate(self._layers):
                self._refresh_one(layer_idx, layer, world_bbox)

    def _world_viewport(self) -> tuple[float, float, float, float] | None:
        """Visible world bbox (y0, y1, x0, x1) or None if unknown.

        Reads napari's camera + canvas size. Uses the smallest known
        set of attributes for portability across napari versions.
        """
        camera = self._viewer.camera
        try:
            zoom = float(camera.zoom)
            center = list(camera.center)  # (z, y, x) or (y, x)
        except Exception:  # noqa: BLE001
            return None
        if zoom <= 0 or len(center) < 2:
            return None

        canvas_size = self._canvas_size()
        if canvas_size is None:
            return None
        canvas_w, canvas_h = canvas_size
        if canvas_w <= 0 or canvas_h <= 0:
            return None

        # camera.center is in world coordinates; last two are Y, X.
        y_center = float(center[-2])
        x_center = float(center[-1])
        world_h = canvas_h / zoom
        world_w = canvas_w / zoom
        return (
            y_center - world_h / 2,
            y_center + world_h / 2,
            x_center - world_w / 2,
            x_center + world_w / 2,
        )

    def _canvas_size(self) -> tuple[int, int] | None:
        """Canvas size in screen pixels (width, height), if we can find it.

        Napari 0.5's public path is
        ``viewer.window.qt_viewer.canvas.size``; older builds went
        through ``viewer.window._qt_viewer.canvas.size``. Both are
        probed, and either returning a QSize or a tuple is handled.
        """
        try:
            window = self._viewer.window
        except AttributeError:
            return None
        qt_viewer = getattr(window, "qt_viewer", None) or getattr(window, "_qt_viewer", None)
        if qt_viewer is None:
            return None
        canvas = getattr(qt_viewer, "canvas", None)
        if canvas is None:
            return None
        size = getattr(canvas, "size", None)
        if size is None:
            return None
        # QSize -> width(), height(); tuple/list -> [w, h]; callable
        # -> call and probe again.
        if callable(size):
            try:
                size = size()
            except Exception:  # noqa: BLE001
                return None
        w = getattr(size, "width", None)
        h = getattr(size, "height", None)
        if callable(w) and callable(h):
            try:
                return (int(w()), int(h()))
            except Exception:  # noqa: BLE001
                return None
        try:
            return (int(size[0]), int(size[1]))
        except (TypeError, IndexError, ValueError):
            return None

    def _refresh_one(self, layer_idx: int, layer, world_bbox) -> None:
        """Crop one layer to the world bbox at its current level."""
        levels = self._per_layer_levels[layer_idx]
        if not levels:
            return
        lvl_idx = self._current_level[layer_idx]
        if lvl_idx < 0 or lvl_idx >= len(levels):
            return
        full_array = levels[lvl_idx]
        if full_array is None:
            return

        scales = self._per_layer_scales[layer_idx] if self._per_layer_scales else None
        scale = (
            scales[lvl_idx]
            if scales and lvl_idx < len(scales) and scales[lvl_idx]
            else self._infer_scale(layer)
        )
        if scale is None or len(scale) < 2:
            return
        scale_y = float(scale[-2])
        scale_x = float(scale[-1])
        if scale_y <= 0 or scale_x <= 0:
            return

        base_translate = self._base_translate[layer_idx]
        trans_y = float(base_translate[-2]) if len(base_translate) >= 2 else 0.0
        trans_x = float(base_translate[-1]) if len(base_translate) >= 1 else 0.0

        # Data shape at this level (channel axis is already stripped
        # in the arrays we hold, so shape is (Z, Y, X) or (Y, X)).
        shape = getattr(full_array, "shape", None)
        if not shape or len(shape) < 2:
            return
        shape_y = int(shape[-2])
        shape_x = int(shape[-1])

        y0_world, y1_world, x0_world, x1_world = world_bbox

        # world = data_index * scale + translate
        # data_index = (world - translate) / scale
        y0_data = int((y0_world - trans_y) / scale_y)
        y1_data = int((y1_world - trans_y) / scale_y) + 1
        x0_data = int((x0_world - trans_x) / scale_x)
        x1_data = int((x1_world - trans_x) / scale_x) + 1

        # Quantise to chunk boundaries. dask exposes ``chunks`` as a
        # tuple of tuples of sizes per axis. A tiny pan then does not
        # rebuild the graph, and each pan lands on a whole chunk.
        chunks = getattr(full_array, "chunks", None)
        if chunks and len(chunks) >= 2:
            y_bounds = _chunk_boundaries(chunks[-2])
            x_bounds = _chunk_boundaries(chunks[-1])
            y0_data = _snap_down(y_bounds, y0_data, self.CHUNK_MARGIN)
            y1_data = _snap_up(y_bounds, y1_data, self.CHUNK_MARGIN)
            x0_data = _snap_down(x_bounds, x0_data, self.CHUNK_MARGIN)
            x1_data = _snap_up(x_bounds, x1_data, self.CHUNK_MARGIN)

        # Clamp to shape.
        y0_data = max(0, min(shape_y, y0_data))
        y1_data = max(y0_data + 1, min(shape_y, y1_data))
        x0_data = max(0, min(shape_x, x0_data))
        x1_data = max(x0_data + 1, min(shape_x, x1_data))

        key = (lvl_idx, y0_data, y1_data, x0_data, x1_data)
        if self._last_crop[layer_idx] == key:
            return

        # Build the cropped view. We do NOT compute here -- indexing a
        # dask array returns a dask array whose graph is a subset of
        # the source's. Napari's slicer then only asks for the chunks
        # inside this subrange.
        try:
            if len(shape) == 3:
                cropped = full_array[:, y0_data:y1_data, x0_data:x1_data]
            else:
                cropped = full_array[y0_data:y1_data, x0_data:x1_data]
        except Exception as exc:  # noqa: BLE001
            print(
                f"[lightsheet] viewport clip: crop of {layer.name!r} failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return

        # Update layer.data and layer.translate together so world
        # coordinates stay locked. The new translate anchors the
        # cropped array's [0, 0] to (trans + y0*scale_y,
        # trans + x0*scale_x) in world coords, which is where its
        # first pixel used to sit before the crop.
        new_translate = list(base_translate)
        while len(new_translate) < len(shape):
            new_translate.insert(0, 0.0)
        new_translate[-2] = trans_y + y0_data * scale_y
        new_translate[-1] = trans_x + x0_data * scale_x

        elapsed = time.monotonic() - self._session_start
        print(
            f"[lightsheet] viewport clip: layer {layer.name!r} level {lvl_idx} "
            f"crop y=[{y0_data}:{y1_data}] x=[{x0_data}:{x1_data}] "
            f"at t=+{elapsed:.1f}s",
            file=sys.stderr,
            flush=True,
        )

        try:
            layer.data = cropped
            layer.translate = new_translate
        except Exception as exc:  # noqa: BLE001
            print(
                f"[lightsheet] viewport clip: apply crop to {layer.name!r} " f"failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return
        self._last_crop[layer_idx] = key

    def _infer_scale(self, layer) -> list[float] | None:
        s = getattr(layer, "scale", None)
        if s is None:
            return None
        try:
            return [float(v) for v in list(s)]
        except (TypeError, ValueError):
            return None


def _chunk_boundaries(chunk_sizes) -> list[int]:
    """Cumulative offsets from a dask ``chunks`` axis tuple.

    ``(32, 32, 17)`` becomes ``[0, 32, 64, 81]`` -- the boundaries at
    which chunks start, ending one past the last chunk. Used to snap
    a requested pixel range outward to whole-chunk edges.
    """
    bounds = [0]
    for size in chunk_sizes:
        bounds.append(bounds[-1] + int(size))
    return bounds


def _snap_down(bounds: list[int], value: int, margin: int) -> int:
    """Snap ``value`` down to the boundary at least ``margin`` chunks
    before the last one that is <= value."""
    idx = 0
    for i, b in enumerate(bounds):
        if b <= value:
            idx = i
        else:
            break
    idx = max(0, idx - margin)
    return bounds[idx]


def _snap_up(bounds: list[int], value: int, margin: int) -> int:
    """Snap ``value`` up to the boundary at least ``margin`` chunks
    after the first one that is > value."""
    idx = len(bounds) - 1
    for i, b in enumerate(bounds):
        if b >= value:
            idx = i
            break
    idx = min(len(bounds) - 1, idx + margin)
    return bounds[idx]
