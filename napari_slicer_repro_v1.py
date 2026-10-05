"""napari slicer-wedge diagnostic -- v1 (BASELINE: works).

Minimal reproducer skeleton for the slicer wedge seen in the
lightsheet viewer on macOS + napari 0.9.1 + PyQt6. This file is
the control: a lazy dask MultiScaleData pyramid, two channels,
same shape ratios as the production dataset. On the user's own
machine (vanhoosr, 2026-10-04) this version RUNS CORRECTLY --
~1,600 block reads, no vispy "QBasicTimer::start: current
thread's event dispatcher has already been destroyed" warnings,
zoom and pan work.

That means the wedge is caused by something our launcher does
on top of this baseline, NOT by napari/vispy on this shape of
data. Subsequent versions (_v2, _v3, ...) each add one more
piece of the production launcher's startup until the wedge
reproduces. The one that triggers it is the fix target.

Usage:
    python napari_slicer_repro_v1.py
    # Zoom in. "block read" lines in the terminal tell you
    # whether napari ever actually asks for a chunk. Press
    # Shift+V to apply the visibility-toggle workaround.
"""

# Diagnostic output BEFORE any heavy imports: if nothing below
# prints, Python isn't actually running this file at all.
import sys

print("[repro] script started", flush=True)
print(f"[repro] python = {sys.version.splitlines()[0]}", flush=True)
print(f"[repro] argv = {sys.argv}", flush=True)

# Guarded imports -- surface any missing dependency as a message,
# not a traceback that might scroll off.
try:
    import os
    import time

    import numpy as np

    print("[repro] stdlib + numpy ok", flush=True)
    import dask
    import dask.array as da

    print(f"[repro] dask = {dask.__version__}", flush=True)
    import napari

    print(f"[repro] napari = {napari.__version__}", flush=True)
    import vispy

    print(f"[repro] vispy = {vispy.__version__}", flush=True)
    import qtpy

    print(f"[repro] qtpy = {qtpy.API_NAME}", flush=True)
except Exception as exc:
    print(f"[repro] IMPORT FAILED: {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1)


# --- fake lightsheet pyramid --------------------------------------
# 4 levels, dyadic, matching the production dataset's shape ratios.
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
    """Fake chunk reader. Prints every time napari asks for a chunk.

    If this NEVER prints after the viewer window is up, the slicer
    is wedged -- which is the bug this script demonstrates.
    """
    _READ_COUNT["n"] += 1
    n = _READ_COUNT["n"]
    print(
        f"[repro] block read #{n}: level={level} indices=({zi},{yi},{xi}) shape={shape}",
        flush=True,
    )
    z, y, x = np.indices(shape)
    arr = ((z + zi * shape[0]) + (y + yi * shape[1]) + (x + xi * shape[2])) * (level + 1)
    return (arr % 4096).astype(DTYPE)


def _build_level(level, shape_zyx):
    """Build one level as a lazy dask.array of per-chunk delayed reads."""
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
    print("[repro] building lazy dask pyramid ...", flush=True)
    t0 = time.monotonic()
    per_channel = []
    for _c in range(N_CHANNELS):
        levels_for_this_channel = []
        for lvl_idx, zyx in enumerate(LEVELS):
            levels_for_this_channel.append(_build_level(lvl_idx, zyx))
        per_channel.append(levels_for_this_channel)
    print(
        f"[repro] built pyramid in {time.monotonic() - t0:.2f}s "
        f"(no chunk read fired during build)",
        flush=True,
    )
    return per_channel


def _attach_unstick_hotkey(viewer, layers):
    """Shift+V applies the visibility-toggle workaround."""
    try:
        from qtpy.QtCore import QTimer
    except ImportError:
        return

    @viewer.bind_key("Shift-V", overwrite=True)
    def _unstick(_viewer):
        print("[repro] applying unstick workaround ...", flush=True)
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
                f"[repro] unstick: toggled {len(hidden)} layer(s). "
                "If the slicer was wedged, you should now see "
                "'block read' lines when you zoom.",
                flush=True,
            )

        QTimer.singleShot(50, _finish)


def main():
    print(
        "[repro] env: NAPARI_ASYNC=" + os.environ.get("NAPARI_ASYNC", "<unset>"),
        flush=True,
    )

    per_channel = build_pyramid()

    print("[repro] creating napari.Viewer() ...", flush=True)
    viewer = napari.Viewer()
    print("[repro] Viewer created; adding images ...", flush=True)
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
        "[repro] after add_image: "
        + ", ".join(
            f"{lyr.name}: loaded={lyr.loaded} multiscale={lyr.multiscale}" for lyr in layers
        ),
        flush=True,
    )
    print(
        "[repro] zoom/pan now. 'block read' lines => slicer working. "
        "No 'block read' + vispy QBasicTimer spam => slicer wedged. "
        "Press Shift+V in the viewer window to apply the workaround.",
        flush=True,
    )
    _attach_unstick_hotkey(viewer, layers)

    print("[repro] entering napari.run() -- window should open now.", flush=True)
    napari.run()

    print(f"[repro] session end: total chunk reads = {_READ_COUNT['n']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"[repro] UNCAUGHT: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(2)
