"""
ndi.cloud.internal - Internal utilities for NDI Cloud operations.

MATLAB equivalents: +ndi/+cloud/+internal/*.m,
    +ndi/+cloud/+sync/+internal/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def getFileUidsFromDocuments(documents: list[Any]) -> list[str]:
    """Extract unique file UIDs from a list of documents.

    MATLAB equivalent: +sync/+internal/getFileUidsFromDocuments.m
    """
    uids: set[str] = set()
    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        # Check files.file_info
        files = props.get("files", {})
        if isinstance(files, dict):
            for fi in files.get("file_info", []):
                if isinstance(fi, dict):
                    for loc in fi.get("locations", []):
                        uid = loc.get("uid", "")
                        if uid:
                            uids.add(uid)
        # Also check top-level file_uid
        fuid = props.get("file_uid", "")
        if fuid:
            uids.add(fuid)
    return list(uids)


def filesNotYetUploaded(
    file_manifest: list[dict[str, Any]],
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> list[dict[str, Any]]:
    """Filter a file manifest to only files not yet in the cloud.

    MATLAB equivalent: +sync/+internal/filesNotYetUploaded.m
    """
    from .api.files import listFiles

    try:
        remote_files = listFiles(cloud_dataset_id, client=client).data
    except Exception:
        return file_manifest  # can't check, assume all need upload

    remote_uids = set()
    for rf in remote_files:
        uid = rf.get("uid", "")
        if uid:
            remote_uids.add(uid)

    return [f for f in file_manifest if f.get("uid", "") not in remote_uids]


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
