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
    # Build mapping from NDI ID (base.id) → MongoDB _id so we can
    # match bulk-downloaded documents (which lack MongoDB _id) back
    # to the identifiers used for filenames and resume checks.
    _log("Listing all document IDs...")
    all_doc_ids: list[str] = []
    ndi_to_mongo: dict[str, str] = {}
    page = 1
    page_size = 1000
    while page <= 1000:
        result = docs_api.list_documents(client, dataset_id, page=page, page_size=page_size)
        docs = result.get("documents", [])
        if not docs:
            break
        for d in docs:
            doc_id = d.get("_id", d.get("id", ""))
            ndi_id = d.get("ndiId", "")
            if doc_id:
                all_doc_ids.append(doc_id)
                if ndi_id:
                    ndi_to_mongo[ndi_id] = doc_id
        if len(docs) < page_size:
            break
        page += 1
    _log(f"Found {len(all_doc_ids)} documents")

    # --- Phase 2: bulk download full documents in chunks (matches MATLAB) ---
    # Filter out already-downloaded docs for resume support
    remaining_ids = [did for did in all_doc_ids if not (docs_dir / f"{did}.json").exists()]
    already = len(all_doc_ids) - len(remaining_ids)
    if already:
        _log(f"Skipping {already} already-downloaded documents")
        report["documents_downloaded"] += already

    if remaining_ids:
        _log(f"Downloading {len(remaining_ids)} documents via bulk chunks...")
        try:
            full_docs = download_document_collection(
                client,
                dataset_id,
                doc_ids=remaining_ids,
                progress=progress,
            )
            for doc in full_docs:
                # Bulk-downloaded docs may lack top-level _id/id.
                # Try top-level first, then map NDI ID → MongoDB ID.
                doc_id = doc.get("_id", doc.get("id", ""))
                if not doc_id:
                    ndi_id = doc.get("base", {}).get("id", "")
                    doc_id = ndi_to_mongo.get(ndi_id, ndi_id)
                if not doc_id:
                    continue
                out_path = docs_dir / f"{doc_id}.json"
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2)
                report["documents_downloaded"] += 1
        except Exception as exc:
            report["documents_failed"] += len(remaining_ids)
            logger.debug("Bulk document download failed: %s", exc)

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


def _download_chunk_zip(
    url: str,
    timeout: float = 20.0,
    retry_interval: float = 1.0,
) -> list[dict[str, Any]]:
    """Download and extract a bulk-download ZIP from a presigned S3 URL.

    Mirrors MATLAB's ``downloadDocumentCollection.m`` retry logic:
    polls the URL every *retry_interval* seconds until the ZIP is ready
    or *timeout* is exceeded.

    Args:
        url: Presigned S3 URL for the ZIP.
        timeout: Maximum seconds to wait for the ZIP to become available.
        retry_interval: Seconds between retry attempts.

    Returns:
        List of document dicts extracted from the ZIP.

    Raises:
        TimeoutError: If the ZIP is not ready within *timeout* seconds.
    """
    import io
    import time
    import zipfile

    import requests

    t0 = time.time()
    last_exc: Exception | None = None

    while time.time() - t0 < timeout:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                # ZIP is ready — extract documents
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                all_docs: list[dict[str, Any]] = []
                for name in zf.namelist():
                    if name.endswith(".json"):
                        data = json.loads(zf.read(name))
                        docs = data if isinstance(data, list) else [data]
                        all_docs.extend(docs)
                return all_docs
        except Exception as exc:
            last_exc = exc

        time.sleep(retry_interval)

    msg = f"Download timed out after {timeout:.0f}s"
    if last_exc:
        msg += f": {last_exc}"
    raise TimeoutError(msg)


def download_document_collection(
    client: CloudClient,
    dataset_id: str,
    doc_ids: list[str] | None = None,
    chunk_size: int = 2000,
    timeout: float = 20.0,
    retry_interval: float = 1.0,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Download full documents from the cloud using chunked bulk download.

    Mirrors MATLAB ``ndi.cloud.download.downloadDocumentCollection``:
    splits document IDs into chunks of *chunk_size* (default 2000),
    requests a bulk-download ZIP for each chunk, and concatenates
    the results.

    Args:
        client: Authenticated cloud client.
        dataset_id: Cloud dataset ID.
        doc_ids: Specific document IDs to download. If ``None``,
            discovers all document IDs via paginated listing first.
        chunk_size: Number of documents per bulk-download request.
            Default 2000 matches MATLAB.
        timeout: Seconds to wait for each chunk's ZIP to become
            available. Default 20 matches MATLAB.
        retry_interval: Seconds between polling attempts for each
            chunk. Default 1 matches MATLAB.
        progress: Optional callback for status messages.

    Returns:
        List of full document dicts.
    """
    import math

    from .api import documents as docs_api

    def _log(msg: str) -> None:
        logger.info(msg)
        if progress:
            progress(msg)

    # If no IDs given, discover all via paginated summaries
    if doc_ids is None:
        _log("Listing all document IDs...")
        summaries = docs_api.list_all_documents(client, dataset_id)
        doc_ids = [
            s.get("_id", s.get("id", "")) for s in summaries if s.get("_id", s.get("id", ""))
        ]
        _log(f"Found {len(doc_ids)} documents")

    if not doc_ids:
        return []

    # Split into chunks
    num_chunks = math.ceil(len(doc_ids) / chunk_size)
    all_documents: list[dict[str, Any]] = []

    for i in range(num_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, len(doc_ids))
        chunk_ids = doc_ids[start:end]

        _log(f"  Processing chunk {i + 1} of {num_chunks} " f"({len(chunk_ids)} documents)...")

        # Get presigned URL for this chunk
        try:
            url = docs_api.get_bulk_download_url(client, dataset_id, chunk_ids)
        except Exception as exc:
            _log(f"  Chunk {i + 1}: failed to get download URL: {exc}")
            continue

        if not url:
            _log(f"  Chunk {i + 1}: no download URL returned")
            continue

        # Download and extract the ZIP
        try:
            chunk_docs = _download_chunk_zip(url, timeout, retry_interval)
            all_documents.extend(chunk_docs)
            _log(f"  Chunk {i + 1}: extracted {len(chunk_docs)} documents")
        except TimeoutError as exc:
            _log(f"  Chunk {i + 1}: {exc}")
        except Exception as exc:
            _log(f"  Chunk {i + 1}: extraction failed: {exc}")

    _log(f"Downloaded {len(all_documents)} documents total")
    return all_documents


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
