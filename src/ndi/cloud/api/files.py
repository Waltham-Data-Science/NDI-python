"""
ndi.cloud.api.files - File transfer via presigned URLs.

MATLAB equivalents: +ndi/+cloud/+api/+files/*.m,
    +implementation/+files/*.m
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import CloudClient


def get_upload_url(
    client: CloudClient,
    org_id: str,
    dataset_id: str,
    file_uid: str,
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
    return result.get("url", "") if isinstance(result, dict) else ""


def get_bulk_upload_url(
    client: CloudClient,
    org_id: str,
    dataset_id: str,
) -> str:
    """POST /datasets/{organizationId}/{datasetId}/files/bulk

    Returns a presigned S3 URL for bulk file upload.
    """
    result = client.post(
        "/datasets/{organizationId}/{datasetId}/files/bulk",
        organizationId=org_id,
        datasetId=dataset_id,
    )
    return result.get("url", "") if isinstance(result, dict) else ""


def put_file(
    url: str,
    file_path: str | Path,
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


def put_file_bytes(
    url: str,
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


def get_file(
    url: str,
    target_path: str | Path,
    timeout: int = 120,
) -> bool:
    """Download a file from a presigned URL.

    MATLAB equivalent: +cloud/+api/+files/getFile.m
    """
    import requests

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(url, timeout=timeout, stream=True)
    if resp.status_code == 200:
        with open(target_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        return True
    return False


def list_files(
    client: CloudClient,
    dataset_id: str,
) -> list[dict[str, Any]]:
    """List all files associated with a cloud dataset.

    Fetches the dataset metadata and extracts the files list.

    MATLAB equivalent: +cloud/+api/+files/listFiles.m
    """
    from . import datasets as ds_api

    ds = ds_api.get_dataset(client, dataset_id)
    return ds.get("files", []) if isinstance(ds, dict) else []


def get_file_details(
    client: CloudClient,
    dataset_id: str,
    file_uid: str,
) -> dict[str, Any]:
    """Get detail info (including download URL) for a file.

    MATLAB equivalent: +cloud/+api/+files/getFileDetails.m
    """
    return client.get(
        "/datasets/{datasetId}/files/{file_uid}/detail",
        datasetId=dataset_id,
        file_uid=file_uid,
    )


def get_bulk_file_download_url(
    client: CloudClient,
    dataset_id: str,
    file_uids: list[str] | None = None,
) -> str:
    """POST /datasets/{datasetId}/files/bulk-download

    .. note:: **Railway-only.** This endpoint does not exist on the
       Lambda API.  For Lambda-compatible file downloads, use
       :func:`get_file_details` to get individual presigned URLs.

    Returns a presigned S3 URL where the backend will place a ZIP of
    all binary files for the dataset.  The ZIP is created asynchronously;
    the caller must poll the returned URL until it becomes available.

    Args:
        client: Authenticated cloud client.
        dataset_id: Cloud dataset ID.
        file_uids: Optional list of specific file UIDs to include.
            If ``None`` or empty, all uploaded files are included.

    Returns:
        Presigned S3 URL string.
    """
    body: dict[str, Any] = {"fileUids": file_uids or []}
    result = client.post(
        "/datasets/{datasetId}/files/bulk-download",
        json=body,
        datasetId=dataset_id,
    )
    return result.get("url", "") if isinstance(result, dict) else ""


def get_file_collection_upload_url(
    client: CloudClient,
    org_id: str,
    dataset_id: str,
) -> str:
    """Get a presigned URL for bulk file collection upload.

    MATLAB equivalent: +cloud/+api/+files/getFileCollectionUploadURL.m
    """
    result = client.get(
        "/datasets/{organizationId}/{datasetId}/files/bulk",
        organizationId=org_id,
        datasetId=dataset_id,
    )
    return result.get("url", "") if isinstance(result, dict) else ""
