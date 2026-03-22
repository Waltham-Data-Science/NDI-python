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

from ndi.util import rehydrateJSONNanNull

if TYPE_CHECKING:
    from .client import CloudClient

logger = logging.getLogger(__name__)


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
                        raw_text = zf.read(name).decode("utf-8")
                        raw_text = rehydrateJSONNanNull(raw_text)
                        data = json.loads(raw_text)
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


def downloadDocumentCollection(
    dataset_id: str,
    doc_ids: list[str] | None = None,
    chunk_size: int = 2000,
    timeout: float = 20.0,
    retry_interval: float = 1.0,
    progress: Callable[[str], None] | None = None,
    *,
    client: CloudClient | None = None,
) -> list[dict[str, Any]]:
    """Download full documents from the cloud using chunked bulk download.

    Mirrors MATLAB ``ndi.cloud.download.downloadDocumentCollection``:
    splits document IDs into chunks of *chunk_size* (default 2000),
    requests a bulk-download ZIP for each chunk, and concatenates
    the results.

    Args:
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
        client: Authenticated cloud client (auto-created if omitted).

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
        summaries = docs_api.listDatasetDocumentsAll(dataset_id, client=client)
        doc_ids = [
            s.get("_id", s.get("id", "")) for s in summaries.data if s.get("_id", s.get("id", ""))
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
            url = docs_api.getBulkDownloadURL(dataset_id, chunk_ids, client=client)
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


def downloadFilesForDocument(
    dataset_id: str,
    document: dict[str, Any],
    target_dir: Path,
    *,
    client: CloudClient | None = None,
) -> list[Path]:
    """Download associated binary files for a single document.

    Args:
        dataset_id: Cloud dataset ID.
        document: ndi_document dict (must include ``file_uid``).
        target_dir: Directory to save downloaded files.
        client: Authenticated cloud client (auto-created if omitted).

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
        details = files_api.getFileDetails(dataset_id, file_uid, client=client)
    except Exception:
        return downloaded

    url = details.get("downloadUrl", "") if hasattr(details, "get") else ""
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


