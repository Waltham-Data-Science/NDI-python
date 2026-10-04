"""Napari-side helpers that let ``ndi.pyramid`` nudge the viewer.

The pyramid loader is deliberately napari-independent: it does not
know about ``qtpy``, ``QTimer`` or ``layer.refresh()``. When a
background fine-chunk fetch completes, the loader fires the
``on_complete`` callback that was handed in from the caller. On the
napari side, that callback is a :class:`RefreshHint` -- a debounced
prod that tells napari to re-slice so a fresh call to the reader
finds the freshly-cached fine data.

Kept in :mod:`ndi.gui.app.lightsheetZarr` (not in :mod:`ndi.pyramid`)
because the Qt dependency belongs on the viewer side. A
matplotlib-driven caller would build its own equivalent -- a
callback that redraws the current figure -- and the loader stays
uninvolved either way.
"""

from __future__ import annotations

import sys

# RefreshHint must be a QObject so it can own a Signal and live on
# the Qt main thread. The signal is marshalled from any worker
# thread's __call__ into the main thread with Qt.QueuedConnection,
# which is the ONLY way to get the slot to fire on the Qt event
# loop from a non-Qt thread; a bare QTimer.singleShot(ms, callable)
# posts to whichever thread called it, so from a background
# fetcher-pool worker it silently never fires (that is what the
# vispy "QBasicTimer::start: current thread's event dispatcher
# has already been destroyed" warnings describe).


def _tryImportQt():
    """Return (QObject, Qt, Signal, QTimer, QApplication) or None.

    Pulled out as a function so the ImportError path returns a
    uniform shape and :class:`RefreshHint` only has to check once.
    """
    try:
        from qtpy.QtCore import QObject, Qt, Signal
        from qtpy.QtCore import QTimer as _QTimer
        from qtpy.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - Qt required for napari
        return None
    return (QObject, Qt, Signal, _QTimer, QApplication)


_qt = _tryImportQt()


if _qt is not None:
    _QObject, _Qt, _Signal, _QTimer, _QApplication = _qt

    class _RefreshHintImpl(_QObject):
        """QObject that owns the main-thread signal.

        The ``_request`` signal is wired to ``_onRequest`` with
        ``Qt.QueuedConnection``. Emitting it from any thread posts
        a queued event to the main-thread event loop; Qt then
        invokes the slot on the main thread when the loop next
        runs. Equivalent to the ``_NapariStatusReporter._Bridge``
        in viewer.py.
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
            self._request.connect(self._onRequest, _Qt.QueuedConnection)

        def __call__(self, _path=None) -> None:
            """Called from the completion of an async fetch. Not on Qt thread."""
            from ndi.pyramid.upsample_fallback import bump as _bump_stat

            _bump_stat("refresh_hints_called")
            # emit() with a QueuedConnection target returns
            # immediately on the worker thread; the slot runs on
            # the main thread.
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
            # Running on the main thread now. Debounce via QTimer:
            # it was never the problem, we just needed to be on
            # the right thread first.
            try:
                _QTimer.singleShot(self._debounce_ms, self._fire)
            except Exception:  # noqa: BLE001
                self._fire()

        def _fire(self) -> None:
            from ndi.pyramid.upsample_fallback import _fallback_debug
            from ndi.pyramid.upsample_fallback import bump as _bump_stat

            _bump_stat("refresh_hints_fired")
            debug = _fallback_debug()
            for layer in self._layers:
                emitted = []
                try:
                    layer.refresh()
                    emitted.append("refresh")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    events = getattr(layer, "events", None)
                    if events is not None:
                        set_data = getattr(events, "set_data", None)
                        if set_data is not None:
                            set_data()
                            emitted.append("events.set_data")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    reload = getattr(layer, "reload", None) or getattr(layer, "_reload_async", None)
                    if callable(reload):
                        reload()
                        emitted.append("reload")
                except Exception:  # noqa: BLE001
                    pass
                if debug and emitted:
                    print(
                        f"[lightsheet] refresh-hint fired on "
                        f"{getattr(layer, 'name', '?')!r}: {', '.join(emitted)}",
                        file=sys.stderr,
                        flush=True,
                    )

    RefreshHint = _RefreshHintImpl

else:

    class RefreshHint:  # type: ignore[no-redef]
        """Headless no-op shim used in environments without Qt.

        Kept so callers can import :class:`RefreshHint` without
        wrapping every reference in a conditional; ``refreshHintFor``
        returns None in this case so the hint is never actually
        installed.
        """

        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, _path=None) -> None:
            return None


def refreshHintFor(viewer, layers, debounce_ms: int = 250):
    """Factory: build a debounced refresh hint or None when Qt is missing.

    Returns None when the layers list is empty (nothing to refresh)
    or when qtpy cannot be imported (headless test, no display).
    """
    if not layers:
        return None
    if _qt is None:
        return None
    return RefreshHint(viewer, layers, debounce_ms=debounce_ms)
