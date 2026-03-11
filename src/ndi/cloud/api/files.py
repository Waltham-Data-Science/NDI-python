"""
ndi.cloud.api.files - File transfer via presigned URLs.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+files/*.m,
    +implementation/+files/*.m
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, CloudId, FilePath, NonEmptyStr

_Client = Annotated[CloudClient | None, SkipValidation()]


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
) -> bool:
    """PUT a local file to a presigned S3 URL.

    Args:
        url: Presigned URL.
        file_path: Path to file on disk.
        timeout: Request timeout in seconds.

    Returns:
        True on success.

    Raises:
        CloudUploadError: On failure.
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

    if resp.status_code == 200:
        return True
    raise CloudUploadError(f"File upload failed (HTTP {resp.status_code}): {resp.text}")


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
) -> str:
    """Get a presigned URL for bulk file collection upload.

    MATLAB equivalent: +cloud/+api/+files/getFileCollectionUploadURL.m
    """
    result = client.get(
        "/datasets/{organizationId}/{datasetId}/files/bulk",
        organizationId=org_id,
        datasetId=dataset_id,
    )
    return result.get("url", "")
