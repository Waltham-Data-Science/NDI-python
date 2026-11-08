"""
ndi.fun.doc_lightsheet.dtypeName

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/dtypeName.m

A voxel type as a Zarr (NumPy) dtype string or as a MATLAB class name.
"""

from __future__ import annotations

from typing import Any, Literal

import pydantic

__all__ = ["dtypeName"]

#: (accepted spellings) -> (MATLAB class, Zarr dtype). Byte order is not
#: converted: chunks are little-endian (the documents' byte_order).
_TABLE: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("uint8", "u1"), "uint8", "|u1"),
    (("int8", "i1"), "int8", "|i1"),
    (("uint16", "u2"), "uint16", "<u2"),
    (("int16", "i2"), "int16", "<i2"),
    (("uint32", "u4"), "uint32", "<u4"),
    (("int32", "i4"), "int32", "<i4"),
    (("uint64", "u8"), "uint64", "<u8"),
    (("int64", "i8"), "int64", "<i8"),
    (("single", "float32", "f4"), "single", "<f4"),
    (("double", "float64", "f8"), "double", "<f8"),
    (("logical", "bool", "b1", "?"), "logical", "|b1"),
)


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def dtypeName(dtype: Any, form: Literal["zarr", "matlab"]) -> str:
    """A voxel type as a Zarr dtype (``'<u2'``) or a MATLAB class (``'uint16'``).

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.dtypeName(dtype, form)``

    lightsheetZarrPyramid and lightsheetZarrLevel documents record the dtype
    as the Zarr (NumPy) dtype string, ``'<u2'``, little-endian; the code that
    builds chunks in MATLAB works with the class name ``'uint16'``. *dtype*
    may be either form, or a Zarr v3 name (``'uint16'``, ``'float32'``), so
    documents written before the dtype was normalized read the same.

    Args:
        dtype: the type, as a string (any of the spellings above) or anything
            whose ``str()`` is one, e.g. a :class:`numpy.dtype`.
        form: ``'zarr'`` or ``'matlab'``.

    Returns:
        The type in the requested form.

    Raises:
        ValueError: if the type is not one of the known voxel types
            (MATLAB: ``NDI:lightsheet:dtypeName:unknown``).

    Example:
        >>> dtypeName("uint16", "zarr")
        '<u2'
        >>> dtypeName("<f4", "matlab")
        'single'
    """
    d = str(dtype).strip().lower()
    if d and d[0] in "<>|=":
        d = d[1:]
    for names, matlab, zarr in _TABLE:
        if d in names:
            return zarr if form == "zarr" else matlab
    raise ValueError(f"Unknown voxel type '{dtype}'.")
