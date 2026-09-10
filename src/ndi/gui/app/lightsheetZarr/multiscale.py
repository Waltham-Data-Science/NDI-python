"""Dask multiscale over a lightsheetZarrPyramid stored as file_series.

The reader here is the load-bearing piece that the ``napariViewLightsheet``
console script and any programmatic viewer both drive. It:

* Enumerates ``lightsheetZarrLevel`` documents whose ``depends_on``
  ``lightsheetZarrPyramid_id`` matches the parent pyramid, optionally
  filtered to a single reduction.
* Presents each level as a lazy ``dask.array.Array`` backed by the
  level's ``chunk.bin_#`` file series.
* Composes them into a napari-consumable multiscale layer spec, with
  per-level ``scale`` and ``translate`` filled in from the level
  documents.

A reader that wants reduction ``R`` keeps levels with
``reduction_function in {'none', R}`` (the shared raw level 0 plus the
reduced tail), sorted by ``level`` ascending. Callers that want the
whole ladder pass ``reduction=None`` (the default) and get every level.

Chunk bytes go through the standard NDI cloud-cache path
``session.database_openbinarydoc(level_doc, "chunk.bin_#") ->
.fullpathfilename`` (same idiom as genepyramid.multiscale). That keeps
lightsheet reads on the same HIPAA-compliant cloud API that the rest of
the session uses; no separate zarr store or external URL is opened.

Napari itself is NOT imported here - the module returns plain dask
arrays and a dict for ``add_image(**spec)`` so a headless caller can
build the ladder without a display. ``napari`` and ``dask`` are
optional install extras (``pip install 'ndi[napari]'``).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# depends_on / doc discovery


def levelDocs(session: Any, pyramid_doc: Any, reduction: str | None = None) -> list[Any]:
    """Return the ``lightsheetZarrLevel`` documents of a pyramid, finest-first.

    Uses the standard NDI query surface: query for the class and filter
    by the ``lightsheetZarrPyramid_id`` dependency slot. When
    ``reduction`` is given, keeps only levels with ``reduction_function``
    in ``{'none', reduction}`` -- the shared raw level(s) plus the
    requested reduction. ``reduction=None`` returns every level.
    """
    from ndi.query import ndi_query

    q = ndi_query("").isa("lightsheetZarrLevel") & ndi_query("").depends_on(
        "lightsheetZarrPyramid_id", pyramid_doc.id
    )
    docs = list(session.database_search(q))
    if reduction is not None:
        keep = {"none", reduction}
        docs = [
            d
            for d in docs
            if d.document_properties["lightsheetZarrLevel"].get("reduction_function", "none")
            in keep
        ]
    docs.sort(key=lambda d: int(d.document_properties["lightsheetZarrLevel"]["level"]))
    return docs


def levelTable(session: Any, pyramid_doc: Any, reduction: str | None = None) -> list[dict]:
    """One row per level: level, reduction_function, shape, chunks, voxel_size, id.

    Metadata-only. Used by ``napariViewLightsheet --report`` and by
    ``chooseLevel``-style callers that must not read chunk bytes.
    When ``reduction`` is given, the returned rows are the ladder the
    named reduction would read.
    """
    rows: list[dict] = []
    for doc in levelDocs(session, pyramid_doc, reduction=reduction):
        p = doc.document_properties["lightsheetZarrLevel"]
        rows.append(
            {
                "level": int(p["level"]),
                "reduction_function": p.get("reduction_function", "none"),
                "shape": list(p["shape"]),
                "chunks": list(p["chunks"]),
                "voxel_size": list(p.get("voxel_size", [])),
                "translation": list(p.get("translation", [])),
                "dtype": p.get("dtype", ""),
                "id": doc.id,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# world transform


def worldTransform(session: Any, pyramid_doc: Any) -> tuple[list[float], list[float]]:
    """Return ``(scale_level0, translation_level0)`` for a napari layer.

    Follows napari's rule that ``scale``/``translate`` on a multiscale
    layer describe the FINEST level; coarser levels are then placed at
    ``scale * 2**level`` (or whatever the level document's own
    ``voxel_size`` says, when it does not agree with a power-of-two
    ladder).
    """
    _ = session  # signature parity with genepyramid; kept for a future world-frame lookup
    p = pyramid_doc.document_properties["lightsheetZarrPyramid"]
    scale = [float(v) for v in p.get("voxel_size_level0", [])]
    translation = [float(v) for v in p.get("translation_level0", [])]
    if not translation and scale:
        translation = [0.0] * len(scale)
    return scale, translation


# ---------------------------------------------------------------------------
# multiscale arrays


def levelArrays(
    session: Any,
    pyramid_doc: Any,
    channel: int | None = None,
    reduction: str | None = None,
) -> list[Any]:
    """One lazy dask array per level, in the same order napari expects.

    Each array reads its chunks from the level document's
    ``chunk.bin_#`` file series through the NDI cloud cache; a missing
    chunk resolves to the level's ``fill_value``.

    ``channel`` (1-based) narrows the returned arrays to a single
    channel along the pyramid's ``c`` axis; ``None`` returns every
    channel as its own axis.

    ``reduction`` filters the ladder to ``reduction_function`` in
    ``{'none', reduction}``; ``None`` returns every level.
    """
    import dask.array as da
    from dask import delayed

    docs = levelDocs(session, pyramid_doc, reduction=reduction)
    if not docs:
        raise ValueError(
            f"pyramid {pyramid_doc.id!s} has no lightsheetZarrLevel children for "
            f"reduction={reduction!r}."
        )

    _ = channel  # single-channel narrowing lands with the magicgui panels

    arrays: list[Any] = []
    for doc in docs:
        p = doc.document_properties["lightsheetZarrLevel"]
        shape = tuple(int(v) for v in p["shape"])
        chunks = tuple(int(v) for v in p["chunks"])
        chunk_grid = tuple(int(v) for v in p["chunk_grid"])
        dtype = _numpy_dtype(str(p.get("dtype", "uint16")))
        fill = int(p.get("fill_value", 0))
        codec = str(p.get("codec", "raw"))

        # Build a nested list of dask blocks in the shape of the chunk
        # grid so da.block concatenates them into one array.
        nested = _build_block_grid(
            session, doc, shape, chunks, chunk_grid, dtype, fill, codec, delayed, da
        )
        arrays.append(da.block(nested))

    return arrays


def _numpy_dtype(s: str):
    """Turn a Zarr / MATLAB dtype string into a numpy dtype."""
    import numpy as np

    s = s.strip().lower()
    if s and s[0] in "<>|=":
        endian = s[0]
        rest = s[1:]
    else:
        endian = "<"
        rest = s
    aliases = {
        "u1": "u1",
        "u2": "u2",
        "u4": "u4",
        "u8": "u8",
        "i1": "i1",
        "i2": "i2",
        "i4": "i4",
        "i8": "i8",
        "f2": "f2",
        "f4": "f4",
        "f8": "f8",
        "uint8": "u1",
        "uint16": "u2",
        "uint32": "u4",
        "uint64": "u8",
        "int8": "i1",
        "int16": "i2",
        "int32": "i4",
        "int64": "i8",
        "float16": "f2",
        "float32": "f4",
        "float64": "f8",
        "half": "f2",
        "single": "f4",
        "double": "f8",
    }
    code = aliases.get(rest, rest)
    return np.dtype(f"{endian}{code}")


def _linear_chunk_index(indices: tuple, chunk_grid: tuple) -> int:
    """C-order linear index from a per-axis 0-based tuple, returned 1-based."""
    linear = 0
    n = len(chunk_grid)
    for a, idx0 in enumerate(indices):
        stride = 1
        for b in range(a + 1, n):
            stride *= chunk_grid[b]
        linear += idx0 * stride
    return linear + 1


def _build_block_grid(session, doc, shape, chunks, chunk_grid, dtype, fill, codec, delayed, da):
    """Recursively build a nested list of dask blocks matching chunk_grid.

    All chunk paths are resolved EAGERLY on the main thread via
    ``_fetch_chunk`` before any dask ``delayed`` task is created. The
    delayed task itself only opens the resolved file and decodes bytes,
    which is thread-safe. Doing the SQLite lookup inside a delayed task
    is not: dask's default threaded scheduler runs those tasks on worker
    threads, and DID's SQLiteDB is a stdlib ``sqlite3.Connection`` that
    raises "SQLite objects created in a thread can only be used in that
    same thread". ``find_by_id`` swallows that error and returns None,
    which surfaced as a silent black napari canvas.

    Each block is a ``da.from_delayed(_read_chunk_from_path(...))`` at
    that chunk position, with the true edge-block shape so ``da.block``
    can concatenate.
    """

    def one_block(indices: tuple):
        idx_1 = _linear_chunk_index(indices, chunk_grid)
        # Edge blocks are smaller along one or more axes.
        block_shape = tuple(
            min(chunks[a], shape[a] - indices[a] * chunks[a]) for a in range(len(indices))
        )
        # Resolve the on-disk path here, on the main thread. `path` may
        # be None for a sparse chunk that was never materialised; the
        # reader falls back to fill_value in that case.
        path = _fetch_chunk(session, doc, idx_1)
        d = delayed(_read_chunk_from_path)(path, chunks, block_shape, dtype, fill, codec)
        return da.from_delayed(d, shape=block_shape, dtype=dtype)

    def recurse(prefix: list) -> list:
        axis = len(prefix)
        if axis == len(chunk_grid):
            return one_block(tuple(prefix))
        return [recurse(prefix + [i]) for i in range(chunk_grid[axis])]

    return recurse([])


def _read_chunk_from_path(path, chunks_full, block_shape, dtype, fill, codec):
    """Open a pre-resolved chunk file, decode bytes, trim to block_shape.

    This runs inside a dask delayed task and MUST NOT touch the NDI
    database or session. All it does is open a plain filesystem path,
    decompress the bytes if the level's codec says so, and reshape the
    result. A ``path`` of None (no such chunk on disk) resolves to
    ``fill_value``.

    Two codecs are supported today: ``raw`` (uncompressed C-order bytes)
    and ``blosc-zstd`` (Blosc v1 container wrapping byte-shuffled Zstd
    output). numcodecs.Blosc reads its parameters straight out of the
    container header, so ``codec_params`` is not consulted here.
    """
    import os

    import numpy as np

    n_expected = int(np.prod(chunks_full)) * dtype.itemsize
    if path is None or not os.path.isfile(path):
        return np.full(block_shape, fill, dtype=dtype)
    with open(path, "rb") as f:
        raw = f.read()

    if codec == "blosc-zstd":
        from numcodecs import Blosc

        raw = Blosc().decode(raw)

    if len(raw) < n_expected:
        raw = raw + b"\x00" * (n_expected - len(raw))
    arr = np.frombuffer(raw[:n_expected], dtype=dtype).reshape(chunks_full)
    # Edge blocks trim the padded chunk to the true shape.
    if block_shape != chunks_full:
        arr = arr[tuple(slice(0, s) for s in block_shape)]
    return arr


def layerSpec(
    session: Any,
    pyramid_doc: Any,
    channel: int | None = None,
    name: str | None = None,
    reduction: str | None = None,
) -> dict:
    """Return kwargs suitable for ``napari.Viewer.add_image(**spec)``.

    ``data`` is the list of dask arrays from :func:`levelArrays`;
    ``multiscale=True``; ``scale`` and ``translate`` come from
    :func:`worldTransform`; ``name`` defaults to the pyramid's own label.
    """
    arrays = levelArrays(session, pyramid_doc, channel=channel, reduction=reduction)
    scale, translate = worldTransform(session, pyramid_doc)
    if name is None:
        p = pyramid_doc.document_properties["lightsheetZarrPyramid"]
        name = p.get("label") or p.get("pyramid_name") or "lightsheet zarr"

    return {
        "data": arrays,
        "multiscale": True,
        "name": name,
        "scale": scale or None,
        "translate": translate or None,
    }


# ---------------------------------------------------------------------------
# private


def _fetch_chunk(session: Any, level_doc: Any, one_based_index: int) -> str | None:
    """Resolve one chunk file through the NDI cloud cache; return its path.

    Opens the level document's ``chunk.bin_<index>`` file series entry
    with ``session.database_openbinarydoc``, records the local cache
    path from ``.fullpathfilename``, closes the handle, and returns the
    path. The caller opens the file itself and reads raw bytes.

    Returns ``None`` when the file is not present (index out of range,
    or a sparse chunk that was never materialised). Callers use that
    to fall back to ``fill_value``.

    Set ``NDI_LIGHTSHEET_DEBUG=1`` in the environment to print the
    exception raised by ``database_openbinarydoc`` instead of silently
    resolving to ``fill_value``. Useful when a napari layer opens as a
    black canvas -- swallowing the exception is what makes that failure
    mode silent.
    """
    import os

    filename = f"chunk.bin_{one_based_index:d}"
    try:
        fh = session.database_openbinarydoc(level_doc, filename)
    except Exception as exc:
        if os.environ.get("NDI_LIGHTSHEET_DEBUG"):
            import sys

            print(
                f"[lightsheet] _fetch_chunk({filename}) failed: " f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        return None
    try:
        path = getattr(fh, "fullpathfilename", None)
        if path is None and os.environ.get("NDI_LIGHTSHEET_DEBUG"):
            import sys

            print(
                f"[lightsheet] _fetch_chunk({filename}): open returned a handle "
                f"without .fullpathfilename (type={type(fh).__name__})",
                file=sys.stderr,
            )
        return str(path) if path else None
    finally:
        try:
            session.database_closebinarydoc(fh)
        except Exception:
            pass
