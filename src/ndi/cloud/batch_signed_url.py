"""
ndi.cloud.batch_signed_url - Per-document signed-URL cache.

MATLAB equivalent: +ndi/+cloud/+download/+internal/batchSignedUrlLookup.m

The naive path: getFileDetails once per uid, minting a fresh presigned URL
each time. For an ordinary document that is fine. For a file series with
many members -- 28,000 in the lightsheet-pyramid case that motivates this
(VH-Lab/NDI-matlab#952) -- it is one API round trip per member.

The batch path: submit an async signed-URL-set job (createSignedURLSetJob
-> waitForSignedURLSetJob -> getSignedURLSetResult) that builds the whole
document's uid -> URL map server-side and hands it back in one gzipped
blob. Subsequent uids in the same (dataset, document [, series]) scope
resolve from the cached map without another round trip. The paged
getSignedURLSetAll walk is still supported as an API entry point but the
default signer no longer uses it -- for a 121k-uid document the walk
takes 100+ minutes at ~25 s per 500-uid page (NDI-matlab#952,
NDI-matlab#1009).

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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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

# 500 ms: pause before re-fetching a scope whose first answer was a
# partial map -- the scope was populated, but it did not name the uid the
# caller asked about. On some cloud environments the batch endpoint lags
# briefly behind ``waitForAllBulkUploads``, and the second call names the
# whole set. See Waltham-Data-Science/NDI-python#309.
DEFAULT_PARTIAL_MAP_RETRY_SECONDS = 0.5

# Backoff schedule for :func:`_default_signer` when the batch endpoint call
# raises. One transient TLS or connection error at start of run used to
# mark the scope failed and drop every uid in it to per-member
# getFileDetails -- O(N) API calls on a series that should have cost one.
# Retrying the batch itself keeps the O(1) fast path across residential
# network blips. See Waltham-Data-Science/NDI-python#322 (and the parallel
# VH-Lab/NDI-matlab#1010). Only the default production signer retries;
# a caller-injected signer is left as-is so tests keep control of counts.
DEFAULT_BATCH_RETRY_DELAYS: tuple[float, ...] = (1.0, 4.0, 16.0)


class BatchScopeUnreachable(RuntimeError):
    """The async signed-URL-set job path could not answer for a scope.

    Raised by :func:`_default_signer` after every retry attempt has failed
    -- ``createSignedURLSetJob``, ``waitForSignedURLSetJob`` and
    ``getSignedURLSetResult`` between them have not produced a usable map
    for this (dataset, document, series) scope.

    Why raise rather than return ``(False, ...)`` and let the caller fall
    back to per-member ``getFileDetails``? A napari viewport loads dozens
    of chunks per frame, and per-member fallback for a 100k-member series
    is thousands of API calls per zoom -- unusable UX. Worse, that
    fallback works "well enough" that the underlying bug (the async job
    endpoint returned 404 / timed out / drifted from the schema) stays
    hidden while the viewer feels merely slow. Raising forces the real
    error to the surface so we see and fix it, and never silently ship a
    bad path.

    The partial-map case is separate and does NOT raise: a batch that
    successfully returned a map but did not happen to name a particular
    uid still hits the per-uid fallback in ``fetch_cloud_file``, because
    that is a data-drift case rather than a broken endpoint. Only real
    failures of the async job path raise here.
    """


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
            called (one per scope fetch, plus one per partial-map retry).
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
        partial_map_retries: How many scopes were re-fetched because the
            first answer was populated but did not name a requested uid.
            One retry per scope, ever, whether it settled or not; a caller
            that wants to know "does this scope EVER answer for this uid"
            gets that answer after the retry. See Waltham-Data-Science/
            NDI-python#309.
    """

    signer_calls: int = 0
    uid_hits: int = 0
    uid_misses: int = 0
    last_map_size: int = 0
    last_map_uids: list[str] = field(default_factory=list)
    last_failure_reason: str = ""
    partial_map_retries: int = 0


