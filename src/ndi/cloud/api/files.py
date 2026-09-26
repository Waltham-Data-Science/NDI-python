"""
ndi.cloud.api.files - File transfer via presigned URLs.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+files/*.m,
    +implementation/+files/*.m
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ._validators import (
    VALIDATE_CONFIG,
    CloudId,
    FilePath,
    NonEmptyStr,
    assert_safe_transfer_url,
)

_Client = Annotated[CloudClient | None, SkipValidation()]

# Terminal job states reported by the bulk-upload service.
_TERMINAL_BULK_STATES = ("complete", "failed")
_ACTIVE_BULK_STATES = ("queued", "extracting")

# Terminal job states reported by the file-tier service. 'superseded' is
# unique to file-tier: a later job for the same file has taken over, so
# polling on is pointless. See ndi-cloud-node/manuals/file-tier-design.md.
_TERMINAL_FILE_TIER_STATES = ("completed", "failed", "superseded")

# Target tiers accepted by the server. PSEUDO_COLD is a non-production
# server-side test target that skips S3 entirely; it is not exposed here as
# a normal option but is accepted at the wire level for callers who need it
# in test environments. See ndi-cloud-node/manuals/file-tier-design.md.
FileTier = Literal[
    "STANDARD",
    "STANDARD_IA",
    "GLACIER_IR",
    "GLACIER",
    "DEEP_ARCHIVE",
]


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getFileUploadURL(
    org_id: NonEmptyStr,
    dataset_id: CloudId,
    file_uid: NonEmptyStr,
    *,
    client: _Client = None,
) -> str:
    """GET /datasets/{organizationId}/{datasetId}/files/{file_uid}

    Returns a presigned S3 URL for uploading.
    """
    result = client.get(
        "/datasets/{organizationId}/{datasetId}/files/{file_uid}",
        organizationId=org_id,
        datasetId=dataset_id,
        file_uid=file_uid,
    )
    return result.get("url", "")


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getBulkUploadURL(
    org_id: NonEmptyStr,
    dataset_id: CloudId,
    *,
    client: _Client = None,
) -> str:
    """POST /datasets/{organizationId}/{datasetId}/files/bulk

    Returns a presigned S3 URL for bulk file upload.
    """
    result = client.post(
        "/datasets/{organizationId}/{datasetId}/files/bulk",
        organizationId=org_id,
        datasetId=dataset_id,
    )
    return result.get("url", "")


@validate_call
def putFiles(
    url: NonEmptyStr,
    file_path: FilePath,
    timeout: int = 120,
    *,
    job_id: str = "",
    wait_for_completion: bool = False,
    completion_timeout: float = 60.0,
) -> bool:
    """PUT a local file to a presigned S3 URL.

    Args:
        url: Presigned URL.
        file_path: Path to file on disk.
        timeout: Per-request timeout in seconds for the PUT.
        job_id: Bulk-upload job identifier returned by
            :func:`getFileCollectionUploadURL`.  Only meaningful for
            bulk (zip) uploads; ignored for single-file uploads.
        wait_for_completion: If True, after a successful PUT the
            function polls :func:`waitForBulkUpload` and only returns
            once the server has finished extracting the zip (or the
            timeout is hit).  Requires a non-empty ``job_id``.
            Single-file uploads have no server-side job to wait on;
            the signed PUT returning 200 already means done.
        completion_timeout: Overall wait-for-completion deadline, in
            seconds.  Default 60.

    Returns:
        True on success (and, when ``wait_for_completion`` is True, the
        server-side bulk extraction job reached state ``'complete'``).

    Raises:
        CloudUploadError: On failure.

    MATLAB equivalent: +cloud/+api/+files/putFiles.m
    """
    import requests

    from ..exceptions import CloudUploadError

    assert_safe_transfer_url(url, what="upload URL")
    file_path = Path(file_path)
    with open(file_path, "rb") as fh:
        resp = requests.put(
            url,
            data=fh,
            headers={"Content-Type": "application/octet-stream"},
            timeout=timeout,
        )

    if resp.status_code != 200:
        raise CloudUploadError(f"File upload failed (HTTP {resp.status_code}): {resp.text}")

    if wait_for_completion:
        if not job_id:
            # Single-file upload: nothing server-side to wait on.
            return True
        final = waitForBulkUpload(job_id, timeout=completion_timeout)
        state = final.get("state", "") if hasattr(final, "get") else ""
        return state == "complete"

    return True


@validate_call
def putFileBytes(
    url: NonEmptyStr,
    data: bytes,
    timeout: int = 120,
) -> bool:
    """PUT raw bytes to a presigned S3 URL.

    Args:
        url: Presigned URL.
        data: Bytes to upload.
        timeout: Request timeout in seconds.

    Returns:
        True on success.

    Raises:
        CloudUploadError: On failure.
    """
    import requests

    from ..exceptions import CloudUploadError

    assert_safe_transfer_url(url, what="upload URL")
    resp = requests.put(
        url,
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        timeout=timeout,
    )

    if resp.status_code == 200:
        return True
    raise CloudUploadError(f"Bytes upload failed (HTTP {resp.status_code}): {resp.text}")


@validate_call
def _download_session():
    """Return the module-level ``requests.Session`` used for downloads.

    A single Session lets ``requests`` reuse the underlying HTTPS
    connection across sibling ``getFile`` calls. Every tile of a
    pyramid goes to the same S3 host, so a shared Session amortises
    the TLS handshake (~100-500ms) across N chunks. Thread-safe for
    GET; the default pool holds 10 connections which is comfortable
    for the lightsheet fetcher's 8 workers.

    A previous version opened a fresh connection per call
    (``requests.get(url, ...)``) which added handshake latency to
    every tile. See NDI-python#$(TBD).
    """
    import requests

    session = getattr(_download_session, "_session", None)
    if session is None:
        session = requests.Session()
        _download_session._session = session
    return session


def getFile(
    url: NonEmptyStr,
    target_path: str | Path,
    timeout: int = 120,
    *,
    progress=None,
) -> bool:
    """Download a file from a presigned URL.

    ``target_path`` is overwritten if it already exists, without warning and
    without a backup. Callers that must not clobber an existing file have to
    check for it themselves.

    ``progress``, if given, is called as ``progress(done, total)`` after each
    chunk, in bytes; *total* is the ``Content-Length`` the server sent, or
    None when it sent none. It is keyword-only so it cannot be mistaken for
    ``timeout``, and it is called from whichever thread is downloading --
    a caller that renders it is responsible for its own locking.

    WHY HERE. This is the one place every on-demand fetch passes through:
    the cell table, the contour file, the gene list and every pyramid tile
    all arrive by fetch_cloud_file -> getFile. Reporting anywhere else
    would cover some of the wait and not the rest.

    MATLAB equivalent: +cloud/+api/+files/getFile.m
    """
    import logging

    logger = logging.getLogger(__name__)

    assert_safe_transfer_url(url, what="download URL")
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # 256 KiB chunk_size (was 8 KiB). Python iterates once per chunk, and
    # every iteration is a socket read + a progress() callback + GIL
    # contention. 8 KiB meant ~500 iterations per 4 MB tile which caps
    # single-stream throughput well below what the link can actually push;
    # 256 KiB drops that to ~16 iterations and lets the TCP buffer stay
    # full. A larger buffer costs a little peak memory (256 KiB per
    # concurrent download) and gives up nothing.
    resp = _download_session().get(url, timeout=timeout, stream=True)
    if resp.status_code == 200:
        total = None
        if progress is not None:
            # Absent on a chunked response, and a caller must cope with that
            # rather than the bar guessing a denominator.
            try:
                total = int(resp.headers.get("Content-Length", "") or 0) or None
            except (TypeError, ValueError):
                total = None
        done = 0
        with open(target_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=262144):
                fh.write(chunk)
                if progress is not None:
                    done += len(chunk)
                    # A reporting callback must never cost the download.
                    try:
                        progress(done, total)
                    except Exception:  # noqa: BLE001
                        progress = None
        return True

    # Log the failure with S3 error details when available
    body = ""
    try:
        body = resp.text[:500]
    except Exception:
        pass
    logger.warning(
        "File download failed (HTTP %d) from %s: %s",
        resp.status_code,
        url[:80],
        body[:200],
    )
    return False


# ---------------------------------------------------------------------------
# File listing (keyset / cursor pagination)
#
# GET /datasets/{datasetId}/files is keyset-paginated: a `limit` and an opaque
# `after` cursor go in, and an envelope comes out --
#   {datasetId, limit, count, cursor, hasMore, totalNumber, files: [...]}
# where each file summary carries uid, uploaded, sourceDatasetId, size. Follow
# the cursor by passing the returned `cursor` back as `after` while `hasMore`
# is true; listFilesAll does that walk.
#
# getDataset NO LONGER embeds the files array (it returns fileCount instead),
# so this endpoint is the only way to enumerate a dataset's files. Callers
# that used to read dataset["files"] must list here or use fileCount for a
# count. See NDI-matlab#1004 and ndi-cloud-node#142.
# ---------------------------------------------------------------------------

#: Safety cap on the number of keyset pages listFilesAll will fetch before
#: giving up, so a server that never clears hasMore cannot loop forever. With
#: the default limit of 1000 this bounds a walk at 100 million files.
_MAX_FILE_PAGES = 100_000


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listFiles(
    dataset_id: CloudId,
    *,
    limit: int = 1000,
    after: str = "",
    client: _Client = None,
) -> APIResponse:
    """List one keyset page of files associated with a cloud dataset.

    Retrieves a single keyset-paginated page from
    ``GET /datasets/{datasetId}/files``. To retrieve the complete file list
    across all pages, use :func:`listFilesAll`.

    Args:
        dataset_id: The cloud dataset id.
        limit: Maximum number of files in the page. Default 1000.
        after: Opaque keyset cursor from a prior page's ``cursor`` field.
            Omit (or ``""``) for the first page.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        The page envelope with fields ``datasetId``, ``limit``, ``count``,
        ``cursor``, ``hasMore``, ``totalNumber``, and ``files`` -- a list of
        file summaries, each with ``uid``, ``uploaded``, ``sourceDatasetId``,
        and ``size``. Follow ``cursor`` by passing it back as *after* while
        ``hasMore`` is true.

    MATLAB equivalent: +cloud/+api/+files/listFiles.m
    """
    params: dict[str, Any] = {"limit": limit}
    # The cursor is sent only when set; the first page omits it. (An empty
    # `after` is not a valid cursor, and sending one would ask the server to
    # resume from nowhere.)
    if after:
        params["after"] = after
    return client.get(
        "/datasets/{datasetId}/files",
        params=params,
        datasetId=dataset_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listFilesAll(
    dataset_id: CloudId,
    *,
    limit: int = 1000,
    check_for_updates: bool = False,
    wait_for_updates: float = 5.0,
    max_update_reads: int = 100,
    client: _Client = None,
) -> APIResponse:
    """List every file in a dataset by following the keyset cursor.

    Walks :func:`listFiles` page by page, following the response envelope's
    ``cursor`` while ``hasMore`` is true, and de-duplicates by ``uid`` so a
    file that reappears across a page boundary (or after a concurrent write)
    is returned exactly once. This is the whole-dataset counterpart to
    :func:`listFiles`; it mirrors
    :func:`~ndi.cloud.api.documents.listDatasetDocumentsAll` and returns an
    :class:`~ndi.cloud.client.APIResponse` wrapping the list of file
    summaries.

    Keyset pagination (a cursor on insertion order) is used instead of
    page/offset: it is O(1) per page at any depth and stable under concurrent
    writes, and it lets an update poll resume from the last cursor to pick up
    files appended while the scan ran.

    Args:
        dataset_id: The cloud dataset id.
        limit: Maximum number of files fetched per page. Default 1000.
        check_for_updates: If true, after the initial full scan re-poll from
            the last cursor to pick up files appended while the scan ran,
            stopping once a poll adds nothing new. Default false.
        wait_for_updates: Seconds to pause before each update re-poll.
            Default 5.
        max_update_reads: Cap on the number of update re-polls, to bound the
            loop. Default 100.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        An :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the list
        of de-duplicated file summaries (``uid``, ``uploaded``,
        ``sourceDatasetId``, ``size``).

    MATLAB equivalent: +cloud/+api/+files/listFilesAll.m
    """
    seen_uids: set[str] = set()
    all_files: list[dict[str, Any]] = []

    def _scan(after: str) -> str:
        """Walk pages from *after* to the last, appending files not already
        seen. Returns the last cursor observed (the resume token)."""
        last_cursor = after
        for _ in range(_MAX_FILE_PAGES):
            page = listFiles(dataset_id, limit=limit, after=after, client=client)
            files = page.get("files", []) if hasattr(page, "get") else []
            for f in files or []:
                uid = f.get("uid", "") if hasattr(f, "get") else ""
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    all_files.append(f)
            cursor = page.get("cursor", "") if hasattr(page, "get") else ""
            if cursor:
                last_cursor = cursor
            has_more = bool(page.get("hasMore", False)) if hasattr(page, "get") else False
            # Advance only when there is a next page AND the cursor actually
            # moved. A server that echoes the same cursor with hasMore=true
            # would otherwise page in place forever.
            if has_more and cursor and cursor != after:
                after = cursor
            else:
                break
        return last_cursor

    last_cursor = _scan("")

    if check_for_updates:
        for _ in range(max_update_reads):
            if wait_for_updates > 0:
                time.sleep(wait_for_updates)
            count_before = len(all_files)
            last_cursor = _scan(last_cursor)
            if len(all_files) == count_before:
                break  # nothing new was added

    return APIResponse(all_files, success=True, status_code=200, url="")


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getFileDetails(
    dataset_id: CloudId,
    file_uid: NonEmptyStr,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """Get detail info (including download URL) for a file.

    MATLAB equivalent: +cloud/+api/+files/getFileDetails.m
    """
    return client.get(
        "/datasets/{datasetId}/files/{file_uid}/detail",
        datasetId=dataset_id,
        file_uid=file_uid,
    )


# ---------------------------------------------------------------------------
# Signed-URL-set family
#
# The cloud exposes a "signed-URL-set" route that returns a document's uid ->
# pre-signed URL map in one call, cursor-paginated. NDI's own callers hold NDI
# document ids (data.base.id), so the ndi-documents route is the one to use;
# the by-_id route exists for callers who hold the mongo _id.
#
# For an ordinary document that references a handful of files, calling
# getFileDetails per uid is fine. For a file series with many members --
# 28,000 in the lightsheet-pyramid case that motivates this -- that becomes
# one API round trip per member. See NDI-python#262 and NDI-matlab#952.
# ---------------------------------------------------------------------------


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getSignedURLSet(
    dataset_id: CloudId,
    document_id: NonEmptyStr,
    *,
    limit: int = 500,
    cursor: str = "",
    file_series: str = "",
    id_namespace: Literal["cloud", "ndi"] = "cloud",
    client: _Client = None,
) -> dict[str, Any]:
    """GET one page of a document's uid -> signed URL map.

    Returns a dict with fields ``datasetId``, ``documentId``, ``totalCount``,
    ``pageCount``, optionally ``nextCursor``, ``expiresAt``, and ``files``
    (a dict mapping file uid to pre-signed download URL, in uid-sorted order).

    Args:
        dataset_id: The cloud dataset id.
        document_id: The document id. Namespace controlled by *id_namespace*.
        limit: Per-page limit. Server default 500, cap 1000.
        cursor: Opaque cursor from a prior response's ``nextCursor``.
        file_series: If set, restrict the set to one file series' members.
            A document holding a dual pyramid references several series; a
            viewer wants the level it is showing, not all of them.
        id_namespace: ``"cloud"`` (default) sends the mongo ``_id`` to the
            by-_id route; ``"ndi"`` sends ``data.base.id`` to the
            ndi-documents route. NDI's own callers hold NDI ids and must
            pass ``"ndi"``; passing one as ``"cloud"`` is a 404. See
            NDI-matlab#968.

    MATLAB equivalent: +cloud/+api/+files/getSignedURLSet.m
    """
    if id_namespace == "ndi":
        endpoint = "/datasets/{datasetId}/ndi-documents/{ndiDocumentId}/signed-url-set"
        path_params = {"datasetId": dataset_id, "ndiDocumentId": document_id}
    else:
        endpoint = "/datasets/{datasetId}/documents/{documentId}/signed-url-set"
        path_params = {"datasetId": dataset_id, "documentId": document_id}

    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if file_series:
        params["fileSeries"] = file_series

    return client.get(endpoint, params=params, **path_params)


class SignedURLSetCursorDidNotAdvance(RuntimeError):
    """The server handed back the same cursor it was given.

    Following it would page in place until ``max_pages`` for no gain. Named
    so a caller can distinguish "the server is looping" from an ordinary
    transport error.
    """


class SignedURLSetMaxPagesReached(RuntimeError):
    """Ran off *max_pages* without a terminating page.

    The partial result is attached as ``.merged`` for inspection.
    """

    def __init__(self, merged: dict[str, Any]):
        super().__init__(
            f"getSignedURLSetAll gave up after {merged.get('pages', 0)} pages "
            "without a terminating page"
        )
        self.merged = merged


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getSignedURLSetAll(
    dataset_id: CloudId,
    document_id: NonEmptyStr,
    *,
    limit: int = 500,
    max_pages: int = 1000,
    file_series: str = "",
    id_namespace: Literal["cloud", "ndi"] = "cloud",
    client: _Client = None,
) -> dict[str, Any]:
    """Walk every page of a document's signed URL set and merge them.

    Calls :func:`getSignedURLSet` repeatedly, following ``nextCursor`` until
    the server signals no more pages, and merges the per-page ``files`` maps
    into a single dict.

    For a document that references a few thousand files this is fine; for the
    much larger lightsheet / spatial-transcriptomics case, the async job
    family (``createSignedURLSetJob`` + ``waitForSignedURLSetJob``) is
    preferred and is tracked separately in the bridge YAML.

    Args:
        dataset_id: The cloud dataset id.
        document_id: The document id.
        limit: Per-page limit forwarded to :func:`getSignedURLSet`.
        max_pages: Safety cap. Raises :class:`SignedURLSetMaxPagesReached`
            if hit.
        file_series: If set, restrict the walk to one file series' members.
        id_namespace: See :func:`getSignedURLSet`.

    Returns:
        Merged dict with ``datasetId``, ``documentId``, ``files``
        (uid -> URL), ``pageCount`` (total uids across pages), ``pages``
        (number of HTTP calls), ``totalCount`` (server-reported total),
        and ``expiresAt`` (from the last page carrying it).

    Raises:
        SignedURLSetCursorDidNotAdvance: If the server returned a cursor
            equal to the one it was given.
        SignedURLSetMaxPagesReached: If the walk hit *max_pages*.

    MATLAB equivalent: +cloud/+api/+files/getSignedURLSetAll.m
    """
    merged: dict[str, Any] = {
        "datasetId": dataset_id,
        "documentId": document_id,
        "files": {},
        "pageCount": 0,
        "totalCount": 0,
        "pages": 0,
    }
    cursor = ""
    for _ in range(max_pages):
        page = getSignedURLSet(
            dataset_id,
            document_id,
            limit=limit,
            cursor=cursor,
            file_series=file_series,
            id_namespace=id_namespace,
            client=client,
        )
        files = page.get("files", {}) if hasattr(page, "get") else {}
        if isinstance(files, dict):
            merged["files"].update(files)
            merged["pageCount"] += len(files)
        total = page.get("totalCount") if hasattr(page, "get") else None
        if isinstance(total, int):
            merged["totalCount"] = total
        expires_at = page.get("expiresAt") if hasattr(page, "get") else None
        if expires_at:
            merged["expiresAt"] = expires_at
        merged["pages"] += 1

        next_cursor = page.get("nextCursor", "") if hasattr(page, "get") else ""
        if not next_cursor:
            return merged
        if next_cursor == cursor:
            raise SignedURLSetCursorDidNotAdvance(
                f"The signed URL set cursor did not advance after page "
                f"{merged['pages']}. Refusing to page in place."
            )
        cursor = next_cursor

    raise SignedURLSetMaxPagesReached(merged)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getFileCollectionUploadURL(
    org_id: NonEmptyStr,
    dataset_id: CloudId,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """Get a presigned URL (and ``jobId``) for bulk file collection upload.

    Returns a dict with keys ``url`` (the pre-signed PUT URL for the zip
    archive) and ``jobId`` (identifier of the server-side extraction
    job).  Pass ``jobId`` to :func:`waitForBulkUpload` -- or to
    :func:`putFiles` with ``wait_for_completion=True`` -- to wait for
    the server to finish extracting the zip before attempting to
    download the extracted files.  ``jobId`` is an empty string for
    older server versions that don't return one.

    MATLAB equivalent: +cloud/+api/+files/getFileCollectionUploadURL.m
    """
    result = client.get(
        "/datasets/{organizationId}/{datasetId}/files/bulk",
        organizationId=org_id,
        datasetId=dataset_id,
    )
    url = result.get("url", "") if hasattr(result, "get") else ""
    job_id = result.get("jobId", "") if hasattr(result, "get") else ""
    return {"url": url, "jobId": job_id}


# ---------------------------------------------------------------------------
# Bulk-upload status / wait helpers
# ---------------------------------------------------------------------------


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getBulkUploadStatus(
    job_id: NonEmptyStr,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /bulk-uploads/{jobId} -- Get the state of a bulk file-upload job.

    Returns a dict with fields ``jobId``, ``datasetId``, ``state``,
    ``createdAt``, ``startedAt``, ``completedAt``, ``filesExtracted``,
    ``totalFiles``, ``error``.

    MATLAB equivalent: +cloud/+api/+files/getBulkUploadStatus.m
    """
    return client.get("/bulk-uploads/{jobId}", jobId=job_id)


