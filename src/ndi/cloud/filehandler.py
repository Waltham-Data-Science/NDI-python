"""
ndi.cloud.filehandler - On-demand cloud file fetching via ndic:// protocol.

MATLAB equivalents:
    +ndi/+cloud/+sync/+internal/updateFileInfoForRemoteFiles.m
    didsqlite.m:do_openbinarydoc (customFileHandler callback)

The ndic:// URI scheme provides stable references to cloud-hosted binary
files.  When a dataset is downloaded without ``sync_files=True``, document
file_info locations are rewritten to ``ndic://{dataset_id}/{file_uid}``.
When a binary file is opened, the URI is resolved on demand.

For an ordinary file the resolver calls ``getFileDetails`` once for a fresh
presigned URL. For a file series with many members -- the case that
motivates the batch path -- DID passes the document id in the per-call
context and every member's URL is served from a single ``/signed-url-set``
call cached in :mod:`.batch_signed_url`. See NDI-python#262.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .batch_signed_url import BatchSignedUrlLookup
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


#: Installed by :func:`watchFetches`. Module-level rather than a parameter
#: because DID fixes the file handler's signature -- it counts positional
#: parameters to decide between the two- and three-argument forms -- so
#: there is nowhere to thread one through from a caller.
_fetch_observer = None


@contextlib.contextmanager
def watchFetches(observer):
    """Report every on-demand cloud fetch to *observer* for the duration.

    *observer* is called as ``observer(event, uri, done, total)``, where
    *event* is ``"start"``, ``"chunk"`` or ``"done"``, sizes are bytes, and
    *total* is None when the server sent no Content-Length.

    Restores the previous observer on exit, including on an exception, so
    nested use and a failed launch both leave the hook as they found it.

    Fetches happen on whichever thread asked for the file -- the launch
    thread for the cell table and the gene list, a _TileFetcher worker for
    a tile -- so an observer that renders anything owns its own locking.
    """
    global _fetch_observer
    previous = _fetch_observer
    _fetch_observer = observer
    try:
        yield
    finally:
        _fetch_observer = previous


def fetch_cloud_file(
    ndic_uri: str,
    target_path: str | Path,
    client: CloudClient | None = None,
    *,
    ndi_document_id: str = "",
    series_name: str = "",
    batch_lookup: BatchSignedUrlLookup | None = None,
) -> bool:
    """Download a cloud file on demand.

    Parses the ``ndic://`` URI. When *ndi_document_id* is given, first
    consults the per-document signed-URL cache (:mod:`.batch_signed_url`),
    which turns one API call per uid into one call per (dataset, document,
    series) scope. On a cache miss for the uid -- or when no document id is
    available -- falls back to a per-uid ``getFileDetails`` call for a fresh
    presigned URL. Streams the file to *target_path* using an atomic write
    (download to ``.tmp``, then rename) to avoid partial files.

    Args:
        ndic_uri: An ``ndic://dataset_id/file_uid`` URI.
        target_path: Local path where the file should be saved.
        client: Authenticated :class:`CloudClient`.  If *None*,
            :func:`get_or_create_cloud_client` is used as a fallback.
        ndi_document_id: The NDI document id (``data.base.id``) whose
            signed-URL set covers this uid. Empty disables the batch path.
        series_name: When *ndi_document_id* is set, restrict the batch scope
            to one file series. Empty scopes the batch to the whole document.
        batch_lookup: Cache instance to use. Defaults to the process-wide
            one. Present so tests can inject their own.

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

    download_url = ""
    if ndi_document_id:
        # Batch path first. Empty means the batch could not answer for this
        # uid; fall back per uid so the read still succeeds.
        from .batch_signed_url import get_default

        lookup = batch_lookup if batch_lookup is not None else get_default()
        download_url = lookup.lookup(
            dataset_id,
            ndi_document_id,
            series_name,
            file_uid,
            client=client,
        )

    if not download_url:
        details = getFileDetails(dataset_id, file_uid, client=client)
        download_url = details.get("downloadUrl", "")
        if not download_url:
            from .exceptions import CloudError

            raise CloudError(f"No downloadUrl in file details for {ndic_uri}. Response: {details}")

    # Stream download to temp file, then atomic rename
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")

    logger.debug("Fetching cloud file %s -> %s", ndic_uri, target)
    observer = _fetch_observer
    if observer is None:
        success = getFile(download_url, tmp_path, timeout=300)
    else:
        observer("start", ndic_uri, 0, None)
        try:
            success = getFile(
                download_url,
                tmp_path,
                timeout=300,
                progress=lambda done, total: observer("chunk", ndic_uri, done, total),
            )
        finally:
            observer("done", ndic_uri, 0, None)

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