def downloadDatasetFiles(
    dataset_id: str,
    documents: list[dict[str, Any]],
    target_dir: Path,
    *,
    client: CloudClient | None = None,
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
            paths = downloadFilesForDocument(dataset_id, doc, target_dir, client=client)
            report["downloaded"] += len(paths)
        except Exception as exc:
            report["failed"] += 1
            report["errors"].append(str(exc))

    return report


def jsons2documents(
    doc_jsons: list[dict[str, Any]],
) -> list[Any]:
    """Convert a list of raw JSON dicts into ndi.ndi_document objects.

    MATLAB equivalent: downloadDataset.m conversion step.
    """
    from ndi.document import ndi_document

    documents = []
    for dj in doc_jsons:
        try:
            documents.append(ndi_document(dj))
        except Exception:
            pass
    return documents


def downloadGenericFiles(
    ndi_dataset: Any,
    ndi_document_ids: list[str],
    target_folder: str | Path,
    *,
    verbose: bool = True,
    zip_result: bool = False,
    naming_strategy: str = "original",
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Download generic_file documents from cloud to a folder with extensions.

    MATLAB equivalent: ``ndi.cloud.download.downloadGenericFiles``

    Identifies ``generic_file`` documents among the specified NDI document
    IDs and their dependencies, downloads their associated data files to
    *target_folder* using their original filenames (including extensions).

    Args:
        ndi_dataset: The local NDI dataset (or session) object.
        ndi_document_ids: NDI document IDs to download.
        target_folder: Destination folder for the files.
        verbose: Print progress messages.
        zip_result: If True, zip the downloaded files.
        naming_strategy: One of ``'original'``, ``'id'``, ``'id_original'``.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(success, error_message, report)`` where *report*
        contains ``downloaded_filenames`` and optionally ``zip_file``.
    """
    import requests as _requests

    from .api import files as files_api
    from .internal import getCloudDatasetIdForLocalDataset

    target = Path(target_folder)
    target.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"downloaded_filenames": [], "zip_file": ""}

    if not ndi_document_ids:
        if verbose:
            print("No NDI document IDs provided.")
        return True, "", report

    try:
        # Resolve cloud dataset ID
        cloud_dataset_id, _ = getCloudDatasetIdForLocalDataset(ndi_dataset, client=client)
        if not cloud_dataset_id:
            return False, "ndi_dataset is not linked to an NDI cloud dataset", report

        # Get documents from the local database
        from ndi.query import ndi_query

        all_docs = []
        for doc_id in ndi_document_ids:
            q = ndi_query("base.id", "exact_string", doc_id, "")
            results = (
                ndi_dataset.database_search(q) if hasattr(ndi_dataset, "database_search") else []
            )
            all_docs.extend(results)

        if not all_docs:
            if verbose:
                print("No matching documents found in the dataset.")
            return True, "", report

        # Filter for generic_file documents
        generic_docs = []
        for doc in all_docs:
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            if isinstance(props, dict) and "generic_file" in props:
                generic_docs.append(doc)

        if not generic_docs:
            if verbose:
                print("No generic_file documents found.")
            return True, "", report

        # Build download list
        download_list: list[dict[str, str]] = []
        for doc in generic_docs:
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            if not isinstance(props, dict):
                continue
            files_info = props.get("files", {}).get("file_info", [])
            if isinstance(files_info, dict):
                files_info = [files_info]
            generic_file = props.get("generic_file", {})
            original_filename = generic_file.get("filename", "")
            doc_id = props.get("base", {}).get("id", "")

            for fi in files_info:
                locations = fi.get("locations", [])
                if isinstance(locations, dict):
                    locations = [locations]
                if locations:
                    uid = locations[0].get("uid", "")
                    if not uid:
                        continue

                    import os

                    name_part, ext_part = os.path.splitext(original_filename)
                    if not name_part:
                        name_part, ext_part = os.path.splitext(fi.get("name", ""))

                    if naming_strategy == "id":
                        filename = f"{doc_id}{ext_part}"
                    elif naming_strategy == "id_original":
                        filename = f"{doc_id}_{name_part}{ext_part}"
                    else:  # "original"
                        filename = f"{name_part}{ext_part}"

                    download_list.append({"uid": uid, "filename": filename})

        if not download_list:
            if verbose:
                print("No files associated with these documents.")
            return True, "", report

        # Download files
        if verbose:
            print(f"Downloading {len(download_list)} files to {target}...")

        for i, item in enumerate(download_list):
            uid = item["uid"]
            filename = item["filename"]
            target_path = target / filename

            if verbose:
                print(f"  [{i + 1}/{len(download_list)}] Downloading {filename} (UID: {uid})...")

            try:
                details = files_api.getFileDetails(cloud_dataset_id, uid, client=client)
                url = details.get("downloadUrl", "") if hasattr(details, "get") else ""
                if not url:
                    logger.warning("No download URL for file %s (UID: %s)", filename, uid)
                    continue

                resp = _requests.get(url, timeout=300, stream=True)
                if resp.status_code == 200:
                    with open(target_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=65536):
                            fh.write(chunk)
                    report["downloaded_filenames"].append(filename)
            except Exception as exc:
                logger.warning("Failed to download file %s: %s", filename, exc)

        # Optional zip
        if zip_result and report["downloaded_filenames"]:
            import zipfile as _zipfile

            zip_name = target / "exported_generic_files.zip"
            with _zipfile.ZipFile(zip_name, "w", _zipfile.ZIP_DEFLATED) as zf:
                for fname in report["downloaded_filenames"]:
                    zf.write(target / fname, fname)
            report["zip_file"] = str(zip_name)
            if verbose:
                print(f"Zip complete: {zip_name}")

    except Exception as exc:
        return False, str(exc), report

    return True, "", report


def structsToNdiDocuments(
    ndi_document_structs: list[dict[str, Any]],
) -> list[Any]:
    """Convert downloaded NDI document structures to ndi.ndi_document objects.

    MATLAB equivalent: ``ndi.cloud.download.internal.structsToNdiDocuments``

    This is equivalent to :func:`jsons2documents` but named to match
    the MATLAB function.

    Args:
        ndi_document_structs: List of document property dicts.

    Returns:
        List of :class:`ndi.ndi_document` objects.
    """
    return jsons2documents(ndi_document_structs)
