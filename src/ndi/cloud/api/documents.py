"""
ndi.cloud.api.documents - Document CRUD and bulk operations.

MATLAB equivalents: +ndi/+cloud/+api/+documents/*.m,
    +implementation/+documents/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import CloudClient


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


def delete_document(
    client: CloudClient,
    dataset_id: str,
    document_id: str,
) -> bool:
    """DELETE /datasets/{datasetId}/documents/{documentId}"""
    client.delete(
        "/datasets/{datasetId}/documents/{documentId}",
        datasetId=dataset_id,
        documentId=document_id,
    )
    return True


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
        if isinstance(result, dict) and "count" in result:
            return result["count"]
    except Exception:
        pass
    # Fallback: get from dataset metadata
    from .datasets import get_dataset

    ds = get_dataset(client, dataset_id)
    return ds.get("documentCount", 0)


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


def get_bulk_upload_url(
    client: CloudClient,
    dataset_id: str,
) -> str:
    """Get a presigned URL for bulk document upload."""
    result = client.post(
        "/datasets/{datasetId}/documents/bulk-upload",
        datasetId=dataset_id,
    )
    return result.get("url", "") if isinstance(result, dict) else ""


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
    return result.get("url", "") if isinstance(result, dict) else ""


def bulk_delete(
    client: CloudClient,
    dataset_id: str,
    doc_ids: list[str],
) -> dict[str, Any]:
    """POST /datasets/{datasetId}/documents/bulk-delete"""
    return client.post(
        "/datasets/{datasetId}/documents/bulk-delete",
        json={"documentIds": doc_ids},
        datasetId=dataset_id,
    )


def ndi_query(
    client: CloudClient,
    scope: str,
    search_structure: dict[str, Any],
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Query documents across datasets via the NDI query API.

    MATLAB equivalent: +cloud/+api/+documents/ndiquery.m

    Args:
        client: Authenticated cloud client.
        scope: One of ``'public'``, ``'private'``, ``'all'``.
        search_structure: Query search structure dict.
        page: Page number (1-based).
        page_size: Results per page.

    Returns:
        Dict with ``documents`` list and pagination metadata.
    """
    return client.post(
        f"/ndiquery?page={page}&pageSize={page_size}",
        json={"scope": scope, "searchstructure": search_structure},
    )


def ndi_query_all(
    client: CloudClient,
    scope: str,
    search_structure: dict[str, Any],
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Auto-paginate through all ndiquery results.

    MATLAB equivalent: +cloud/+api/+documents/ndiqueryAll.m
    """
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
