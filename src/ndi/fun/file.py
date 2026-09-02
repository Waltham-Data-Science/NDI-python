"""
ndi.fun.file - File utility functions.

MATLAB equivalents: +ndi/+fun/+file/MD5.m, dateCreated.m, dateUpdated.m
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def MD5(file_path: str) -> str:
    """Compute MD5 checksum of a file.

    MATLAB equivalent: ndi.fun.file.MD5

    Args:
        file_path: Path to the file.

    Returns:
        32-character lowercase hex digest.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def dateCreated(file_path: str) -> datetime | None:
    """Get the creation date of a file.

    MATLAB equivalent: ndi.fun.file.dateCreated

    Uses ``st_birthtime`` on macOS, falls back to ``st_ctime`` elsewhere.

    Args:
        file_path: Path to the file.

    Returns:
        UTC datetime or ``None`` if unavailable.
    """
    p = Path(file_path)
    if not p.exists():
        return None
    try:
        stat = p.stat()
        # macOS provides st_birthtime
        ts = getattr(stat, "st_birthtime", None)
        if ts is None:
            ts = stat.st_ctime  # Windows: creation; Linux: metadata change
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


def dateUpdated(file_path: str) -> datetime | None:
    """Get the last modification date of a file.

    MATLAB equivalent: ndi.fun.file.dateUpdated

    Args:
        file_path: Path to the file.

    Returns:
        UTC datetime or ``None`` if file doesn't exist.
    """
    p = Path(file_path)
    if not p.exists():
        return None
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return None


# Backward-compatible aliases
md5 = MD5
date_created = dateCreated
date_updated = dateUpdated

#: Windows reserved device names. Illegal with or without an extension.
_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def utf16_units(text: str) -> list[int]:
    """Return *text* as a list of UTF-16 code units.

    MATLAB ``char`` arrays hold UTF-16 code units, so a character above
    U+FFFF is a surrogate **pair** and occupies two positions. Python strings
    are sequences of code points, where the same character occupies one.

    :func:`pathSafeName` is a *filename* contract, and the two languages must
    agree on the folder an element's data lives in, so the port reproduces
    MATLAB's unit counting rather than Python's natural one. That is why an
    astral character sanitizes to **two** ``-``, not one.
    """
    units: list[int] = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF:
            cp -= 0x10000
            units.append(0xD800 + (cp >> 10))
            units.append(0xDC00 + (cp & 0x3FF))
        else:
            units.append(cp)
    return units


def _is_portable(unit: int) -> bool:
    """Is this UTF-16 code unit in the portable set ``[A-Za-z0-9._-]``?"""
    return (
        0x41 <= unit <= 0x5A  # A-Z
        or 0x61 <= unit <= 0x7A  # a-z
        or 0x30 <= unit <= 0x39  # 0-9
        or unit in (0x5F, 0x2D, 0x2E)  # _ - .
    )


def pathSafeName(name: str) -> str:  # noqa: N802 (MATLAB mirror)
    """Convert a string into a file/folder name legal on every platform.

    Returns a version of *name* that is legal as a single file or folder name
    on Windows, macOS and Linux, and that survives a trip through a URL or a
    zip archive without escaping. The result is drawn from ``[A-Za-z0-9._-]``
    only:

    - whitespace and control characters become ``_``
    - every other character outside the portable set becomes ``-``
      (including those Windows forbids outright: ``< > : " / \\ | ? *``)
    - trailing ``.`` characters are removed (Windows silently strips them)
    - a name matching a Windows reserved device name (``CON``, ``PRN``,
      ``AUX``, ``NUL``, ``COM1``-``COM9``, ``LPT1``-``LPT9``), with or
      without an extension, is prefixed with ``_``
    - an empty result becomes ``x``

    The order matters and is pinned by the symmetry battery: the trailing-dot
    strip runs **before** the empty check and **before** the reserved-name
    check.

    MATLAB equivalent: ``ndi.fun.file.pathSafeName``.

    Example:
        >>> pathSafeName('ctx_|_1')
        'ctx_-_1'
    """
    if not isinstance(name, str):
        # MATLAB's arguments block rejects this with mustBeTextScalar. Only
        # the fact of the error is compared across languages, never its
        # identifier or message.
        raise TypeError(f"name must be a text scalar; got {type(name).__name__}.")

    out: list[str] = []
    for unit in utf16_units(name):
        if unit < 32 or unit == 127 or unit == 0x20:
            out.append("_")  # whitespace and control
        elif _is_portable(unit):
            out.append(chr(unit))
        else:
            out.append("-")

    s = "".join(out)

    # Windows drops trailing dots from file and folder names.
    s = s.rstrip(".")

    if not s:
        s = "x"

    # Reserved device names are illegal with or without an extension. The
    # base name is what precedes the FIRST dot, so '.hidden' has an empty
    # base name and is never prefixed.
    dot = s.find(".")
    base = s if dot < 0 else s[:dot]
    if base.upper() in _RESERVED:
        s = "_" + s

    return s


