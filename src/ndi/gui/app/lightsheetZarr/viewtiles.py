"""How many tiles does the current view need, and how many are here?

The fetch counter in :mod:`.viewer` sees fetches only as napari asks
for them, so it can say "12 in flight" but not "12 in flight, 83 to
go". The total IS knowable: napari draws one level per layer
(``layer.data_level``) over one region of it (``layer.corner_pixels``)
at one slice of the non-displayed axes (``viewer.dims.point``). The
level documents give the chunk grid and the list of stored chunks, so
the set of chunk files covering that region -- minus the sparse ones
that resolve to fill_value with no fetch -- is the set the view needs.
A chunk is "ready" once the fetcher has it on local disk.

Split in two so the arithmetic is testable without napari:

* :func:`chunksInBox` -- pure: per-axis inclusive data bounds in, the
  stored ``chunk.bin_#`` names covering them out.
* :func:`layerBox` / :func:`viewTally` -- read napari state and feed
  the pure half. Anything napari does not expose the way we expect
  returns None, and the viewer falls back to the in-flight count.

:func:`attachViewTally` polls on a main-thread QTimer (napari layer
state is not safe to read from the fetcher threads) and hands each
change to the fetch counter, which owns the status bar and overlay.
"""

from __future__ import annotations

from typing import Any

__all__ = ["chunksInBox", "layerBox", "viewChunks", "viewTally", "attachViewTally"]

#: A view whose box spans more chunk positions than this is not
#: tallied (it would stall the main thread on every tick). napari's 3D
#: mode draws the coarsest level, which stays far below it.
MAX_POSITIONS = 50_000

#: Poll interval for the main-thread timer, in milliseconds.
POLL_MS = 400

#: Why the last :func:`viewTally` returned None. A silent fallback to
#: the in-flight count looks exactly like a viewer without this
#: feature, so the poll logs this whenever it changes.
lastReason = ""


def _why(reason: str):
    """Record why the view cannot be tallied; return None."""
    global lastReason
    lastReason = reason
    return None