def _ndic_location_record(cloud_dataset_id: str, file_uid: str) -> dict:
    """One ``locations`` entry pointing at ``file_uid`` in the cloud.

    The same record :meth:`ndi.document.ndi_document.add_file` builds for an
    ``ndic://`` location, spelled out here because this function works on a
    properties DICT rather than a document -- as updateFileInfoForRemoteFiles
    does, and as the whole download pipeline does, so that both rewrites
    mutate the same objects in place. ``test_the_record_matches_add_files``
    pins the two together so this cannot drift.

    The uid inside the URI is the file's ORIGINAL uid, the one the cloud
    knows it by. The record gets a fresh uid of its own, exactly as add_file
    mints one: DID passes only the location STRING to the handler, and a
    series member's uid comes from the context.
    """
    from ..ido import ndi_ido

    return {
        "delete_original": 0,
        "uid": ndi_ido().id,
        "location": f"{NDIC_SCHEME}{cloud_dataset_id}/{file_uid}",
        "parameters": "",
        "location_type": "ndicloud",
        "ingest": 0,
    }


def reconstructSeriesIngestLocations(
    doc_props: dict,
    file_directory: str,
    cloud_dataset_id: str,
) -> None:
    """Rebuild a downloaded series' ingest_locations from its manifest.

    MATLAB equivalent:
    ``ndi.cloud.sync.internal.reconstructSeriesIngestLocations``

    ``ingest_locations`` is transient authoring data that DID strips before
    storing a document, so a cloud round trip returns ``n_present`` with no
    way to locate any of the uids it counts. DID refuses exactly that shape
    (DID-matlab#185: "declares N present members but records no
    ingest_locations"), so without this every ``sync_files=True`` download
    would fail on the first document carrying a populated series -- and fail
    at ``add_docs``, losing the document rather than merely mis-resolving it.

    The manifest bytes are on disk by the time this runs, because the file
    pass has already written them, so the uid of each present slot can be
    read back and the entries rebuilt.

    Every reconstructed entry is ``ingest=0`` and ``delete_original=0``. The
    point is to satisfy the guard, not to pull 28,000 members down at add
    time -- the members stay on the cloud, which is what a series is for.

    A series whose manifest cannot be located or read is left alone, so the
    guard fires on ``add_docs``. That is the right signal when the download
    itself was incomplete: better to refuse the document than to store a
    series recording half its members.

    Mutates *doc_props* in place.

    Args:
        doc_props: ndi_document properties dict (as from JSON).
        file_directory: Directory the file pass downloaded into.
        cloud_dataset_id: Used to build each member's ``ndic://`` location.
    """
    import os

    from did.file import read_series_manifest

    files = doc_props.get("files")
    if not isinstance(files, dict):
        return
    raw_series_info = files.get("series_info")
    series_info = _as_list(raw_series_info)
    if not series_info:
        return
    file_info = _as_list(files.get("file_info"))

    for entry in series_info:
        if not isinstance(entry, dict):
            continue
        try:
            n_present = int(entry.get("n_present", 0) or 0)
        except (TypeError, ValueError):
            continue
        if n_present <= 0:
            continue
        if entry.get("ingest_locations"):
            continue

        manifest_uid = _manifest_uid(file_info, entry.get("name", ""))
        if not manifest_uid:
            continue
        manifest_path = os.path.join(file_directory, manifest_uid)
        if not os.path.isfile(manifest_path):
            continue

        try:
            manifest = read_series_manifest(manifest_path)
        except Exception as error:  # noqa: BLE001 - a bad manifest is not ours to fix
            logger.warning(
                'Cannot read the manifest for series "%s" at %s: %s',
                entry.get("name", ""),
                manifest_path,
                error,
            )
            continue

        ingest_locations = []
        for slot, member_uid in enumerate(manifest.get("uids", []), start=1):
            # Slots are ONE-BASED here, as they are throughout DID's series
            # API: member NAME_1 is index 1, and _open_series_member hands
            # that number straight to read_series_manifest_uid. An empty uid
            # is an absent member; a sparse series is the ordinary case.
            if not member_uid:
                continue
            ingest_locations.append(
                {
                    "index": slot,
                    "uid": member_uid,
                    "location": f"{NDIC_SCHEME}{cloud_dataset_id}/{member_uid}",
                    "location_type": "ndicloud",
                    "ingest": 0,
                    "delete_original": 0,
                }
            )

        if ingest_locations:
            entry["ingest_locations"] = ingest_locations

    # Written back in the shape it arrived in. The entries were mutated in
    # place, so this only matters for the one-element-as-bare-object case.
    if isinstance(raw_series_info, dict):
        files["series_info"] = series_info[0]


