"""
ndi.fun.file - File utility functions.

MATLAB equivalents: +ndi/+fun/+file/MD5.m, dateCreated.m, dateUpdated.m,
pathSafeName.m, elementDirectoryName.m, elementDirectory.m
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Windows reserved device names.  Illegal as a file or folder name with or
# without an extension.  Compared case-insensitively.
_WINDOWS_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


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


def pathSafeName(name: str) -> str:
    """Convert a string into a file/folder name that is legal on all platforms.

    MATLAB equivalent: ndi.fun.file.pathSafeName

    Returns a version of *name* that is legal as a single file or folder name on
    Windows, macOS, and Linux, and that survives a trip through a URL or a zip
    archive without escaping.

    The returned name is drawn from the portable character set
    ``[A-Za-z0-9._-]`` only:

    - whitespace and control characters become ``'_'``
    - every other character outside the portable set becomes ``'-'``
      (this includes the characters Windows forbids outright: ``< > : " / \\ | ? *``)
    - trailing ``'.'`` characters are removed (Windows silently strips them)
    - a name that matches a Windows reserved device name (``CON``, ``PRN``,
      ``AUX``, ``NUL``, ``COM1``-``COM9``, ``LPT1``-``LPT9``), with or without an
      extension, is prefixed with ``'_'``
    - an empty result becomes ``'x'``

    This is the sanitizer used by :func:`elementDirectoryName` to build the
    per-element working directories used by the probe export and spike-sorter
    import functions.  Earlier versions of NDI used
    :meth:`ndi.element.ndi_element.elementstring` directly, which embeds a
    ``' | '`` separator; ``'|'`` is not a legal filename character on Windows.

    MATLAB operates on UTF-16 code units, so a character outside the Basic
    Multilingual Plane (a surrogate pair in MATLAB) maps to *two* ``'-'``
    characters.  This function reproduces that so the two languages agree on
    the folder name for the same element.

    Args:
        name: The string to sanitize.

    Returns:
        A name drawn from ``[A-Za-z0-9._-]``, never empty.

    Raises:
        TypeError: If *name* is not a string (MATLAB ``mustBeTextScalar``).

    Example:
        >>> pathSafeName('ctx_|_1')
        'ctx_-_1'
    """
    if not isinstance(name, str):
        raise TypeError(f"pathSafeName expects a string, got {type(name).__name__}")

    out: list[str] = []
    for ch in name:
        code = ord(ch)
        # whitespace and control characters -> '_'
        if code < 32 or code == 127 or ch == " ":
            out.append("_")
        # the portable set survives unchanged
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "_-.":
            out.append(ch)
        # everything else -> '-', one per UTF-16 code unit (MATLAB parity)
        else:
            out.append("-" * (2 if code > 0xFFFF else 1))
    s = "".join(out)

    # Windows drops trailing dots from file and folder names
    s = s.rstrip(".")

    if not s:
        s = "x"

    # Windows reserved device names are illegal with or without an extension
    base_name = s.split(".", 1)[0]
    if base_name.upper() in _WINDOWS_RESERVED_NAMES:
        s = "_" + s

    return s


def elementDirectoryName(element: Any) -> tuple[str, str]:
    """The folder name that NDI uses for an element or probe.

    MATLAB equivalent: ndi.fun.file.elementDirectoryName

    Returns the name of the per-element working folder used by the probe export
    and spike-sorter import functions (see
    :func:`ndi.fun.probe.export_all_binary`,
    :func:`ndi.fun.probe.import_.kilosort.probe`).

    Args:
        element: An :class:`ndi.element.ndi_element` or
            :class:`ndi.probe.ndi_probe` object (anything that answers
            ``elementstring()``), or the element string itself.

    Returns:
        Tuple ``(dir_name, legacy_dir_name)``.

        ``dir_name`` is the current, platform-independent name: the element
        string with whitespace turned into ``'_'`` and every character outside
        ``[A-Za-z0-9._-]`` turned into ``'-'`` by :func:`pathSafeName`.  For an
        element named ``'ctx'`` with reference 1 this is ``'ctx_-_1'``.

        ``legacy_dir_name`` is the name that versions of NDI before this change
        wrote: the element string with whitespace turned into ``'_'`` and nothing
        else changed, which for the same element is ``'ctx_|_1'``.  The ``'|'``
        character is not legal in a filename on Windows.  ``legacy_dir_name`` is
        returned so that callers can keep reading data that was written under the
        old name; use :func:`elementDirectory` to do that resolution.
    """
    if isinstance(element, str):
        element_string = element
    else:
        element_string = str(element.elementstring())

    legacy_dir_name = element_string.replace(" ", "_")
    dir_name = pathSafeName(legacy_dir_name)

    return dir_name, legacy_dir_name


def elementDirectory(parent_dir: str | Path, element: Any) -> tuple[Path, str, bool]:
    """The working directory for an element or probe, with legacy fallback.

    MATLAB equivalent: ndi.fun.file.elementDirectory

    Returns the full path of the per-element working folder inside *parent_dir*
    (typically ``Path(session.path) / 'kilosort'`` or similar).

    The platform-independent folder name from :func:`elementDirectoryName` is
    preferred.  If no folder by that name exists but a folder with the legacy
    name does -- the pre-existing form that separates the element name from its
    reference with ``'|'``, which is not a legal filename character on Windows --
    then the legacy folder is returned instead, so that data written by earlier
    versions of NDI is still found.  When neither exists, the new name is
    returned, so callers that create the folder create it under the new name.

    This function never creates anything on disk.

    Args:
        parent_dir: The directory that holds the per-element folders.
        element: An ndi.element / ndi.probe object (anything that answers
            ``elementstring()``), or the element string itself.

    Returns:
        Tuple ``(dir_path, dir_name, is_legacy)``.  ``is_legacy`` is ``True``
        when the legacy folder was chosen.

    Example:
        >>> probedir, _, _ = elementDirectory(Path(S.path) / 'kilosort', probe)
    """
    parent = Path(parent_dir)

    dir_name, legacy_dir_name = elementDirectoryName(element)
    is_legacy = False

    if dir_name != legacy_dir_name:
        if not (parent / dir_name).is_dir() and (parent / legacy_dir_name).is_dir():
            dir_name = legacy_dir_name
            is_legacy = True

    return parent / dir_name, dir_name, is_legacy


# Backward-compatible aliases
md5 = MD5
date_created = dateCreated
date_updated = dateUpdated
