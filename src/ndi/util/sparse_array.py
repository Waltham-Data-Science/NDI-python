"""ndi.util.readSparse / writeSparse - the NDI sparse array file format.

MATLAB counterparts: ``src/ndi/+ndi/+util/readSparse.m``,
``src/ndi/+ndi/+util/writeSparse.m``

A sparse N-dimensional array on disk, in a format both toolboxes read and
write. ``ndi.element.ensemble`` stores spike matrices this way, and an
ensemble is meant to move between MATLAB and Python -- so the bytes have to
agree exactly, not merely the values.

WHY THIS EXISTS RATHER THAN .npz OR .mat
MATLAB cannot read NumPy's formats without a reader of its own, NumPy
cannot read MATLAB's sparse types faithfully, and neither language's
native container survives the round trip with N-dimensional subscripts
intact. The format below is small enough to implement twice and be sure.

FORMAT (the NDI sparse array format, version 1)
All multi-byte fields are little-endian. Subscripts are stored 0-BASED on
disk::

    offset  type                  meaning
    ------  --------------------  -------------------------------------
    0       8 x uint8 (ASCII)     magic string 'NDISPARS'
    8       uint32                format version (currently 1)
    12      uint32                ndims, the number of dimensions
    16      ndims x uint64        shape (size of each dimension)
    ...     uint64                nnz, the number of stored entries
    ...     ndims blocks of       subscripts, DIMENSION-MAJOR, 0-based:
            nnz x uint64            all nnz indices for dimension 1, then
                                    all nnz indices for dimension 2, ...
    ...     nnz x float64         the stored values, in the same order

INDEXING, AND WHY THE FILE IS STILL IDENTICAL
Subscripts are 0-based on disk. MATLAB holds them 1-based in memory and
converts on the way in and out; Python holds them 0-based and does not
convert, because scipy and numpy are 0-based and a sample subscript is an
internal data-structure position rather than a user-facing count (see
docs/developer_notes/ndi_xlang_principles.md). Both languages therefore
write the same bytes while reading the subscripts they each expect. A
caller porting MATLAB code that passes literal subscripts must subtract
one; a caller handing over a scipy matrix has nothing to think about.

ENTRY ORDER MATTERS FOR BYTE EQUALITY
MATLAB's one-argument form gets its entries from ``find(A)``, which
returns them in column-major order. :func:`writeSparse` therefore sorts
the same way when given an array, so the two languages produce identical
files for identical matrices. The explicit ``(subs, vals, shape)`` form
preserves the caller's order in both languages, exactly as MATLAB does --
so two callers who pass differently ordered coordinate lists get
different (equally valid) files.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["readSparse", "writeSparse", "MAGIC", "FORMAT_VERSION"]

#: The 8-byte file signature.
MAGIC = b"NDISPARS"

#: The only format version this reader accepts.
FORMAT_VERSION = 1

_HEADER = struct.Struct("<8sII")  # magic, version, ndims
_U64 = np.dtype("<u8")
_F64 = np.dtype("<f8")


def _coordinates_from_array(a: Any) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Column-major (subs, vals, shape) for a 2-D array, as MATLAB's find gives.

    Accepts a scipy sparse matrix or anything numpy can make a 2-D array
    of.  Explicitly stored zeros are DROPPED: a scipy matrix can carry
    one, MATLAB's ``find`` never sees one, and writing it would make two
    equal matrices produce different files.
    """
    try:
        from scipy.sparse import issparse
    except ImportError:  # pragma: no cover - scipy is a core dependency
        issparse = None  # type: ignore[assignment]

    if issparse is not None and issparse(a):
        coo = a.tocoo()
        rows, cols, vals = coo.row, coo.col, coo.data
        shape = tuple(int(x) for x in coo.shape)
    else:
        dense = np.asarray(a)
        if dense.ndim > 2:
            raise ValueError(
                "writeSparse: the one-argument form takes a 2-D array; pass "
                "(subs, vals, shape) for an N-dimensional array."
            )
        if dense.ndim < 2:
            dense = dense.reshape(-1, 1)
        if not (np.issubdtype(dense.dtype, np.number) or np.issubdtype(dense.dtype, np.bool_)):
            raise ValueError("writeSparse: A must be numeric or logical.")
        rows, cols = np.nonzero(dense)
        vals = dense[rows, cols]
        shape = tuple(int(x) for x in dense.shape)

    keep = np.asarray(vals) != 0
    rows, cols, vals = np.asarray(rows)[keep], np.asarray(cols)[keep], np.asarray(vals)[keep]

    # MATLAB's find returns column-major order: column first, then row.
    order = np.lexsort((rows, cols))
    subs = np.column_stack((rows[order], cols[order])).astype(np.int64, copy=False)
    return subs, np.asarray(vals, dtype=float)[order], shape


