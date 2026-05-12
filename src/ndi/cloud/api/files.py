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
from ._validators import VALIDATE_CONFIG, CloudId, FilePath, NonEmptyStr

_Client = Annotated[CloudClient | None, SkipValidation()]

# Terminal job states reported by the bulk-upload service.
_TERMINAL_BULK_STATES = ("complete", "failed")
_ACTIVE_BULK_STATES = ("queued", "extracting")


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
def getFile(
    url: NonEmptyStr,
    target_path: str | Path,
    timeout: int = 120,
) -> bool:
    """Download a file from a presigned URL.

    MATLAB equivalent: +cloud/+api/+files/getFile.m
    """
    import logging

    import requests

    logger = logging.getLogger(__name__)

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(url, timeout=timeout, stream=True)
    if resp.status_code == 200:
        with open(target_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
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


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listFiles(
    dataset_id: CloudId,
    *,
    client: _Client = None,
) -> APIResponse:
    """List all files associated with a cloud dataset.

    Fetches the dataset metadata and extracts the files list.

    MATLAB equivalent: +cloud/+api/+files/listFiles.m
    """
    from . import datasets as ds_api

    ds = ds_api.getDataset(dataset_id, client=client)
    files = ds.get("files", []) if hasattr(ds, "get") else []
    return APIResponse(files, success=True, status_code=200, url="")


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
    while True:
        elapsed = time.monotonic() - start
        try:
            scope = "all" if require_all_complete else "active"
            listing = listActiveBulkUploads(dataset_id, state=scope, client=client)
            jobs = listing.get("jobs", []) if hasattr(listing, "get") else []
            last_jobs = list(jobs) if jobs else []

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
        except Exception:
            active_jobs = last_jobs  # treat error as still active; let timeout govern
        if elapsed + interval > timeout:
            return {
                "state": "timeout",
                "jobs": last_jobs,
                "elapsed": time.monotonic() - start,
            }
        time.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)
