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
from collections.abc import Callable, Sequence
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

# Exponential backoff for re-fetching a scope whose previous answer was a
# partial map -- the scope was populated, but it did not name the uid the
# caller asked about. On some cloud environments the batch endpoint lags
# briefly behind ``waitForAllBulkUploads``, and a later call names the
# whole set. Three retries at 1 s / 3 s / 9 s cover the User-1-prod tail
# observed on Waltham-Data-Science/NDI-python#320: one 0.5 s retry was not
# enough to bridge the settle between bulk-upload extraction and the
# signed-URL-set index catching up. Each retry costs one signer call for
# the whole scope, not one per uid; once the map settles every subsequent
# uid resolves from the fresh cache entry. See
# Waltham-Data-Science/NDI-python#309 and #320.
DEFAULT_PARTIAL_MAP_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 9.0)

# Deprecated name kept for callers that still pass ``partial_map_retry_seconds``
# explicitly (a single scalar means "one retry after this many seconds").
# New code should use ``partial_map_retry_delays`` instead.
DEFAULT_PARTIAL_MAP_RETRY_SECONDS = DEFAULT_PARTIAL_MAP_RETRY_DELAYS[0]

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
    """A scope's most recent batch failure, with the uid that saw it.

    ``unreachable`` distinguishes a real async-job failure (surfaced as
    :class:`BatchScopeUnreachable`, no per-uid fallback) from an
    injected-signer failure or a partial-map miss (per-uid fallback OK).
    """

    at: float
    uid: str
    unreachable: bool = False
    cause: str = ""


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
    scope_started = time.monotonic()
    for attempt in range(attempts):
        try:
            logger.info(
                "batch signed-URL job: submitting createSignedURLSetJob for scope "
                "(%s, %s, series=%r) attempt %d/%d",
                dataset_id,
                document_id,
                file_series,
                attempt + 1,
                attempts,
            )
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
            logger.info(
                "batch signed-URL job: submitted jobId=%s, waiting for terminal state "
                "(timeout %.0fs)",
                job_id,
                job_timeout,
            )

            status = files_api.waitForSignedURLSetJob(
                job_id,
                timeout=job_timeout,
                client=client,
            )
            state = status.get("state", "") if hasattr(status, "get") else ""
            logger.info(
                "batch signed-URL job: jobId=%s reached state=%r after %.1fs total",
                job_id,
                state,
                time.monotonic() - scope_started,
            )
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
            logger.info(
                "batch signed-URL job: jobId=%s ready, fetching result blob",
                job_id,
            )

            answer = files_api.getSignedURLSetResult(result_url)
            # Carry the URL-expiration fields over from the JOB STATUS
            # into the RESULT payload. The status is the only place the
            # server puts filesExpireAt / expiresAt; the result blob
            # itself does not include them (see getSignedURLSetResult's
            # docstring for the blob shape). Without this merge the
            # disk cache's save() correctly refuses to persist a
            # payload it cannot age-check, and the on-disk cache stays
            # empty even after a full successful signing -- exactly
            # what we saw on the first fresh-machine run. Non-string /
            # missing values are dropped so an accidental None does
            # not overwrite a good value we might learn to fill in
            # elsewhere later.
            if isinstance(answer, dict):
                for expiry_key in ("filesExpireAt", "expiresAt"):
                    value = status.get(expiry_key, "") if hasattr(status, "get") else ""
                    if isinstance(value, str) and value and expiry_key not in answer:
                        answer[expiry_key] = value
            n_files = 0
            if isinstance(answer, dict) and isinstance(answer.get("files"), dict):
                n_files = len(answer["files"])
            logger.info(
                "batch signed-URL job: jobId=%s delivered %d uid->URL entries "
                "for scope (%s, %s, series=%r) in %.1fs total",
                job_id,
                n_files,
                dataset_id,
                document_id,
                file_series,
                time.monotonic() - scope_started,
            )
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
        partial_map_retry_delays: tuple[float, ...] | None = None,
        partial_map_retry_seconds: float | None = None,
        sleep: Callable[[float], None] | None = None,
        disk_cache: bool = False,
    ) -> None:
        self._signer = signer or _default_signer
        self._ttl_seconds = ttl_seconds
        self._failure_ttl_seconds = failure_ttl_seconds
        # partial_map_retry_seconds (scalar, deprecated) reduces to a
        # one-element schedule, kept for callers/tests that pin the old
        # single-retry contract. The scalar names the WAIT before the
        # single retry, so ``0`` still fires one retry (with no wait),
        # matching the pre-schedule behavior.
        if partial_map_retry_delays is not None:
            self._partial_map_retry_delays: tuple[float, ...] = tuple(partial_map_retry_delays)
        elif partial_map_retry_seconds is not None:
            self._partial_map_retry_delays = (partial_map_retry_seconds,)
        else:
            self._partial_map_retry_delays = DEFAULT_PARTIAL_MAP_RETRY_DELAYS
        # Injected only for tests: the retry has a real wait, and a test
        # that runs it 20 times should not pay 10 seconds for it.
        self._sleep = sleep or time.sleep
        # Disk cache off by default: a scripted signer in a test suite
        # would otherwise persist fake URLs to ~/.ndi/signed-url-cache
        # and hit them on the next test's first lookup. Production
        # callers (the DID chunk-download path) turn it on explicitly
        # via ``get_default()``, which is where reopens actually pay.
        # See :mod:`ndi.cloud.signed_url_disk_cache`.
        self._disk_cache = disk_cache
        self._cache: dict[str, _CacheEntry] = {}
        self._failed_scopes: dict[str, _FailureEntry] = {}
        # Per-scope count of partial-map retries already spent. Bounded
        # by ``len(self._partial_map_retry_delays)``: once exhausted, a
        # subsequent uid miss on the scope surfaces as a data-drift miss
        # without another signer call.
        self._scope_retry_attempts: dict[str, int] = {}
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

            if entry is None and self._disk_cache:
                # Consult the on-disk cache before running the async
                # signed-URL-set job. On hit, populate the in-memory
                # cache so every uid in the scope resolves without
                # another disk read. On miss (no file, corrupt file,
                # expired-or-within-safety-buffer), fall through to the
                # signer as before.
                entry = self._try_disk_cache(
                    cache_key, cloud_dataset_id, ndi_document_id, series_name
                )

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
                    elif failure.unreachable:
                        # The async job path was strict-mode-failed for
                        # this scope within the TTL. Re-raise fast rather
                        # than running another 4-attempt retry cycle for
                        # every next uid the viewport asks about. The
                        # cause carried on the entry preserves what the
                        # first raise said.
                        raise BatchScopeUnreachable(
                            f"scope {cache_key!r} was unreachable "
                            f"{now - failure.at:.1f}s ago: {failure.cause}"
                        )
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
            # to distinguish them a priori -- so retry with a bounded
            # exponential-backoff schedule (default 1 s / 3 s / 9 s),
            # sleep between attempts, and if the last answer still does
            # not name the uid, take that as data drift and warn.
            #
            # Bounded and per-scope: a data-drift miss costs at most
            # len(delays) extra signer calls for the whole scope, not
            # one per uid. A lagged index that recovers replaces the
            # cache entry for every subsequent uid in the same scope,
            # so a whole series' worth of misses becomes a whole
            # series' worth of hits from one retry. Three waves cover
            # the User-1-prod tail after ``waitForAllBulkUploads``
            # returns; on a User-2-prod-shaped environment the first
            # retry lands and the rest never fire. See
            # Waltham-Data-Science/NDI-python#309 and #320.
            attempts_spent = self._scope_retry_attempts.get(cache_key, 0)
            while attempts_spent < len(self._partial_map_retry_delays):
                delay = self._partial_map_retry_delays[attempts_spent]
                if delay > 0:
                    self._sleep(delay)
                # Drop the stale entry so _fetch_scope replaces it fresh.
                self._cache.pop(cache_key, None)
                self._stats.partial_map_retries += 1
                attempts_spent += 1
                self._scope_retry_attempts[cache_key] = attempts_spent
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
            self._scope_retry_attempts.clear()
            self._warned.clear()
            self._stats = Stats()

    def prefetch_scope(
        self,
        cloud_dataset_id: str,
        ndi_document_id: str,
        series_name: str,
        *,
        client: CloudClient | None = None,
    ) -> bool:
        """Populate the cache for one scope without asking about a specific uid.

        Seeds the cache so a subsequent :meth:`lookup` on any uid in the
        scope resolves without another signer call. Safe to call from a
        background thread; the same lock that guards :meth:`lookup`
        serialises the fetch so a concurrent lookup on the same scope
        does not stampede the endpoint.

        The partial-map retry is NOT run here on purpose: prefetch's
        job is to seed the cache, and the retry only helps when a
        specific uid is expected to be present. If the map that arrives
        is partial, the first lookup that misses will drive its own
        retry through the existing bounded schedule.

        Args:
            cloud_dataset_id: The dataset id.
            ndi_document_id: The NDI document id. Empty returns False
                immediately: nothing to batch against.
            series_name: ``""`` for a whole-document scope, or a file
                series name to scope the batch.
            client: Passed to the signer (default signer only).

        Returns:
            True when a cache entry now exists for the scope (either
            just populated, or already fresh); False otherwise.
        """
        if not ndi_document_id:
            return False

        cache_key = f"{cloud_dataset_id}/{ndi_document_id}/{series_name}"
        now = time.monotonic()

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None and (now - entry.fetched_at) < self._ttl_seconds:
                return True
            # Drop stale entry so _fetch_scope replaces it.
            if entry is not None:
                del self._cache[cache_key]

            # Consult the on-disk cache before running the async signed-
            # URL-set job -- the whole point of the disk cache is that
            # a scope warmed by a previous process should not have to
            # re-sign 100k URLs at every viewer launch. Mirrors what
            # ``lookup`` does. ``_try_disk_cache`` filters entries whose
            # URLs would expire within the safety buffer, so a hit here
            # is safe to hand to callers. See
            # :mod:`ndi.cloud.signed_url_disk_cache`.
            if self._disk_cache:
                entry = self._try_disk_cache(
                    cache_key, cloud_dataset_id, ndi_document_id, series_name
                )
                if entry is not None:
                    return True

            entry = self._fetch_scope(
                cache_key,
                cloud_dataset_id,
                ndi_document_id,
                series_name,
                uid="",
                client=client,
            )
            return entry is not None

    def start_prefetch(
        self,
        scopes: Sequence[tuple[str, str, str]],
        *,
        client: CloudClient | None = None,
    ) -> threading.Thread:
        """Spawn a daemon thread that prefetches ``scopes`` in order.

        Each scope is ``(cloud_dataset_id, ndi_document_id, series_name)``.
        Scopes with an empty ``ndi_document_id`` are skipped (nothing to
        batch against). A :class:`BatchScopeUnreachable` from one scope
        is logged and the thread continues with the next -- the point
        of prefetch is to warm the cache best-effort, not to fail loud.

        Returns the started thread so tests can join it; production
        callers can fire and forget.
        """
        scopes_list = list(scopes)

        def _run() -> None:
            logger.info(
                "signed-URL prefetch: warming %d scope(s) in background",
                len(scopes_list),
            )
            for cloud_dataset_id, ndi_document_id, series_name in scopes_list:
                if not ndi_document_id:
                    logger.info(
                        "signed-URL prefetch: skipping scope "
                        "(%s, <empty doc id>, series=%r) -- nothing to batch against",
                        cloud_dataset_id,
                        series_name,
                    )
                    continue
                started = time.monotonic()
                try:
                    ok = self.prefetch_scope(
                        cloud_dataset_id,
                        ndi_document_id,
                        series_name,
                        client=client,
                    )
                except BatchScopeUnreachable as exc:
                    logger.warning(
                        "signed-URL prefetch: scope (%s, %s, series=%r) unreachable "
                        "after %.1fs: %s -- continuing with the next scope",
                        cloud_dataset_id,
                        ndi_document_id,
                        series_name,
                        time.monotonic() - started,
                        exc,
                    )
                    continue
                logger.info(
                    "signed-URL prefetch: scope (%s, %s, series=%r) %s in %.1fs",
                    cloud_dataset_id,
                    ndi_document_id,
                    series_name,
                    "cached" if ok else "failed",
                    time.monotonic() - started,
                )

        thread = threading.Thread(
            target=_run,
            name="ndi-signed-url-prefetch",
            daemon=True,
        )
        thread.start()
        return thread

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
        except BatchScopeUnreachable as exc:
            # Real failure of the async signed-URL-set path. Record the
            # scope as unreachable so subsequent lookups in the same scope
            # fast-fail (re-raising a fresh BatchScopeUnreachable) instead
            # of running another full retry cycle every time napari asks
            # for a chunk. Then propagate so the caller sees the cause.
            self._stats.last_failure_reason = f"async job path unreachable: {exc}"
            self._stats.uid_misses += 1
            self._failed_scopes[cache_key] = _FailureEntry(
                at=time.monotonic(),
                uid=uid,
                unreachable=True,
                cause=str(exc),
            )
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

        # Persist to disk when the caller has opted in AND the payload
        # carries a server-signed expiry we can age-check off of. A
        # payload with neither filesExpireAt nor expiresAt is not
        # cacheable -- the disk cache refuses to invent a TTL, on
        # purpose (see :func:`signed_url_disk_cache.save`). Best-effort:
        # any I/O failure is swallowed so a full disk does not break a
        # read that just succeeded.
        if self._disk_cache:
            try:
                from . import signed_url_disk_cache

                signed_url_disk_cache.save(cloud_dataset_id, ndi_document_id, series_name, answer)
            except Exception:  # noqa: BLE001 - best-effort
                logger.debug(
                    "signed-URL disk cache save raised for scope %r; ignored",
                    cache_key,
                    exc_info=True,
                )
        return entry

    def _try_disk_cache(
        self,
        cache_key: str,
        cloud_dataset_id: str,
        ndi_document_id: str,
        series_name: str,
    ) -> _CacheEntry | None:
        """Load one scope from the on-disk cache, or return None.

        Populates the in-memory cache on hit so subsequent uids in the
        same scope don't re-read the file. A miss is silent -- the
        caller falls through to the signer, which is the shape a fresh
        or expired-cache first open takes.
        """
        try:
            from . import signed_url_disk_cache

            disk = signed_url_disk_cache.load(cloud_dataset_id, ndi_document_id, series_name)
        except Exception:  # noqa: BLE001 - never fail a read on disk I/O
            logger.debug(
                "signed-URL disk cache load raised for scope %r; ignored",
                cache_key,
                exc_info=True,
            )
            return None
        if not disk:
            return None
        files = disk.get("files")
        if not isinstance(files, dict) or not files:
            return None
        entry = _CacheEntry(files=dict(files), fetched_at=time.monotonic())
        self._cache[cache_key] = entry
        self._stats.last_map_size = len(entry.files)
        self._stats.last_map_uids = list(entry.files.keys())
        logger.info(
            "signed-URL disk cache: served scope (%s, %s, series=%r) "
            "with %d uids -- signer not called",
            cloud_dataset_id,
            ndi_document_id,
            series_name,
            len(entry.files),
        )
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
    """The process-wide default cache. Created on first use.

    Constructed with the on-disk cache enabled: this is the production
    reopen path. A scientist reopening the same lightsheet the next
    morning must not pay the ~85 min signed-URL-set job again -- the
    first open persists the scope to ``~/.ndi/signed-url-cache/`` (or
    wherever ``NDI_SIGNED_URL_CACHE_DIR`` points), the reopen reads it
    back and never touches the signer. See
    :mod:`ndi.cloud.signed_url_disk_cache`.

    Tests inject their own :class:`BatchSignedUrlLookup` -- disk cache
    off by default there -- so scripted-signer suites don't persist
    fake URLs into the user's real cache directory.
    """
    global _DEFAULT_LOOKUP
    if _DEFAULT_LOOKUP is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_LOOKUP is None:
                _DEFAULT_LOOKUP = BatchSignedUrlLookup(disk_cache=True)
    return _DEFAULT_LOOKUP


def set_default(lookup: BatchSignedUrlLookup | None) -> None:
    """Replace (or clear) the process-wide default. Test seam."""
    global _DEFAULT_LOOKUP
    with _DEFAULT_LOCK:
        _DEFAULT_LOOKUP = lookup
