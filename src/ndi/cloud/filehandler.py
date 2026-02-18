"""
ndi.cloud.filehandler - On-demand cloud file fetching via ndic:// protocol.

MATLAB equivalents:
    +ndi/+cloud/+sync/+internal/updateFileInfoForRemoteFiles.m
    +ndi/+cloud/+download/+internal/setFileInfo.m
    didsqlite.m:do_openbinarydoc (customFileHandler callback)

The ndic:// URI scheme provides stable references to cloud-hosted binary
files.  When a dataset is downloaded without ``sync_files=True``, document
file_info locations are rewritten to ``ndic://{dataset_id}/{file_uid}``.
When a binary file is opened, the URI is resolved on demand: a fresh
presigned S3 URL is fetched via ``get_file_details`` and the file is
streamed to local storage.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import CloudClient

logger = logging.getLogger(__name__)

NDIC_SCHEME = "ndic://"


def parse_ndic_uri(uri: str) -> tuple[str, str]:
    """Parse an ``ndic://`` URI into (dataset_id, file_uid).

    Args:
        uri: A string like ``"ndic://dataset_id/file_uid"``.

    Returns:
        Tuple of (dataset_id, file_uid).

    Raises:
        ValueError: If the URI is not a valid ``ndic://`` URI.
    """
    if not uri.startswith(NDIC_SCHEME):
        raise ValueError(f"Not an ndic:// URI: {uri!r}")
    path = uri[len(NDIC_SCHEME) :]
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid ndic:// URI (expected ndic://dataset_id/file_uid): {uri!r}")
    return parts[0], parts[1]


def rewrite_file_info_for_cloud(doc_props: dict, cloud_dataset_id: str) -> None:
    """Rewrite a document's file_info locations to use ``ndic://`` URIs.

    Mutates *doc_props* in-place.  Handles both list-style and dict-style
    (MATLAB struct) ``file_info`` and ``locations`` fields.

    Args:
        doc_props: Document properties dict (as from JSON).
        cloud_dataset_id: The cloud dataset ID to embed in URIs.
    """
    files = doc_props.get("files")
    if not files or not isinstance(files, dict):
        return

    file_info = files.get("file_info")
    if file_info is None:
        return

    # Normalise to list (MATLAB struct serialisation may produce a single dict)
    if isinstance(file_info, dict):
        fi_list = [file_info]
        was_dict = True
    elif isinstance(file_info, list):
        fi_list = file_info
        was_dict = False
    else:
        return

    for fi in fi_list:
        if not isinstance(fi, dict):
            continue

        locations = fi.get("locations")
        if locations is None:
            continue

        if isinstance(locations, dict):
            loc_list = [locations]
            loc_was_dict = True
        elif isinstance(locations, list):
            loc_list = locations
            loc_was_dict = False
        else:
            continue

        for loc in loc_list:
            if not isinstance(loc, dict):
                continue
            uid = loc.get("uid", "")
            if not uid:
                continue
            loc["location"] = f"{NDIC_SCHEME}{cloud_dataset_id}/{uid}"
            loc["location_type"] = "ndicloud"
            loc["ingest"] = 0
            loc["delete_original"] = 0

        # Write back if was single dict
        if loc_was_dict:
            fi["locations"] = loc_list[0]

    if was_dict:
        files["file_info"] = fi_list[0]


def fetch_cloud_file(
    ndic_uri: str,
    target_path: str | Path,
    client: CloudClient | None = None,
) -> bool:
    """Download a cloud file on demand.

    Parses the ``ndic://`` URI, calls ``get_file_details`` for a fresh
    presigned S3 URL, then streams the file to *target_path*.  Uses an
    atomic write (download to ``.tmp``, then rename) to avoid partial files.

    Args:
        ndic_uri: An ``ndic://dataset_id/file_uid`` URI.
        target_path: Local path where the file should be saved.
        client: Authenticated :class:`CloudClient`.  If *None*,
            :func:`get_or_create_cloud_client` is used as a fallback.

    Returns:
        True on success.

    Raises:
        ValueError: If the URI is invalid.
        CloudError: If the download fails.
    """
    from .api.files import get_file, get_file_details

    dataset_id, file_uid = parse_ndic_uri(ndic_uri)

    if client is None:
        client = get_or_create_cloud_client()

    # Get fresh presigned URL
    details = get_file_details(client, dataset_id, file_uid)
    download_url = details.get("downloadUrl", "")
    if not download_url:
        from .exceptions import CloudError

        raise CloudError(f"No downloadUrl in file details for {ndic_uri}. " f"Response: {details}")

    # Stream download to temp file, then atomic rename
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")

    logger.debug("Fetching cloud file %s -> %s", ndic_uri, target)
    success = get_file(download_url, tmp_path, timeout=300)

    if success:
        tmp_path.rename(target)
        logger.debug("Cloud file cached: %s", target)
        return True
    else:
        # Clean up partial download
        tmp_path.unlink(missing_ok=True)
        from .exceptions import CloudError

        raise CloudError(f"Failed to download file from {ndic_uri}")


def get_or_create_cloud_client() -> CloudClient:
    """Create an authenticated CloudClient from environment variables.

    Reads ``NDI_CLOUD_USERNAME`` and ``NDI_CLOUD_PASSWORD`` from the
    environment and calls :func:`login`.

    Returns:
        An authenticated :class:`CloudClient`.

    Raises:
        CloudAuthError: If credentials are missing or login fails.
    """
    from .auth import login
    from .client import CloudClient
    from .exceptions import CloudAuthError

    username = os.environ.get("NDI_CLOUD_USERNAME", "")
    password = os.environ.get("NDI_CLOUD_PASSWORD", "")

    if not username or not password:
        raise CloudAuthError(
            "Cannot auto-authenticate for cloud file download. "
            "Set NDI_CLOUD_USERNAME and NDI_CLOUD_PASSWORD environment "
            "variables, or pass a CloudClient explicitly."
        )

    config = login(username, password)
    return CloudClient(config)
