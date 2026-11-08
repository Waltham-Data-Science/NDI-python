"""
ndi.fun.doc_lightsheet.reduceBlocks

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/reduceBlocks.m

Vectorized per-axis block mean / max of an N-D array, with the semantics of
``ndr.format.omezarr.reduce`` (trailing partial block included).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
import pydantic

from .dtypeName import dtypeName

__all__ = ["reduceBlocks"]

#: Classes whose mean MATLAB accumulates in single precision.
_SINGLE_ACCUMULATE = (np.uint8, np.int8, np.uint16, np.int16, np.float32)


def _outDtype(outClass: Any, arr: np.ndarray) -> np.dtype:
    """*outClass* as a NumPy dtype; MATLAB class names are accepted."""
    if outClass is None:
        return arr.dtype
    if isinstance(outClass, str):
        try:
            return np.dtype(dtypeName(outClass, "zarr"))
        except ValueError:
            pass
    return np.dtype(outClass)


def _matlabRound(x: np.ndarray) -> np.ndarray:
    """MATLAB's round: half away from zero (NumPy's rounds half to even)."""
    return np.sign(x) * np.floor(np.abs(x) + 0.5)


def _matlabCast(work: np.ndarray, out: np.dtype) -> np.ndarray:
    """MATLAB's cast: a float into an integer class rounds and saturates."""
    if np.issubdtype(out, np.integer) and np.issubdtype(work.dtype, np.floating):
        info = np.iinfo(out)
        work = np.nan_to_num(_matlabRound(work), nan=0.0)
        work = np.clip(work, info.min, info.max)
    elif out == np.bool_:
        return work != 0
    return work.astype(out)


def _reduceAxis(A: np.ndarray, d: int, f: int, reduction: str) -> np.ndarray:
    """Reduce A along axis d by factor f, trailing partial block included."""
    n = A.shape[d]
    m = -(-n // f)
    pad = m * f - n
    if pad > 0:
        if reduction == "mean":
            # Zeros add nothing to the sum; the last block's divisor is
            # corrected below.
            padShape = list(A.shape)
            padShape[d] = pad
            A = np.concatenate([A, np.zeros(padShape, dtype=A.dtype)], axis=d)
        else:
            # Repeat the last element: it cannot change the max.
            last = np.take(A, [n - 1] * pad, axis=d)
            A = np.concatenate([A, last], axis=d)
    # Split axis d into (m, f) -- consecutive runs of f -- and reduce over f.
    newShape = A.shape[:d] + (m, f) + A.shape[d + 1 :]
    A = A.reshape(newShape)
    if reduction == "mean":
        A = A.sum(axis=d + 1, dtype=A.dtype)
        counts = np.full(m, f, dtype=A.dtype)
        counts[-1] = n - (m - 1) * f
        cshape = [1] * A.ndim
        cshape[d] = m
        A = A / counts.reshape(cshape)
    else:
        A = A.max(axis=d + 1)
    return A


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def reduceBlocks(
    arr: Any,
    factor: int | Sequence[int],
    reduction: Literal["mean", "max"],
    outClass: Any = None,
) -> np.ndarray:
    """Block-reduce an N-D array, one axis at a time.

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.reduceBlocks(arr, factor,
    reduction, outClass)``

    Downsamples *arr* by the per-axis integer *factor* using *reduction*.
    Output element ``i`` (0-based) along an axis covers input elements
    ``i*f .. (i+1)*f - 1``; the trailing block may be partial and is reduced
    over the elements it has, so an axis of length 5 with factor 2 gives 3
    outputs (blocks of 2, 2 and 1). These are the semantics of
    ``ndr.format.omezarr.reduce``.

    The mean is accumulated in float32 for 8- and 16-bit integer and float32
    inputs and in float64 otherwise, as in MATLAB. A mean into an integer
    class is rounded to nearest, half away from zero (MATLAB's ``round``).

    Args:
        arr: a numeric array (anything :func:`numpy.asarray` accepts).
        factor: one positive integer per axis, or a scalar for every axis.
            Entries beyond ``arr.ndim`` refer to MATLAB's implicit trailing
            singleton axes and change nothing.
        reduction: ``'mean'`` or ``'max'``.
        outClass: the output type -- a MATLAB class name (``'uint16'``,
            ``'single'``, ``'double'``), a Zarr/NumPy dtype string or a
            :class:`numpy.dtype`. Default: the type of *arr*.

    Returns:
        The reduced array.

    Raises:
        ValueError: if *factor* has fewer entries than *arr* has axes
            (MATLAB: ``NDI:lightsheet:reduceBlocks:badFactor``), or is not
            all positive integers, or *arr* is not numeric.
    """
    arr = np.asarray(arr)
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"arr must be numeric, got dtype {arr.dtype}.")
    f = np.atleast_1d(np.asarray(factor))
    if f.ndim != 1 or not np.all(f == np.round(f)) or np.any(f < 1):
        raise ValueError("factor must be positive integers.")
    f = [int(v) for v in f]
    if len(f) == 1:
        f = f * max(arr.ndim, 1)
    if len(f) < arr.ndim:
        raise ValueError(f"factor has {len(f)} entries for a {arr.ndim}-D array.")
    out = _outDtype(outClass, arr)

    if reduction == "mean":
        work = arr.astype(np.float32 if arr.dtype.type in _SINGLE_ACCUMULATE else np.float64)
    else:
        work = arr

    for d in range(arr.ndim):
        if f[d] == 1 or work.shape[d] == 1:
            continue  # nothing to reduce along this axis
        work = _reduceAxis(work, d, f[d], reduction)

    return _matlabCast(work, out)
