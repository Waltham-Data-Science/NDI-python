"""
ndi.cloud.internal - Internal utilities for NDI Cloud operations.

MATLAB equivalents: +ndi/+cloud/+internal/*.m,
    +ndi/+cloud/+sync/+internal/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import CloudClient


def list_remote_document_ids(
    client: CloudClient,
    cloud_dataset_id: str,
) -> dict[str, str]:
    """Return a mapping of ``ndiId → apiId`` for all remote documents.

    Paginates through the full document list and extracts the IDs.

    Returns:
        Dict mapping NDI document IDs to their API IDs.
    """
    from .api import documents as docs_api

    all_docs = docs_api.list_all_documents(client, cloud_dataset_id)
    mapping: dict[str, str] = {}
    for doc in all_docs:
        ndi_id = doc.get("ndiId", doc.get("id", ""))
        api_id = doc.get("id", doc.get("_id", ""))
        if ndi_id:
            mapping[ndi_id] = api_id
    return mapping


def get_cloud_dataset_id(
    client: CloudClient,
    dataset: Any,
) -> tuple[str, dict | None]:
    """Resolve the cloud dataset ID from a local dataset.

    Looks for a ``dataset_remote`` document in the local database
    that links this dataset to a cloud dataset.

    Args:
        client: Authenticated cloud client.
        dataset: A local :class:`~ndi.dataset.Dataset` instance.

    Returns:
        Tuple of ``(cloud_dataset_id, remote_doc)`` where
        *remote_doc* is the linking document or ``None``.
    """
    try:
        db = dataset.database
        from ndi.query import Query

        q = Query("").isa("dataset_remote")
        results = db.search(q)
        if results:
            doc = results[0]
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            cloud_id = ""
            if isinstance(props, dict):
                remote = props.get("dataset_remote", {})
                cloud_id = remote.get("dataset_id", "")
            return cloud_id, doc
    except Exception:
        pass
    return "", None


def create_remote_dataset_doc(
    cloud_dataset_id: str,
    dataset: Any,
) -> Any:
    """Create a ``dataset_remote`` document linking to the cloud.

    Args:
        cloud_dataset_id: The cloud-side dataset ID.
        dataset: Local dataset to add the document to.

    Returns:
        The created Document instance.
    """
    from ndi.document import Document

    doc = Document("dataset_remote")
    doc._set_nested_property("dataset_remote.dataset_id", cloud_dataset_id)
    return doc


def list_local_documents(dataset: Any) -> tuple[list[Any], list[str]]:
    """Retrieve all documents and their IDs from a local dataset.

    MATLAB equivalent: +sync/+internal/listLocalDocuments.m

    Returns:
        Tuple of (documents, document_ids).
    """
    from ndi.query import Query

    try:
        docs = dataset.session.database_search(Query("").isa("base"))
    except Exception:
        docs = []

    ids = []
    for d in docs:
        p = d.document_properties if hasattr(d, "document_properties") else d
        if isinstance(p, dict):
            ids.append(p.get("base", {}).get("id", ""))
    return docs, ids


def get_file_uids_from_documents(documents: list[Any]) -> list[str]:
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


def files_not_yet_uploaded(
    file_manifest: list[dict[str, Any]],
    client: CloudClient,
    cloud_dataset_id: str,
) -> list[dict[str, Any]]:
    """Filter a file manifest to only files not yet in the cloud.

    MATLAB equivalent: +sync/+internal/filesNotYetUploaded.m
    """
    from .api.files import list_files

    try:
        remote_files = list_files(client, cloud_dataset_id)
    except Exception:
        return file_manifest  # can't check, assume all need upload

    remote_uids = set()
    for rf in remote_files:
        uid = rf.get("uid", "")
        if uid:
            remote_uids.add(uid)

    return [f for f in file_manifest if f.get("uid", "") not in remote_uids]


def validate_sync(
    client: CloudClient,
    dataset: Any,
    cloud_dataset_id: str,
) -> dict[str, Any]:
    """Compare local dataset with remote to identify sync discrepancies.

    MATLAB equivalent: +cloud/+sync/validate.m

    Returns:
        Report dict with local_only, remote_only, common, mismatched IDs.
    """
    _, local_ids = list_local_documents(dataset)
    remote_id_map = list_remote_document_ids(client, cloud_dataset_id)

    local_set = set(local_ids)
    remote_set = set(remote_id_map.keys())

    return {
        "local_only_ids": list(local_set - remote_set),
        "remote_only_ids": list(remote_set - local_set),
        "common_ids": list(local_set & remote_set),
        "local_count": len(local_set),
        "remote_count": len(remote_set),
    }


def dataset_session_id_from_docs(documents: list[Any]) -> str:
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
