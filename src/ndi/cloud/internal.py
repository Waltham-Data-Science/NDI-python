"""
ndi.cloud.internal - Internal utilities for NDI Cloud operations.

MATLAB equivalents: +ndi/+cloud/+internal/*.m,
    +ndi/+cloud/+sync/+internal/*.m
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .exceptions import CloudOrganizationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .client import CloudClient


def listRemoteDocumentIds(
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> dict[str, str]:
    """Return a mapping of ``ndiId → apiId`` for all remote documents.

    Paginates through the full document list and extracts the IDs.

    Returns:
        Dict mapping NDI document IDs to their API IDs.
    """
    from .api import documents as docs_api

    all_docs = docs_api.listDatasetDocumentsAll(cloud_dataset_id, client=client)
    mapping: dict[str, str] = {}
    for doc in all_docs.data:
        ndi_id = doc.get("ndiId", doc.get("id", ""))
        api_id = doc.get("id", doc.get("_id", ""))
        if ndi_id:
            mapping[ndi_id] = api_id
    return mapping


def getCloudDatasetIdForLocalDataset(
    dataset: Any,
    *,
    client: CloudClient | None = None,
) -> tuple[str, dict | None]:
    """Resolve the cloud dataset ID from a local dataset.

    Looks for a ``dataset_remote`` document in the local database
    that links this dataset to a cloud dataset.

    Args:
        dataset: A local :class:`~ndi.dataset.ndi_dataset` instance.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(cloud_dataset_id, remote_doc)``. When the dataset has
        never been uploaded, that is ``("", None)``.

    Raises:
        CloudSyncError: More than one ``dataset_remote`` document is present.
            MATLAB raises ``NDICloud:Sync:MultipleCloudDatasetId`` here and
            so do we: the caller is about to decide which remote dataset to
            write to, and picking one of several arbitrarily is worse than
            stopping.

    Note:
        This searches through :meth:`ndi.dataset.ndi_dataset.database_search`,
        which also covers linked sessions, matching MATLAB. The related
        :meth:`ndi.dataset.ndi_dataset.is_in_cloud` searches only the
        dataset's own session and never raises, likewise matching MATLAB --
        the two differ on purpose, because one resolves a sync target and the
        other answers a status question while a tree of datasets is listed.
    """
    from ndi.query import ndi_query

    # NOT wrapped in try/except. An unreadable database is not the same
    # answer as "never uploaded", and reporting it as one is what made this
    # function return ("", None) for every dataset that had in fact been
    # uploaded: it reached for a `database` attribute that ndi_dataset does
    # not have, and a bare `except Exception: pass` swallowed the
    # AttributeError. Callers act on a "" by CREATING a new remote dataset,
    # so a swallowed error here silently duplicates datasets in the cloud.
    results = dataset.database_search(ndi_query("").isa("dataset_remote"))

    if not results:
        return "", None
    if len(results) > 1:
        from .exceptions import CloudSyncError

        raise CloudSyncError(
            f"Found more than one remote cloud dataset id ({len(results)}) "
            f"for the local dataset: {getattr(dataset, 'path', dataset)!r}."
        )

    doc = results[0]
    props = doc.document_properties if hasattr(doc, "document_properties") else doc
    cloud_id = ""
    if isinstance(props, dict):
        cloud_id = props.get("dataset_remote", {}).get("dataset_id", "")
    return cloud_id, doc


def createRemoteDatasetDoc(
    cloud_dataset_id: str,
    dataset: Any,
) -> Any:
    """Create a ``dataset_remote`` document linking to the cloud.

    Args:
        cloud_dataset_id: The cloud-side dataset ID.
        dataset: Local dataset to add the document to.

    Returns:
        The created ndi_document instance.
    """
    from ndi.document import ndi_document

    doc = ndi_document("dataset_remote")
    doc._set_nested_property("dataset_remote.dataset_id", cloud_dataset_id)
    return doc


def listLocalDocuments(dataset: Any) -> tuple[list[Any], list[str]]:
    """Retrieve all documents and their IDs from a local dataset.

    MATLAB equivalent: +sync/+internal/listLocalDocuments.m

    Returns:
        Tuple of (documents, document_ids).
    """
    from ndi.query import ndi_query

    # NOT wrapped in try/except, and NOT `dataset.session`: ndi_dataset has
    # no `session` attribute, so the previous version raised AttributeError
    # on every real dataset and a bare `except Exception` turned that into an
    # empty document list. Callers -- validateSync and documentDifference --
    # then reported every remote document as "remote only" and every local
    # one as absent. An empty list must mean an empty dataset, nothing else.
    docs = dataset.database_search(ndi_query("").isa("base"))

    ids = []
    for d in docs:
        p = d.document_properties if hasattr(d, "document_properties") else d
        if isinstance(p, dict):
            ids.append(p.get("base", {}).get("id", ""))
    return docs, ids


#: Where a sync stages downloaded binaries before the database ingests them.
#: Relative to the dataset folder, mirroring
#: ``ndi.cloud.sync.internal.Constants.FileSyncLocation``.
#:
#: TEMPORARY, and deliberately NOT DID's file store. DID ingests a file by
#: copying it from the location a document records into ``FileDir/<uid>`` and
#: then deleting the original, so staging is what gives the ingest something
#: to copy FROM. Downloading straight into ``FileDir`` skips ingestion
#: altogether: the bytes are findable by uid, but no files-table row is
#: written and the document's file_info still points at the cloud.
FILE_SYNC_LOCATION = Path("download") / "files"


def _as_list(value: Any) -> list[Any]:
    """A ``file_info`` or ``locations`` field as a list, whatever arrived.

    MATLAB's jsonencode writes a one-element struct array as a bare object,
    so a document with exactly one file comes back with ``file_info`` as a
    dict rather than a list of one. Iterating that dict yields its KEYS --
    strings -- which are then skipped as "not a dict", so the document's
    only file is silently invisible. filehandler.py normalises the same two
    fields for the same reason.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


