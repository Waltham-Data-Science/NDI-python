"""napari slicer-wedge diagnostic -- v6.

Bisect so far:
  v1 baseline            -> works (1,600+ block reads)
  v2 +threads            -> works (1,500+ block reads before force-quit)
  v3 +shrink +app +bridge-> WEDGES (zero block reads)
  v4  shrink only        -> works (shape is innocent)
  v5  shrink + app       -> works (QApplication pre-create is innocent)

Only piece left: the cross-thread Qt bridge. v6 = v5 + the bridge:
  * QObject with a Signal
  * moveToThread(app.thread())
  * Qt.QueuedConnection
  * background daemon thread that calls bridge.push(...) every second,
    starting BEFORE napari.Viewer() exists

If v6 wedges, the Qt bridge is confirmed as the trigger -- this
reproduces what the production launcher does with _NapariStatusReporter
and would be the fix target. If v6 somehow works, we have a Heisenbug
and need another dimension.

Usage:
    python napari_slicer_repro_v6.py
"""

import sys

print("[repro-v6] script started", flush=True)
print(f"[repro-v6] python = {sys.version.splitlines()[0]}", flush=True)
print(f"[repro-v6] argv = {sys.argv}", flush=True)

try:
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    print("[repro-v6] stdlib + numpy ok", flush=True)
    import dask
    import dask.array as da

    print(f"[repro-v6] dask = {dask.__version__}", flush=True)
    import napari

    print(f"[repro-v6] napari = {napari.__version__}", flush=True)
    import vispy

    print(f"[repro-v6] vispy = {vispy.__version__}", flush=True)
    import qtpy

    print(f"[repro-v6] qtpy = {qtpy.API_NAME}", flush=True)
except Exception as exc:
    print(f"[repro-v6] IMPORT FAILED: {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1)


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
            f"[repro-v6] block read #{n}: level={level} indices=({zi},{yi},{xi}) shape={shape}",
            flush=True,
        )
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
    print("[repro-v6] building lazy dask pyramid ...", flush=True)
    t0 = time.monotonic()
    per_channel = []
    for _c in range(N_CHANNELS):
        levels_for_this_channel = []
        for lvl_idx, zyx in enumerate(LEVELS):
            levels_for_this_channel.append(_build_level(lvl_idx, zyx))
        per_channel.append(levels_for_this_channel)
    print(
        f"[repro-v6] built pyramid in {time.monotonic() - t0:.2f}s "
        f"(no chunk read fired during build)",
        flush=True,
    )
    return per_channel


_STOP = threading.Event()


def _heartbeat_loop():
    while not _STOP.wait(5.0):
        print("[repro-v6] (heartbeat tick)", flush=True)


def _warm_worker(i):
    time.sleep(0.05)
    return i


def start_background_threads():
    print("[repro-v6] starting daemon heartbeat thread ...", flush=True)
    hb = threading.Thread(
        target=_heartbeat_loop,
        name="repro-v6-heartbeat",
        daemon=True,
    )
    hb.start()
    print("[repro-v6] starting ThreadPoolExecutor (4 workers) ...", flush=True)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="repro-v6-pool")
    for i in range(8):
        pool.submit(_warm_worker, i)
    print("[repro-v6] background threads up.", flush=True)
    return hb, pool


# <<< v6 addition >>>: cross-thread Qt bridge, same shape as the
# launcher's _NapariStatusReporter._Bridge.
_BRIDGE_HOLDER: dict = {}


def _build_cross_thread_bridge():
    from qtpy.QtCore import QObject, Qt, Signal
    from qtpy.QtWidgets import QApplication

    class _Bridge(QObject):
        status = Signal(str)

        def __init__(self):
            super().__init__()
            app = QApplication.instance()
            if app is not None:
                try:
                    self.moveToThread(app.thread())
                except Exception:
                    pass

        def push(self, msg: str):
            self.status.emit(msg)

    def make_bridge():
        bridge = _Bridge()

        def _on_status(msg):
            print(f"[repro-v6] (bridge->main) {msg}", flush=True)

        bridge.status.connect(_on_status, Qt.QueuedConnection)
        _BRIDGE_HOLDER["bridge"] = bridge
        return bridge

    def start_emitter(bridge):
        def _loop():
            n = 0
            while not _STOP.wait(1.0):
                n += 1
                bridge.push(f"heartbeat {n}")

        t = threading.Thread(target=_loop, name="repro-v6-bridge-emitter", daemon=True)
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
        print("[repro-v6] applying unstick workaround ...", flush=True)
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
                f"[repro-v6] unstick: toggled {len(hidden)} layer(s).", flush=True
            )

        QTimer.singleShot(50, _finish)


def main():
    print(
        "[repro-v6] env: NAPARI_ASYNC=" + os.environ.get("NAPARI_ASYNC", "<unset>"),
        flush=True,
    )

    per_channel = build_pyramid()
    hb, pool = start_background_threads()

    from qtpy.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    print(
        f"[repro-v6] QApplication pre-created: {type(app).__module__}.{type(app).__name__}",
        flush=True,
    )

    print("[repro-v6] building cross-thread bridge + emitter ...", flush=True)
    make_bridge, start_emitter = _build_cross_thread_bridge()
    bridge = make_bridge()
    start_emitter(bridge)

    print("[repro-v6] creating napari.Viewer() ...", flush=True)
    viewer = napari.Viewer()
    print("[repro-v6] Viewer created; adding images ...", flush=True)
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
        "[repro-v6] after add_image: "
        + ", ".join(
            f"{lyr.name}: loaded={lyr.loaded} multiscale={lyr.multiscale}" for lyr in layers
        ),
        flush=True,
    )
    print(
        "[repro-v6] zoom/pan now. 'block read' lines => slicer working. "
        "No 'block read' => slicer WEDGED (expected per bisect).",
        flush=True,
    )
    _attach_unstick_hotkey(viewer, layers)

    print("[repro-v6] entering napari.run() -- window should open now.", flush=True)
    try:
        napari.run()
    finally:
        _STOP.set()
        pool.shutdown(wait=False)

    print(f"[repro-v6] session end: total chunk reads = {_READ_COUNT['n']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"[repro-v6] UNCAUGHT: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(2)