def chunksInBox(meta: dict, lo: list[int], hi: list[int]) -> list[str] | None:
    """Stored chunk names covering the inclusive data box [LO, HI].

    LO and HI have one entry per axis of the level's chunk grid. Bounds
    are clipped to the grid; a box past the edge just covers fewer
    chunks. Returns None when the box spans more than
    :data:`MAX_POSITIONS` chunk positions.
    """
    chunks = meta["chunks"]
    grid = meta["chunk_grid"]
    stored = meta.get("stored")
    n = len(grid)
    if len(lo) != n or len(hi) != n:
        return None

    ranges = []
    count = 1
    for a in range(n):
        first = max(0, int(lo[a]) // chunks[a])
        last = min(grid[a] - 1, int(hi[a]) // chunks[a])
        if last < first:
            return []
        ranges.append(range(first, last + 1))
        count *= last - first + 1
    if count > MAX_POSITIONS:
        return None

    strides = [1] * n
    for a in range(n - 2, -1, -1):
        strides[a] = strides[a + 1] * grid[a + 1]

    names: list[str] = []

    def walk(axis: int, linear: int) -> None:
        if axis == n:
            name = f"chunk.bin_{linear + 1:d}"
            if stored is None or name in stored:
                names.append(name)
            return
        for i in ranges[axis]:
            walk(axis + 1, linear + i * strides[axis])

    walk(0, 0)
    return names


def _gridAxisMap(meta: dict, layer_ndim: int) -> tuple[list[int], int] | None:
    """Map layer axes onto grid axes.

    Returns ``(layer_to_grid, c_axis)``: the grid axis for each layer
    axis, and the grid's channel axis (-1 when there is none). The
    layer arrays are the level arrays with the channel axis taken out,
    so a ``tczyx`` grid backs a ``tzyx`` layer. Layer axes line up
    with the TRAILING grid axes; any leading grid axis the layer does
    not carry (a singleton ``t``) is pinned to 0 by the caller.
    """
    n = len(meta["chunk_grid"])
    axes = meta.get("axes") or ("tczyx" if n == 5 else "")
    c = axes.index("c") if len(axes) == n and "c" in axes else -1
    if n == layer_ndim:
        # Nothing was stripped: the layer IS the grid.
        return list(range(n)), -1
    spatial = [a for a in range(n) if a != c]
    if len(spatial) < layer_ndim:
        return None
    return spatial[-layer_ndim:], c


def layerBox(layer, viewer, meta_levels: list[dict], channel: int = 0):
    """``(level_index, lo, hi)`` for what napari is drawing of LAYER.

    LO/HI are inclusive data bounds on the level's chunk grid. None
    when napari does not expose what we need.
    """
    # The level index only lines up with META_LEVELS on a native
    # multiscale layer over the full ladder (not single-level mode).
    if not getattr(layer, "multiscale", False):
        return _why(f"layer {getattr(layer, 'name', '?')!r} is not multiscale")
    try:
        if len(layer.data) != len(meta_levels):
            return _why(
                f"layer has {len(layer.data)} level(s) but the pyramid has "
                f"{len(meta_levels)} level document(s)"
            )
        level = int(layer.data_level)
        meta = meta_levels[level]
        corners = layer.corner_pixels
        ndim = int(layer.ndim)
        # Layer axes are the LAST ndim world axes.
        offset = int(viewer.dims.ndim) - ndim
        displayed = [int(d) - offset for d in viewer.dims.displayed]
        point = list(viewer.dims.point)[-ndim:]
        data_pt = list(layer.world_to_data(point))
        factors = layer.downsample_factors[level]
    except Exception as exc:  # noqa: BLE001 - any napari shape surprise -> unknown
        return _why(f"could not read napari layer state ({type(exc).__name__}: {exc})")

    mapping = _gridAxisMap(meta, ndim)
    if mapping is None:
        return _why(
            f"cannot map a {ndim}-D layer onto a {len(meta['chunk_grid'])}-D chunk "
            f"grid (axes_order={meta.get('axes')!r})"
        )
    layer_to_grid, c_axis = mapping

    n = len(meta["chunk_grid"])
    lo = [0] * n
    hi = [0] * n
    for j in range(ndim):
        g = layer_to_grid[j]
        if j in displayed:
            lo[g] = int(corners[0][j])
            hi[g] = int(corners[1][j])
        else:
            # world_to_data maps to level-0 data; scale down to LEVEL.
            idx = int(float(data_pt[j]) / float(factors[j]))
            lo[g] = hi[g] = idx
    if c_axis >= 0:
        lo[c_axis] = hi[c_axis] = int(channel)
    return level, lo, hi


def viewChunks(viewer, layers, meta_levels: list[dict]) -> dict | None:
    """Stored chunks the current view needs: ``{(doc_id, name): doc}``.

    Keyed the way :class:`ndi.pyramid.multiscale._ChunkFetcher` keys its
    cache, so the result can be handed to ``fetcher.setView``. Counts
    each chunk once even when two channel layers share it. Invisible
    layers draw nothing and are skipped. None when the view cannot be
    worked out (``lastReason`` says why).
    """
    if not meta_levels:
        return _why("no level chunk metadata from the loader")
    wanted: dict[tuple, Any] = {}
    for c, layer in enumerate(layers):
        if not getattr(layer, "visible", True):
            continue
        box = layerBox(layer, viewer, meta_levels, channel=c)
        if box is None:
            return None
        level, lo, hi = box
        names = chunksInBox(meta_levels[level], lo, hi)
        if names is None:
            return _why(f"view spans more than {MAX_POSITIONS:,} chunk positions")
        doc = meta_levels[level]["doc"]
        doc_id = getattr(doc, "id", str(doc))
        for name in names:
            wanted[(doc_id, name)] = doc
    return wanted


def _countReady(wanted: dict, fetcher) -> int:
    ready = 0
    for (_doc_id, name), doc in wanted.items():
        try:
            if fetcher.chunkPathIfCached(doc, name) is not None:
                ready += 1
        except Exception:  # noqa: BLE001 - unreachable scope: not ready
            pass
    return ready


def viewTally(viewer, layers, meta_levels: list[dict], fetcher) -> tuple[int, int] | None:
    """``(ready, needed)`` stored chunks for the current view, or None."""
    wanted = viewChunks(viewer, layers, meta_levels)
    if wanted is None:
        return None
    return _countReady(wanted, fetcher), len(wanted)


def attachViewTally(viewer, layers, meta_levels: list[dict], fetcher, counter):
    """Poll :func:`viewTally` on a main-thread timer; report to COUNTER.

    COUNTER gets ``set_view_tally(ready, needed)`` on every change and
    ``set_view_tally(None, None)`` when the view cannot be tallied.
    Returns the QTimer (kept alive by its parent window), or None when
    Qt or the window is not available.
    """
    import sys

    def log(msg: str) -> None:
        print(f"[lightsheet] view tile tally: {msg}", file=sys.stderr, flush=True)

    try:
        from qtpy.QtCore import QTimer
    except Exception as exc:  # noqa: BLE001
        log(f"off -- no Qt timer ({exc})")
        return None

    parent = None
    try:
        window = viewer.window
        parent = getattr(window, "_qt_window", None)
    except Exception:  # noqa: BLE001
        pass

    last = {"value": object(), "reason": "", "keys": object()}

    # The coarsest level is never released as stale: napari's
    # auto-contrast samples it whatever the view is.
    coarsest = meta_levels[-1]["doc"] if meta_levels else None
    never_stale = [getattr(coarsest, "id", str(coarsest))] if coarsest is not None else []
    set_view = getattr(fetcher, "setView", None)

    def tick() -> None:
        try:
            wanted = viewChunks(viewer, layers, meta_levels)
            value = None if wanted is None else (_countReady(wanted, fetcher), len(wanted))
        except Exception as exc:  # noqa: BLE001 - never take the viewer down
            wanted = None
            value = _why(f"tally raised {type(exc).__name__}: {exc}")
        # Hand the view to the fetcher only when it CHANGES: the change
        # time is what decides whether a waiting read is stale.
        keys = None if wanted is None else frozenset(wanted)
        if set_view is not None and keys != last["keys"]:
            last["keys"] = keys
            try:
                set_view(wanted, never_stale_doc_ids=never_stale)
            except Exception as exc:  # noqa: BLE001
                log(f"could not prioritise the view ({exc})")
        if value is None and lastReason != last["reason"]:
            last["reason"] = lastReason
            log(f"cannot count this view -- {lastReason}")
        if value is not None:
            last["reason"] = ""
        if value == last["value"]:
            return
        last["value"] = value
        if value is None:
            counter.set_view_tally(None, None)
        else:
            counter.set_view_tally(*value)

    timer = QTimer(parent)
    timer.setInterval(POLL_MS)
    timer.timeout.connect(tick)
    timer.start()
    log(f"on ({len(meta_levels)} level(s), polling every {POLL_MS} ms)")
    return timer
