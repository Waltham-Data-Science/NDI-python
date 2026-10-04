"""
ndi.cloud.signed_url_disk_cache - Persistent (on-disk) signed-URL cache.

MATLAB equivalent:
    +ndi/+cloud/+download/+internal/signedUrlDiskCache.m
    (VH-Lab/NDI-matlab commit 27661a3 on the same branch)

This is the disk-backed layer that sits beneath the in-process cache
inside :class:`ndi.cloud.batch_signed_url.BatchSignedUrlLookup`. It exists
so a working scientist reopening the same dataset over a day pays the
~85-minute async signed-URL-set-job cost ONCE and reads from disk on
every subsequent viewer open. NDI cloud infrastructure, not DID: DID's
file-bytes cache is a separate, complementary concern.

Scope key
---------
The unit the cache stores and evicts is one ``(dataset_id, document_id,
series_name)`` tuple -- the same tuple ``BatchSignedUrlLookup`` uses. An
empty ``series_name`` marks a whole-document scope.

Payload
-------
What :func:`save` writes and :func:`load` returns is a dict with the
fields the ``getSignedURLSetResult`` answer already carries:

    files         dict[str, str]: uid -> pre-signed download URL.
    filesExpireAt ISO-8601 UTC string; the server's authoritative expiry
                  for the signed URLs. Preferred.
    expiresAt     ISO-8601 UTC string; older paging-path field. Used
                  when filesExpireAt is not present.
    generatedAt   ISO-8601 UTC string; when the server built the map.
                  Optional, informational.
    fileCount     int; how many uids the server reported. Optional.

On-disk contract
----------------
The MATLAB and Python implementations write the SAME bytes: a scientist
can hand a cache dir written by MATLAB to a Python viewer and see
zero-cost reopens, and vice versa.

Location:  <cache_dir>/<dataset_id>/<document_id>.json.gz         (whole-doc)
           <cache_dir>/<dataset_id>/<document_id>_<escaped>.json.gz (scoped)

``cache_dir`` defaults to ``~/.ndi/signed-url-cache``, overridable via
``NDI_SIGNED_URL_CACHE_DIR``. The base directory is created with
mode 0700 on POSIX because a signed URL is a bearer token for 24 h;
Windows relies on the default per-user profile ACL.

Filename escaping for ``series_name``: any byte outside
``[A-Za-z0-9._-]`` becomes ``%XX`` (uppercase hex). A resulting string
longer than 96 characters is replaced with ``hash-<sha1(raw)>`` (45
chars). MATLAB does the same, byte-for-byte.

Format:    Standard gzip framing (RFC 1952), single member, UTF-8
           JSON body. Unzipping yields a human-readable JSON object::

               {
                 "schemaVersion": 1,
                 "datasetId":     "<mongo _id>",
                 "documentId":    "<ndi id>",
                 "seriesName":    "" or "<name>",
                 "cachedAt":      "YYYY-MM-DDTHH:MM:SSZ",
                 "filesExpireAt": "YYYY-MM-DDTHH:MM:SSZ" or "",
                 "expiresAt":     "YYYY-MM-DDTHH:MM:SSZ" or "",
                 "generatedAt":   "YYYY-MM-DDTHH:MM:SSZ" or "",
                 "fileCount":     N,
                 "files":         { "<uid>": "<url>", ... }
               }

TTL and safety buffer
---------------------
The cache does not invent a TTL. It reads the authoritative
``filesExpireAt`` (or ``expiresAt``) from the payload; a payload with
neither is treated as un-cacheable (:func:`save` is a no-op) and, on
load, as an immediate miss. A URL that would expire in less than the
safety buffer (default 30 min, override with
``NDI_SIGNED_URL_CACHE_SAFETY_SECONDS``) is also treated as a miss --
we never hand a caller a URL likely to 403 before they can use it.

Concurrency
-----------
Writes go to a per-writer temp file next to the target and are moved
into place with :func:`os.replace`, which is atomic on both POSIX
(``rename(2)``) and Windows (``MoveFileEx MOVEFILE_REPLACE_EXISTING``).
Two viewers signing the same scope concurrently is fine: whichever
atomic move lands last wins, both readers see a consistent file
afterwards. There is no cross-process lock; the contract is
last-writer-wins, not exclusive.

Invalidation
------------
:func:`forget` removes the file for one scope. The caller does this
from the chunk-download path when it sees an S3 403 -- the cached URL
was in the map but the object rotated or the token was revoked, so
drop the scope and let the next lookup refetch. Failing to remove the
file is not fatal.

Miss / error semantics
----------------------
:func:`load` returns ``None`` on ANY of: no cache file, unreadable file,
corrupt gzip, invalid JSON, missing timestamp, expired-or-within-buffer.
The caller has no need to distinguish -- every one of them means
"refetch from the server".

:func:`save` swallows every I/O error: a full disk, permission denied
or a race with another process must never break the read that just
succeeded. The in-memory cache still works; the next viewer open pays
one signer call and tries again.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1
DEFAULT_SAFETY_SECONDS = 1800  # 30 min; task-declared floor.
MAX_ESCAPED_SERIES_LEN = 96  # Beyond this we hash the series name.

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

_SAFE_BYTE_RE = re.compile(rb"[A-Za-z0-9._-]")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cache_dir() -> Path:
    """Absolute path to the on-disk cache root.

    Honors ``NDI_SIGNED_URL_CACHE_DIR``; otherwise
    ``~/.ndi/signed-url-cache``. Creates the directory the first time
    it is asked for, with mode 0700 on POSIX so a file that is legibly
    a bearer token is not world-readable.
    """
    override = os.environ.get("NDI_SIGNED_URL_CACHE_DIR", "")
    if override:
        base = Path(override)
    else:
        base = Path.home() / ".ndi" / "signed-url-cache"
    if not base.exists():
        try:
            base.mkdir(parents=True, exist_ok=True)
            _chmod_user_only(base)
        except OSError:
            # Best-effort: BatchSignedUrlLookup treats a missing cache
            # dir as "no disk cache available", so a failure to create
            # here is not fatal to the read.
            pass
    return base


def load(dataset_id: str, document_id: str, series_name: str = "") -> dict[str, Any] | None:
    """Read one scope's cached signed-URL set, or ``None`` on any miss.

    Returns a dict (fields: files, filesExpireAt, expiresAt,
    generatedAt, fileCount) on cache hit. Returns ``None`` on any of:
    no cache file, corrupt file, JSON parse error,
    expired-or-within-safety-buffer.

    The safety buffer is 30 min by default, overridable via
    ``NDI_SIGNED_URL_CACHE_SAFETY_SECONDS``. A URL that would expire
    inside that window is a miss so the caller refetches rather than
    handing bytes to a viewer that then 403s.
    """
    file_path = _cache_path(dataset_id, document_id, series_name)
    if not file_path.is_file():
        return None

    try:
        with gzip.open(file_path, "rb") as fh:
            raw = fh.read()
        body = raw.decode("utf-8")
        data = json.loads(body)
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    files = data.get("files")
    if not isinstance(files, dict):
        return None

    # Enforce the safety-buffer floor against the authoritative server
    # timestamp. A payload with no timestamp is a miss: better to
    # refetch than hand out a URL we can't age-check.
    expiry_str = _read_string(data, "filesExpireAt") or _read_string(data, "expiresAt")
    if not expiry_str:
        return None
    expiry = _parse_iso_utc(expiry_str)
    if expiry is None:
        return None
    remaining = (expiry - _now_utc()).total_seconds()
    if remaining < _safety_seconds():
        return None

    return {
        "files": {str(k): str(v) for k, v in files.items()},
        "filesExpireAt": _read_string(data, "filesExpireAt"),
        "expiresAt": _read_string(data, "expiresAt"),
        "generatedAt": _read_string(data, "generatedAt"),
        "fileCount": _read_int(data, "fileCount", default=len(files)),
    }


def save(
    dataset_id: str,
    document_id: str,
    series_name: str,
    payload: dict[str, Any],
) -> None:
    """Persist a scope's signed-URL set. Best-effort, atomic.

    Writes the payload to the scope's cache path via a temp file +
    :func:`os.replace`. A payload without a ``filesExpireAt`` /
    ``expiresAt`` is NOT written -- the cache cannot age-check
    something it has no timestamp for, and we refuse to invent a TTL.

    Any I/O failure (missing dir, permission denied, disk full,
    another process racing us) is swallowed silently: the in-memory
    cache still works, so the read the caller just finished still
    succeeded.
    """
    if not isinstance(payload, dict):
        return
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        # Empty maps are legal ("scope exists, has zero members") but
        # so is the "endpoint gave us nothing back" case; we cannot
        # tell them apart, so err on the side of not persisting.
        # A caller who wants to persist an empty scope should still be
        # able to next-lookup with no penalty.
        if not isinstance(files, dict):
            return

    files_expire_at = _read_string(payload, "filesExpireAt")
    expires_at = _read_string(payload, "expiresAt")
    if not files_expire_at and not expires_at:
        # Refuse to persist an un-age-checkable payload. This is a
        # CALLER bug, not an environmental issue -- a signer that hands
        # us a payload with neither expiry field means the disk cache
        # will silently stay empty forever, which is exactly how the
        # Waltham-Data-Science/NDI-python#320 first-fresh-machine run
        # spent minutes signing 121k URLs and left no trace to reuse.
        # WARN rather than raise: the surrounding read has already
        # succeeded and we don't want to break it, but the noise is
        # what turns "the cache mysteriously never fills" into "here
        # is the exact scope and the exact reason". Silent on I/O
        # errors (missing dir, permission, disk full) below -- those
        # are legitimate best-effort skips, not callee bugs.
        logger.warning(
            "signed-URL disk cache: refusing to persist scope "
            "(dataset=%s, document=%s, series=%r): payload carries "
            "neither 'filesExpireAt' nor 'expiresAt', so the cache "
            "cannot age-check it. This is a signer bug -- the URL "
            "expiration must be carried on the payload passed to "
            "save(). Cache stays empty for this scope.",
            dataset_id,
            document_id,
            series_name,
        )
        return

    generated_at = _read_string(payload, "generatedAt")
    file_count = _read_int(payload, "fileCount", default=len(files))

    file_path = _cache_path(dataset_id, document_id, series_name)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    body = {
        "schemaVersion": SCHEMA_VERSION,
        "datasetId": str(dataset_id),
        "documentId": str(document_id),
        "seriesName": str(series_name),
        "cachedAt": _iso_now(),
        "filesExpireAt": files_expire_at,
        "expiresAt": expires_at,
        "generatedAt": generated_at,
        "fileCount": int(file_count),
        # dict insertion order maps to JSON key order; digit-prefixed
        # uids are legal JSON object keys, so nothing here renames them.
        "files": {str(k): str(v) for k, v in files.items()},
    }
    try:
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return

    # Per-writer temp path in the SAME directory so os.replace is a
    # rename() rather than a cross-device copy+unlink. The random
    # suffix means two writers on the same scope in the same process
    # don't collide on their own temp file.
    tmp_path = file_path.parent / (file_path.name + f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        with gzip.open(tmp_path, "wb") as gz:
            gz.write(text.encode("utf-8"))
        os.replace(tmp_path, file_path)
    except OSError:
        # Any I/O failure: try to clean up the temp file, then swallow.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def forget(dataset_id: str, document_id: str, series_name: str = "") -> None:
    """Remove one scope's cache file. Best-effort.

    Called from the chunk-download path when an S3 403 says the cached
    URL is no longer valid. If the file is not present -- or the delete
    itself fails -- it is not an error: the next lookup will refetch.
    """
    file_path = _cache_path(dataset_id, document_id, series_name)
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        # Best-effort: a failed delete is not fatal to the caller who
        # is already recovering from a 403.
        pass


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _safety_seconds() -> float:
    """Read the safety buffer, honoring the env-var override."""
    override = os.environ.get("NDI_SIGNED_URL_CACHE_SAFETY_SECONDS", "")
    if override:
        try:
            v = float(override)
            if v >= 0:
                return v
        except ValueError:
            pass
    return DEFAULT_SAFETY_SECONDS


def _cache_path(dataset_id: str, document_id: str, series_name: str) -> Path:
    """The absolute path this (ds, doc, series) scope lands at.

    Empty ``series_name`` maps to a whole-document file so
    ``<doc>.json.gz`` and ``<doc>_<series>.json.gz`` can never collide.
    NDI-matlab uses exactly the same convention.
    """
    base = cache_dir() / str(dataset_id)
    if not series_name:
        return base / f"{document_id}.json.gz"
    escaped = _escape_series_name(str(series_name))
    return base / f"{document_id}_{escaped}.json.gz"


def _escape_series_name(raw: str) -> str:
    """Percent-encode a series name for filesystem safety.

    Any byte outside ``[A-Za-z0-9._-]`` becomes ``%XX`` (uppercase
    hex). Above :data:`MAX_ESCAPED_SERIES_LEN` fall back to
    ``hash-<sha1(raw)>`` so a pathologically long name never overflows
    a filesystem's 255-byte name limit.
    """
    bytes_ = raw.encode("utf-8")
    parts: list[str] = []
    for b in bytes_:
        if _SAFE_BYTE_RE.fullmatch(bytes([b])):
            parts.append(chr(b))
        else:
            parts.append(f"%{b:02X}")
    s = "".join(parts)
    if len(s) > MAX_ESCAPED_SERIES_LEN:
        digest = hashlib.sha1(bytes_, usedforsecurity=False).hexdigest()
        s = f"hash-{digest}"
    return s


def _chmod_user_only(path: Path) -> None:
    """Set the cache root to user-only permissions on POSIX.

    A signed URL is effectively a bearer token for 24 h. Windows
    relies on the default per-user profile ACL for ``~/.ndi/``, which
    is roughly equivalent -- and ``os.chmod`` there is largely a no-op.
    """
    if os.name != "posix":
        return
    try:
        os.chmod(path, stat.S_IRWXU)  # 0o700
    except OSError:
        # Best-effort: an unusual filesystem (SMB mount, WSL under Win)
        # can refuse chmod but still work. The cache should not fail
        # solely because we could not tighten the mode.
        pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now_utc().strftime(_ISO_FMT)


_ISO_FRACTION_RE = re.compile(r"\.\d+")


def _parse_iso_utc(text: str) -> datetime | None:
    """Parse a server-emitted UTC timestamp.

    Handles ``YYYY-MM-DDTHH:MM:SSZ`` and ``YYYY-MM-DDTHH:MM:SS.SSSZ``,
    the two shapes the ``getSignedURLSetJob`` ready-state payload has
    been observed to use. A trailing ``+00:00`` or ``-00:00`` is
    equivalent to ``Z``. Anything else is a parse failure and returns
    ``None``.
    """
    if not text:
        return None
    trimmed = text.strip()
    if trimmed.endswith("Z"):
        trimmed = trimmed[:-1]
    elif trimmed.endswith("+00:00") or trimmed.endswith("-00:00"):
        trimmed = trimmed[:-6]
    trimmed = trimmed.replace(" ", "T")
    # Strip fractional seconds if present -- our own writer does not
    # emit them, but the server sometimes does, and we do not need
    # millisecond precision to age-check a 24 h URL.
    trimmed = _ISO_FRACTION_RE.sub("", trimmed)
    try:
        parsed = datetime.strptime(trimmed, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _read_string(data: dict[str, Any], name: str) -> str:
    """Read a field as a string, "" for missing / null / non-string."""
    value = data.get(name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _read_int(data: dict[str, Any], name: str, *, default: int) -> int:
    """Read a field as an int, ``default`` for missing / non-numeric."""
    value = data.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
