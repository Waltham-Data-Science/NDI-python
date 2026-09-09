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

    q = (
        ndi_query("")
        .isa("lightsheetZarrLevel")
        .depends_on("lightsheetZarrPyramid_id", pyramid_doc.id())
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


def levelTable(
    session: Any, pyramid_doc: Any, reduction: str | None = None
) -> list[dict]:
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
                "id": doc.id(),
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
    chunk (``# > n_chunks_stored``) resolves to the level's
    ``fill_value``.

    ``channel`` (1-based) narrows the returned arrays to a single
    channel along the pyramid's ``c`` axis; ``None`` returns every
    channel as its own axis.

    ``reduction`` filters the ladder to ``reduction_function`` in
    ``{'none', reduction}``; ``None`` returns every level.

    STATUS: scaffold. Enumerating levels and reading level metadata is
    wired up; the per-chunk read + dask assembly is the next step. See
    the package's README for the exact hook to complete.
    """
    docs = levelDocs(session, pyramid_doc, reduction=reduction)
    if not docs:
        raise ValueError(
            f"pyramid {pyramid_doc.id()!s} has no lightsheetZarrLevel children for "
            f"reduction={reduction!r}."
        )

    _ = channel  # signature is stable while the chunk fetcher lands
    _ = _fetch_chunk  # keep the private helper reachable for the follow-up

    raise NotImplementedError(
        "levelArrays: the per-chunk reader through "
        "session.database_openbinarydoc(level_doc, 'chunk.bin_#') is a "
        "scaffold in this PR. See src/ndi/gui/app/lightsheetZarr/README-"
        "lightsheet-zarr.md for the hook to complete."
    )


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


def _fetch_chunk(session: Any, level_doc: Any, one_based_index: int):
    """Read one chunk file through the NDI cloud cache and return raw bytes.

    Mirrors the genepyramid tile fetcher: open, read
    ``.fullpathfilename``, close. Called from a dask.delayed block; the
    caller is responsible for decoding those bytes per the level's
    ``codec``/``dtype``/``chunk_order`` and reshaping to the level's
    ``chunks`` shape.

    STATUS: scaffold. The signature is fixed so the follow-up PR that
    lands the dask block can drop it in without changing the call
    sites in :func:`levelArrays`.
    """
    filename = f"chunk.bin_{one_based_index:d}"
    _ = session, level_doc, filename
    raise NotImplementedError(
        "_fetch_chunk: read the file through "
        "session.database_openbinarydoc(level_doc, 'chunk.bin_#') and "
        "decode per the level's codec. See the package README."
    )
