"""napari slicer-wedge diagnostic -- v3.

v3 = v2 + a cross-thread Qt bridge (the thing _NapariStatusReporter
does in the production launcher), PLUS a smaller fake pyramid so
each movement doesn't take a minute of synthetic compute.

The bridge: a QObject that lives on the Qt main thread
(moveToThread(app.thread())) and exposes a Signal that a background
thread emits via Qt.ConnectionType.QueuedConnection. A background
thread then calls bridge.push("...") every second or so, which lands
on the main thread as a status-bar update. This is what the launcher
does to funnel the fetch-counter thread's "N/M tiles" line into
viewer.status without touching Qt from the wrong thread.

What changed vs v2:
  * fake pyramid shrunk 8x per axis -> every level's chunk count is
    O(100-1000) rather than O(1M). Each move now takes seconds, not
    minutes.
  * a daemon thread emits status updates through a cross-thread Qt
    signal every 1.0 s, starting before napari.Viewer() exists.
  * everything from v2 (heartbeat + ThreadPoolExecutor) still runs.

If v3 wedges and v2 did not, the cross-thread Qt bridge is the fix
target. If v3 does not wedge, v4 will add the next piece
(refresh-hint registration via viewer.camera.events).

Usage:
    python napari_slicer_repro_v3.py
    # Zoom in. "block read" lines in the terminal tell you whether
    # napari ever actually asks for a chunk. Press Shift+V to apply
    # the visibility-toggle workaround.
"""

import sys

print("[repro-v3] script started", flush=True)
print(f"[repro-v3] python = {sys.version.splitlines()[0]}", flush=True)
print(f"[repro-v3] argv = {sys.argv}", flush=True)

try:
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    print("[repro-v3] stdlib + numpy ok", flush=True)
    import dask
    import dask.array as da

    print(f"[repro-v3] dask = {dask.__version__}", flush=True)
    import napari

    print(f"[repro-v3] napari = {napari.__version__}", flush=True)
    import vispy

    print(f"[repro-v3] vispy = {vispy.__version__}", flush=True)
    import qtpy

    print(f"[repro-v3] qtpy = {qtpy.API_NAME}", flush=True)
