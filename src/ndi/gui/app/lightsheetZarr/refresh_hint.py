"""Napari-side helpers that let ``ndi.pyramid`` nudge the viewer.

The pyramid loader is deliberately napari-independent: it does not
know about ``qtpy``, ``QTimer`` or ``layer.refresh()``. When a
background fine-chunk fetch completes, the loader fires the
``on_complete`` callback that was handed in from the caller. On the
napari side, that callback is a :class:`RefreshHint` -- a debounced
prod that tells napari to re-slice so a fresh call to the reader
finds the freshly-cached fine data.

Kept in :mod:`ndi.gui.app.lightsheetZarr` (not in :mod:`ndi.pyramid`)
because the Qt dependency belongs on the viewer side.
"""

from __future__ import annotations

import sys


def _tryImportQt():
    """Return the Qt classes we need or ``None`` headlessly."""
    try:
        from qtpy.QtCore import QEvent, QObject, QPoint, QPointF, Qt, Signal
        from qtpy.QtCore import QTimer as _QTimer
        from qtpy.QtGui import QWheelEvent
        from qtpy.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - Qt required for napari
        return None
    return {
        "QObject": QObject,
        "Qt": Qt,
        "Signal": Signal,
        "QTimer": _QTimer,
        "QApplication": QApplication,
        "QPoint": QPoint,
        "QPointF": QPointF,
        "QEvent": QEvent,
        "QWheelEvent": QWheelEvent,
    }


_qt = _tryImportQt()


