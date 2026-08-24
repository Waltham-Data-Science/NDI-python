"""
ndi.cloud.internal - Internal utilities for NDI Cloud operations.

MATLAB equivalents: +ndi/+cloud/+internal/*.m,
    +ndi/+cloud/+sync/+internal/*.m
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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


def formatApiError(api_response: Any) -> str:
    """Format a human-readable message from a cloud API response.

    MATLAB equivalent: ``+ndi/+cloud/+internal/formatApiError.m``.

    Combines the HTTP status line with the server's error body (``message`` or
    ``error`` field, or a string body). Accepts an :class:`APIResponse`, a
    ``requests.Response``, a raw dict body, or ``None``.
    """
    if api_response is None:
        return "no response from server"

    status_part = ""
    try:
        status_code = getattr(api_response, "status_code", None)
        if status_code is not None:
            status_part = f"HTTP {int(status_code)}"
            reason = getattr(api_response, "reason", "") or ""
            if reason:
                status_part = f"{status_part} {reason}"
    except Exception:
        pass

    body_part = ""
    try:
        data = getattr(api_response, "data", api_response)
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error")
            if msg:
                body_part = str(msg)
        elif isinstance(data, str):
            body_part = data
    except Exception:
        pass

    if status_part and body_part:
        return f"{status_part} - {body_part}"
    if status_part:
        return status_part
    if body_part:
        return body_part
    return "unknown error"


def _localDatabase(dataset: Any) -> Any | None:
    """Return the ``ndi_database`` behind *dataset*, or ``None``.

    A session exposes it as the ``database`` property; an ``ndi_dataset``
    does not — it keeps the database on its backing session
    (``dataset._session._database``). Accept either shape.
    """
    database = getattr(dataset, "database", None)
    if database is not None:
        return database
    session = getattr(dataset, "_session", None)
    if session is not None:
        return getattr(session, "_database", None)
    return None


def getCloudDatasetIdForLocalDataset(
    dataset: Any,
    *,
    client: CloudClient | None = None,
) -> tuple[str, dict | None]:
    """Resolve the cloud dataset ID from a local dataset.

    Looks for a ``dataset_remote`` document in the local database
    that links this dataset to a cloud dataset. Purely local: no network
    call is made, and *client* is accepted only for signature compatibility.

    Args:
        dataset: A local :class:`~ndi.dataset.ndi_dataset` instance, or any
            object exposing a ``database``.
        client: Unused; accepted for call-site compatibility.

    Returns:
        Tuple of ``(cloud_dataset_id, remote_doc)`` where
        *remote_doc* is the linking document or ``None``.

    See also: :meth:`ndi.dataset.ndi_dataset.isInCloud`, which answers the
    same question and must agree with this function.
    """
    try:
        db = _localDatabase(dataset)
        if db is None:
            logger.debug("getCloudDatasetIdForLocalDataset: no database on %r", type(dataset))
            return "", None

        from ndi.query import ndi_query

        q = ndi_query("").isa("dataset_remote")
        results = db.search(q)
        if results:
            doc = results[0]
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            cloud_id = ""
            if isinstance(props, dict):
                remote = props.get("dataset_remote", {})
                if isinstance(remote, dict):
                    cloud_id = remote.get("dataset_id", "") or ""
            return cloud_id, doc
    except Exception:  # noqa: BLE001 - a lookup helper must never break a caller
        logger.debug("getCloudDatasetIdForLocalDataset: lookup failed", exc_info=True)
    return "", None


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

    Enumerates from ``dataset.database_search`` (matching MATLAB's
    ``ndiDataset.database_search``). For an ``ndi.dataset`` this traverses the
    dataset's own database and every linked session — using the private
    ``.session`` attribute here would both raise (a dataset has no public
    ``.session``) and miss linked-session documents.

    Returns:
        Tuple of (documents, document_ids).
    """
    from ndi.query import ndi_query

    try:
        docs = dataset.database_search(ndi_query("").isa("base"))
    except Exception as exc:
        logger.warning("listLocalDocuments: database_search failed: %s", exc)
        docs = []

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