except Exception as exc:
    print(f"[repro-v3] IMPORT FAILED: {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1)


# Pyramid shape: same ratios as production, 8x smaller per axis so
# each slice compute is seconds instead of minutes. The slicer-wedge
# bug does not depend on absolute size, only on multiscale + dask +
# per-chunk delayed reads.
LEVELS = [
    (481, 1094, 924),
    (241, 547, 462),
    (121, 274, 231),
    (61, 137, 116),
]
N_CHANNELS = 2
DTYPE = np.uint16
CHUNK_SHAPE = {
    0: (16, 128, 128),
    1: (16, 128, 128),
    2: (16, 128, 128),
    3: (16, 128, 128),
}


_READ_COUNT = {"n": 0}


def _read_block(level, zi, yi, xi, shape):
    _READ_COUNT["n"] += 1
    n = _READ_COUNT["n"]
    if n <= 50 or n % 20 == 0:
        print(
            f"[repro-v3] block read #{n}: level={level} indices=({zi},{yi},{xi}) shape={shape}",
            flush=True,
        )
    # Return cheap data: tiling a tiny array is much faster than
    # np.indices on a 2M-cell chunk and still fills the dtype-correct
    # buffer napari needs.
    val = ((level + 1) * 97 + zi * 13 + yi * 7 + xi * 3) % 4096
    return np.full(shape, val, dtype=DTYPE)


def _build_level(level, shape_zyx):
    cz, cy, cx = CHUNK_SHAPE[level]
    sz, sy, sx = shape_zyx
    nz = -(-sz // cz)
    ny = -(-sy // cy)
    nx = -(-sx // cx)
    blocks = np.empty((nz, ny, nx), dtype=object)
    for zi in range(nz):
        for yi in range(ny):
            for xi in range(nx):
                this_shape = (
                    min(cz, sz - zi * cz),
                    min(cy, sy - yi * cy),
                    min(cx, sx - xi * cx),
                )
                blk = dask.delayed(_read_block)(level, zi, yi, xi, this_shape)
                blocks[zi, yi, xi] = da.from_delayed(blk, shape=this_shape, dtype=DTYPE)
    return da.block(blocks.tolist())


def build_pyramid():
    print("[repro-v3] building lazy dask pyramid ...", flush=True)
    t0 = time.monotonic()
    per_channel = []
    for _c in range(N_CHANNELS):
        levels_for_this_channel = []
        for lvl_idx, zyx in enumerate(LEVELS):
            levels_for_this_channel.append(_build_level(lvl_idx, zyx))
        per_channel.append(levels_for_this_channel)
    print(
        f"[repro-v3] built pyramid in {time.monotonic() - t0:.2f}s "
        f"(no chunk read fired during build)",
        flush=True,
    )
    return per_channel


# --- v2 pieces: heartbeat + worker pool ---------------------------
_STOP = threading.Event()


def _heartbeat_loop():
    while not _STOP.wait(5.0):
        print("[repro-v3] (heartbeat tick)", flush=True)


def _warm_worker(i):
    time.sleep(0.05)
    return i


def start_background_threads():
    print("[repro-v3] starting daemon heartbeat thread ...", flush=True)
    hb = threading.Thread(
        target=_heartbeat_loop,
        name="repro-v3-heartbeat",
        daemon=True,
    )
    hb.start()
    print("[repro-v3] starting ThreadPoolExecutor (4 workers) ...", flush=True)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="repro-v3-pool")
    for i in range(8):
        pool.submit(_warm_worker, i)
    print("[repro-v3] background threads up.", flush=True)
    return hb, pool


# --- v3 addition: cross-thread Qt bridge --------------------------
# Same shape as _NapariStatusReporter._Bridge in the launcher:
#   * a QObject with a Signal
#   * moveToThread(app.thread()) so Qt knows it lives on main
#   * background thread calls bridge.emit via Qt.QueuedConnection
# This is the piece most likely to interact with vispy's own QThread
# machinery during slicer init.

_BRIDGE_HOLDER: dict = {}  # keep refs alive


def _build_cross_thread_bridge():
    """Build the bridge + its background emitter.

    Can't construct a QObject until QApplication exists, so this
    returns a 2-arg factory: (make_bridge, start_emitter).
    """
    from qtpy.QtCore import QObject, Qt, Signal
    from qtpy.QtWidgets import QApplication

    class _Bridge(QObject):
        status = Signal(str)

        def __init__(self):
            super().__init__()
            # Match the launcher: hop ourselves to the Qt main thread
            # so queued connections marshal correctly.
            app = QApplication.instance()
            if app is not None:
                try:
                    self.moveToThread(app.thread())
                except Exception:
                    pass

        def push(self, msg: str):
            # Emit on whichever thread called us; the slot is wired
            # via Qt.QueuedConnection so it will land on main.
            self.status.emit(msg)

    def make_bridge():
        bridge = _Bridge()

        def _on_status(msg):
            # Normally this would call viewer.status = msg, but we
            # keep it a pure print so this bridge works before Viewer
            # exists (that is the production ordering too).
            print(f"[repro-v3] (bridge->main) {msg}", flush=True)

        bridge.status.connect(_on_status, Qt.QueuedConnection)
        _BRIDGE_HOLDER["bridge"] = bridge
        return bridge

    def start_emitter(bridge):
        def _loop():
            n = 0
            while not _STOP.wait(1.0):
                n += 1
                bridge.push(f"heartbeat {n}")

        t = threading.Thread(target=_loop, name="repro-v3-bridge-emitter", daemon=True)
        t.start()
        _BRIDGE_HOLDER["emitter"] = t
        return t

    return make_bridge, start_emitter


def _attach_unstick_hotkey(viewer, layers):
    try:
        from qtpy.QtCore import QTimer
    except ImportError:
        return

    @viewer.bind_key("Shift-V", overwrite=True)
    def _unstick(_viewer):
        print("[repro-v3] applying unstick workaround ...", flush=True)
        hidden = []
        for layer in layers:
            try:
                if layer.visible:
                    layer.visible = False
                    hidden.append(layer)
            except Exception:
                pass

        def _finish():
            for layer in hidden:
                try:
                    layer.visible = True
                except Exception:
                    pass
            for layer in layers:
                try:
                    layer.refresh()
                except Exception:
                    pass
            print(
                f"[repro-v3] unstick: toggled {len(hidden)} layer(s).", flush=True
            )

        QTimer.singleShot(50, _finish)


def main():
    print(
        "[repro-v3] env: NAPARI_ASYNC=" + os.environ.get("NAPARI_ASYNC", "<unset>"),
        flush=True,
    )

    per_channel = build_pyramid()
    hb, pool = start_background_threads()

    # QApplication must exist before the bridge is built. napari's
    # Viewer() constructor creates one if none exists, but the launcher
    # builds the bridge BEFORE Viewer(), so we match that by poking
    # QApplication ourselves.
    from qtpy.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    print("[repro-v3] QApplication ready; building cross-thread bridge ...", flush=True)
    make_bridge, start_emitter = _build_cross_thread_bridge()
    bridge = make_bridge()
    start_emitter(bridge)

    print("[repro-v3] creating napari.Viewer() ...", flush=True)
    viewer = napari.Viewer()
    print("[repro-v3] Viewer created; adding images ...", flush=True)
    layers = []
    for c, levels in enumerate(per_channel):
        layer = viewer.add_image(
            levels,
            multiscale=True,
            name=f"Ch{c + 1}",
            colormap="green" if c == 0 else "magenta",
            blending="additive",
            contrast_limits=(0, 4096),
        )
        layers.append(layer)
    try:
        viewer.dims.set_point(0, LEVELS[0][0] // 2)
    except Exception:
        pass
    print(
        "[repro-v3] after add_image: "
        + ", ".join(
            f"{lyr.name}: loaded={lyr.loaded} multiscale={lyr.multiscale}" for lyr in layers
        ),
        flush=True,
    )
    print(
        "[repro-v3] zoom/pan now. 'block read' lines => slicer working. "
        "No 'block read' + vispy QBasicTimer spam => slicer wedged. "
        "Press Shift+V in the viewer window to apply the workaround.",
        flush=True,
    )
    _attach_unstick_hotkey(viewer, layers)

    print("[repro-v3] entering napari.run() -- window should open now.", flush=True)
    try:
        napari.run()
    finally:
        _STOP.set()
        pool.shutdown(wait=False)

    print(f"[repro-v3] session end: total chunk reads = {_READ_COUNT['n']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"[repro-v3] UNCAUGHT: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(2)