if _qt is not None:
    _QObject = _qt["QObject"]
    _Qt = _qt["Qt"]
    _Signal = _qt["Signal"]
    _QTimer = _qt["QTimer"]
    _QApplication = _qt["QApplication"]
    _QPoint = _qt["QPoint"]
    _QPointF = _qt["QPointF"]
    _QWheelEvent = _qt["QWheelEvent"]

    class _RefreshHintImpl(_QObject):
        """QObject that marshals fetch completions into a main-thread refresh.

        The ``_request`` signal is wired to ``_onRequest`` with
        ``Qt.QueuedConnection``, so emitting it from any background
        thread posts a queued event to the main-thread event loop.
        ``_onRequest`` (re)starts a single debounce timer; when the
        burst of fetch completions quiets down for ``debounce_ms``,
        the timer fires ``_fire`` once.

        ``_fire`` has to do more than ``layer.refresh()``: observed
        on this user's napari 0.9.1 + PyQt6, calling ``refresh()`` or
        emitting ``events.set_data()`` -- or even reassigning
        ``viewer.camera.zoom`` from Python -- does NOT trigger the
        async slicer to re-run against the newly-cached fine chunks.
        Only an actual mouse wheel event over the canvas does. So we
        post a synthetic ``QWheelEvent`` to the vispy canvas widget,
        which is the one Qt path we have proof works on this build.
        """

        _request = _Signal()

        def __init__(self, viewer, layers, debounce_ms: int):
            super().__init__()
            self._viewer = viewer
            self._layers = list(layers)
            self._debounce_ms = debounce_ms
            app = _QApplication.instance()
            if app is not None:
                try:
                    self.moveToThread(app.thread())
                except Exception:  # noqa: BLE001
                    pass
            # One timer, reused: QTimer.start() restarts it, so
            # a burst of __call__s collapses into a single _fire.
            self._timer = None  # built lazily on main thread
            self._request.connect(self._onRequest, _Qt.QueuedConnection)

        # Entry point from any thread (fetch worker calls us).
        def __call__(self, _path=None) -> None:
            from ndi.pyramid.upsample_fallback import bump as _bump_stat

            _bump_stat("refresh_hints_called")
            try:
                self._request.emit()
                _bump_stat("refresh_hints_scheduled")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[lightsheet] refresh-hint emit failed: " f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

        def _onRequest(self) -> None:
            # On the Qt main thread now; safe to touch QTimer.
            if self._timer is None:
                self._timer = _QTimer(self)
                self._timer.setSingleShot(True)
                self._timer.timeout.connect(self._fire)
            # Restart the debounce window. If a hundred fetches
            # complete in 50 ms, this gets restarted a hundred
            # times and _fire runs exactly ONCE, ~250 ms after the
            # last one.
            self._timer.start(self._debounce_ms)

        def _fire(self) -> None:
            from ndi.pyramid.upsample_fallback import _fallback_debug
            from ndi.pyramid.upsample_fallback import bump as _bump_stat

            _bump_stat("refresh_hints_fired")
            debug = _fallback_debug()

            # 1. The in-API calls. Cheap, no-op on this user's
            # napari but harmless and the right thing to do on
            # napari builds where it works.
            for layer in self._layers:
                try:
                    layer.refresh()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    events = getattr(layer, "events", None)
                    if events is not None:
                        set_data = getattr(events, "set_data", None)
                        if set_data is not None:
                            set_data()
                except Exception:  # noqa: BLE001
                    pass

            # 2. The real nudge: post a synthetic QWheelEvent to
            # the vispy canvas. The user's log shows programmatic
            # camera.zoom writes don't re-slice but real mouse
            # wheels do, so we send what the kernel-level wheel
            # handler would post. Two notches cancel out so the
            # zoom level does not visibly change.
            posted = self._postCancellingWheelPair()

            if debug:
                print(
                    f"[lightsheet] refresh-hint fired: "
                    f"refresh()+set_data() on {len(self._layers)} layer(s), "
                    f"synth-wheel posted={'yes' if posted else 'no'}",
                    file=sys.stderr,
                    flush=True,
                )

        def _findCanvasWidget(self):
            """Return the Qt widget to post wheel events to, or None.

            napari's internal layout changes between versions; try a
            few known attribute paths and fall back to the viewer
            window's central widget.
            """
            viewer = self._viewer
            try:
                window = getattr(viewer, "window", None)
                qt_viewer = getattr(window, "_qt_viewer", None) or getattr(
                    window, "qt_viewer", None
                )
                if qt_viewer is None:
                    return None
                canvas = getattr(qt_viewer, "canvas", None)
                if canvas is None:
                    return None
                native = getattr(canvas, "native", None) or getattr(canvas, "_backend", None)
                if native is None:
                    return canvas  # may itself be a QWidget
                return native
            except Exception:  # noqa: BLE001
                return None

        def _postCancellingWheelPair(self) -> bool:
            """Post wheel-up then wheel-down to the canvas.

            Returns True if events were posted. The two notches
            cancel so the user does not see a zoom flicker, but
            napari's view machinery sees two real camera events
            and re-slices accordingly.
            """
            widget = self._findCanvasWidget()
            if widget is None:
                return False
            try:
                app = _QApplication.instance()
                w = widget.width() if hasattr(widget, "width") else 400
                h = widget.height() if hasattr(widget, "height") else 300
                pos_f = _QPointF(w / 2, h / 2)
                global_pos = widget.mapToGlobal(pos_f.toPoint())
                for dy in (120, -120):
                    ev = _QWheelEvent(
                        pos_f,
                        _QPointF(global_pos),
                        _QPoint(0, 0),
                        _QPoint(0, dy),
                        _Qt.NoButton,
                        _Qt.NoModifier,
                        _Qt.NoScrollPhase,
                        False,
                    )
                    app.postEvent(widget, ev)
                return True
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[lightsheet] synth-wheel post failed: " f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                return False

    RefreshHint = _RefreshHintImpl

else:

    class RefreshHint:  # type: ignore[no-redef]
        """Headless no-op shim for environments without Qt."""

        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, _path=None) -> None:
            return None


def refreshHintFor(viewer, layers, debounce_ms: int = 250):
    """Build a debounced refresh hint, or None when Qt is unavailable."""
    if not layers:
        return None
    if _qt is None:
        return None
    return RefreshHint(viewer, layers, debounce_ms=debounce_ms)
