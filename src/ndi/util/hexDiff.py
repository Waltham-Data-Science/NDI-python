"""
ndi.util.hexDiff

MATLAB equivalent: +ndi/+util/hexDiff.m

Compares two files and prints the 16-byte lines where they differ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pydantic


@pydantic.validate_call
def hexDiff(
    filename1: str | Path,
    filename2: str | Path,
    *,
    StartByte: Annotated[int, pydantic.Field(ge=0)] = 0,
    StopByte: Annotated[int, pydantic.Field(ge=0)] | None = None,
) -> None:
    """Compare two files and print differing 16-byte lines.

    MATLAB equivalent: ``ndi.util.hexDiff(filename1, filename2, ...)``

    Parameters
    ----------
    filename1, filename2 : str or Path
        Paths to the files to compare.
    StartByte : int, optional
        Zero-based byte offset to start comparison (default 0).
    StopByte : int or None, optional
        Zero-based byte offset to end comparison.  ``None`` means end of
        the longer file.

    Raises
    ------
    ValidationError
        If types are wrong or byte offsets are negative.
    FileNotFoundError
        If either file does not exist.
    ValueError
        If *StartByte* > *StopByte*.
    """
    data1 = Path(filename1).read_bytes()
    data2 = Path(filename2).read_bytes()

    max_size = max(len(data1), len(data2))

    if StopByte is None:
        StopByte = max_size - 1 if max_size > 0 else -1

    if StartByte >= max_size and max_size > 0:
        raise ValueError(
            f"StartByte ({StartByte}) is beyond the end of both files."
        )
    if StartByte > StopByte:
        raise ValueError(
            f"StartByte ({StartByte}) cannot be greater than "
            f"StopByte ({StopByte})."
        )

    print(
        f'Comparing "{filename1}" ({len(data1)} bytes) with '
        f'"{filename2}" ({len(data2)} bytes)'
    )
    print("Displaying only differing 16-byte lines...")
    print("-" * 140)

    differences_found = False
    for offset in range(StartByte, StopByte + 1, 16):
        chunk1 = data1[offset : offset + 16]
        chunk2 = data2[offset : offset + 16]

        if chunk1 != chunk2:
            if not differences_found:
                _print_header()
                differences_found = True
            _print_diff_line(offset, chunk1, chunk2)

    if not differences_found:
        print("Files are identical in the specified range.")
    print("-" * 140)


def _print_header() -> None:
    h1 = (
        " Offset(h)  00 01 02 03 04 05 06 07  "
        "08 09 0A 0B 0C 0D 0E 0F  |ASCII           |"
    )
    h2 = (
        "  |  00 01 02 03 04 05 06 07  "
        "08 09 0A 0B 0C 0D 0E 0F  |ASCII           |"
    )
    print(h1 + h2)
    print("-" * 140)


def _format_chunk(chunk: bytes) -> str:
    hex_parts: list[str] = []
    for k in range(16):
        if k < len(chunk):
            hex_parts.append(f"{chunk[k]:02X} ")
        else:
            hex_parts.append("   ")
        if k == 7:
            hex_parts.append(" ")

    ascii_parts: list[str] = []
    for k in range(16):
        if k < len(chunk):
            ch = chunk[k]
            ascii_parts.append(chr(ch) if 32 <= ch <= 126 else ".")
        else:
            ascii_parts.append(" ")

    return "".join(hex_parts) + " |" + "".join(ascii_parts) + "|"


def _print_diff_line(offset: int, chunk1: bytes, chunk2: bytes) -> None:
    print(
        f"{offset:08x}:   {_format_chunk(chunk1)}  |  "
        f"{_format_chunk(chunk2)}"
    )
