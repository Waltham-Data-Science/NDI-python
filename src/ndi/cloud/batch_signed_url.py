"""
ndi.cloud.batch_signed_url - Per-document signed-URL cache.

MATLAB equivalent: +ndi/+cloud/+download/+internal/batchSignedUrlLookup.m

The naive path: getFileDetails once per uid, minting a fresh presigned URL
each time. For an ordinary document that is fine. For a file series with
many members -- 28,000 in the lightsheet-pyramid case that motivates this
(VH-Lab/NDI-matlab#952) -- it is one API round trip per member.

The batch path: one call to /signed-url-set (walked with getSignedURLSetAll)
returns the whole document's uid -> URL map. Subsequent uids in the same
(dataset, document [, series]) scope resolve from the cached map without
another round trip.

Empty return values are legitimate answers, not errors: the batch call may
fail (network, auth, timeout) or the map it returns may not name this uid
(data drift). The caller falls back to getFileDetails in either case. The
batch is an optimisation, not an authority. See NDI-python#262 and
NDI-matlab#968.
"""

from __future__ import annotations

import logging
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .client import CloudClient

logger = logging.getLogger(__name__)


# 20 hours: the server currently signs URLs for 24 h; keep a buffer so a
# cached scope is not handed back to a caller whose S3 GET would refuse it.
DEFAULT_TTL_SECONDS = 20 * 3600

# 60 seconds: a scope that just failed is not retried per uid for the rest
# of a sweep. Short-lived because the point is to stop hammering within one
# sweep, not to give up on the scope -- see the same reasoning in the
# MATLAB counterpart's testFailingSignerReturnsEmpty.
DEFAULT_FAILURE_TTL_SECONDS = 60


@dataclass
class _CacheEntry:
    """One cached scope: uid -> URL, and when we fetched it."""

    files: dict[str, str]
    fetched_at: float  # time.monotonic()


@dataclass
class _FailureEntry:
    """A scope's most recent batch failure, with the uid that saw it."""

    at: float
    uid: str


@dataclass
class Stats:
    """Cumulative counters, exposed to make the fallback VISIBLE.

    A test of the batch path that silently falls back to N per-uid calls
    still passes, having proved nothing about the path it was written for.
    These counters are what turn "the bytes arrived" into "the batch answered
    for this uid" or "the batch could not, so we fell back". See
    NDI-matlab#968 for the same reasoning on the MATLAB side.

    Fields:
        signer_calls: How many times the batch endpoint was actually
            called (one per scope fetch).
        uid_hits: uids answered from a batch map.
        uid_misses: uids the batch could NOT answer, each of which sends
            the caller to the per-uid getFileDetails fallback.
        last_map_size: Entries in the most recent batch map. Names whether
            a scope was honored: a series-scoped answer names the series'
            members, an unscoped one also names every other file the
            document has.
        last_map_uids: Those entries' uids, for the same reason.
        last_failure_reason: Why the last batch attempt did not produce a
            usable map. Four unrelated causes end there; reporting them as
            one silent miss leaves the endpoint owner with nothing to act
            on. See NDI-matlab#968.
    """

    signer_calls: int = 0
    uid_hits: int = 0
    uid_misses: int = 0
    last_map_size: int = 0
    last_map_uids: list[str] = field(default_factory=list)
    last_failure_reason: str = ""


