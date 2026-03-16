"""
ndi.cloud.upload - Upload orchestration for NDI Cloud.

Provides batch (ZIP) and serial upload modes for document collections,
plus presigned-URL file uploads.

MATLAB equivalents: +ndi/+cloud/+upload/*.m, uploadSingleFile.m
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import _auto_client

if TYPE_CHECKING:
    from .client import CloudClient


def uploadDocumentCollection(
    dataset_id: str,
    documents: list[dict[str, Any]],
    only_missing: bool = True,
    max_chunk: int | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload a list of document dicts to the cloud.

    Args:
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        only_missing: If True, skip documents already on the remote.
        max_chunk: Maximum documents per ZIP chunk (None = all at once).
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with ``upload_type``, ``manifest``, ``status``.
    """
    from .api import documents as docs_api

    report: dict[str, Any] = {
        "upload_type": "batch",
        "total": len(documents),
        "uploaded": 0,
        "skipped": 0,
        "manifest": [],
        "status": "ok",
    }

    if only_missing:
        try:
            existing = docs_api.listDatasetDocumentsAll(dataset_id, client=client)
            existing_ids = {d.get("ndiId", d.get("id", "")) for d in existing.data}
            filtered = [d for d in documents if d.get("ndiId", d.get("id", "")) not in existing_ids]
            report["skipped"] = len(documents) - len(filtered)
            documents = filtered
        except Exception:
            pass  # proceed with all

    if not documents:
        return report

    # Chunk if needed
    chunks = [documents]
    if max_chunk and max_chunk > 0:
        chunks = [documents[i : i + max_chunk] for i in range(0, len(documents), max_chunk)]

    for chunk in chunks:
        for doc in chunk:
            try:
                docs_api.addDocument(dataset_id, doc, client=client)
                report["uploaded"] += 1
                doc_id = doc.get("ndiId", doc.get("id", ""))
                report["manifest"].append(doc_id)
            except Exception as exc:
                report["status"] = "partial"
                if report.get("errors") is None:
                    report["errors"] = []
                report["errors"].append(str(exc))

    return report


def zipForUpload(
    documents: list[dict[str, Any]],
    dataset_id: str,
    target_dir: Path | None = None,
) -> tuple[Path, list[str]]:
    """Serialize documents to JSON and create a ZIP archive.

    Args:
        documents: ndi_document property dicts.
        dataset_id: Used for the archive filename.
        target_dir: Directory for the ZIP file. Defaults to a temp dir.

    Returns:
        Tuple of (zip_path, manifest) where manifest is a list of
        document IDs included in the archive.
    """
    if target_dir is None:
        target_dir = Path(tempfile.mkdtemp())
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    zip_path = target_dir / f"{dataset_id}_upload.zip"
    manifest: list[str] = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, doc in enumerate(documents):
            doc_id = doc.get("ndiId", doc.get("id", f"doc_{i}"))
            filename = f"{doc_id}.json"
            zf.writestr(filename, json.dumps(doc, indent=2))
            manifest.append(doc_id)

    return zip_path, manifest