def _validate_coordinates(
    subs: Any, vals: Any, shape: Any
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Check an explicit coordinate list, mirroring MATLAB's four errors."""
    shape_t = tuple(int(x) for x in np.asarray(shape).ravel())
    ndims = len(shape_t)

    subs_a = np.asarray(subs)
    if subs_a.size == 0:
        subs_a = np.zeros((0, ndims), dtype=np.int64)
    if subs_a.ndim != 2 or subs_a.shape[1] != ndims:
        raise ValueError(
            f"writeSparse: SUBS has {subs_a.shape[1] if subs_a.ndim == 2 else '?'} "
            f"columns; the number of SUBS columns must equal len(shape) ({ndims})."
        )

    vals_a = np.asarray(vals, dtype=float).ravel()
    if subs_a.shape[0] != vals_a.size:
        raise ValueError(
            f"writeSparse: SUBS has {subs_a.shape[0]} rows but VALS has " f"{vals_a.size} elements."
        )

    if subs_a.size:
        if np.any(subs_a < 0) or not np.all(subs_a == np.round(subs_a)):
            raise ValueError(
                "writeSparse: every subscript must be a non-negative integer "
                "(Python subscripts are 0-based; MATLAB's are 1-based)."
            )
        for d in range(ndims):
            if subs_a[:, d].max() >= shape_t[d]:
                raise ValueError(
                    f"writeSparse: a subscript in dimension {d} reaches "
                    f"{int(subs_a[:, d].max())}, outside the size {shape_t[d]}."
                )

    return subs_a.astype(np.int64, copy=False), vals_a, shape_t


def writeSparse(filename: str | Path, *args: Any) -> None:  # noqa: N802
    """Write a sparse array in the NDI sparse array format.

    MATLAB equivalent: ndi.util.writeSparse

    Two calling forms, mirroring MATLAB::

        writeSparse(filename, a)                  # a 2-D array
        writeSparse(filename, subs, vals, shape)  # any dimensionality

    Args:
        filename: Destination path (``.ndisparse`` by convention).
        *args: Either one array, or three values ``subs``, ``vals``,
            ``shape``.  ``subs`` is an ``nnz x ndims`` array of **0-based**
            subscripts (MATLAB's are 1-based; the file is the same either
            way -- see the module docstring).

    Raises:
        ValueError: For a non-2-D array in the one-argument form, a
            non-numeric array, a subs/vals/shape mismatch, a negative or
            non-integer subscript, or a subscript outside the shape.
            These mirror MATLAB's ``ndi:util:writeSparse:*`` errors.
    """
    if len(args) == 1:
        subs, vals, shape = _coordinates_from_array(args[0])
    elif len(args) == 3:
        subs, vals, shape = _validate_coordinates(*args)
    else:
        raise ValueError(
            "writeSparse: call as writeSparse(filename, a) or "
            "writeSparse(filename, subs, vals, shape)."
        )

    ndims = len(shape)
    with open(filename, "wb") as fh:
        fh.write(_HEADER.pack(MAGIC, FORMAT_VERSION, ndims))
        fh.write(np.asarray(shape, dtype=_U64).tobytes())
        fh.write(np.asarray(subs.shape[0], dtype=_U64).tobytes())
        for d in range(ndims):  # dimension-major
            fh.write(np.ascontiguousarray(subs[:, d], dtype=_U64).tobytes())
        fh.write(np.ascontiguousarray(vals, dtype=_F64).tobytes())


def readSparse(filename: str | Path, *, as_coordinates: bool = False) -> Any:  # noqa: N802
    """Read a sparse array written by :func:`writeSparse` or MATLAB's.

    MATLAB equivalent: ndi.util.readSparse

    Args:
        filename: Path to an ``.ndisparse`` file.
        as_coordinates: Return the raw ``(subs, vals, shape)`` triple
            instead of a container.  This stands in for MATLAB's
            ``nargout>=2`` branch, Python having no nargout -- the same
            substitution ``ndi.fun.ensemble``'s ``build_objects`` flag
            makes.

    Returns:
        With *as_coordinates*: ``(subs, vals, shape)``, where ``subs`` is
        an ``nnz x ndims`` int64 array of 0-based subscripts.

        Otherwise, for a 1-D or 2-D array a ``scipy.sparse.coo_matrix``
        (a 1-D array becomes an ``m x 1`` column, as in MATLAB); for
        3 or more dimensions a dict with ``subs``, ``vals`` and ``size``,
        mirroring the struct MATLAB returns because it has no native
        N-dimensional sparse type.

    Raises:
        ValueError: If the magic string or version is wrong.
        OSError: If the file cannot be opened or ends early.
    """
    raw = Path(filename).read_bytes()
    if len(raw) < _HEADER.size:
        raise OSError(f"{filename} is too short to be an NDI sparse file.")

    magic, version, ndims = _HEADER.unpack_from(raw, 0)
    if magic != MAGIC:
        raise ValueError(f"{filename} is not an NDI sparse file (bad magic string).")
    if version != FORMAT_VERSION:
        raise ValueError(f"Unsupported NDI sparse format version {version} in {filename}.")

    offset = _HEADER.size
    shape = tuple(int(x) for x in np.frombuffer(raw, _U64, count=ndims, offset=offset))
    offset += ndims * 8
    nnz = int(np.frombuffer(raw, _U64, count=1, offset=offset)[0])
    offset += 8

    expected = offset + ndims * nnz * 8 + nnz * 8
    if len(raw) < expected:
        raise OSError(
            f"{filename} ends early: expected {expected} bytes for {nnz} entries "
            f"in {ndims} dimensions, found {len(raw)}."
        )

    subs = np.empty((nnz, ndims), dtype=np.int64)
    for d in range(ndims):  # dimension-major, as written
        subs[:, d] = np.frombuffer(raw, _U64, count=nnz, offset=offset)
        offset += nnz * 8
    vals = np.array(np.frombuffer(raw, _F64, count=nnz, offset=offset), dtype=float)

    if as_coordinates:
        return subs, vals, shape

    if ndims > 2:
        return {"subs": subs, "vals": vals, "size": shape}

    from scipy.sparse import coo_matrix

    rows = subs[:, 0] if nnz else np.zeros(0, dtype=np.int64)
    if ndims == 1:
        cols = np.zeros(nnz, dtype=np.int64)
        full_shape = (shape[0], 1)
    else:
        cols = subs[:, 1] if nnz else np.zeros(0, dtype=np.int64)
        full_shape = shape  # type: ignore[assignment]
    return coo_matrix((vals, (rows, cols)), shape=full_shape)
