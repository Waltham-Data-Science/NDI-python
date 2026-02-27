"""
ndi.cloud.api.documents - Document CRUD and bulk operations.

All functions accept an optional :class:`~ndi.cloud.client.CloudClient` as
the first argument.  When omitted, a client is created automatically from
environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+documents/*.m,
    +implementation/+documents/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..client import _auto_client

if TYPE_CHECKING:
    from ..client import CloudClient


def _coerce_search_structure(search_structure: Any) -> Any:
    """Convert Query objects to JSON-serializable dicts.

    Accepts :class:`~ndi.query.Query` objects, raw dicts/lists, or lists
    containing a mix of both.  Returns a JSON-serializable value suitable
    for the cloud ``searchstructure`` POST body.
    """
    # Single Query object
    if hasattr(search_structure, "to_search_structure"):
        return search_structure.to_search_structure()
    # List that may contain Query objects
    if isinstance(search_structure, list):
        return [
            q.to_search_structure() if hasattr(q, "to_search_structure") else q
            for q in search_structure
        ]
    return search_structure


@_auto_client
def get_document(
    client: CloudClient,
    dataset_id: str,
    document_id: str,
) -> dict[str, Any]:
    """GET /datasets/{datasetId}/documents/{documentId}"""
    return client.get(
        "/datasets/{datasetId}/documents/{documentId}",
        datasetId=dataset_id,
        documentId=document_id,
    )


@_auto_client
def add_document(
    client: CloudClient,
    dataset_id: str,
    doc_json: dict[str, Any],
) -> dict[str, Any]:
    """POST /datasets/{datasetId}/documents"""
    return client.post(
        "/datasets/{datasetId}/documents",
        json=doc_json,
        datasetId=dataset_id,
    )


@_auto_client
def update_document(
    client: CloudClient,
    dataset_id: str,
    document_id: str,
    doc_json: dict[str, Any],
) -> dict[str, Any]:
    """POST /datasets/{datasetId}/documents/{documentId}"""
    return client.post(
        "/datasets/{datasetId}/documents/{documentId}",
        json=doc_json,
        datasetId=dataset_id,
        documentId=document_id,
    )


@_auto_client
def delete_document(
    client: CloudClient,
    dataset_id: str,
    document_id: str,
    when: str = "7d",
) -> dict[str, Any]:
    """DELETE /datasets/{datasetId}/documents/{documentId}?when=...

    Soft-delete a document.  See :func:`~ndi.cloud.api.datasets.delete_dataset`
    for the *when* parameter format.
    """
    return client.delete(
        "/datasets/{datasetId}/documents/{documentId}",
        params={"when": when},
        datasetId=dataset_id,
        documentId=document_id,
    )


@_auto_client
def list_documents(
    client: CloudClient,
    dataset_id: str,
    page: int = 1,
    page_size: int = 1000,
) -> dict[str, Any]:
    """GET /datasets/{datasetId}/documents?page=&pageSize="""
    return client.get(
        "/datasets/{datasetId}/documents",
        params={"page": page, "pageSize": page_size},
        datasetId=dataset_id,
    )


_MAX_PAGES = 1000


@_auto_client
def list_all_documents(
    client: CloudClient,
    dataset_id: str,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Auto-paginate through all documents in a dataset."""
    all_docs: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = list_documents(client, dataset_id, page=page, page_size=page_size)
        docs = result.get("documents", [])
        all_docs.extend(docs)
        # Stop when a page returns fewer docs than requested (last page)
        if len(docs) < page_size:
            break
        page += 1
    return all_docs


@_auto_client
def get_document_count(client: CloudClient, dataset_id: str) -> int:
    """Return the document count for a dataset.

    Tries the dedicated ``GET /datasets/{datasetId}/document-count``
    endpoint first.  Falls back to the ``documentCount`` field from
    ``GET /datasets/{datasetId}`` if the count endpoint times out.
    """
    try:
        result = client.get(
            "/datasets/{datasetId}/document-count",
            datasetId=dataset_id,
        )
        if "count" in result:
            return result["count"]
    except Exception:
        pass
    # Fallback: get from dataset metadata
    from .datasets import get_dataset

    ds = get_dataset(client, dataset_id)
    return ds.get("documentCount", 0)