# The default signer walks every page. Injected for tests.
def _default_signer(
    dataset_id: str,
    document_id: str,
    *,
    file_series: str = "",
    client: "CloudClient | None" = None,
) -> tuple[bool, dict[str, Any]]:
    """Fetch the whole scope through the paged getSignedURLSetAll call.

    Returns ``(True, answer)`` on success, ``(False, {})`` on any failure --
    the batch is best-effort and its caller's fallback is what keeps the
    read correct.
    """
    from .api import files as files_api

    try:
        answer = files_api.getSignedURLSetAll(
            dataset_id,
            document_id,
            id_namespace="ndi",
            file_series=file_series,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 - reported as a miss reason
        return False, {"__error__": f"{type(exc).__name__}: {exc}"}
    return True, answer


class BatchSignedUrlLookup:
    """A per-process (dataset, document, series) -> uid map cache.

    Instantiated once and shared -- there is a module-level default in
    :func:`get_default`. Tests use their own instance to keep state from
    leaking, and inject a signer for the same reason.

    Callers who lack a document id (a 2-arg handler, or one that never got a
    context) get ``""`` back without touching the cache: nothing was asked
    of the batch, so nothing failed. That is also the call a test uses to
    read the counters without touching state.
    """

    def __init__(
        self,
        *,
        signer: Callable[..., tuple[bool, dict[str, Any]]] | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        failure_ttl_seconds: float = DEFAULT_FAILURE_TTL_SECONDS,
    ) -> None:
        self._signer = signer or _default_signer
        self._ttl_seconds = ttl_seconds
        self._failure_ttl_seconds = failure_ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._failed_scopes: dict[str, _FailureEntry] = {}
        self._warned: set[str] = set()
        self._stats = Stats()
        # A batch fetch is IO-bound and slow, and download handlers can be
        # called from multiple threads (DID's parallel add / open, or a
        # caller's own thread pool). A lock keeps concurrent misses on the
        # same scope from stampeding the endpoint.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        cloud_dataset_id: str,
        ndi_document_id: str,
        series_name: str,
        uid: str,
        *,
        client: "CloudClient | None" = None,
    ) -> str:
        """Return the pre-signed URL for one uid, or ``""`` if none.

        Args:
            cloud_dataset_id: The dataset id.
            ndi_document_id: The NDI document id (``data.base.id``). When
                empty, the lookup is bypassed -- there is nothing to batch
                against.
            series_name: ``""`` for a whole-document scope, or a file-series
                name to scope the batch to that series only.
            uid: The file uid to resolve.
            client: Passed to the signer (default signer only).
        """
        if not ndi_document_id:
            return ""

        cache_key = f"{cloud_dataset_id}/{ndi_document_id}/{series_name}"
        now = time.monotonic()

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None and (now - entry.fetched_at) >= self._ttl_seconds:
                # Stale; drop and refetch.
                del self._cache[cache_key]
                entry = None

            if entry is None:
                # A scope that just failed is not retried for every uid
                # after it. Without this, a batch endpoint that cannot
                # answer costs one FAILED call per uid on top of the per-uid
                # getFileDetails fallback -- so a 28,000-member series makes
                # 56,000 calls where the naive path would have made 28,000.
                #
                # Narrow: it suppresses the NEXT uid in the sweep, not a
                # retry of THIS one. A caller re-asking for the same uid is
                # retrying on purpose and gets a fresh attempt.
                failure = self._failed_scopes.get(cache_key)
                if failure is not None:
                    if (now - failure.at) >= self._failure_ttl_seconds:
                        del self._failed_scopes[cache_key]
                    elif failure.uid != uid:
                        self._stats.uid_misses += 1
                        self._warn_once(cache_key)
                        return ""
                    else:
                        del self._failed_scopes[cache_key]

                entry = self._fetch_scope(
                    cache_key,
                    cloud_dataset_id,
                    ndi_document_id,
                    series_name,
                    uid,
                    client=client,
                )
                if entry is None:
                    return ""

            url = entry.files.get(uid, "")
            if url:
                self._stats.uid_hits += 1
                return url

            # The scope was fetched but does not name this uid -- data
            # drift, or a scope that does not cover the file. The caller
            # falls back per uid.
            self._stats.uid_misses += 1
            self._warn_once(cache_key)
            return ""

    def stats(self) -> Stats:
        """A snapshot of the counters. Read without disturbing the cache."""
        with self._lock:
            return Stats(
                signer_calls=self._stats.signer_calls,
                uid_hits=self._stats.uid_hits,
                uid_misses=self._stats.uid_misses,
                last_map_size=self._stats.last_map_size,
                last_map_uids=list(self._stats.last_map_uids),
                last_failure_reason=self._stats.last_failure_reason,
            )

    def clear(self) -> None:
        """Drop every cached scope and reset the counters."""
        with self._lock:
            self._cache.clear()
            self._failed_scopes.clear()
            self._warned.clear()
            self._stats = Stats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_scope(
        self,
        cache_key: str,
        cloud_dataset_id: str,
        ndi_document_id: str,
        series_name: str,
        uid: str,
        *,
        client: "CloudClient | None",
    ) -> _CacheEntry | None:
        """Populate the cache for one scope. None on any failure."""
        failure_reason = ""
        try:
            ok, answer = self._signer(
                cloud_dataset_id,
                ndi_document_id,
                file_series=series_name,
                client=client,
            )
        except Exception as exc:  # noqa: BLE001 - reported as a miss reason
            ok = False
            answer = {}
            failure_reason = f"the call raised {type(exc).__name__}: {exc}"

        self._stats.signer_calls += 1

        files: dict[str, str] = {}
        if ok and isinstance(answer, dict) and isinstance(answer.get("files"), dict):
            files = answer["files"]

        if not ok or not files:
            # SAY WHICH cause. Four unrelated ones end here -- the call
            # raised, the signer reported failure, the payload had no files
            # field, the files field was the wrong type -- and one silent
            # miss leaves the endpoint owner with nothing to act on.
            if not failure_reason:
                failure_reason = _describe_failure(ok, answer)
            self._stats.last_failure_reason = failure_reason
            self._stats.uid_misses += 1
            self._failed_scopes[cache_key] = _FailureEntry(
                at=time.monotonic(), uid=uid
            )
            self._warn_once(cache_key)
            return None

        entry = _CacheEntry(files=dict(files), fetched_at=time.monotonic())
        self._cache[cache_key] = entry
        self._stats.last_map_size = len(entry.files)
        self._stats.last_map_uids = list(entry.files.keys())
        return entry

    def _warn_once(self, cache_key: str) -> None:
        """Once per scope, warn that a fallback happened; then stay quiet.

        The fallback is correct -- the bytes still arrive -- so nothing
        fails and nothing is logged, and that is the problem. Reading a
        10,000-member series then costs 10,000 presign calls instead of
        one, and what the user sees is not an error but NDI being slow.
        A single line naming the scope turns "this is slow" into "this
        fell back, and here is where". Once per scope, not once per uid:
        the case worth warning about is exactly the one that would
        otherwise print 10,000 times. See NDI-matlab#968.
        """
        if cache_key in self._warned:
            return
        self._warned.add(cache_key)
        why = self._stats.last_failure_reason or (
            "the batch answered but did not name this uid"
        )
        message = (
            f'The batch signed-URL lookup did not answer for scope "{cache_key}", '
            "so files there are being resolved one API call at a time. This "
            "still works, but for a large file series it is one call per "
            f"member rather than one per series. Cause: {why}. Reported once "
            "per scope."
        )
        warnings.warn(message, stacklevel=3)
        logger.info("%s", message)


