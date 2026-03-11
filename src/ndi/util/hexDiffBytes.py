"""
ndi.util.hexDiffBytes

MATLAB equivalent: +ndi/+util/hexDiffBytes.m

Compares two byte sequences and returns a formatted hex diff string.
"""

from __future__ import annotations

from typing import Annotated

import pydantic

from .hexDiff import _format_chunk


@pydantic.validate_call
def hexDiffBytes(
    data1: bytes,
    data2: bytes,
    *,
    StartOffset: Annotated[int, pydantic.Field(ge=0)] = 0,
) -> str:
    """Compare two byte sequences and return a hex diff string.

    MATLAB equivalent:
    ``diff_string = ndi.util.hexDiffBytes(data1, data2, ...)``

    Parameters
    ----------
    data1, data2 : bytes
        The byte sequences to compare.
    StartOffset : int, optional
        Zero-based byte offset at which to start (default 0).

    Returns
    -------
    str
        A formatted hex diff string.  Empty if the sequences are
        identical in the compared range.

    Raises
    ------
    ValidationError
        If types are wrong or *StartOffset* is negative.
    """
    max_size = max(len(data1), len(data2))
    lines: list[str] = []
    header_added = False

    for offset in range(StartOffset, max_size, 16):
        chunk1 = data1[offset : offset + 16]
        chunk2 = data2[offset : offset + 16]

        if chunk1 != chunk2:
            if not header_added:
                h1 = (
                    " Offset(h)  00 01 02 03 04 05 06 07  "
                    "08 09 0A 0B 0C 0D 0E 0F  |ASCII           |"
                )
                h2 = (
                    "  |  00 01 02 03 04 05 06 07  "
                    "08 09 0A 0B 0C 0D 0E 0F  |ASCII           |"
                )
                lines.append(h1 + h2)
                lines.append("-" * 140)
                header_added = True

            lines.append(
                f"{offset:08x}:   {_format_chunk(chunk1)}  |  "
                f"{_format_chunk(chunk2)}"
            )

    return "\n".join(lines) if lines else ""
