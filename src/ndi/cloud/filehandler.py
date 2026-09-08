"""
ndi.cloud.filehandler - On-demand cloud file fetching via ndic:// protocol.

MATLAB equivalents:
    +ndi/+cloud/+sync/+internal/updateFileInfoForRemoteFiles.m
    didsqlite.m:do_openbinarydoc (customFileHandler callback)

The ndic:// URI scheme provides stable references to cloud-hosted binary
files.  When a dataset is downloaded without ``sync_files=True``, document
file_info locations are rewritten to ``ndic://{dataset_id}/{file_uid}``.
When a binary file is opened, the URI is resolved on demand: a fresh
presigned S3 URL is fetched via ``getFileDetails`` and the file is
streamed to local storage.
"""

from __future__ import annotations

import logging
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


def updateFileInfoForRemoteFiles(doc_props: dict, cloud_dataset_id: str) -> None:
    """Rewrite a document's file_info locations to use ``ndic://`` URIs.

    MATLAB equivalent: ``ndi.cloud.sync.internal.updateFileInfoForRemoteFiles``

    Mutates *doc_props* in-place.  Sets each location to
    ``ndic://{dataset_id}/{file_uid}`` with ``location_type='ndicloud'``
    and ``ingest=0``, ``delete_original=0``.

    Handles both list-style and dict-style (MATLAB struct) ``file_info``
    and ``locations`` fields.

    Args:
        doc_props: ndi_document properties dict (as from JSON).
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

    Parses the ``ndic://`` URI, calls ``getFileDetails`` for a fresh
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
    from .api.files import getFile, getFileDetails

    dataset_id, file_uid = parse_ndic_uri(ndic_uri)

    if client is None:
        client = get_or_create_cloud_client()

    # Get fresh presigned URL
    details = getFileDetails(dataset_id, file_uid, client=client)
    download_url = details.get("downloadUrl", "")
    if not download_url:
        from .exceptions import CloudError

        raise CloudError(f"No downloadUrl in file details for {ndic_uri}. " f"Response: {details}")

    # Stream download to temp file, then atomic rename
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")

    logger.debug("Fetching cloud file %s -> %s", ndic_uri, target)
    success = getFile(download_url, tmp_path, timeout=300)

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

    Delegates to :meth:`CloudClient.from_env`, which checks for an
    existing valid token first, then falls back to username/password
    login.

    Returns:
        An authenticated :class:`CloudClient`.

    Raises:
        CloudAuthError: If credentials are missing or login fails.
    """
    from .client import CloudClient

    return CloudClient.from_env()


def updateFileInfoForLocalFiles(
    doc_props: dict,
    file_directory: str,
) -> None:
    """Update file_info locations to point to local files.

    MATLAB equivalent: ``ndi.cloud.sync.internal.updateFileInfoForLocalFiles``

    Mutates *doc_props* in-place.  For each file_info entry, replaces
    the location with the local file path ``{file_directory}/{uid}``
    and sets ``delete_original=1``, ``ingest=1``.

    Args:
        doc_props: ndi_document properties dict (as from JSON).
        file_directory: Directory where local files are stored.
    """
    import os

    files = doc_props.get("files")
    if not files or not isinstance(files, dict):
        return

    file_info = files.get("file_info")
    if file_info is None:
        return

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
            file_location = os.path.join(file_directory, uid)
            if os.path.isfile(file_location):
                loc["location"] = file_location
                loc["location_type"] = "file"
                loc["delete_original"] = 1
                loc["ingest"] = 1
            else:
                logger.warning(
                    "Local file does not exist for uid %s at %s",
                    uid,
                    file_location,
                )

        if loc_was_dict:
            fi["locations"] = loc_list[0]

    if was_dict:
        files["file_info"] = fi_list[0]


# Backward-compatible alias
rewrite_file_info_for_cloud = updateFileInfoForRemoteFiles


def series_member_uid(context: object) -> str:
    """The uid DID is really asking for, or ``""`` for an ordinary file.

    WHICH UID IS BEING ASKED FOR. On an ordinary file, ``source_path`` names
    it and its uid is the one in the ``ndic://`` reference. On a SERIES
    MEMBER it is not: a member has no location of its own, so DID passes the
    series MANIFEST's location as ``source_path`` and names the member in the
    context (DID-matlab#188).

    ``seriesName`` is what marks a call as a member fetch, and taking the
    uid on that condition rather than on "context carries a uid" is
    deliberate -- DID passes a ``uid`` for ordinary files too, where it is
    the files-table row rather than what the ``ndic://`` reference names.
    NDI-matlab's ``didsqlite.m`` states the same rule for the same reason.

    Reads defensively. The context is DID's to define and DID-matlab#186 is
    recent, so a missing key means "not a member", never an exception.
    """
    if not isinstance(context, dict):
        return ""
    if not str(context.get("seriesName", "") or ""):
        return ""
    return str(context.get("uid", "") or "")


def download_file_from_cloud(
    dest_path: str | Path,
    source_path: str,
    context: dict | None = None,
    *,
    client: CloudClient | None = None,
) -> None:
    """Retrieve a remote file for DID, satisfying its ``custom_file_handler``.

    DID downloads nothing itself, in either language. Both ``add_docs`` and
    ``open_doc`` take a ``custom_file_handler`` that a downstream package
    supplies; this is NDI's, and the counterpart of the
    ``@download_file_from_cloud`` handle NDI-matlab's ``didsqlite.m`` passes to
    ``add_docs`` and ``open_doc``.

    Note the argument order. DID calls ``handler(dest_path, source_path)`` --
    destination first -- while :func:`fetch_cloud_file` takes the URI first.
    This wrapper exists mostly to get that the right way round in one place.

    THE CONTEXT. DID dispatches with a third argument, a per-call dict
    carrying ``documentId``, ``filename``, ``uid``, ``mode`` and -- for a
    series member -- ``seriesName`` (DID-matlab#186, #188). It decides
    between the two- and three-argument forms by counting the handler's
    positional parameters, so a handler that declares only two is quietly
    called without the context and never learns which member it is being
    asked for. It would then fetch the MANIFEST a second time and store it
    under the member's uid, which DID refuses with
    ``DID:SQLITEDB:FileSeries:HandlerReturnedManifest`` -- and, where that
    guard cannot read the manifest's size to compare, does not refuse, so
    every later read of that member returns the manifest instead.

    ``client`` is keyword-only for the same counting rule: as a third
    positional parameter it would have absorbed the context DID passes.

    A location that is not an ``ndic://`` URI is left alone: DID only calls
    this for locations it has already decided are remote, and a scheme NDI
    does not serve should surface as "no file was produced" from DID rather
    than as a confusing parse error from here.

    Args:
        dest_path: Where DID expects the file to exist when this returns.
        source_path: The remote location recorded for the file. For a series
            member this is the MANIFEST's location, not the member's.
        context: DID's per-call context, or None when called two-argument.
        client: Authenticated client; falls back to the ambient one.

    Raises:
        CloudError: If the download fails. DID reports the failure against the
            location that produced it.
    """
    if not str(source_path).startswith(NDIC_SCHEME):
        return

    uri = str(source_path)
    member_uid = series_member_uid(context)
    if member_uid:
        # Same dataset, the member's uid in place of the manifest's. Built
        # rather than parsed out of any location, because the member has no
        # location to parse.
        dataset_id, _manifest_uid = parse_ndic_uri(uri)
        uri = f"{NDIC_SCHEME}{dataset_id}/{member_uid}"

    fetch_cloud_file(uri, dest_path, client=client)
