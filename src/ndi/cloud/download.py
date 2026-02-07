"""
ndi.cloud.download - Download orchestration for NDI Cloud.

MATLAB equivalents: +ndi/+cloud/+download/*.m
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import CloudClient


def download_document_collection(
    client: 'CloudClient',
    dataset_id: str,
    doc_ids: Optional[List[str]] = None,
    chunk_size: int = 2000,
) -> List[Dict[str, Any]]:
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
    client: 'CloudClient',
    dataset_id: str,
    document: Dict[str, Any],
    target_dir: Path,
) -> List[Path]:
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

    downloaded: List[Path] = []
    file_uid = document.get('file_uid', '')
    if not file_uid:
        return downloaded

    # Get download URL
    from .api import files as files_api
    url = files_api.get_upload_url(
        client,
        client.config.org_id,
        dataset_id,
        file_uid,
    )
    if not url:
        return downloaded

    # Download
    resp = requests.get(url, timeout=60)
    if resp.status_code == 200:
        out_path = target_dir / file_uid
        out_path.write_bytes(resp.content)
        downloaded.append(out_path)

    return downloaded


def download_dataset_files(
    client: 'CloudClient',
    dataset_id: str,
    documents: List[Dict[str, Any]],
    target_dir: Path,
) -> Dict[str, Any]:
    """Download binary files for a batch of documents.

    MATLAB equivalent: downloadDataset.m file-download loop.

    Returns:
        Report with ``downloaded``, ``failed`` counts.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = {'downloaded': 0, 'failed': 0, 'errors': []}

    for doc in documents:
        try:
            paths = download_files_for_document(client, dataset_id, doc, target_dir)
            report['downloaded'] += len(paths)
        except Exception as exc:
            report['failed'] += 1
            report['errors'].append(str(exc))

    return report


def jsons_to_documents(
    doc_jsons: List[Dict[str, Any]],
) -> List[Any]:
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
