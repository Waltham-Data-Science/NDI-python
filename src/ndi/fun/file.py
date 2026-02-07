"""
ndi.fun.file - File utility functions.

MATLAB equivalents: +ndi/+fun/+file/MD5.m, dateCreated.m, dateUpdated.m
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def md5(file_path: str) -> str:
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
        raise FileNotFoundError(f'File not found: {file_path}')
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def date_created(file_path: str) -> Optional[datetime]:
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
        ts = getattr(stat, 'st_birthtime', None)
        if ts is None:
            ts = stat.st_ctime  # Windows: creation; Linux: metadata change
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


def date_updated(file_path: str) -> Optional[datetime]:
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
