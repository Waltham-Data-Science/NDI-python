"""
ndi.cloud.download - Download orchestration for NDI Cloud.

MATLAB equivalents: +ndi/+cloud/+download/*.m
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import CloudClient

logger = logging.getLogger(__name__)


def download_full_dataset(
    client: CloudClient,
    dataset_id: str,
    target_dir: str | Path,
    *,
    include_files: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Download a complete dataset (full documents + binary files) to disk.

    This is the recommended way to download an entire dataset.  It fetches
    the full JSON for every document (not just summaries) and optionally
    downloads all associated binary files.  Already-downloaded items are
    skipped, so the function is safe to resume after interruption.

    Args:
        client: Authenticated cloud client.
        dataset_id: Cloud dataset ID.
        target_dir: Local directory to save everything into.  Structure::

            target_dir/
              documents/       # one JSON file per document
              files/           # binary files keyed by uid

        include_files: Whether to also download binary files (default True).
        progress: Optional callback that receives status strings, e.g.
            ``print`` or ``logger.info``.

    Returns:
        Report dict with keys ``documents_downloaded``, ``documents_failed``,
        ``files_downloaded``, ``files_failed``.
    """
    from .api import documents as docs_api
    from .api import files as files_api

    def _log(msg: str) -> None:
        logger.info(msg)
        if progress:
            progress(msg)

    target = Path(target_dir)
    docs_dir = target / "documents"
    files_dir = target / "files"
    docs_dir.mkdir(parents=True, exist_ok=True)
    if include_files:
        files_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "documents_downloaded": 0,
        "documents_failed": 0,
        "files_downloaded": 0,
        "files_failed": 0,
    }

    # --- Phase 1: list all document IDs (paginated summaries) ---
    _log("Listing all document IDs...")
    all_doc_ids: list[str] = []
    page = 1
    page_size = 1000
    while page <= 1000:
        result = docs_api.list_documents(client, dataset_id, page=page, page_size=page_size)
        docs = result.get("documents", [])
        if not docs:
            break
        for d in docs:
            doc_id = d.get("_id", d.get("id", ""))
            if doc_id:
                all_doc_ids.append(doc_id)
        if len(docs) < page_size:
            break
        page += 1
    _log(f"Found {len(all_doc_ids)} documents")

    # --- Phase 2: fetch full JSON for each document ---
    _log("Downloading full document JSON...")
    for i, doc_id in enumerate(all_doc_ids):
        out_path = docs_dir / f"{doc_id}.json"
        if out_path.exists():
            report["documents_downloaded"] += 1
            continue
        try:
            full_doc = docs_api.get_document(client, dataset_id, doc_id)
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(full_doc, fh, indent=2)
            report["documents_downloaded"] += 1
        except Exception as exc:
            report["documents_failed"] += 1
            logger.debug("Failed to download doc %s: %s", doc_id, exc)
        if (i + 1) % 500 == 0 or (i + 1) == len(all_doc_ids):
            _log(f"  Documents: {i + 1}/{len(all_doc_ids)}")

    # --- Phase 3: download binary files ---
    if include_files:
        _log("Listing dataset files...")
        try:
            file_list = files_api.list_files(client, dataset_id)
        except Exception:
            file_list = []
        _log(f"Found {len(file_list)} files")

        import requests as _requests

        for i, f_info in enumerate(file_list):
            uid = f_info.get("uid", "")
            if not uid:
                continue
            out_path = files_dir / uid
            if out_path.exists():
                report["files_downloaded"] += 1
                continue
            try:
                details = files_api.get_file_details(client, dataset_id, uid)
                url = details.get("downloadUrl", "") if isinstance(details, dict) else ""
                if not url:
                    report["files_failed"] += 1
                    continue
                resp = _requests.get(url, timeout=300, stream=True)
                if resp.status_code == 200:
                    with open(out_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=65536):
                            fh.write(chunk)
                    report["files_downloaded"] += 1
                else:
                    report["files_failed"] += 1
            except Exception as exc:
                report["files_failed"] += 1
                logger.debug("Failed to download file %s: %s", uid, exc)
            if (i + 1) % 100 == 0 or (i + 1) == len(file_list):
                _log(
                    f"  Files: {i + 1}/{len(file_list)} "
                    f"(ok: {report['files_downloaded']}, "
                    f"fail: {report['files_failed']})"
                )

    _log(
        f"Done — {report['documents_downloaded']} docs, "
        f"{report['files_downloaded']} files downloaded"
    )
    return report


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
