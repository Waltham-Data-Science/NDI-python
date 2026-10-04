"""napari slicer-wedge diagnostic -- v4.

v3 wedged the slicer: zero block reads, just heartbeat chatter.
v4 isolates the SIZE of the pyramid as a possible trigger by
keeping v2's thread setup but using v3's shrunken LEVELS and
cheap np.full reader. Specifically:

  v4 = v2 (daemon heartbeat + ThreadPoolExecutor) + v3's smaller
       pyramid + v3's cheap chunk reader.
  v4 does NOT pre-create a QApplication.
  v4 does NOT build the cross-thread Qt bridge.

If v4 reproduces the wedge, the smaller pyramid shape itself is
the trigger (which would be weird but informative).
If v4 does NOT reproduce the wedge, v5 adds the QApplication
pre-create; if v5 is still fine, v6 adds the Qt bridge and that
one has to be the trigger.

Usage:
    python napari_slicer_repro_v4.py
"""

import sys

print("[repro-v4] script started", flush=True)
print(f"[repro-v4] python = {sys.version.splitlines()[0]}", flush=True)
print(f"[repro-v4] argv = {sys.argv}", flush=True)

try:
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    print("[repro-v4] stdlib + numpy ok", flush=True)
    import dask
    import dask.array as da

    print(f"[repro-v4] dask = {dask.__version__}", flush=True)
    import napari

    print(f"[repro-v4] napari = {napari.__version__}", flush=True)
    import vispy

    print(f"[repro-v4] vispy = {vispy.__version__}", flush=True)
    import qtpy

    print(f"[repro-v4] qtpy = {qtpy.API_NAME}", flush=True)
except Exception as exc:
    print(f"[repro-v4] IMPORT FAILED: {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1)


# Same shrunken shapes as v3.
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
            f"[repro-v4] block read #{n}: level={level} indices=({zi},{yi},{xi}) shape={shape}",
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
    print("[repro-v4] building lazy dask pyramid ...", flush=True)
    t0 = time.monotonic()
    per_channel = []
    for _c in range(N_CHANNELS):
        levels_for_this_channel = []
        for lvl_idx, zyx in enumerate(LEVELS):
            levels_for_this_channel.append(_build_level(lvl_idx, zyx))
        per_channel.append(levels_for_this_channel)
    print(
        f"[repro-v4] built pyramid in {time.monotonic() - t0:.2f}s "
        f"(no chunk read fired during build)",
        flush=True,
    )
    return per_channel


# v2's thread setup -- no bridge, no QApplication pre-create.
_STOP = threading.Event()


def _heartbeat_loop():
    while not _STOP.wait(5.0):
        print("[repro-v4] (heartbeat tick)", flush=True)


def _warm_worker(i):
    time.sleep(0.05)
    return i


def start_background_threads():
    print("[repro-v4] starting daemon heartbeat thread ...", flush=True)
    hb = threading.Thread(
        target=_heartbeat_loop,
        name="repro-v4-heartbeat",
        daemon=True,
    )
    hb.start()
    print("[repro-v4] starting ThreadPoolExecutor (4 workers) ...", flush=True)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="repro-v4-pool")
    for i in range(8):
        pool.submit(_warm_worker, i)
    print("[repro-v4] background threads up.", flush=True)
    return hb, pool


def _attach_unstick_hotkey(viewer, layers):
    try:
        from qtpy.QtCore import QTimer
    except ImportError:
        return

    @viewer.bind_key("Shift-V", overwrite=True)
    def _unstick(_viewer):
        print("[repro-v4] applying unstick workaround ...", flush=True)
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
                f"[repro-v4] unstick: toggled {len(hidden)} layer(s).", flush=True
            )

        QTimer.singleShot(50, _finish)


def main():
    print(
        "[repro-v4] env: NAPARI_ASYNC=" + os.environ.get("NAPARI_ASYNC", "<unset>"),
        flush=True,
    )

    per_channel = build_pyramid()
    hb, pool = start_background_threads()

    # NOTE: no QApplication pre-create. napari.Viewer() builds its
    # own.
    print("[repro-v4] creating napari.Viewer() ...", flush=True)
    viewer = napari.Viewer()
    print("[repro-v4] Viewer created; adding images ...", flush=True)
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
        "[repro-v4] after add_image: "
        + ", ".join(
            f"{lyr.name}: loaded={lyr.loaded} multiscale={lyr.multiscale}" for lyr in layers
        ),
        flush=True,
    )
    print(
        "[repro-v4] zoom/pan now. 'block read' lines => slicer working. "
        "No 'block read' => slicer wedged. "
        "Press Shift+V in the viewer window to apply the workaround.",
        flush=True,
    )
    _attach_unstick_hotkey(viewer, layers)

    print("[repro-v4] entering napari.run() -- window should open now.", flush=True)
    try:
        napari.run()
    finally:
        _STOP.set()
        pool.shutdown(wait=False)

    print(f"[repro-v4] session end: total chunk reads = {_READ_COUNT['n']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"[repro-v4] UNCAUGHT: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(2)
