"""
ndi.util.hexDump

MATLAB equivalent: +ndi/+util/hexDump.m

Displays the hexadecimal and ASCII content of a file.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from .hexDiff import _format_chunk


def hexDump(
    filename: str | Path,
    *,
    StartByte: int = 0,
    StopByte: int | None = None,
) -> None:
    """Print a hex dump of a file.

    MATLAB equivalent: ``ndi.util.hexDump(filename, ...)``

    Parameters
    ----------
    filename : str or Path
        Path to the file.
    StartByte : int, optional
        Zero-based byte offset to start (default 0).
    StopByte : int or None, optional
        Zero-based byte offset to end.  ``None`` means end of file.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If *StartByte* > *StopByte* or beyond end of file.
    """
    path = Path(filename)
    data = path.read_bytes()
    file_size = len(data)

    if file_size == 0:
        print("-" * 77)
        print(f" Hex Dump of: {filename}")
        print(" File Size: 0 bytes")
        print("-" * 77)
        print("No data to display in the specified range.")
        print("-" * 77)
        return

    if StopByte is None:
        StopByte = file_size - 1

    if StartByte >= file_size:
        raise ValueError(
            f"StartByte ({StartByte}) is beyond the end of the file "
            f"(size: {file_size} bytes)."
        )
    if StopByte >= file_size:
        warnings.warn(
            f"StopByte ({StopByte}) is beyond the end of the file. "
            f"Adjusting to {file_size - 1}.",
            stacklevel=2,
        )
        StopByte = file_size - 1
    if StartByte > StopByte:
        raise ValueError(
            f"StartByte ({StartByte}) cannot be greater than "
            f"StopByte ({StopByte})."
        )

    print("-" * 77)
    print(f" Hex Dump of: {filename}")
    print(f" File Size: {file_size} bytes")
    print(f" Displaying bytes {StartByte} through {StopByte}")
    print("-" * 77)
    print(
        " Offset(h)  00 01 02 03 04 05 06 07  "
        "08 09 0A 0B 0C 0D 0E 0F  |ASCII           |"
    )
    print("-" * 77)

    region = data[StartByte : StopByte + 1]
    for offset in range(0, len(region), 16):
        chunk = region[offset : offset + 16]
        addr = StartByte + offset
        print(f"{addr:08x}:   {_format_chunk(chunk)}")

    print("-" * 77)