def uploadFilesForDatasetDocuments(
    org_id: str,
    dataset_id: str,
    documents: list[dict[str, Any]],
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload associated binary files for a list of documents.

    For each document that has a ``file_uid`` field, obtains a
    presigned URL and uploads the file.

    Args:
        org_id: Organisation ID.
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with counts of uploaded and failed files.
    """
    from .api import files as files_api

    report: dict[str, Any] = {
        "uploaded": 0,
        "failed": 0,
        "errors": [],
    }

    for doc in documents:
        file_uid = doc.get("file_uid", "")
        file_path = doc.get("file_path", "")
        if not file_uid or not file_path:
            continue
        try:
            url = files_api.getFileUploadURL(org_id, dataset_id, file_uid, client=client)
            files_api.putFiles(url, file_path)
            report["uploaded"] += 1
        except Exception as exc:
            report["failed"] += 1
            report["errors"].append(str(exc))

    return report


@_auto_client
def uploadSingleFile(
    dataset_id: str,
    file_uid: str,
    file_path: str,
    *,
    use_bulk_upload: bool = False,
    client: CloudClient | None = None,
) -> tuple[bool, str]:
    """Upload a single file to the NDI cloud service.

    MATLAB equivalent: ndi.cloud.uploadSingleFile

    Args:
        dataset_id: The cloud dataset ID.
        file_uid: Unique ID to assign to the uploaded file.
        file_path: Local path of the file to upload.
        use_bulk_upload: If True, zip the file and use the bulk upload
            mechanism. Defaults to False.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(success, error_message)``.
    """
    import os
    import uuid

    from .api import files as files_api

    try:
        if use_bulk_upload:
            zip_name = f"{dataset_id}.{uuid.uuid4().hex}.zip"
            zip_path = Path(tempfile.gettempdir()) / zip_name
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(file_path, os.path.basename(file_path))
                url = files_api.getFileCollectionUploadURL(
                    client.config.org_id,
                    dataset_id,
                    client=client,
                )
                files_api.putFiles(url, str(zip_path))
            finally:
                if zip_path.exists():
                    zip_path.unlink()
        else:
            url = files_api.getFileUploadURL(
                client.config.org_id,
                dataset_id,
                file_uid,
                client=client,
            )
            files_api.putFiles(url, file_path)

        return True, ""
    except Exception as exc:
        return False, str(exc)


@_auto_client
def uploadToNDICloud(
    dataset: Any,
    dataset_id: str,
    *,
    verbose: bool = True,
    client: CloudClient | None = None,
) -> tuple[bool, str]:
    """Upload an NDI database to NDI Cloud.

    MATLAB equivalent: ``ndi.cloud.upload.uploadToNDICloud``

    Reads all documents from the local dataset, determines which
    are already uploaded, and uploads the remainder.

    Args:
        dataset: An ndi.session or ndi.dataset object.
        dataset_id: The cloud dataset ID to upload to.
        verbose: Print progress messages.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(success, error_message)``.
    """
    from ndi.query import ndi_query

    from .api import documents as docs_api

    try:
        if verbose:
            print("Loading documents...")
        all_docs = dataset.database_search(ndi_query("")) if hasattr(dataset, "database_search") else []

        if verbose:
            print("Getting list of previously uploaded documents...")
        doc_structs, file_structs, total_size = scanForUpload(dataset, dataset_id, client=client)

        docs_left = sum(1 for ds in doc_structs if not ds["is_uploaded"])
        files_left = sum(1 for fs in file_structs if not fs["is_uploaded"])
        if verbose:
            print(f"Found {docs_left} new documents and {files_left} files. Uploading...")

        # Build docid → index lookup
        doc_id_to_idx = {ds["docid"]: i for i, ds in enumerate(doc_structs)}

        cur_doc = 0
        for doc in all_docs:
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            if not isinstance(props, dict):
                continue
            doc_id = props.get("base", {}).get("id", "")
            idx = doc_id_to_idx.get(doc_id)
            if idx is not None and not doc_structs[idx]["is_uploaded"]:
                cur_doc += 1
                if verbose:
                    print(
                        f"Uploading {cur_doc} JSON portions of {docs_left} "
                        f"({100 * cur_doc / max(docs_left, 1):.0f}%)"
                    )
                try:
                    docs_api.addDocumentAsFile(dataset_id, props, client=client)
                    doc_structs[idx]["is_uploaded"] = True
                except Exception:
                    if verbose:
                        print(f"  Warning: Failed to add document {doc_id}")

        # Upload files via zip
        file_docs = [
            (doc.document_properties if hasattr(doc, "document_properties") else doc)
            for doc in all_docs
        ]
        file_docs = [d for d in file_docs if isinstance(d, dict)]
        success, msg = zipForUpload(file_docs, dataset_id)
        if not success:
            return False, msg

        return True, ""
    except Exception as exc:
        return False, str(exc)


def scanForUpload(
    dataset: Any,
    dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> tuple[list[dict], list[dict], float]:
    """Scan local documents/files to determine what needs uploading.

    MATLAB equivalent: ``ndi.cloud.upload.scanForUpload``

    Returns:
        Tuple of ``(doc_structs, file_structs, total_size_kb)``.
    """
    from ndi.query import ndi_query

    from .internal import listRemoteDocumentIds

    try:
        all_docs = dataset.database_search(ndi_query("")) if hasattr(dataset, "database_search") else []
    except Exception:
        all_docs = []

    remote_ids = {}
    if dataset_id:
        try:
            remote_ids = listRemoteDocumentIds(dataset_id, client=client)
        except Exception:
            pass

    doc_structs: list[dict] = []
    file_structs: list[dict] = []
    total_size = 0.0

    for doc in all_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        doc_id = ""
        if isinstance(props, dict):
            doc_id = props.get("base", {}).get("id", "")

        is_uploaded = doc_id in remote_ids
        doc_structs.append({"docid": doc_id, "is_uploaded": is_uploaded})

        file_uid = props.get("file_uid", "") if isinstance(props, dict) else ""
        if file_uid:
            file_structs.append(
                {
                    "uid": file_uid,
                    "docid": doc_id,
                    "is_uploaded": is_uploaded,
                }
            )

    return doc_structs, file_structs, total_size
