"""napari slicer-wedge diagnostic -- v2 (adds background threads).

v2 = v1 + background work started BEFORE napari.Viewer():
  * one daemon threading.Thread that heartbeats on a wait()
    loop (mimics _FetchCounter._heartbeat in the production
    launcher).
  * a ThreadPoolExecutor with a handful of submitted jobs that
    run a trivial "pretend to warm a worker pool" (mimics
    fetcher.warm() and loader.startPrefetch()).

Everything is pure Python; no Qt, no I/O, no dask execution.
If just spawning threads before Viewer() construction wedges
the slicer on macOS + PyQt6, this file reproduces that; if it
doesn't, the next version adds more of the launcher's startup
and we move on.

Usage:
    python napari_slicer_repro_v2.py
    # Zoom in. "block read" lines in the terminal tell you
    # whether napari ever actually asks for a chunk. Press
    # Shift+V to apply the visibility-toggle workaround.
"""

import sys

print("[repro-v2] script started", flush=True)
print(f"[repro-v2] python = {sys.version.splitlines()[0]}", flush=True)
print(f"[repro-v2] argv = {sys.argv}", flush=True)

try:
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    print("[repro-v2] stdlib + numpy ok", flush=True)
    import dask
    import dask.array as da

    print(f"[repro-v2] dask = {dask.__version__}", flush=True)
    import napari

    print(f"[repro-v2] napari = {napari.__version__}", flush=True)
    import vispy

    print(f"[repro-v2] vispy = {vispy.__version__}", flush=True)
    import qtpy

    print(f"[repro-v2] qtpy = {qtpy.API_NAME}", flush=True)
except Exception as exc:
    print(f"[repro-v2] IMPORT FAILED: {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1)


LEVELS = [
    (3844, 8751, 7390),
    (1922, 4376, 3695),
    (961, 2188, 1848),
    (481, 1094, 924),
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
    print(
        f"[repro-v2] block read #{n}: level={level} indices=({zi},{yi},{xi}) shape={shape}",
        flush=True,
    )
    z, y, x = np.indices(shape)
    arr = ((z + zi * shape[0]) + (y + yi * shape[1]) + (x + xi * shape[2])) * (level + 1)
    return (arr % 4096).astype(DTYPE)


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
    print("[repro-v2] building lazy dask pyramid ...", flush=True)
    t0 = time.monotonic()
    per_channel = []
    for _c in range(N_CHANNELS):
        levels_for_this_channel = []
        for lvl_idx, zyx in enumerate(LEVELS):
            levels_for_this_channel.append(_build_level(lvl_idx, zyx))
        per_channel.append(levels_for_this_channel)
    print(
        f"[repro-v2] built pyramid in {time.monotonic() - t0:.2f}s "
        f"(no chunk read fired during build)",
        flush=True,
    )
    return per_channel


# --- the thing v2 adds on top of v1 -------------------------------
# A daemon heartbeat thread + a worker pool with a few submitted
# jobs, all started BEFORE napari.Viewer() exists. Same shape as
# the launcher's _FetchCounter._heartbeat + fetcher.warm() +
# loader.startPrefetch() sequence.

_STOP = threading.Event()


def _heartbeat_loop():
    """Wake every 5 s, print, loop. Just like the launcher's."""
    while not _STOP.wait(5.0):
        print("[repro-v2] (heartbeat tick)", flush=True)


def _warm_worker(i):
    """Pretend to warm a worker. Short CPU-free wait."""
    time.sleep(0.05)
    return i


def start_background_threads():
    print("[repro-v2] starting daemon heartbeat thread ...", flush=True)
    hb = threading.Thread(
        target=_heartbeat_loop,
        name="repro-v2-heartbeat",
        daemon=True,
    )
    hb.start()

    print("[repro-v2] starting ThreadPoolExecutor (4 workers) ...", flush=True)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="repro-v2-pool")
    # Submit a handful of trivial jobs. We don't wait for them; the
    # launcher doesn't either -- startPrefetch returns immediately.
    for i in range(8):
        pool.submit(_warm_worker, i)
    print("[repro-v2] background threads up (heartbeat + 4-worker pool).", flush=True)
    return hb, pool


def _attach_unstick_hotkey(viewer, layers):
    try:
        from qtpy.QtCore import QTimer
    except ImportError:
        return

    @viewer.bind_key("Shift-V", overwrite=True)
    def _unstick(_viewer):
        print("[repro-v2] applying unstick workaround ...", flush=True)
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
                f"[repro-v2] unstick: toggled {len(hidden)} layer(s). "
                "If the slicer was wedged, you should now see "
                "'block read' lines when you zoom.",
                flush=True,
            )

        QTimer.singleShot(50, _finish)


def main():
    print(
        "[repro-v2] env: NAPARI_ASYNC=" + os.environ.get("NAPARI_ASYNC", "<unset>"),
        flush=True,
    )

    per_channel = build_pyramid()

    # <<< v2 addition >>> background threads come up before Viewer().
    hb, pool = start_background_threads()

    print("[repro-v2] creating napari.Viewer() ...", flush=True)
    viewer = napari.Viewer()
    print("[repro-v2] Viewer created; adding images ...", flush=True)
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
        "[repro-v2] after add_image: "
        + ", ".join(
            f"{lyr.name}: loaded={lyr.loaded} multiscale={lyr.multiscale}" for lyr in layers
        ),
        flush=True,
    )
    print(
        "[repro-v2] zoom/pan now. 'block read' lines => slicer working. "
        "No 'block read' + vispy QBasicTimer spam => slicer wedged. "
        "Press Shift+V in the viewer window to apply the workaround.",
        flush=True,
    )
    _attach_unstick_hotkey(viewer, layers)

    print("[repro-v2] entering napari.run() -- window should open now.", flush=True)
    try:
        napari.run()
    finally:
        _STOP.set()
        pool.shutdown(wait=False)

    print(f"[repro-v2] session end: total chunk reads = {_READ_COUNT['n']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"[repro-v2] UNCAUGHT: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(2)