# Default timeout for the async signed-URL-set job. The server has to sign
# every member and gzip the resulting map, so a 121k-uid document is not a
# short wait -- 15 min gives it room while still surfacing a truly stuck
# job. The batch cache's caller (fetch_cloud_file) falls back per-member if
# the wait times out, so this is a "give up on the fast path" deadline,
# not a "give up on the read" one.
DEFAULT_JOB_TIMEOUT_SECONDS = 15 * 60


# The default signer submits the async job, waits for it to reach 'ready',
# and reads the gzipped result blob. Injected for tests.
def _default_signer(
    dataset_id: str,
    document_id: str,
    *,
    file_series: str = "",
    client: CloudClient | None = None,
    retry_delays: tuple[float, ...] = DEFAULT_BATCH_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
    job_timeout: float = DEFAULT_JOB_TIMEOUT_SECONDS,
) -> tuple[bool, dict[str, Any]]:
    """Fetch the whole scope through the async signed-URL-set-job path.

    Submits a ``createSignedURLSetJob`` for the (dataset, document, series)
    scope, waits for the job to reach state ``"ready"`` (or ``"failed"``,
    or the overall ``job_timeout``), and downloads and parses the gzipped
    result blob. Returns ``(True, answer)`` on success and
    ``(False, {"__error__": ...})`` on any failure -- the batch is
    best-effort and its caller's fallback keeps the read correct.

    Preferred over the paged ``getSignedURLSetAll`` walk: for a document
    with 121k members the walk takes 100+ minutes at ~25 s per 500-uid
    page, whereas the async job builds the whole map server-side and
    returns it in one blob (NDI-matlab#952, NDI-matlab#1009).

    A raise anywhere in ``create -> wait -> read`` is retried with the
    delays in ``retry_delays`` before it is reported as a failure. This is
    what keeps one transient TLS blip on a residential connection from
    cascading to the O(N) per-member fallback: the batch itself gets a few
    more chances at ~20 s of wall clock in the worst case before its
    caller is told the scope is unreachable. See
    Waltham-Data-Science/NDI-python#322.
    """
    from .api import files as files_api

    attempts = len(retry_delays) + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            job = files_api.createSignedURLSetJob(
                dataset_id,
                document_id,
                id_namespace="ndi",
                file_series=file_series,
                client=client,
            )
            job_id = job.get("jobId", "") if hasattr(job, "get") else ""
            if not job_id:
                raise RuntimeError(f"createSignedURLSetJob returned no jobId (payload: {job!r})")

            status = files_api.waitForSignedURLSetJob(
                job_id,
                timeout=job_timeout,
                client=client,
            )
            state = status.get("state", "") if hasattr(status, "get") else ""
            if state == "failed":
                err = status.get("error", "") if hasattr(status, "get") else ""
                raise RuntimeError(
                    f"signed-URL-set job {job_id} failed: {err}"
                    if err
                    else f"signed-URL-set job {job_id} failed"
                )
            if state == "timeout":
                elapsed = (
                    status.get("elapsed", job_timeout) if hasattr(status, "get") else job_timeout
                )
                raise RuntimeError(
                    f"signed-URL-set job {job_id} did not finish within "
                    f"{elapsed:.0f}s (state after wait: {state!r})"
                )
            if state != "ready":
                raise RuntimeError(
                    f"signed-URL-set job {job_id} ended in unexpected state "
                    f"{state!r} (expected 'ready')"
                )

            result_url = status.get("resultUrl", "") if hasattr(status, "get") else ""
            if not result_url:
                raise RuntimeError(
                    f"signed-URL-set job {job_id} was ready but carried no resultUrl"
                )

            answer = files_api.getSignedURLSetResult(result_url)
            return True, answer
        except Exception as exc:  # noqa: BLE001 - reported by BatchScopeUnreachable
            last_exc = exc
            if attempt < attempts - 1:
                delay = retry_delays[attempt]
                logger.info(
                    "batch signed-URL fetch attempt %d/%d for scope "
                    "(%s, %s, series=%r) failed (%s: %s); retrying in %.1fs",
                    attempt + 1,
                    attempts,
                    dataset_id,
                    document_id,
                    file_series,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                sleep(delay)
    # Every attempt raised. Surface the last cause instead of returning
    # (False, ...) -- see BatchScopeUnreachable's docstring for why a
    # silent per-uid fallback would just hide the bug.
    raise BatchScopeUnreachable(
        f"async signed-URL-set job failed for scope "
        f"({dataset_id!r}, {document_id!r}, file_series={file_series!r}) "
        f"after {attempts} attempts. Last cause: "
        f"{type(last_exc).__name__}: {last_exc}"
    ) from last_exc


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
        partial_map_retry_seconds: float = DEFAULT_PARTIAL_MAP_RETRY_SECONDS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._signer = signer or _default_signer
        self._ttl_seconds = ttl_seconds
        self._failure_ttl_seconds = failure_ttl_seconds
        self._partial_map_retry_seconds = partial_map_retry_seconds
        # Injected only for tests: the retry has a real wait, and a test
        # that runs it 20 times should not pay 10 seconds for it.
        self._sleep = sleep or time.sleep
        self._cache: dict[str, _CacheEntry] = {}
        self._failed_scopes: dict[str, _FailureEntry] = {}
        self._retried_scopes: set[str] = set()
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
        client: CloudClient | None = None,
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

            # The scope was fetched but does not name this uid. Two
            # distinct causes: data drift (this file was never in the
            # scope), or a lagged index (the file IS in the scope on the
            # server, but the batch endpoint's map has not caught up yet).
            # Only the second is worth a retry, and this side has no way
            # to distinguish them a priori -- so retry ONCE per scope,
            # sleep briefly first, and if the second answer still does not
            # name the uid, take that as data drift and warn.
            #
            # Bounded and per-scope: a data-drift miss costs one extra
            # signer call for the whole scope, not one per uid. A lagged
            # index that recovers replaces the cache entry for every
            # subsequent uid in the same scope, so a whole series' worth
            # of misses becomes a whole series' worth of hits from one
            # retry. See Waltham-Data-Science/NDI-python#309.
            if cache_key not in self._retried_scopes:
                self._retried_scopes.add(cache_key)
                if self._partial_map_retry_seconds > 0:
                    self._sleep(self._partial_map_retry_seconds)
                # Drop the stale entry so _fetch_scope replaces it fresh.
                self._cache.pop(cache_key, None)
                self._stats.partial_map_retries += 1
                refreshed = self._fetch_scope(
                    cache_key,
                    cloud_dataset_id,
                    ndi_document_id,
                    series_name,
                    uid,
                    client=client,
                )
                if refreshed is None:
                    # _fetch_scope already recorded the miss and warned.
                    # Do not double-count here.
                    return ""
                url = refreshed.files.get(uid, "")
                if url:
                    self._stats.uid_hits += 1
                    return url

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
                partial_map_retries=self._stats.partial_map_retries,
            )

    def clear(self) -> None:
        """Drop every cached scope and reset the counters."""
        with self._lock:
            self._cache.clear()
            self._failed_scopes.clear()
            self._retried_scopes.clear()
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
        client: CloudClient | None,
    ) -> _CacheEntry | None:
        """Populate the cache for one scope. None on any failure.

        :class:`BatchScopeUnreachable` from the signer is NOT caught -- it
        means the async job path itself is broken and per-uid fallback
        would just hide the real error. Every other exception from an
        injected signer is still reported as a miss reason so existing
        tests keep working.
        """
        failure_reason = ""
        try:
            ok, answer = self._signer(
                cloud_dataset_id,
                ndi_document_id,
                file_series=series_name,
                client=client,
            )
        except BatchScopeUnreachable:
            # Real failure of the async signed-URL-set path; propagate so
            # the caller (viewer, download orchestrator, test) sees the
            # cause instead of a slow per-uid walk that hides the bug.
            raise
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
            self._failed_scopes[cache_key] = _FailureEntry(at=time.monotonic(), uid=uid)
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
        why = self._stats.last_failure_reason or ("the batch answered but did not name this uid")
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
    return f"'files' arrived as a {type(answer['files']).__name__}, not a dict"


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
