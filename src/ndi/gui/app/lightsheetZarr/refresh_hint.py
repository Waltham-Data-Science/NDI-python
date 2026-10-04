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
import threading


class RefreshHint:
    """Debounce ``layer.refresh()`` calls triggered by async fetches.

    An async fine-fetch fires this on completion. Many hundreds of
    chunks in flight would swamp napari's slicer with refresh events,
    so this collects them into one refresh per ``debounce_ms``
    window.
    """

    def __init__(self, viewer, layers, debounce_ms: int = 250):
        self._viewer = viewer
        self._layers = list(layers)
        self._debounce_ms = debounce_ms
        self._lock = threading.Lock()
        self._timer = None
        self._QTimer = None
        try:
            from qtpy.QtCore import QTimer

            self._QTimer = QTimer
        except ImportError:  # pragma: no cover - Qt required for napari
            return
        # The QTimer lives on the main thread; construct it lazily
        # on first use so we do not touch Qt at import time.

    def __call__(self, _path=None) -> None:
        """Called from the completion of an async fetch. Not on Qt thread."""
        if self._QTimer is None:
            return
        # QTimer.singleShot is safe from any thread; the callback
        # runs on the Qt main thread.
        try:
            self._QTimer.singleShot(self._debounce_ms, self._fire)
        except Exception:  # noqa: BLE001
            pass

    def _fire(self) -> None:
        # napari 0.5 has three different ways to force a re-slice
        # depending on whether the async slicer is on, and they do
        # not overlap in every version. Try them in order of least
        # invasive to most; whichever one napari actually reacts to
        # is what makes the swap from coarse to fine visible.
        # Under debug, print each attempt so we can see which one
        # napari finally responded to.
        from ndi.pyramid.upsample_fallback import _fallback_debug
        from ndi.pyramid.upsample_fallback import bump as _bump_stat

        _bump_stat("refresh_hints_fired")
        debug = _fallback_debug()
        for layer in self._layers:
            emitted = []
            try:
                # 1. Public API: refresh() -- best case, napari
                # re-slices from current view. Some versions only
                # redraw the cached slice, which is why we do more.
                layer.refresh()
                emitted.append("refresh")
            except Exception:  # noqa: BLE001
                pass
            try:
                # 2. Fire the set_data event by hand. napari's
                # async slicer listens to this; it is what
                # `layer.data = layer.data` would emit, without
                # re-assigning the array.
                events = getattr(layer, "events", None)
                if events is not None:
                    set_data = getattr(events, "set_data", None)
                    if set_data is not None:
                        set_data()
                        emitted.append("events.set_data")
            except Exception:  # noqa: BLE001
                pass
            try:
                # 3. Private force-reload -- present on napari
                # >= 0.4.18 to invalidate the slice cache and
                # trigger a fresh compute.
                reload = getattr(layer, "reload", None) or getattr(layer, "_reload_async", None)
                if callable(reload):
                    reload()
                    emitted.append("reload")
            except Exception:  # noqa: BLE001
                pass
            if debug and emitted:
                print(
                    f"[lightsheet] refresh-hint fired on {getattr(layer, 'name', '?')!r}: "
                    f"{', '.join(emitted)}",
                    file=sys.stderr,
                    flush=True,
                )


def refreshHintFor(viewer, layers, debounce_ms: int = 250) -> RefreshHint | None:
    """Factory: build a debounced refresh hint or None when Qt is missing.

    Returns None when the layers list is empty (nothing to refresh)
    or when qtpy cannot be imported (headless test, no display).
    """
    if not layers:
        return None
    hint = RefreshHint(viewer, layers, debounce_ms=debounce_ms)
    if hint._QTimer is None:
        return None
    return hint