def elementDirectory(  # noqa: N802 (MATLAB mirror)
    parent_dir: str | Path, element: Any
) -> tuple[str, str, bool]:
    """The per-element working folder inside PARENT_DIR, with legacy fallback.

    Returns ``(dir_path, dir_name, is_legacy)``.

    *element* may be an object answering ``elementstring()`` or the element
    string itself. The current, platform-independent name from
    :func:`elementDirectoryName` is preferred; when no folder by that name
    exists but one by the legacy ``|``-separated name does, the legacy folder
    is returned instead, so data written by earlier versions of NDI is still
    found. When neither exists the NEW name is returned, so a caller that
    creates the folder creates it under the current name.

    MATLAB equivalent: ``ndi.fun.file.elementDirectory``.
    """
    parent = Path(parent_dir)
    dir_name, legacy_dir_name = elementDirectoryName(element)
    is_legacy = False

    if dir_name != legacy_dir_name:
        if not (parent / dir_name).is_dir() and (parent / legacy_dir_name).is_dir():
            dir_name = legacy_dir_name
            is_legacy = True

    return str(parent / dir_name), dir_name, is_legacy


#: snake_case alias, as elsewhere in this module.
element_directory = elementDirectory


def elementDirectoryName(element: Any) -> tuple[str, str]:  # noqa: N802 (MATLAB mirror)
    """The folder name NDI uses for an element or probe.

    Returns ``(dirName, legacyDirName)``.

    *element* may be an object answering ``elementstring()``, or the element
    string itself.

    ``dirName`` is the current, platform-independent name: the element string
    with whitespace turned into ``_`` and everything outside
    ``[A-Za-z0-9._-]`` turned into ``-`` by :func:`pathSafeName`. For an
    element named ``ctx`` with reference 1 that is ``ctx_-_1``.

    ``legacyDirName`` is what NDI wrote before that change: the element
    string with whitespace turned into ``_`` and **nothing else** changed,
    which for the same element is ``ctx_|_1``. ``|`` is not legal in a
    Windows filename. It is returned so callers can keep reading data written
    under the old name.

    MATLAB equivalent: ``ndi.fun.file.elementDirectoryName``.
    """
    if isinstance(element, str):
        element_string = element
    else:
        element_string = str(element.elementstring())

    legacy_dir_name = element_string.replace(" ", "_")
    return pathSafeName(legacy_dir_name), legacy_dir_name


def elementDirectory(  # noqa: N802 (MATLAB mirror)
    parentDir: str | Path,  # noqa: N803 (MATLAB mirror)
    element: Any,
) -> tuple[str, str, bool]:
    """The working directory for an element or probe, with legacy fallback.

    Returns ``(dirPath, dirName, isLegacy)``.

    *parentDir* is the folder the per-element folder lives in -- typically
    ``<session.path>/kilosort`` or ``<session.path>/kiasort``. *element* may
    be an object answering ``elementstring()``, or the element string itself.

    The platform-independent name from :func:`elementDirectoryName` is
    preferred. If no folder by that name exists but one by the legacy name
    does -- the pre-existing form separating the element name from its
    reference with ``|``, which is not a legal Windows filename character --
    the legacy folder is returned instead, so data written by earlier
    versions of NDI is still found. When neither exists the new name is
    returned, so a caller that creates the folder creates it under the new
    name.

    ``isLegacy`` is True when the legacy folder was chosen.

    MATLAB equivalent: ``ndi.fun.file.elementDirectory``.
    """
    parent = Path(str(parentDir))
    dir_name, legacy_dir_name = elementDirectoryName(element)
    is_legacy = False

    if dir_name != legacy_dir_name:
        if not (parent / dir_name).is_dir() and (parent / legacy_dir_name).is_dir():
            dir_name = legacy_dir_name
            is_legacy = True

    return str(parent / dir_name), dir_name, is_legacy


#: snake_case spelling of :func:`elementDirectory`, the house style for new
#: code; the MATLAB spelling stays the primary name, as elsewhere in this
#: module.
element_directory = elementDirectory
element_directory_name = elementDirectoryName