def _describe_failure(ok: bool, answer: Any) -> str:
    """Name the specific cause, so a report is actionable."""
    if not ok:
        if isinstance(answer, dict):
            err = answer.get("__error__")
            if err:
                return f"the call raised {err}"
            msg = answer.get("message") or answer.get("state")
            if msg:
                return f"the call reported failure: {msg}"
        return "the call reported failure"
    if not isinstance(answer, dict):
        return f"the payload was a {type(answer).__name__}, not a dict"
    if "files" not in answer:
        fields = ", ".join(str(k) for k in answer.keys())
        return f"the payload has no 'files' field; fields present: {fields}"
    return (
        f"'files' arrived as a {type(answer['files']).__name__}, not a dict"
    )


# ---------------------------------------------------------------------------
# Module-level default instance
#
# One cache per process, shared across every caller that does not pass its
# own. Tests instantiate their own to keep state from leaking between them.
# ---------------------------------------------------------------------------

_DEFAULT_LOOKUP: BatchSignedUrlLookup | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default() -> BatchSignedUrlLookup:
    """The process-wide default cache. Created on first use."""
    global _DEFAULT_LOOKUP
    if _DEFAULT_LOOKUP is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_LOOKUP is None:
                _DEFAULT_LOOKUP = BatchSignedUrlLookup()
    return _DEFAULT_LOOKUP


def set_default(lookup: BatchSignedUrlLookup | None) -> None:
    """Replace (or clear) the process-wide default. Test seam."""
    global _DEFAULT_LOOKUP
    with _DEFAULT_LOCK:
        _DEFAULT_LOOKUP = lookup