# Convenience alias matching the MATLAB doc-string label.
bulkUploadsJobInfo = getBulkUploadStatus


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listActiveBulkUploads(
    dataset_id: CloudId,
    *,
    state: Literal["active", "all", "queued", "extracting", "complete", "failed"] = "active",
    client: _Client = None,
) -> dict[str, Any]:
    """GET /datasets/{datasetId}/bulk-uploads[?state=...]

    List bulk upload jobs the server is tracking for *dataset_id*.

    Args:
        dataset_id: The cloud dataset ID.
        state: Filter by job state.  One of ``'active'`` (default;
            ``queued + extracting``), ``'all'`` (includes recent
            history), ``'queued'``, ``'extracting'``, ``'complete'``,
            ``'failed'``.

    Returns:
        Dict with fields ``datasetId`` and ``jobs`` (a list of job
        status dicts; see :func:`getBulkUploadStatus` for fields).

    MATLAB equivalent: +cloud/+api/+files/listActiveBulkUploads.m
    """
    return client.get(
        "/datasets/{datasetId}/bulk-uploads",
        params={"state": state},
        datasetId=dataset_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def waitForBulkUpload(
    job_id: NonEmptyStr,
    *,
    timeout: float = 60.0,
    initial_interval: float = 1.0,
    max_interval: float = 30.0,
    backoff_factor: float = 2.0,
    client: _Client = None,
) -> dict[str, Any]:
    """Poll a bulk file-upload job until it finishes or times out.

    Repeatedly calls :func:`getBulkUploadStatus` at exponentially
    growing intervals until the job reaches a terminal state
    (``'complete'`` or ``'failed'``) or the overall timeout elapses.

    Returns:
        The last status dict from the server.  On timeout, the
        returned dict has ``state='timeout'`` and ``elapsed`` set to
        the wall-clock seconds spent polling.

    MATLAB equivalent: +cloud/+api/+files/waitForBulkUpload.m
    """
    start = time.monotonic()
    interval = initial_interval
    last: Any = None
    while True:
        elapsed = time.monotonic() - start
        try:
            status = getBulkUploadStatus(job_id, client=client)
            last = status
            state = status.get("state", "") if hasattr(status, "get") else ""
            if state in _TERMINAL_BULK_STATES:
                return status
        except Exception:
            pass
        if elapsed + interval > timeout:
            payload: dict[str, Any]
            if last is not None and hasattr(last, "data") and isinstance(last.data, dict):
                payload = dict(last.data)
            elif isinstance(last, dict):
                payload = dict(last)
            else:
                payload = {}
            payload["state"] = "timeout"
            payload["elapsed"] = time.monotonic() - start
            return payload
        time.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def waitForAllBulkUploads(
    dataset_id: CloudId,
    *,
    timeout: float = 300.0,
    initial_interval: float = 1.0,
    max_interval: float = 30.0,
    backoff_factor: float = 2.0,
    require_all_complete: bool = True,
    client: _Client = None,
) -> dict[str, Any]:
    """Wait for every bulk-upload job on a dataset to finish.

    Polls :func:`listActiveBulkUploads` at exponentially growing
    intervals until no active (queued + extracting) bulk-upload jobs
    remain on the dataset or the overall timeout elapses.  Intended for
    use at sync-pipeline boundaries: before inventorying remote state,
    callers should wait for any in-flight extractions so the inventory
    is stable.

    Args:
        dataset_id: The cloud dataset ID.
        timeout: Overall deadline in seconds.  Default 300.
        initial_interval: First sleep between polls (s).  Default 1.
        max_interval: Cap on the per-poll sleep (s).  Default 30.
        backoff_factor: Multiplier applied after each poll.  Default 2.
        require_all_complete: If True, return ``state='failed'`` when
            any job on the dataset ended in ``'failed'``.  If False,
            return ``state='complete'`` as soon as the active set
            drains, regardless of failure history.  Default True.

    Returns:
        Dict describing the final state with fields ``state``
        (``'complete'``, ``'failed'``, or ``'timeout'``), ``jobs``
        (active or failed jobs), and ``elapsed`` (wall-clock seconds).

    MATLAB equivalent: +cloud/+api/+files/waitForAllBulkUploads.m
    """
    start = time.monotonic()
    interval = initial_interval
    last_jobs: list[dict[str, Any]] = []
    ever_listed = False
    while True:
        elapsed = time.monotonic() - start
        try:
            scope = "all" if require_all_complete else "active"
            listing = listActiveBulkUploads(dataset_id, state=scope, client=client)
            jobs = listing.get("jobs", []) if hasattr(listing, "get") else []
            last_jobs = list(jobs) if jobs else []
            ever_listed = True

            active_jobs = [
                j
                for j in last_jobs
                if (j.get("state", "") if isinstance(j, dict) else "") in _ACTIVE_BULK_STATES
            ]
            failed_jobs = [
                j
                for j in last_jobs
                if (j.get("state", "") if isinstance(j, dict) else "") == "failed"
            ]

            if not active_jobs:
                if require_all_complete and failed_jobs:
                    return {
                        "state": "failed",
                        "jobs": failed_jobs,
                        "elapsed": time.monotonic() - start,
                    }
                return {
                    "state": "complete",
                    "jobs": [],
                    "elapsed": time.monotonic() - start,
                }
        except Exception as exc:
            # A blip after we have seen the listing work is worth riding out:
            # there may be a real extraction in flight, and abandoning the
            # wait on one failed poll is how a race gets reintroduced.
            #
            # A failure on the FIRST poll is different. Nothing has ever been
            # observed, so the error is not evidence of activity -- it is
            # evidence the wait cannot be performed at all (the endpoint is
            # absent, the credentials do not reach it, the deployment has no
            # bulk-upload service). Sleeping out the whole timeout there buys
            # nothing and costs every caller the full deadline.
            if not ever_listed:
                return {
                    "state": "unavailable",
                    "jobs": [],
                    "elapsed": time.monotonic() - start,
                    "error": str(exc),
                }
        if elapsed + interval > timeout:
            return {
                "state": "timeout",
                "jobs": last_jobs,
                "elapsed": time.monotonic() - start,
            }
        time.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)


