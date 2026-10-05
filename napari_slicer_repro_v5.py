"""napari slicer-wedge diagnostic -- v5.

v4 ran: lean pyramid + v2's threads, no bridge, no QApplication
pre-create. The slicer dispatched normally (~1,280+ block reads).

v5 = v4 + QApplication pre-created BEFORE napari.Viewer() exists.
Nothing else changes:
  * no QObject bridge
  * no Signal + QueuedConnection
  * no background emitter thread touching Qt
Just a bare QApplication, built from Python before napari ever
has a chance to build its own.

If v5 wedges, the pre-created QApplication is the trigger (napari's
Viewer() uses whatever QApplication is already around; a Python-
built one differs from the napari-built QNapariApplication class).
If v5 does NOT wedge, v6 keeps the pre-create and adds the Qt
bridge, since that is then the only thing left.

Usage:
    python napari_slicer_repro_v5.py
"""

import sys

print("[repro-v5] script started", flush=True)
print(f"[repro-v5] python = {sys.version.splitlines()[0]}", flush=True)
print(f"[repro-v5] argv = {sys.argv}", flush=True)

try:
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    print("[repro-v5] stdlib + numpy ok", flush=True)
    import dask
    import dask.array as da

    print(f"[repro-v5] dask = {dask.__version__}", flush=True)
    import napari

    print(f"[repro-v5] napari = {napari.__version__}", flush=True)
    import vispy

    print(f"[repro-v5] vispy = {vispy.__version__}", flush=True)
    import qtpy

    print(f"[repro-v5] qtpy = {qtpy.API_NAME}", flush=True)
except Exception as exc:
    print(f"[repro-v5] IMPORT FAILED: {type(exc).__name__}: {exc}", flush=True)
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
            f"[repro-v5] block read #{n}: level={level} indices=({zi},{yi},{xi}) shape={shape}",
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
    print("[repro-v5] building lazy dask pyramid ...", flush=True)
    t0 = time.monotonic()
    per_channel = []
    for _c in range(N_CHANNELS):
        levels_for_this_channel = []
        for lvl_idx, zyx in enumerate(LEVELS):
            levels_for_this_channel.append(_build_level(lvl_idx, zyx))
        per_channel.append(levels_for_this_channel)
    print(
        f"[repro-v5] built pyramid in {time.monotonic() - t0:.2f}s "
        f"(no chunk read fired during build)",
        flush=True,
    )
    return per_channel


_STOP = threading.Event()


def _heartbeat_loop():
    while not _STOP.wait(5.0):
        print("[repro-v5] (heartbeat tick)", flush=True)


def _warm_worker(i):
    time.sleep(0.05)
    return i


def start_background_threads():
    print("[repro-v5] starting daemon heartbeat thread ...", flush=True)
    hb = threading.Thread(
        target=_heartbeat_loop,
        name="repro-v5-heartbeat",
        daemon=True,
    )
    hb.start()
    print("[repro-v5] starting ThreadPoolExecutor (4 workers) ...", flush=True)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="repro-v5-pool")
    for i in range(8):
        pool.submit(_warm_worker, i)
    print("[repro-v5] background threads up.", flush=True)
    return hb, pool


def _attach_unstick_hotkey(viewer, layers):
    try:
        from qtpy.QtCore import QTimer
    except ImportError:
        return

    @viewer.bind_key("Shift-V", overwrite=True)
    def _unstick(_viewer):
        print("[repro-v5] applying unstick workaround ...", flush=True)
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
                f"[repro-v5] unstick: toggled {len(hidden)} layer(s).", flush=True
            )

        QTimer.singleShot(50, _finish)


def main():
    print(
        "[repro-v5] env: NAPARI_ASYNC=" + os.environ.get("NAPARI_ASYNC", "<unset>"),
        flush=True,
    )

    per_channel = build_pyramid()
    hb, pool = start_background_threads()

    # <<< v5 addition >>>: pre-create QApplication before napari.Viewer()
    # No bridge, no QObject, no Signal. Just the bare application
    # instance.
    from qtpy.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    print(
        f"[repro-v5] QApplication pre-created: {type(app).__module__}.{type(app).__name__}",
        flush=True,
    )

    print("[repro-v5] creating napari.Viewer() ...", flush=True)
    viewer = napari.Viewer()
    print("[repro-v5] Viewer created; adding images ...", flush=True)
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
        "[repro-v5] after add_image: "
        + ", ".join(
            f"{lyr.name}: loaded={lyr.loaded} multiscale={lyr.multiscale}" for lyr in layers
        ),
        flush=True,
    )
    print(
        "[repro-v5] zoom/pan now. 'block read' lines => slicer working. "
        "No 'block read' => slicer wedged. "
        "Press Shift+V in the viewer window to apply the workaround.",
        flush=True,
    )
    _attach_unstick_hotkey(viewer, layers)

    print("[repro-v5] entering napari.run() -- window should open now.", flush=True)
    try:
        napari.run()
    finally:
        _STOP.set()
        pool.shutdown(wait=False)

    print(f"[repro-v5] session end: total chunk reads = {_READ_COUNT['n']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"[repro-v5] UNCAUGHT: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(2)
