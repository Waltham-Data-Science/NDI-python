"""
ndi.util.getHexDiffFromFileObj

MATLAB equivalent: +ndi/+util/getHexDiffFromFileObj.m

Compare two file-like objects chunk by chunk for equality.
"""

from __future__ import annotations

from typing import IO

from .hexDiffBytes import hexDiffBytes


def getHexDiffFromFileObj(
    file_obj1: IO[bytes],
    file_obj2: IO[bytes],
    *,
    chunkSize: int = 1024 * 1024,
) -> tuple[bool, str]:
    """Compare two file-like objects chunk by chunk.

    MATLAB equivalent:
    ``[are_identical, diff_output] = ndi.util.getHexDiffFromFileObj(f1, f2)``

    Parameters
    ----------
    file_obj1, file_obj2 : file-like (binary mode)
        Open file objects to compare.
    chunkSize : int, optional
        Number of bytes to read per chunk (default 1 MiB).

    Returns
    -------
    are_identical : bool
        ``True`` if files are identical.
    diff_output : str
        Empty when identical; hex diff of the first mismatched chunk
        otherwise.
    """
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
