"""
ndi.util.getHexDiffFromFileObj

MATLAB equivalent: +ndi/+util/getHexDiffFromFileObj.m

Compare two file-like objects chunk by chunk for equality.
"""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

import pydantic
from pydantic import ConfigDict

from .hexDiffBytes import hexDiffBytes


@runtime_checkable
class _BinaryStream(Protocol):
    """What this function actually needs of a file object.

    NOT ``typing.IO[bytes]``. Under ``@pydantic.validate_call`` that
    annotation compiles to ``isinstance(value, IO)``, and ``typing.IO`` is an
    ordinary generic class that nothing real subclasses -- neither
    ``io.BytesIO`` nor the ``BufferedReader`` that ``open(path, "rb")``
    returns. So EVERY call raised ValidationError before the body ran, and
    the function could not be invoked at all. A runtime-checkable Protocol
    asks the question that was meant: does this object read, seek and tell?
    """

    def read(self, size: int = ..., /) -> bytes: ...

    def seek(self, offset: int, whence: int = ..., /) -> int: ...

    def tell(self) -> int: ...


@pydantic.validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def getHexDiffFromFileObj(
    file_obj1: _BinaryStream,
    file_obj2: _BinaryStream,
    *,
    chunkSize: Annotated[int, pydantic.Field(gt=0)] = 1024 * 1024,
) -> tuple[bool, str]:
    """Compare two file-like objects chunk by chunk.

    MATLAB equivalent:
    ``[are_identical, diff_output] = ndi.util.getHexDiffFromFileObj(f1, f2)``

    Parameters
    ----------
    file_obj1, file_obj2 : file-like (binary mode)
        Open file objects to compare.
    chunkSize : int, optional
        Number of bytes to read per chunk (default 1 MiB).  Must be
        positive.

    Returns
    -------
    are_identical : bool
        ``True`` if files are identical.
    diff_output : str
        Empty when identical; hex diff of the first mismatched chunk
        otherwise.

    Raises
    ------
    ValidationError
        If types are wrong or *chunkSize* is not positive.
    """
    # Both objects are left rewound however this function exits, matching the
    # two onCleanup objects MATLAB installs ("ensure rewind after we are
    # done"). Without it a caller that compares two files and then reads one
    # gets whatever is left after the comparison -- nothing at all in the
    # identical case, since both are then at EOF.
    try:
        file_obj1.seek(0, 2)
        size1 = file_obj1.tell()
        file_obj2.seek(0, 2)
        size2 = file_obj2.tell()

        file_obj1.seek(0)
        file_obj2.seek(0)

        if size1 != size2:
            d1 = file_obj1.read(chunkSize)
            d2 = file_obj2.read(chunkSize)
            msg = f"Files have different sizes ({size1} bytes vs {size2} bytes)."
            if d1 != d2:
                msg += "\nHexdiff of the start of the files:\n" + hexDiffBytes(d1, d2)
            return False, msg

        offset = 0
        while True:
            d1 = file_obj1.read(chunkSize)
            d2 = file_obj2.read(chunkSize)
            if not d1 and not d2:
                break
            if d1 != d2:
                return False, hexDiffBytes(d1, d2, StartOffset=offset)
            offset += len(d1)

        return True, ""
    finally:
        file_obj1.seek(0)
        file_obj2.seek(0)