def _strip_for_compare(props: Any, *, drop_id: bool) -> Any:
    """Return a copy of a document property dict ready for content comparison.

    Mirrors MATLAB validate.m: the ``files`` field is removed from both sides
    (binary contents are compared separately, not by these property structs),
    and the cloud-added top-level ``id`` / ``_id`` / ``ndiId`` are removed from
    the remote side. The NDI id under ``base.id`` is left intact on both sides.
    """
    if not isinstance(props, dict):
        return props
    out = {k: v for k, v in props.items() if k != "files"}
    if drop_id:
        for k in ("id", "_id", "ndiId"):
            out.pop(k, None)
    return out


def _deep_equal_nan(a: Any, b: Any) -> bool:
    """Deep equality with NaN==NaN and int/float equivalence (MATLAB isequaln).

    Dicts compare by key set + recursive value equality; lists elementwise;
    numbers with ``1 == 1.0`` and two NaNs treated as equal.
    """
    import math

    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_deep_equal_nan(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(_deep_equal_nan(x, y) for x, y in zip(a, b))
    a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
    if a_num and b_num:
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        return a == b
    return a == b


def _remote_ndi_id(remote_doc: Any) -> str:
    """Return the NDI id of a downloaded remote document body."""
    if not isinstance(remote_doc, dict):
        return ""
    return remote_doc.get("ndiId") or remote_doc.get("base", {}).get("id", "")


def validateSync(
    dataset: Any,
    cloud_dataset_id: str,
    *,
    compare_content: bool = True,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Compare local dataset with remote to identify sync discrepancies.

    MATLAB equivalent: +cloud/+sync/validate.m

    Identifies documents present only locally, only remotely, or on both, and
    (when *compare_content*) downloads the common remote documents and flags any
    whose property contents differ from the local copy — the MATLAB
    ``isequaln`` comparison after dropping the ``files`` field from both sides
    and the cloud-added ``id`` from the remote side.

    Args:
        dataset: The local NDI dataset.
        cloud_dataset_id: The linked cloud dataset id.
        compare_content: If True (default, MATLAB "bulk" mode), download the
            common remote documents and deep-compare their contents. If False,
            only the id sets are compared (the previous behaviour).
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with ``local_only_ids``, ``remote_only_ids``, ``common_ids``,
        ``mismatched_ids``, ``mismatch_details`` (``{ndiId, apiId, reason}``),
        ``local_count`` and ``remote_count``.
    """
    local_docs, local_ids = listLocalDocuments(dataset)
    remote_id_map = listRemoteDocumentIds(cloud_dataset_id, client=client)

    local_set = set(local_ids)
    remote_set = set(remote_id_map.keys())
    common = local_set & remote_set

    report: dict[str, Any] = {
        "local_only_ids": list(local_set - remote_set),
        "remote_only_ids": list(remote_set - local_set),
        "common_ids": list(common),
        "mismatched_ids": [],
        "mismatch_details": [],
        "local_count": len(local_set),
        "remote_count": len(remote_set),
    }

    if not compare_content or not common:
        return report

    from .download import downloadDocumentCollection

    local_by_ndi = {i: d for d, i in zip(local_docs, local_ids) if i in common}
    api_ids = [remote_id_map[i] for i in common]
    try:
        remote_docs = downloadDocumentCollection(cloud_dataset_id, doc_ids=api_ids, client=client)
    except Exception as exc:  # pragma: no cover - network failure path
        logger.warning("validateSync: could not download remote docs for comparison: %s", exc)
        report["compare_error"] = str(exc)
        return report

    remote_by_ndi = {}
    for rd in remote_docs:
        nid = _remote_ndi_id(rd)
        if nid:
            remote_by_ndi[nid] = rd

    for ndi_id in common:
        local_doc = local_by_ndi.get(ndi_id)
        remote_doc = remote_by_ndi.get(ndi_id)
        detail = {"ndiId": ndi_id, "apiId": remote_id_map[ndi_id]}
        if remote_doc is None:
            report["mismatched_ids"].append(ndi_id)
            report["mismatch_details"].append(
                {**detail, "reason": "Remote document could not be found in bulk download."}
            )
            continue
        local_props = (
            local_doc.document_properties
            if hasattr(local_doc, "document_properties")
            else local_doc
        )
        if not _deep_equal_nan(
            _strip_for_compare(local_props, drop_id=False),
            _strip_for_compare(remote_doc, drop_id=True),
        ):
            report["mismatched_ids"].append(ndi_id)
            report["mismatch_details"].append(
                {**detail, "reason": "Document properties do not match."}
            )

    return report


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