def getFileUidsFromDocuments(documents: list[Any]) -> list[str]:
    """Extract unique file UIDs from a list of documents.

    MATLAB equivalent: +sync/+internal/getFileUidsFromDocuments.m

    Walks ``files.file_info(j).locations(k).uid`` -- every location of every
    file -- because that is where a document records what it has. The
    top-level ``file_uid`` is accepted as well: some cloud payloads carry
    one, and it costs nothing to keep.

    ORDER IS FIRST-SEEN, not arbitrary. MATLAB returns
    ``unique(..., 'stable')``, and a set here made the order depend on
    Python's string hashing -- so the download order, the log, and any
    report built from it differed between runs of the same input for no
    reason. Deduplicated with a dict, which preserves insertion order.
    """
    uids: dict[str, None] = {}
    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        files = props.get("files")
        if isinstance(files, dict):
            for fi in _as_list(files.get("file_info")):
                if not isinstance(fi, dict):
                    continue
                for loc in _as_list(fi.get("locations")):
                    if not isinstance(loc, dict):
                        continue
                    uid = str(loc.get("uid", "") or "")
                    if uid:
                        uids[uid] = None
        fuid = str(props.get("file_uid", "") or "")
        if fuid:
            uids[fuid] = None
    return list(uids)


def filesNotYetUploaded(
    file_manifest: list[dict[str, Any]],
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> list[dict[str, Any]]:
    """Filter a file manifest to only files not yet in the cloud.

    MATLAB equivalent: ``+sync/+internal/filesNotYetUploaded.m``

    A file needs uploading if the remote dataset does not list it at all,
    **or if it is listed and its ``uploaded`` status is false**. Presence in
    the listing is not the same as presence of the bytes: the cloud records
    a file when its upload is registered, and ``uploaded`` is what says the
    transfer finished.

    Matching on the uid alone -- which is what this did -- treats a
    registered-but-unsent file as done, so the document is recorded as
    synced while its binary is not on the cloud. Downstream consumers
    (export, mirror, twoWaySync) then 404, and nothing re-queues the file
    because the sync index says it is finished (NDI-matlab#805).

    A remote entry that OMITS ``uploaded`` is re-queued rather than assumed
    complete, with a warning. The status cannot be confirmed, and the
    asymmetry is deliberate: a needless re-upload costs bandwidth, while a
    wrongly skipped one costs the binary.
    """
    from .api.files import listFilesAll

    try:
        # getDataset no longer embeds the files array; enumerate via the
        # keyset files endpoint (NDI-matlab#1004).
        remote_files = listFilesAll(cloud_dataset_id, client=client).data
    except Exception:
        return file_manifest  # can't check, assume all need upload

    remote_by_uid: dict[str, dict[str, Any]] = {}
    for rf in remote_files:
        uid = rf.get("uid", "") if hasattr(rf, "get") else ""
        if uid:
            remote_by_uid[uid] = rf

    needs_upload: list[dict[str, Any]] = []
    for entry in file_manifest:
        uid = entry.get("uid", "")
        remote = remote_by_uid.get(uid)
        if remote is None:
            needs_upload.append(entry)
            continue
        if "uploaded" not in remote:
            logger.warning(
                "Remote file entry for UID %s lacks an 'uploaded' field; "
                "conservatively re-queuing it for upload.",
                uid,
            )
            needs_upload.append(entry)
            continue
        if not remote.get("uploaded"):
            needs_upload.append(entry)
    return needs_upload


def validateSync(
    dataset: Any,
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Compare local dataset with remote to identify sync discrepancies.

    MATLAB equivalent: +cloud/+sync/validate.m

    Returns:
        Report dict with local_only, remote_only, common, mismatched IDs.
    """
    _, local_ids = listLocalDocuments(dataset)
    remote_id_map = listRemoteDocumentIds(cloud_dataset_id, client=client)

    local_set = set(local_ids)
    remote_set = set(remote_id_map.keys())

    return {
        "local_only_ids": list(local_set - remote_set),
        "remote_only_ids": list(remote_set - local_set),
        "common_ids": list(local_set & remote_set),
        "local_count": len(local_set),
        "remote_count": len(remote_set),
    }


def datasetSessionIdFromDocs(documents: list[Any]) -> str:
    """Extract the unique dataset session ID from a list of documents.

    MATLAB equivalent: +sync/+internal/datasetSessionIdFromDocs.m
    """
    session_ids: set[str] = set()
    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            sid = props.get("base", {}).get("session_id", "")
            if sid:
                session_ids.add(sid)

    if len(session_ids) == 1:
        return session_ids.pop()
    return ""


def duplicateDocuments(
    cloud_dataset_id: str,
    *,
    delete_duplicates: bool = True,
    maximum_delete_batch_size: int = 1000,
    verbose: bool = False,
    client: CloudClient | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find and optionally remove duplicate documents in a cloud dataset.

    MATLAB equivalent: ``ndi.cloud.internal.duplicateDocuments``

    Duplicates are documents sharing the same ``ndiId`` (or ``name``
    as fallback) but with different cloud ``id`` values.  The document
    with the alphabetically earliest ``id`` is kept as the original.

    Args:
        cloud_dataset_id: The cloud dataset ID to scan.
        delete_duplicates: If True, delete identified duplicates.
        maximum_delete_batch_size: Max documents per bulk delete call.
        verbose: Print progress messages.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(duplicate_docs, original_docs)``.
    """
    from .api import documents as docs_api

    if verbose:
        print("Searching for all documents...")
    all_docs_result = docs_api.listDatasetDocumentsAll(cloud_dataset_id, client=client)
    all_docs = all_docs_result.data if hasattr(all_docs_result, "data") else all_docs_result
    if verbose:
        print("Done.")

    if not all_docs:
        return [], []

    # Group by ndiId (or name as fallback) — keep the one with earliest id
    doc_map: dict[str, dict[str, Any]] = {}
    duplicate_docs: list[dict[str, Any]] = []

    for doc in all_docs:
        group_key = doc.get("ndiId", "") or doc.get("name", "")
        if not group_key:
            continue

        if group_key not in doc_map:
            doc_map[group_key] = doc
        else:
            existing = doc_map[group_key]
            current_id = doc.get("id", doc.get("_id", ""))
            existing_id = existing.get("id", existing.get("_id", ""))
            if current_id < existing_id:
                duplicate_docs.append(existing)
                doc_map[group_key] = doc
            else:
                duplicate_docs.append(doc)

    original_docs = list(doc_map.values())

    if delete_duplicates and duplicate_docs:
        if verbose:
            print(f"Found {len(duplicate_docs)} duplicates to delete.")

        doc_ids_to_delete = [
            d.get("id", d.get("_id", "")) for d in duplicate_docs if d.get("id", d.get("_id", ""))
        ]

        # Delete in batches
        for i in range(0, len(doc_ids_to_delete), maximum_delete_batch_size):
            batch = doc_ids_to_delete[i : i + maximum_delete_batch_size]
            batch_num = i // maximum_delete_batch_size + 1
            total_batches = (
                len(doc_ids_to_delete) + maximum_delete_batch_size - 1
            ) // maximum_delete_batch_size
            if verbose:
                print(f"Deleting batch {batch_num} of {total_batches}...")
            try:
                docs_api.bulkDeleteDocuments(cloud_dataset_id, batch, client=client)
            except Exception as exc:
                if verbose:
                    print(f"  Warning: batch delete failed: {exc}")
            if verbose:
                print(f"Batch {batch_num} deleted.")

        if verbose:
            print("All duplicate documents deleted.")
    else:
        if not duplicate_docs:
            if verbose:
                print("No duplicate documents found.")
        elif verbose:
            print(f"Found {len(duplicate_docs)} duplicates, but deletion was not requested.")

    return duplicate_docs, original_docs


def formatApiError(response: Any) -> str:
    """Build a human-readable message describing a failed API call.

    MATLAB equivalent: ndi.cloud.internal.formatApiError

    Args:
        response: Whatever the failing call had to hand -- a
            ``requests.Response``, an :class:`~ndi.cloud.client.APIResponse`,
            an already-parsed body (dict or str), or ``None``.

    Returns:
        A non-empty message.  ``"HTTP 400 Bad Request - MATLAB license
        required"`` when both halves are available, whichever half is
        available on its own otherwise, and ``"no response from server"``
        / ``"unknown error"`` when nothing usable is present.

    The MATLAB version exists because #624 was a crash inside the error
    path: the code that formatted an API failure assumed a struct body
    with a ``message`` field, so a response that carried a string body,
    no body, or a differently-shaped error replaced the real failure with
    a MATLAB error about indexing.  Every branch here is therefore
    tolerant -- an error formatter that can itself fail hides the error
    it was called to report.
    """
    if response is None:
        return "no response from server"

    status_part = ""
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and status:
        status_part = f"HTTP {status}"
        reason = getattr(response, "reason", "")
        if isinstance(reason, str) and reason:
            status_part = f"{status_part} {reason}"

    body: Any = response
    if hasattr(response, "data"):  # APIResponse
        body = response.data
    elif hasattr(response, "json"):  # requests.Response
        try:
            body = response.json()
        except Exception:
            body = getattr(response, "text", "")

    body_part = ""
    if isinstance(body, dict):
        for key in ("message", "error"):
            value = body.get(key)
            if value:
                body_part = str(value)
                break
    elif isinstance(body, str):
        body_part = body

    if status_part and body_part:
        return f"{status_part} - {body_part}"
    if status_part:
        return status_part
    if body_part:
        return body_part
    return "unknown error"


# ---------------------------------------------------------------------------
# Organizations
#
# MATLAB equivalents: +ndi/+cloud/+internal/normalizeOrganizations.m,
#   setOrganizations.m, getOrganizations.m, chooseOrganization.m,
#   userIsAdmin.m
#
# An NDI Cloud user has one token but may belong to several organizations,
# so there is no single "logged-in organization". The list is cached at
# login; any operation that needs one organization asks chooseOrganization.
# ---------------------------------------------------------------------------

#: Environment variable holding the cached organization list as JSON. Same
#: name as NDI-matlab uses, alongside NDI_CLOUD_TOKEN.
ORGANIZATIONS_ENV_VAR = "NDI_CLOUD_ORGANIZATIONS"


def normalizeOrganizations(raw: Any) -> list[dict[str, Any]]:
    """Normalize an NDI Cloud organizations list.

    MATLAB equivalent: ndi.cloud.internal.normalizeOrganizations

    Converts the ``organizations`` field of an NDI Cloud login or
    ``/users/me`` response (or a previously normalized list, or its cached
    JSON) into a list of dicts with the keys:

        id               - (str) the organization id
        name             - (str) the organization name ('' if none)
        canUploadDataset - (bool) whether datasets may be created in it

    RAW may be a list of dicts, a single dict, or empty. Entries without an
    id are dropped. An absent canUploadDataset is treated as True so that an
    older API response never blocks an upload on the client side; the server
    still enforces the permission.

    Raises:
        CloudOrganizationError: ``NDI:Cloud:InvalidOrganizations`` if RAW is
            neither a list nor a dict.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        items: list[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise CloudOrganizationError(
            "NDI:Cloud:InvalidOrganizations",
            "Organizations must be a list of dicts or a dict.",
        )

    organizations: list[dict[str, Any]] = []
    for org in items:
        if not isinstance(org, dict):
            continue
        org_id = org.get("id")
        if org_id is None or str(org_id) == "":
            continue
        name = org.get("name")
        can_upload = org.get("canUploadDataset")
        organizations.append(
            {
                "id": str(org_id),
                "name": "" if name is None else str(name),
                "canUploadDataset": True if can_upload is None else bool(can_upload),
            }
        )
    return organizations


def setOrganizations(organizations: Any = None) -> None:
    """Cache the logged-in user's NDI Cloud organizations.

    MATLAB equivalent: ndi.cloud.internal.setOrganizations

    Stores the list of organizations the current NDI Cloud user belongs to,
    so callers can offer a choice by name without another round trip to the
    server. ORGANIZATIONS is the ``organizations`` field of a login or
    ``/users/me`` response, or a list as returned by :func:`getOrganizations`.

    The list is stored as JSON in the ``NDI_CLOUD_ORGANIZATIONS`` environment
    variable, alongside ``NDI_CLOUD_TOKEN``, for the life of the process.

    ``setOrganizations(None)`` (or an empty list) clears the cache. This is
    what :func:`ndi.cloud.auth.logout` does.
    """
    normalized = normalizeOrganizations(organizations)
    if normalized:
        os.environ[ORGANIZATIONS_ENV_VAR] = json.dumps(normalized)
    else:
        os.environ.pop(ORGANIZATIONS_ENV_VAR, None)


def _cachedOrganizations() -> list[dict[str, Any]]:
    """The cached organization list, or [] if absent or unreadable. No network."""
    cached = os.environ.get(ORGANIZATIONS_ENV_VAR, "")
    if not cached:
        return []
    try:
        return normalizeOrganizations(json.loads(cached))
    except (ValueError, CloudOrganizationError):
        return []


def _unwrap(answer: Any) -> Any:
    """The payload of an API answer, whether or not it is an APIResponse."""
    return getattr(answer, "data", answer)


def getOrganizations(
    *,
    refresh: bool = False,
    client: CloudClient | None = None,
) -> list[dict[str, Any]]:
    """The organizations the logged-in NDI Cloud user belongs to.

    MATLAB equivalent: ndi.cloud.internal.getOrganizations

    Returns a list of dicts with keys ``id``, ``name`` and
    ``canUploadDataset`` (see :func:`normalizeOrganizations`), one per
    organization the current user belongs to, in the order the server
    returned them.

    The list is read from the cache written at login (:func:`setOrganizations`).
    If the cache is empty or unreadable, the list is fetched from
    :func:`ndi.cloud.api.users.me` (which authenticates as needed) and cached.

    Args:
        refresh: Always fetch a fresh list from the server and update the
            cache; use this if the user may have been added to an
            organization since login.
        client: Authenticated cloud client (auto-created if omitted).
    """
    if not refresh:
        cached = _cachedOrganizations()
        if cached:
            return cached

    from .api import users as users_api

    info = _unwrap(users_api.me(client=client))
    raw = info.get("organizations") if isinstance(info, dict) else None
    organizations = normalizeOrganizations(raw)
    setOrganizations(organizations)
    return organizations


def _haveActiveToken() -> bool:
    """True if this process holds an unexpired NDI Cloud token. No network."""
    from .auth import isTokenExpired

    token = os.environ.get("NDI_CLOUD_TOKEN", "")
    return bool(token) and not isTokenExpired(token)


def userIsAdmin(*, client: CloudClient | None = None) -> bool:
    """Whether the logged-in NDI Cloud user is an administrator.

    MATLAB equivalent: ndi.cloud.internal.userIsAdmin

    Returns True if a user is logged in (there is an active token, or a
    CLIENT was given) and :func:`ndi.cloud.api.users.me` reports
    ``isAdmin``. Returns False when no one is logged in or the lookup
    fails; this never logs in.

    NDI Cloud lets administrators create datasets in any organization they
    belong to, regardless of that organization's canUploadDataset flag.
    """
    if client is None and not _haveActiveToken():
        return False
    try:
        from .api import users as users_api

        info = _unwrap(users_api.me(client=client))
    except Exception:  # noqa: BLE001 - "could not tell" is not an admin
        return False
    return isinstance(info, dict) and bool(info.get("isAdmin"))


def _stdinIsInteractive() -> bool:
    """True when a person can answer a prompt on standard input."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _consoleChoose(labels: list[str], prompt: str) -> int | None:
    """Ask on the console for one of LABELS; its 0-based index, or None.

    The list is numbered from 1, as a person counts. An empty answer, or the
    end of input, cancels.
    """
    print(prompt)
    for number, label in enumerate(labels, start=1):
        print(f"  {number}. {label}")
    while True:
        try:
            answer = input(f"Enter 1-{len(labels)} (empty to cancel): ").strip()
        except EOFError:
            return None
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(labels):
            return int(answer) - 1
        print(f"Please enter a number from 1 to {len(labels)}.")


def _describeOrganization(organization: dict[str, Any]) -> str:
    if not organization["name"]:
        return f"(no name) ({organization['id']})"
    return f'"{organization["name"]}" ({organization["id"]})'


def _availableList(organizations: list[dict[str, Any]]) -> str:
    return ", ".join(_describeOrganization(o) for o in organizations)


def chooseOrganization(
    organization_name: str = "",
    organization_id: str = "",
    *,
    require_upload: bool = False,
    interactive: bool | None = None,
    always_ask: bool = False,
    prompt_string: str = "Select an organization:",
    chooser: Callable[[list[str], str], int | None] | None = None,
    client: CloudClient | None = None,
) -> tuple[str, str]:
    """Decide which of the user's NDI Cloud organizations to act on.

    MATLAB equivalent: ndi.cloud.internal.chooseOrganization

    NDI Cloud users may belong to several organizations, so any operation
    that needs one (for example, creating a dataset) must decide which. This
    function makes that decision from the user's organization list
    (:func:`getOrganizations`), in this order:

      1. If ORGANIZATION_NAME or ORGANIZATION_ID is given, it is matched
         against the user's organizations and returned. When logged in, an
         unknown value triggers one refresh of the list from the server
         before failing, in case the user was added to an organization
         after login.
      2. Otherwise, if exactly one organization qualifies, it is returned
         (unless ALWAYS_ASK is true).
      3. Otherwise, if INTERACTIVE is true, the user picks one by name.
      4. Otherwise an error is raised that lists the available organizations
         by name and id, so the caller can pass one explicitly.

    When REQUIRE_UPLOAD is true, only organizations in which the user may
    create datasets qualify: those with canUploadDataset set, or any of the
    user's organizations if the user is an NDI Cloud administrator (as on
    the server). The administrator check (:func:`userIsAdmin`) is only made
    when canUploadDataset would exclude an organization.

    Args:
        organization_name: Name of the organization to use. Matched
            case-sensitively. Mutually exclusive with ORGANIZATION_ID.
        organization_id: Id of the organization to use.
        require_upload: Only consider organizations that allow dataset
            upload.
        interactive: Allow asking the user when a choice is needed.
            Default (None): true when standard input is a terminal.
        always_ask: Ask even when only one organization qualifies. Ignored
            when not interactive.
        prompt_string: Prompt shown when asking.
        chooser: Called as ``chooser(labels, prompt_string)`` to ask; returns
            the 0-based index of the chosen label, or None to cancel.
            Default: a numbered prompt on the console.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(organization_id, organization_name)``; the name is ''
        if the organization has none.

    Raises:
        CloudOrganizationError: with the MATLAB identifier of the failure --
            ``NDI:Cloud:OrganizationArguments``, ``NDI:Cloud:NoOrganizations``,
            ``NDI:Cloud:UnknownOrganization``,
            ``NDI:Cloud:AmbiguousOrganization``,
            ``NDI:Cloud:OrganizationCannotUpload``,
            ``NDI:Cloud:NoUploadableOrganization``,
            ``NDI:Cloud:OrganizationRequired``, or
            ``NDI:CloudDialog:UserCanceled`` when the user cancels.

    Python-specific Notes:
        MATLAB asks in a dialog when running in the desktop. Python asks on
        the console when standard input is a terminal, or through CHOOSER
        (the Qt navigator passes its own list dialog).
    """
    if interactive is None:
        interactive = _stdinIsInteractive()

    if organization_name and organization_id:
        raise CloudOrganizationError(
            "NDI:Cloud:OrganizationArguments",
            "organization_name and organization_id are mutually exclusive.",
        )

    organizations = getOrganizations(client=client)
    if not organizations:
        raise CloudOrganizationError(
            "NDI:Cloud:NoOrganizations",
            "Your NDI Cloud account does not belong to any organizations.",
        )

    # 1. An explicit request.
    if organization_name or organization_id:

        def find(orgs: list[dict[str, Any]]) -> list[int]:
            key, wanted = (
                ("name", organization_name) if organization_name else ("id", organization_id)
            )
            return [i for i, o in enumerate(orgs) if o[key] == wanted]

        matches = find(organizations)
        if not matches and (client is not None or _haveActiveToken()):
            organizations = getOrganizations(refresh=True, client=client)
            matches = find(organizations)
        if not matches:
            requested = (
                f'name "{organization_name}"' if organization_name else f'id "{organization_id}"'
            )
            raise CloudOrganizationError(
                "NDI:Cloud:UnknownOrganization",
                f"Organization {requested} is not one of the organizations you belong "
                f"to. Available: {_availableList(organizations)}.",
            )
        if len(matches) > 1:
            raise CloudOrganizationError(
                "NDI:Cloud:AmbiguousOrganization",
                f'Organization name "{organization_name}" matches {len(matches)} '
                "organizations you belong to; pass organization_id instead. Matches: "
                f"{_availableList([organizations[i] for i in matches])}.",
            )
        chosen = organizations[matches[0]]
        if require_upload and not chosen["canUploadDataset"] and not userIsAdmin(client=client):
            raise CloudOrganizationError(
                "NDI:Cloud:OrganizationCannotUpload",
                f"Organization {_describeOrganization(chosen)} does not allow dataset upload.",
            )
        return chosen["id"], chosen["name"]

    # 2. Only one candidate.
    candidates = organizations
    if (
        require_upload
        and not all(o["canUploadDataset"] for o in organizations)
        and not userIsAdmin(client=client)
    ):
        candidates = [o for o in organizations if o["canUploadDataset"]]
        if not candidates:
            raise CloudOrganizationError(
                "NDI:Cloud:NoUploadableOrganization",
                "None of your organizations allows dataset upload. Your organizations: "
                f"{_availableList(organizations)}.",
            )

    if len(candidates) == 1 and not (always_ask and interactive):
        return candidates[0]["id"], candidates[0]["name"]

    # 3. Ask the user.
    if interactive:
        from .ui.dialog import organizationLabels

        labels = organizationLabels([c["name"] for c in candidates], [c["id"] for c in candidates])
        index = (chooser or _consoleChoose)(labels, prompt_string)
        if index is None or not 0 <= index < len(candidates):
            raise CloudOrganizationError(
                "NDI:CloudDialog:UserCanceled",
                "Operation canceled during selection of an organization.",
            )
        return candidates[index]["id"], candidates[index]["name"]

    # 4. No way to decide.
    raise CloudOrganizationError(
        "NDI:Cloud:OrganizationRequired",
        f"You belong to {len(candidates)} organizations; specify one with "
        f"organization_name or organization_id. Available: {_availableList(candidates)}.",
    )


def _datasetOrganizationId(cloud_dataset_id: str, *, client: CloudClient | None = None) -> str:
    """The id of the organization that owns CLOUD_DATASET_ID.

    MATLAB's file-upload calls read this from the dataset record
    (``dsetinfo.organizationId`` in GetFileUploadURL / GetFileCollectionUploadURL)
    rather than from the logged-in user, because a user in several
    organizations has no single organization to fall back on.
    """
    from .api import datasets as datasets_api

    info = _unwrap(datasets_api.getDataset(cloud_dataset_id, client=client))
    org_id = info.get("organizationId", "") if isinstance(info, dict) else ""
    if not org_id:
        raise CloudOrganizationError(
            "NDI:Cloud:NoOrganizations",
            f"Could not determine the organization of cloud dataset {cloud_dataset_id}.",
        )
    return str(org_id)