@_auto_client
def bulk_upload(
    client: CloudClient,
    dataset_id: str,
    zip_path: str,
) -> dict[str, Any]:
    """POST /datasets/{datasetId}/documents/bulk-upload

    Upload a ZIP file containing documents.
    """
    return client.post(
        "/datasets/{datasetId}/documents/bulk-upload",
        data=zip_path,  # Actual file handling done by caller
        datasetId=dataset_id,
    )


@_auto_client
def get_bulk_upload_url(
    client: CloudClient,
    dataset_id: str,
) -> str:
    """Get a presigned URL for bulk document upload."""
    result = client.post(
        "/datasets/{datasetId}/documents/bulk-upload",
        datasetId=dataset_id,
    )
    return result.get("url", "")


@_auto_client
def get_bulk_download_url(
    client: CloudClient,
    dataset_id: str,
    doc_ids: list[str] | None = None,
) -> str:
    """POST /datasets/{datasetId}/documents/bulk-download

    Returns a pre-signed URL where a ZIP of the requested documents
    will be uploaded by a background worker.  The caller should poll
    the URL until it becomes available.
    """
    body: dict[str, Any] = {"documentIds": doc_ids or []}
    result = client.post(
        "/datasets/{datasetId}/documents/bulk-download",
        json=body,
        datasetId=dataset_id,
    )
    return result.get("url", "")


@_auto_client
def bulk_delete(
    client: CloudClient,
    dataset_id: str,
    doc_ids: list[str],
    when: str = "7d",
) -> dict[str, Any]:
    """POST /datasets/{datasetId}/documents/bulk-delete

    Soft-delete multiple documents.  See
    :func:`~ndi.cloud.api.datasets.delete_dataset` for the *when*
    parameter format.
    """
    return client.post(
        "/datasets/{datasetId}/documents/bulk-delete",
        json={"documentIds": doc_ids, "when": when},
        datasetId=dataset_id,
    )


@_auto_client
def ndi_query(
    client: CloudClient,
    scope: str,
    search_structure: Any,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Query documents across datasets via the NDI query API.

    MATLAB equivalent: +cloud/+api/+documents/ndiquery.m

    Args:
        client: Authenticated cloud client.
        scope: One of ``'public'``, ``'private'``, ``'all'``.
        search_structure: Query object, search structure dict, or list.
            Accepts :class:`~ndi.query.Query` objects (auto-converted),
            raw dicts, or lists of either.
        page: Page number (1-based).
        page_size: Results per page.

    Returns:
        Dict with ``documents`` list and pagination metadata.
    """
    search_structure = _coerce_search_structure(search_structure)
    return client.post(
        f"/ndiquery?page={page}&pageSize={page_size}",
        json={"scope": scope, "searchstructure": search_structure},
    )


@_auto_client
def ndi_query_all(
    client: CloudClient,
    scope: str,
    search_structure: Any,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Auto-paginate through all ndiquery results.

    MATLAB equivalent: +cloud/+api/+documents/ndiqueryAll.m
    """
    search_structure = _coerce_search_structure(search_structure)
    all_docs: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = ndi_query(client, scope, search_structure, page=page, page_size=page_size)
        docs = result.get("documents", [])
        all_docs.extend(docs)
        total = result.get("number_matches", result.get("totalItems", result.get("totalNumber", 0)))
        if len(all_docs) >= total or not docs:
            break
        page += 1
    return all_docs


@_auto_client
def list_deleted_documents(
    client: CloudClient,
    dataset_id: str,
    page: int = 1,
    page_size: int = 1000,
) -> dict[str, Any]:
    """GET /datasets/{datasetId}/documents/deleted?page=&pageSize=

    Returns soft-deleted documents that have not yet been pruned.
    """
    return client.get(
        "/datasets/{datasetId}/documents/deleted",
        params={"page": page, "pageSize": page_size},
        datasetId=dataset_id,
    )


@_auto_client
def add_document_as_file(
    client: CloudClient,
    dataset_id: str,
    file_path: str,
) -> dict[str, Any]:
    """Add a document from a JSON file on disk.

    MATLAB equivalent: +cloud/+api/+documents/addDocumentAsFile.m
    """
    import json
    from pathlib import Path

    content = Path(file_path).read_text(encoding="utf-8")
    doc_json = json.loads(content)
    return add_document(client, dataset_id, doc_json)