def _as_list(value) -> list:
    """A ``file_info``/``locations``/``series_info`` field as a list.

    MATLAB's jsonencode writes a one-element struct array as a bare object.
    Same normalisation, and same reason, as in ndi.cloud.internal.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


def _manifest_uid(file_info: list, series_name: str) -> str:
    """The uid of the manifest file for the series called ``series_name``.

    A series named NAME has an ordinary file_info entry whose ``name`` is
    NAME; its first location's uid is the manifest's, so the downloaded copy
    is at ``file_directory/<that uid>``. First location deliberately: a
    manifest carries a second, ``ndic://`` one by the time this runs, and it
    is the ORIGINAL uid that names the downloaded file.
    """
    wanted = str(series_name or "")
    for entry in file_info:
        if not isinstance(entry, dict) or str(entry.get("name", "")) != wanted:
            continue
        locations = _as_list(entry.get("locations"))
        if not locations or not isinstance(locations[0], dict):
            return ""
        return str(locations[0].get("uid", "") or "")
    return ""


def _declared_series_names(doc_props: dict) -> set:
    """Lowercased names of the file series this document's class declares.

    Asked of did.document rather than read out of files.file_series here:
    which names are series is DID's question, the declaration is a property
    of the document CLASS, and the matching is case-insensitive in a way
    worth having in one place. Document() wraps the dict without copying it,
    so this costs nothing and sees exactly what we are about to edit.

    A document whose class declares no series -- almost all of them -- gives
    an empty set, and nothing below changes.
    """
    try:
        from did.document import Document
    except ImportError:  # pragma: no cover - did is a hard dependency
        return set()
    try:
        return {str(name).lower() for name in Document(doc_props).series_names()}
    except Exception:  # noqa: BLE001 - a malformed document is not ours to fix
        return set()


def updateFileInfoForLocalFiles(
    doc_props: dict,
    file_directory: str,
    cloud_dataset_id: str = "",
) -> None:
    """Update file_info locations to point to local files.

    MATLAB equivalent: ``ndi.cloud.sync.internal.updateFileInfoForLocalFiles``

    Mutates *doc_props* in-place.  For each file_info entry, replaces
    the location with the local file path ``{file_directory}/{uid}``
    and sets ``delete_original=1``, ``ingest=1``.

    SERIES, when ``cloud_dataset_id`` is given. Two things happen that do
    not for an ordinary file:

    A series MANIFEST keeps the cloud reference it came from, as a second
    location beside the local copy. Its members are still on the cloud --
    left there deliberately, so that opening a dataset does not drag down a
    28,000-member series -- and a member has no location of its own, so DID
    resolves one by handing the MANIFEST's location to the file handler with
    the member's uid in the context. That location is the only thing telling
    the handler where to look; with the local path alone the handler is
    given something that does not start with ``ndic://`` and every member of
    a downloaded series is unreadable. See NDI-matlab#966.

    And the series' ``ingest_locations`` are rebuilt from the downloaded
    manifest, which is what lets the document be added at all. See
    :func:`reconstructSeriesIngestLocations`.

    MATLAB carries files.series_info across a ``reset_file_info`` it makes
    here (NDI-matlab#945). There is nothing to carry here: this edits the
    properties dict where it stands and never resets, so the per-series
    record survives on its own.

    Args:
        doc_props: ndi_document properties dict (as from JSON).
        file_directory: Directory where local files are stored.
        cloud_dataset_id: Cloud dataset id. Without it, series get neither
            the manifest's second location nor rebuilt ingest_locations,
            and a document with a populated series will be refused by DID
            on the following add.
    """
    import os

    series_names = _declared_series_names(doc_props)

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

        extra_locations: list[dict] = []
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
                # Manifests only. Every other file is already here, and a
                # second location on each would be rows to no purpose.
                if (
                    cloud_dataset_id
                    and str(fi.get("name", "")).lower() in series_names
                    and not any(
                        isinstance(other, dict)
                        and str(other.get("location", "")).startswith(NDIC_SCHEME)
                        for other in loc_list
                    )
                ):
                    extra_locations.append(_ndic_location_record(cloud_dataset_id, uid))
            else:
                logger.warning(
                    "Local file does not exist for uid %s at %s",
                    uid,
                    file_location,
                )

        loc_list.extend(extra_locations)

        # A manifest that gained its cloud reference now has two locations,
        # so it cannot go back as a bare dict -- doing so would drop the
        # very location the members are resolved through.
        if loc_was_dict and len(loc_list) == 1:
            fi["locations"] = loc_list[0]
        elif loc_was_dict:
            fi["locations"] = loc_list

    if was_dict:
        files["file_info"] = fi_list[0]

    if cloud_dataset_id:
        reconstructSeriesIngestLocations(doc_props, file_directory, cloud_dataset_id)


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

    # Pass DID's context through to fetch_cloud_file so the batch signed-URL
    # cache can key on it. Without documentId, batch lookup is skipped and
    # every uid pays a fresh getFileDetails call -- the naive path.
    ndi_document_id = ""
    series_name = ""
    if isinstance(context, dict):
        ndi_document_id = str(context.get("documentId", "") or "")
        series_name = str(context.get("seriesName", "") or "")

    fetch_cloud_file(
        uri,
        dest_path,
        client=client,
        ndi_document_id=ndi_document_id,
        series_name=series_name,
    )
