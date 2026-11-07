"""
ndi.fun.doc_lightsheet.chooseLevel

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/chooseLevel.m

Pick the coarsest pyramid level whose voxel size still meets a target.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pydantic

__all__ = ["chooseLevel"]


def _field(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row[name]
    return getattr(row, name)


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def chooseLevel(levels: Sequence[Any], targetVoxelSize: float | Sequence[float]) -> tuple[int, Any]:
    """The coarsest level whose per-axis voxel size is still <= the target.

    MATLAB equivalent: ``[levelIndex, levelRow] =
    ndi.fun.doc.lightsheet.chooseLevel(levels, targetVoxelSize)``

    Args:
        levels: the level rows, finest first, each with ``voxel_size`` and
            ``level`` -- the list :func:`levelTable` returns (its first
            element), or any sequence of mappings / objects carrying those
            two fields.
        targetVoxelSize: a scalar (applied to every axis) or a sequence
            aligned with ``voxel_size``. With a shorter (or longer) sequence
            only the common leading axes are compared.

    Returns:
        ``(levelIndex, levelRow)``. *levelIndex* is the level's ``level``
        value, the 0-based ``lightsheetZarrLevel.level``. *levelRow* is the
        chosen element of *levels* itself. If every level is coarser than
        the target, the finest (first) is returned; if every level is finer,
        the coarsest.

    Raises:
        ValueError: if *levels* is empty (MATLAB:
            ``NDI:lightsheet:chooseLevel:emptyLevels``).
    """
    if len(levels) == 0:
        raise ValueError("levels is empty.")
    scalar = not isinstance(targetVoxelSize, Sequence)
    target = float(targetVoxelSize) if scalar else [float(t) for t in targetVoxelSize]

    bestK = 0
    for k, row in enumerate(levels):
        v = [float(x) for x in _field(row, "voxel_size")]
        if scalar:
            ok = all(x <= target for x in v)
        else:
            ok = all(x <= t for x, t in zip(v, target))
        if ok:
            bestK = k

    return int(_field(levels[bestK], "level")), levels[bestK]
