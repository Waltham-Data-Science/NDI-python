"""
ndi.cloud.download - Download orchestration for NDI Cloud.

MATLAB equivalents: +ndi/+cloud/+download/*.m
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import CloudClient


def download_document_collection(
    client: CloudClient,
    dataset_id: str,
    doc_ids: list[str] | None = None,
    chunk_size: int = 2000,
) -> list[dict[str, Any]]:
    """Download documents from the cloud.

    Args:
        client: Authenticated cloud client.
        dataset_id: Cloud dataset ID.
        doc_ids: Specific document IDs to download. If ``None``,
            downloads all documents (auto-paginated).
        chunk_size: Page size for pagination.

    Returns:
        List of document dicts.
    """
    from .api import documents as docs_api

    if doc_ids is not None:
        result = []
        for doc_id in doc_ids:
            try:
                doc = docs_api.get_document(client, dataset_id, doc_id)
                result.append(doc)
            except Exception:
                pass
        return result

    return docs_api.list_all_documents(client, dataset_id)


def download_files_for_document(
    client: CloudClient,
    dataset_id: str,
    document: dict[str, Any],
    target_dir: Path,
) -> list[Path]:
    """Download associated binary files for a single document.

    Args:
        client: Authenticated cloud client.
        dataset_id: Cloud dataset ID.
        document: Document dict (must include ``file_uid``).
        target_dir: Directory to save downloaded files.

    Returns:
        List of paths to downloaded files.
    """
    import requests

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    file_uid = document.get("file_uid", "")
    if not file_uid:
        return downloaded

    # Get download URL via file details endpoint
    from .api import files as files_api

    try:
        details = files_api.get_file_details(client, dataset_id, file_uid)
    except Exception:
        return downloaded

    url = details.get("downloadUrl", "") if isinstance(details, dict) else ""
    if not url:
        return downloaded

    # Download with streaming
    resp = requests.get(url, timeout=120, stream=True)
    if resp.status_code == 200:
        out_path = target_dir / file_uid
        with open(out_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        downloaded.append(out_path)

    return downloaded


def download_dataset_files(
    client: CloudClient,
    dataset_id: str,
    documents: list[dict[str, Any]],
    target_dir: Path,
) -> dict[str, Any]:
    """Download binary files for a batch of documents.

    MATLAB equivalent: downloadDataset.m file-download loop.

    Returns:
        Report with ``downloaded``, ``failed`` counts.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"downloaded": 0, "failed": 0, "errors": []}

    for doc in documents:
        try:
            paths = download_files_for_document(client, dataset_id, doc, target_dir)
            report["downloaded"] += len(paths)
        except Exception as exc:
            report["failed"] += 1
            report["errors"].append(str(exc))

    return report


def jsons_to_documents(
    doc_jsons: list[dict[str, Any]],
) -> list[Any]:
    """Convert a list of raw JSON dicts into ndi.Document objects.

    MATLAB equivalent: downloadDataset.m conversion step.
    """
    from ndi.document import Document

    documents = []
    for dj in doc_jsons:
        try:
            documents.append(Document(dj))
        except Exception:
            pass
    return documents