# ---------------------------------------------------------------------------
# File-tier family
#
# Kick off, poll, wait on, and read back the "move these documents' files to
# storage class X" workflow. See ndi-cloud-node/manuals/file-tier-design.md
# for the full design (warmest-wins shared-UID rule, fencing tokens,
# two-phase thaw semantics, terminal states).
# ---------------------------------------------------------------------------


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def setFileTier(
    dataset_id: CloudId,
    document_ids: list[str] | tuple[str, ...] | str,
    target_tier: str,
    *,
    id_namespace: Literal["auto", "cloud", "ndi"] = "auto",
    client: _Client = None,
) -> dict[str, Any]:
    """POST /datasets/{datasetId}/file-tier-jobs

    Kick off an async job that moves every file referenced by *document_ids*
    to *target_tier*. Documents may be addressed by cloud ``_id`` or NDI id;
    the server infers each selector's namespace unless *id_namespace* forces
    it. Returns the accepted-job envelope with ``jobId``, ``fileCount``,
    ``resolvedDocumentCount``, and ``collateralDocumentIds``. See
    ndi-cloud-node/manuals/file-tier-design.md.

    Args:
        dataset_id: The cloud dataset id.
        document_ids: One document id, a list/tuple of ids, or a mix of
            cloud (24-hex) and NDI ids. Must be non-empty.
        target_tier: Target S3 storage class. One of ``"STANDARD"``,
            ``"STANDARD_IA"``, ``"GLACIER_IR"``, ``"GLACIER"``,
            ``"DEEP_ARCHIVE"``. ``"PSEUDO_COLD"`` is accepted at the wire
            level and used by the server-side non-production test path;
            production stages reject it as ``INVALID_TARGET_TIER``.
        id_namespace: ``"auto"`` (default) lets the server infer each id's
            shape (24-hex → cloud, else NDI). Pass ``"cloud"`` or ``"ndi"``
            to force one interpretation for every selector.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Dict with ``jobId``, ``fileCount``, ``resolvedDocumentCount``,
        ``collateralDocumentIds``. Pass ``jobId`` to
        :func:`waitForFileTierJob` (or :func:`getFileTierJob` for one poll)
        to follow the job to completion.

    MATLAB equivalent: +cloud/+api/+files/setFileTier.m
    """
    if isinstance(document_ids, str):
        ids: list[str] = [document_ids]
    else:
        ids = [str(d) for d in document_ids]
    if not ids:
        raise ValueError("document_ids must be non-empty")

    selectors: list[dict[str, str]] = []
    for did in ids:
        sel: dict[str, str] = {"id": did}
        if id_namespace != "auto":
            sel["kind"] = id_namespace
        selectors.append(sel)

    payload = {
        "targetTier": target_tier,
        "documentSelectors": selectors,
    }
    return client.post(
        "/datasets/{datasetId}/file-tier-jobs",
        json=payload,
        datasetId=dataset_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getFileTierJob(
    job_id: NonEmptyStr,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /file-tier-jobs/{jobId} -- one poll of an async file-tier job.

    Returns a dict with fields ``jobId``, ``datasetId``, ``state``,
    ``targetTier``, ``fileCount``, ``filesDone``, ``filesFailed``,
    ``perPhaseCounts``, ``errors``, ``createdAt``, ``updatedAt``. Terminal
    states are ``'completed'``, ``'failed'``, and ``'superseded'``. See
    ndi-cloud-node/manuals/file-tier-design.md.

    MATLAB equivalent: +cloud/+api/+files/getFileTierJob.m
    """
    return client.get("/file-tier-jobs/{jobId}", jobId=job_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def waitForFileTierJob(
    job_id: NonEmptyStr,
    *,
    timeout: float = 600.0,
    initial_interval: float = 3.0,
    max_interval: float = 30.0,
    backoff_factor: float = 2.0,
    client: _Client = None,
) -> dict[str, Any]:
    """Poll a file-tier job until it finishes or times out.

    Repeatedly calls :func:`getFileTierJob` at exponentially growing
    intervals until the job reaches a terminal state (``'completed'``,
    ``'failed'``, or ``'superseded'``) or the overall timeout elapses. A
    transient API failure is NOT treated as terminal -- a gateway blip
    would otherwise be mistaken for a dead job.

    Args:
        job_id: The file-tier job identifier from :func:`setFileTier`.
        timeout: Overall deadline in seconds. Default 600 -- tier moves
            fan out to many CopyObject calls; give them room.
        initial_interval: First sleep between polls (s). Default 3.
        max_interval: Cap on the per-poll sleep (s). Default 30.
        backoff_factor: Multiplier applied after each poll. Default 2.

    Returns:
        The last status dict from the server. On timeout, the returned
        dict has ``state='timeout'`` and ``elapsed`` set to the
        wall-clock seconds spent polling. The caller decides success by
        reading ``state`` (``'completed'`` is the only "job did what you
        asked" verdict; ``'failed'`` and ``'superseded'`` are terminal
        non-successes).

    MATLAB equivalent: +cloud/+api/+files/waitForFileTierJob.m
    """
    start = time.monotonic()
    interval = initial_interval
    last: Any = None
    while True:
        elapsed = time.monotonic() - start
        try:
            status = getFileTierJob(job_id, client=client)
            last = status
            state = status.get("state", "") if hasattr(status, "get") else ""
            if state in _TERMINAL_FILE_TIER_STATES:
                return status
        except Exception:
            # A failed poll is not a failed job. The gateway (Lambda 29 s
            # cap) or an in-flight worker restart can drop one read; keep
            # polling until the deadline rather than reporting the job
            # dead on the first blip.
            pass
        if elapsed + interval > timeout:
            payload: dict[str, Any]
            if last is not None and hasattr(last, "data") and isinstance(last.data, dict):
                payload = dict(last.data)
            elif isinstance(last, dict):
                payload = dict(last)
            else:
                payload = {}
            payload["state"] = "timeout"
            payload["elapsed"] = time.monotonic() - start
            return payload
        time.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getFileTier(
    dataset_id: CloudId,
    document_id: CloudId,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """Read the cached files-tier summary for one document.

    Answers "what tier are this document's files on?" from the doc's
    cached ``filesTier`` summary. Backed by
    ``GET /datasets/{d}/documents/{doc}`` via
    :func:`~ndi.cloud.api.documents.getDocument` -- there is no dedicated
    tier-read endpoint because the server keeps a per-doc summary
    alongside the doc, recomputed by the tier worker after every job. See
    ndi-cloud-node/manuals/file-tier-design.md.

    Args:
        dataset_id: The cloud dataset id.
        document_id: The cloud API id of the document.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Dict with fields:
            ``counts``    - per-tier file-count map (``STANDARD`` |
                            ``STANDARD_IA`` | ``GLACIER_IR`` | ``GLACIER`` |
                            ``DEEP_ARCHIVE`` | ``PSEUDO_COLD`` -> int).
                            Empty dict when the doc has never had a tier
                            operation.
            ``dominant``  - the coldest tier with a non-zero count (the
                            design's ``dominantFileTier`` shorthand). ``""``
                            if no tier state yet.
            ``notes``     - list of divergence notes, e.g. "warmest-wins
                            overruled a freeze because sibling doc needs
                            file warm". Empty when clean.
            ``updatedAt`` - timestamp of the last summary write, or
                            ``None`` until the first tier job runs.
            ``raw``       - the full get-document response, for callers
                            that want the whole doc.

    MATLAB equivalent: +cloud/+api/+files/getFileTier.m
    """
    from . import documents as docs_api

    doc = docs_api.getDocument(dataset_id, document_id, client=client)

    result: dict[str, Any] = {
        "counts": {},
        "dominant": "",
        "notes": [],
        "updatedAt": None,
        "raw": doc,
    }

    summary = doc.get("filesTier") if hasattr(doc, "get") else None
    if isinstance(summary, dict):
        counts = summary.get("counts")
        if isinstance(counts, dict) and counts:
            result["counts"] = dict(counts)
        dominant = summary.get("dominant")
        if dominant:
            result["dominant"] = str(dominant)
        notes = summary.get("notes")
        if notes:
            if isinstance(notes, (list, tuple)):
                result["notes"] = [str(n) for n in notes]
            else:
                result["notes"] = [str(notes)]
        updated_at = summary.get("updatedAt")
        if updated_at:
            result["updatedAt"] = updated_at

    return result
