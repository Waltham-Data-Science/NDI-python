"""
ndi.fun.doc_lightsheet.chooseTileShape

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/chooseTileShape.m

Pick an OME-Zarr chunk shape that lands near a byte budget with tiles that
are isotropic in world space.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Annotated, Any

import pydantic

__all__ = ["chooseTileShape"]


def _round(x: float) -> int:
    """MATLAB's round: half away from zero."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def _bytesPerVoxel(dtype: str) -> int:
    d = str(dtype).strip().lower()
    if d and d[0] in "<>|=":
        d = d[1:]
    if d in ("uint8", "int8", "u1", "i1", "bool", "?"):
        return 1
    if d in ("uint16", "int16", "u2", "i2", "float16", "f2", "half"):
        return 2
    if d in ("uint32", "int32", "u4", "i4", "float32", "f4", "single"):
        return 4
    if d in ("uint64", "int64", "u8", "i8", "float64", "f8", "double"):
        return 8
    if d in ("complex64", "c8"):
        return 8
    if d in ("complex128", "c16"):
        return 16
    # Unknown dtype: assume uint16 (2 bytes), the common lightsheet case.
    return 2


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def chooseTileShape(
    shape: Sequence[Annotated[int, pydantic.Field(gt=0)]],
    axesOrder: str,
    voxelSize: Any,
    dtype: str,
    budgetBytes: Annotated[float, pydantic.Field(gt=0)] = 32 * 2**20,
) -> list[int]:
    """A chunk shape near *budgetBytes* (uncompressed), isotropic in world space.

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.chooseTileShape(shape,
    axesOrder, voxelSize, dtype, budgetBytes)``

    Each spatial axis gets a chunk length inversely proportional to its voxel
    size, so a volume with 1 um XY and 5 um Z gets pancake tiles. Non-spatial
    axes (``t``, ``c``) get 1. The spatial axes share the budget from::

        s = (voxelsPerTile * prod(voxel_i)) ** (1 / nSpatial)
        chunk_i = round(s / voxel_i)

    Each chunk is clamped to *shape*; when any spatial axis clamps, the
    leftover budget is redistributed across the still-slack axes in one pass.

    Args:
        shape: axis lengths, in *axesOrder*.
        axesOrder: one letter per axis, e.g. ``'tczyx'``.
        voxelSize: one value per axis, same order (zeros/NaN allowed on t/c).
            With no usable value on a spatial axis (wrong length,
            non-positive or non-finite), tiles are isotropic in voxel space.
        dtype: NGFF/NumPy/MATLAB spelling (``'uint16'``, ``'<u2'``, ...).
            Unknown types count as 2 bytes.
        budgetBytes: target uncompressed bytes for one chunk; default
            ``32 * 2**20`` (32 MB), as in MATLAB.

    Returns:
        The chunk shape, a list of ints in *axesOrder*.

    Raises:
        ValueError: if ``len(axesOrder) != len(shape)`` (MATLAB:
            ``NDI:lightsheet:chooseTileShape:axesShapeMismatch``).

    Example:
        >>> chooseTileShape([1200, 2000, 2000], "zyx", [5, 1, 1], "uint16")
        [88, 438, 438]
    """
    shape = [int(v) for v in shape]
    n = len(shape)
    if len(axesOrder) != n:
        raise ValueError(f"axes_order length {len(axesOrder)} does not match shape length {n}.")

    # Element-wise membership on the axes string (NDI-matlab 1d11302).
    isSpatial = [ax not in "tc" for ax in axesOrder.lower()]
    chunks = [1] * n
    if not any(isSpatial):
        return [min(c, s) for c, s in zip(chunks, shape)]

    try:
        vs = [float(v) for v in (voxelSize if voxelSize is not None else [])]
    except TypeError:
        vs = [float(voxelSize)]
    if len(vs) != n or any(not (math.isfinite(v) and v > 0) for v, sp in zip(vs, isSpatial) if sp):
        # No usable voxel size on spatial axes: isotropic in voxel space.
        vs = [1.0] * n

    voxelsPerTile = budgetBytes / _bytesPerVoxel(dtype)
    if voxelsPerTile < 1:
        voxelsPerTile = 1.0

    vsSpatial = [v for v, sp in zip(vs, isSpatial) if sp]
    s = (voxelsPerTile * math.prod(vsSpatial)) ** (1 / len(vsSpatial))
    for i in range(n):
        if isSpatial[i]:
            chunks[i] = max(1, _round(s / vs[i]))
    chunks = [min(c, sh) for c, sh in zip(chunks, shape)]

    # One redistribution pass: if any spatial axis clamped to its shape,
    # spread the leftover budget across the axes still below their shape.
    slack = [sp and c < sh for sp, c, sh in zip(isSpatial, chunks, shape)]
    stuck = [sp and not sl for sp, sl in zip(isSpatial, slack)]
    if any(slack) and any(stuck):
        used = math.prod(c for c, st in zip(chunks, stuck) if st)
        if used < 1:
            used = 1
        remaining = voxelsPerTile / used
        vsSlack = [v for v, sl in zip(vs, slack) if sl]
        s2 = (remaining * math.prod(vsSlack)) ** (1 / len(vsSlack))
        for i in range(n):
            if slack[i]:
                chunks[i] = max(1, _round(s2 / vs[i]))
        chunks = [min(c, sh) for c, sh in zip(chunks, shape)]
    return chunks
