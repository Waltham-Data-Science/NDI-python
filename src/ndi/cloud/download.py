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


def dataset(
    dataset_id: str,
    target_dir: str | Path,
    *,
    include_files: bool = True,
    progress: Callable[[str], None] | None = None,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Download a complete dataset (full documents + binary files) to disk.

    MATLAB equivalent: ``ndi.cloud.download.dataset``

    This is the recommended way to download an entire dataset.  It fetches
    the full JSON for every document (not just summaries) and optionally
    downloads all associated binary files.  Already-downloaded items are
    skipped, so the function is safe to resume after interruption.

    Args:
        dataset_id: Cloud dataset ID.
        target_dir: Local directory to save everything into.  Structure::

            target_dir/
              documents/       # one JSON file per document
              files/           # binary files keyed by uid

        include_files: Whether to also download binary files (default True).
        progress: Optional callback that receives status strings, e.g.
            ``print`` or ``logger.info``.
        client: Authenticated cloud client (auto-created if omitted).

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
        result = docs_api.listDatasetDocuments(
            dataset_id, page=page, page_size=page_size, client=client
        )
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
            full_docs = downloadDocumentCollection(
                dataset_id,
                doc_ids=remaining_ids,
                progress=progress,
                client=client,
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
            file_list = files_api.listFiles(dataset_id, client=client).data
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
                details = files_api.getFileDetails(dataset_id, uid, client=client)
                url = details.get("downloadUrl", "") if hasattr(details, "get") else ""
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


def datasetDocuments(
    dataset_info: dict[str, Any],
    mode: str = "local",
    json_dir: str | Path | None = None,
    files_dir: str | Path | None = None,
    *,
    verbose: bool = True,
    client: CloudClient | None = None,
) -> tuple[bool, str]:
    """Download dataset documents one-by-one from the cloud.

    MATLAB equivalent: ``ndi.cloud.download.datasetDocuments``

    This fetches each document individually via ``getDocument``, sets
    file info according to *mode* (``'local'`` or ``'hybrid'``), and
    saves each document as a JSON file in *json_dir*.

    Args:
        dataset_info: ndi_dataset dict as returned by ``getDataset``, must
            include ``documents`` (list of document IDs) and ``_id``.
        mode: ``'local'`` — files are expected on disk, set ingest/delete
            flags.  ``'hybrid'`` — leave files in cloud, set ndic:// URIs.
        json_dir: Directory to save document JSON files.
        files_dir: Directory containing locally-downloaded binary files
            (used only when *mode* is ``'local'``).
        verbose: Print progress messages.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(success, error_message)``.
    """
    from .api import documents as docs_api

    dataset_id = dataset_info.get("_id", dataset_info.get("id", ""))
    doc_ids = dataset_info.get("documents", [])

    if verbose:
        print(f"Will download {len(doc_ids)} documents...")

    if json_dir is not None:
        json_path = Path(json_dir)
        json_path.mkdir(parents=True, exist_ok=True)
    else:
        json_path = None

    for i, document_id in enumerate(doc_ids):
        if verbose:
            pct = 100 * (i + 1) / max(len(doc_ids), 1)
            print(f"Downloading document {i + 1} of {len(doc_ids)} ({pct:.0f}%)...")

        if json_path is not None:
            out_file = json_path / f"{document_id}.json"
            if out_file.exists():
                if verbose:
                    print(f"  ndi_document {i + 1} already exists. Skipping...")
                continue

        try:
            doc_struct = docs_api.getDocument(dataset_id, document_id, client=client)
            if hasattr(doc_struct, "data"):
                doc_struct = doc_struct.data
        except Exception as exc:
            logger.warning("Failed to get document %s: %s", document_id, exc)
            continue

        # Remove cloud-only 'id' field (MATLAB: rmfield(docStruct, 'id'))
        doc_struct.pop("id", None)

        # Set file info according to mode
        doc_struct = setFileInfo(doc_struct, mode, str(files_dir or ""))

        if json_path is not None:
            out_file = json_path / f"{document_id}.json"
            out_file.write_text(json.dumps(doc_struct, indent=2), encoding="utf-8")

    return True, ""


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


def setFileInfo(
    doc_struct: dict[str, Any],
    mode: str,
    filepath: str,
) -> dict[str, Any]:
    """Set file_info parameters for different download modes.

    MATLAB equivalent: ``ndi.cloud.download.internal.setFileInfo``

    Args:
        doc_struct: ndi_document properties dict.
        mode: ``'local'`` — set delete_original and ingest to 1 and
            update file locations to local paths.  ``'hybrid'`` — set
            delete_original and ingest to 0 (leave files in cloud).
        filepath: Directory containing locally-downloaded files.

    Returns:
        Updated document properties dict.
    """
    new_struct = dict(doc_struct)
    files = new_struct.get("files")
    if not files or not isinstance(files, dict):
        return new_struct

    file_info = files.get("file_info")
    if file_info is None:
        return new_struct

    if isinstance(file_info, dict):
        file_info = [file_info]

    if mode == "local":
        # Rewrite file info to point to local files
        import os

        new_file_info = []
        for fi in file_info:
            if not isinstance(fi, dict):
                new_file_info.append(fi)
                continue
            locations = fi.get("locations", [])
            if isinstance(locations, dict):
                locations = [locations]
            if locations:
                uid = locations[0].get("uid", "")
                file_location = os.path.join(filepath, uid) if uid else ""
                new_fi = dict(fi)
                new_fi["locations"] = [
                    {
                        "uid": uid,
                        "location": file_location,
                        "location_type": "file",
                        "delete_original": 1,
                        "ingest": 1,
                        **{
                            k: v
                            for k, v in locations[0].items()
                            if k not in ("location", "location_type", "delete_original", "ingest")
                        },
                    }
                ]
                new_file_info.append(new_fi)
            else:
                new_file_info.append(fi)
        files["file_info"] = new_file_info if len(new_file_info) != 1 else new_file_info
    else:
        # hybrid: set flags to 0
        for fi in file_info:
            if not isinstance(fi, dict):
                continue
            locations = fi.get("locations", [])
            if isinstance(locations, dict):
                locations = [locations]
            for loc in locations:
                if isinstance(loc, dict):
                    loc["delete_original"] = 0
                    loc["ingest"] = 0

    return new_struct


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


# Backward-compatible alias
downloadFullDataset = dataset
