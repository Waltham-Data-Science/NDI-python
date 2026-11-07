"""
ndi.fun.doc_lightsheet.levelTable

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/levelTable.m

A lightsheetZarrPyramid's lightsheetZarrLevel children, finest first, plus
the parent frame they share.
"""

from __future__ import annotations

from typing import Any

import pydantic

from ...document import ndi_document
from ...query import ndi_query

__all__ = ["levelTable", "COLUMNS"]

#: The MATLAB table's VariableNames, in order: the keys of every row.
COLUMNS = (
    "level",
    "reduction_function",
    "shape",
    "chunks",
    "chunk_grid",
    "n_chunks_stored",
    "voxel_size",
    "translation",
    "dtype",
    "id",
)


def _floats(v: Any) -> list[float]:
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    return [float(x) for x in v]


def _ints(v: Any) -> list[int]:
    return [int(x) for x in _floats(v)]


def _frame(parentDoc: Any, reductionsPresent: list[str]) -> dict[str, Any]:
    p = parentDoc.document_properties["lightsheetZarrPyramid"]
    return {
        "axes_order": str(p.get("axes_order", "")),
        "voxel_size_level0": _floats(p.get("voxel_size_level0")),
        "translation_level0": _floats(p.get("translation_level0")),
        "dtype": str(p.get("dtype", "")),
        "pyramid_name": str(p.get("pyramid_name", "")),
        "id": parentDoc.id,
        "reductions": list(reductionsPresent),
    }


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def levelTable(
    session: Any, pyramidDoc: Any, *, reduction: str = ""
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The pyramid's levels, finest first, and the parent frame.

    MATLAB equivalent: ``t = ndi.fun.doc.lightsheet.levelTable(session,
    pyramidDoc, 'reduction', reduction)``

    Queries *session* for every ``lightsheetZarrLevel`` whose
    ``lightsheetZarrPyramid_id`` dependency is the pyramid's id, sorted by
    ``level`` ascending. With *reduction*, only levels whose
    ``reduction_function`` is ``'none'`` or *reduction* are kept -- the
    shared raw level(s) plus the requested ladder.

    Args:
        session: an ndi session (or dataset) holding the documents.
        pyramidDoc: the lightsheetZarrPyramid document, or its id.
        reduction: ``''`` (every level) or a reduction name.

    Returns:
        ``(levels, frame)``. *levels* is a list of dicts, one per level,
        with the MATLAB table's columns as keys (:data:`COLUMNS`): level,
        reduction_function, shape, chunks, chunk_grid, n_chunks_stored,
        voxel_size, translation, dtype, id. *frame* is what MATLAB keeps in
        ``Properties.UserData``: axes_order, voxel_size_level0,
        translation_level0, dtype, pyramid_name, id (the parent's) and
        reductions (the non-'none' reduction_function values present in the
        full ladder, sorted).

    Raises:
        LookupError: if *pyramidDoc* is an id and no document has it
            (MATLAB: ``NDI:lightsheet:levelTable:noParent``).
    """
    if isinstance(pyramidDoc, ndi_document):
        parentDoc = pyramidDoc
        parentID = parentDoc.id
    else:
        parentID = str(pyramidDoc)
        found = session.database_search(ndi_query("base.id", "exact_string", parentID))
        if not found:
            raise LookupError(f"No lightsheetZarrPyramid with id {parentID} in session.")
        parentDoc = found[0]

    q = ndi_query("").isa("lightsheetZarrLevel") & ndi_query("").depends_on(
        "lightsheetZarrPyramid_id", parentID
    )
    docs = list(session.database_search(q))

    rows: list[dict[str, Any]] = []
    for doc in docs:
        p = doc.document_properties["lightsheetZarrLevel"]
        rows.append(
            {
                "level": int(p["level"]),
                "reduction_function": str(p.get("reduction_function", "none")),
                "shape": _ints(p.get("shape")),
                "chunks": _ints(p.get("chunks")),
                "chunk_grid": _ints(p.get("chunk_grid")),
                "n_chunks_stored": int(p.get("n_chunks_stored", 0)),
                "voxel_size": _floats(p.get("voxel_size")),
                "translation": _floats(p.get("translation")),
                "dtype": str(p.get("dtype", "")),
                "id": doc.id,
            }
        )

    reductionsPresent = sorted({r["reduction_function"] for r in rows} - {"none"})
    if reduction:
        rows = [r for r in rows if r["reduction_function"] in ("none", reduction)]
    rows.sort(key=lambda r: r["level"])  # stable, as MATLAB's sortrows
    return rows, _frame(parentDoc, reductionsPresent)
