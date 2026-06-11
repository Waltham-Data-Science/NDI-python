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


def _props_ndi_id(doc: dict[str, Any]) -> str:
    """Return a document's NDI id whether *doc* is a property dict or a
    remote-listing summary.

    Local ``document_properties`` dicts carry the id at ``base.id``; remote
    listing summaries carry it at the top level as ``ndiId``/``id``. The
    earlier code only looked at the top level, so local documents never
    deduplicated against the remote (audit C1/C3).
    """
    if not isinstance(doc, dict):
        return ""
    base = doc.get("base")
    if isinstance(base, dict) and base.get("id"):
        return base["id"]
    return doc.get("ndiId", doc.get("id", ""))


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
            existing_ids = {_props_ndi_id(d) for d in existing.data}
            filtered = [d for d in documents if _props_ndi_id(d) not in existing_ids]
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
                report["manifest"].append(_props_ndi_id(doc))
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
            doc_id = _props_ndi_id(doc) or f"doc_{i}"
            filename = f"{doc_id}.json"
            zf.writestr(filename, json.dumps(doc, indent=2))
            manifest.append(doc_id)

    return zip_path, manifest


def _binary_file_manifest(dataset: Any, documents: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build a manifest of the binary files attached to *documents*.

    Audit C3: binaries live under ``files.file_info[].locations[].uid`` (a
    cloud file UID) — not a top-level ``file_uid`` field. Each entry's local
    path is resolved from the dataset's binary store via
    ``database_existbinarydoc``; ``ndicloud`` locations are already remote and
    are skipped.

    Returns:
        List of ``{"uid", "name", "file_path"}`` dicts.
    """
    manifest: list[dict[str, str]] = []
    seen: set[str] = set()
    for props in documents:
        if not isinstance(props, dict):
            continue
        doc_id = props.get("base", {}).get("id", "")
        files = props.get("files", {})
        if not isinstance(files, dict):
            continue
        for fi in files.get("file_info", []):
            if not isinstance(fi, dict):
                continue
            name = fi.get("name", "")
            for loc in fi.get("locations", []):
                if not isinstance(loc, dict):
                    continue
                if loc.get("location_type") == "ndicloud":
                    continue  # already on the remote
                uid = loc.get("uid", "")
                if not uid or uid in seen:
                    continue
                try:
                    exists, path = dataset.database_existbinarydoc(doc_id, name)
                except Exception:
                    exists, path = False, None
                if exists and path:
                    manifest.append({"uid": uid, "name": name, "file_path": str(path)})
                    seen.add(uid)
                    break  # one stored binary per file_info entry
    return manifest


def uploadFilesForDatasetDocuments(
    dataset: Any,
    dataset_id: str,
    documents: list[dict[str, Any]],
    *,
    file_upload_strategy: str = "batch",
    only_missing: bool = True,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload the binary files associated with a list of documents.

    MATLAB equivalent: ``ndi.cloud.sync.internal.uploadFilesForDatasetDocuments``.

    The binary UIDs and their local paths are resolved from each document's
    ``files.file_info[].locations[]`` and the dataset's binary store (audit
    C3 — the previous implementation read a nonexistent top-level
    ``file_uid``/``file_path`` and uploaded nothing).

    Args:
        dataset: The local dataset (used to resolve binary file paths).
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        file_upload_strategy: ``"serial"`` (per-file) or ``"batch"``.
        only_missing: Skip files already present on the remote.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with counts of uploaded and failed files.
    """
    from .internal import filesNotYetUploaded

    report: dict[str, Any] = {"uploaded": 0, "failed": 0, "errors": []}

    manifest = _binary_file_manifest(dataset, documents)
    if only_missing and manifest:
        manifest = filesNotYetUploaded(manifest, dataset_id, client=client)

    for entry in manifest:
        use_bulk = file_upload_strategy == "batch"
        success, msg = uploadSingleFile(
            dataset_id,
            entry["uid"],
            entry["file_path"],
            use_bulk_upload=use_bulk,
            client=client,
        )
        if success:
            report["uploaded"] += 1
        else:
            report["failed"] += 1
            report["errors"].append(f"{entry['uid']}: {msg}")

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
    import uuid

    from .api import files as files_api

    try:
        if use_bulk_upload:
            zip_name = f"{dataset_id}.{uuid.uuid4().hex}.zip"
            zip_path = Path(tempfile.gettempdir()) / zip_name
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    # Archive entry keyed by basename, matching MATLAB
                    # uploadSingleFile.m so server-side extraction maps the
                    # file the same way for both clients.
                    zf.write(file_path, Path(file_path).name)
                info = files_api.getFileCollectionUploadURL(
                    client.config.org_id,
                    dataset_id,
                    client=client,
                )
                # getFileCollectionUploadURL returns {"url", "jobId"} — the
                # presigned PUT URL and the server-side extraction job id.
                # Passing the whole dict where putFiles expects a URL string
                # was a guaranteed pydantic failure (audit C3).
                files_api.putFiles(
                    info["url"],
                    str(zip_path),
                    job_id=info.get("jobId", ""),
                )
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

    try:
        if verbose:
            print("Loading documents...")
        all_docs = (
            dataset.database_search(ndi_query("")) if hasattr(dataset, "database_search") else []
        )
        doc_props = [
            (doc.document_properties if hasattr(doc, "document_properties") else doc)
            for doc in all_docs
        ]
        doc_props = [d for d in doc_props if isinstance(d, dict)]

        if verbose:
            print(f"Uploading {len(doc_props)} documents...")
        report = uploadDocumentCollection(dataset_id, doc_props, only_missing=True, client=client)
        if report.get("status") not in ("ok", "partial"):
            return False, f"Document upload failed: {report.get('status')}"

        if verbose:
            print("Uploading associated binary files...")
        uploadFilesForDatasetDocuments(dataset, dataset_id, doc_props, client=client)

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
        all_docs = (
            dataset.database_search(ndi_query("")) if hasattr(dataset, "database_search") else []
        )
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

        # Binary file UIDs live under files.file_info[].locations[].uid, not a
        # top-level file_uid field (audit C3).
        files = props.get("files", {}) if isinstance(props, dict) else {}
        if isinstance(files, dict):
            for fi in files.get("file_info", []):
                if not isinstance(fi, dict):
                    continue
                for loc in fi.get("locations", []):
                    if not isinstance(loc, dict):
                        continue
                    uid = loc.get("uid", "")
                    if uid:
                        file_structs.append(
                            {
                                "uid": uid,
                                "name": fi.get("name", ""),
                                "docid": doc_id,
                                "is_uploaded": is_uploaded,
                            }
                        )

    return doc_structs, file_structs, total_size
