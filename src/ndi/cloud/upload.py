"""
ndi.cloud.upload - Upload orchestration for NDI Cloud.

Provides batch (ZIP) and serial upload modes for document collections,
plus presigned-URL file uploads.

MATLAB equivalents: +ndi/+cloud/+upload/*.m, uploadSingleFile.m
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import _auto_client

if TYPE_CHECKING:
    from .client import CloudClient

logger = logging.getLogger(__name__)


def document_id(doc: dict[str, Any]) -> str:
    """The NDI id of a document, whichever shape it arrived in.

    ``ndiId`` is what the cloud returns and what a manifest entry carries;
    ``base.id`` is what a real ``ndi.document`` carries. Reading only the
    first two meant every document enumerated from a dataset resolved to
    ``""`` -- so an upload manifest came back as a list of empty strings and
    the caller could not tell which documents had landed.
    """
    if not isinstance(doc, dict):
        return ""
    base = doc.get("base")
    return str(
        doc.get("ndiId")
        or (base.get("id") if isinstance(base, dict) else "")
        or doc.get("id")
        or ""
    )


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
            existing_ids = {document_id(d) for d in existing.data}
            filtered = [d for d in documents if document_id(d) not in existing_ids]
            report["skipped"] = len(documents) - len(filtered)
            documents = filtered
        except Exception as exc:
            # Proceeding with all of them is the safe fallback -- the remote
            # rejects a duplicate, it does not corrupt anything. But a bare
            # pass here means a listing call that has stopped working looks
            # exactly like a dataset with nothing on the remote yet: every
            # run re-uploads everything and nothing ever says why.
            logger.warning(
                "Could not list existing remote documents (%s); "
                "uploading all %d documents without the only_missing filter",
                exc,
                len(documents),
            )

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
                report["manifest"].append(document_id(doc))
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
    additional_roots: list[str] | None = None,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload associated binary files for a list of documents.

    For each document that has a ``file_uid`` field, obtains a
    presigned URL and uploads the file.

    Args:
        org_id: Organisation ID.
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        additional_roots: Extra directories to search for a file whose
            recorded ``location`` no longer exists on disk -- typically
            the dataset's DID ``FileDir``. Passed through to
            :func:`file_uploads_for_document`.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with counts of uploaded and failed files.
    """
    from .api import files as files_api

    report: dict[str, Any] = {
        "uploaded": 0,
        "failed": 0,
        "errors": [],
        # Which documents own the binaries that did not make it. A count
        # cannot be acted on: the caller has to know which documents to
        # keep out of the sync index, or it records them as synced with
        # their binaries missing from the remote (NDI-matlab#805).
        "failed_document_ids": [],
    }

    for doc in documents:
        doc_id = document_id(doc)
        for file_uid, file_path in file_uploads_for_document(
            doc, additional_roots=additional_roots
        ):
            try:
                url = files_api.getFileUploadURL(org_id, dataset_id, file_uid, client=client)
                files_api.putFiles(url, file_path)
                report["uploaded"] += 1
            except Exception as exc:
                report["failed"] += 1
                report["errors"].append(str(exc))
                if doc_id and doc_id not in report["failed_document_ids"]:
                    report["failed_document_ids"].append(doc_id)

    return report


def file_uploads_for_document(
    doc: dict[str, Any],
    *,
    additional_roots: list[str] | None = None,
) -> list[tuple[str, str]]:
    """The ``(file_uid, local_path)`` pairs to upload for one document.

    TWO SHAPES REACH THIS, AND ONLY ONE USED TO BE READ.

    A manifest entry carries ``file_uid`` and ``file_path`` at the top level,
    and that is all this looked at. A real ``ndi.document`` carries neither:
    its binaries live under ``files.file_info[].locations[]``, each location
    holding a ``uid`` and a ``location`` that is a filesystem path until
    :mod:`ndi.cloud.filehandler` rewrites it to ``ndic://``. So every caller
    passing real documents -- which is every caller that enumerates a dataset
    -- matched nothing and uploaded nothing, silently, because a document
    with no recognised file is indistinguishable from a document with no
    files at all.

    Locations already rewritten to ``ndic://`` are skipped: that scheme means
    the file is on the cloud, which is the opposite of something to upload.

    A location that no longer resolves on disk is looked up by uid in
    *additional_roots* (typically the dataset's DID ``FileDir``, plus DID's
    global file cache via :func:`did.file.cached_path_for_uid`). The
    recorded location is the source path the caller passed to ``add_file``,
    and DID's ingest moves the bytes into ``<FileDir>/<uid>`` with
    ``delete_original=True`` by default -- so a series manifest, which
    ``did.document.add_file_series`` writes to a tempfile, is gone from its
    original path by the time the upload runs. The bytes are still there,
    keyed by uid, and this fallback finds them. Without it, a series
    document's manifest is silently never uploaded and every reader on the
    cloud side sees "manifest not a file of this dataset" and a series it
    cannot open. See Waltham-Data-Science/NDI-python#306.
    """
    import os

    top_uid = str(doc.get("file_uid", "") or "")
    top_path = str(doc.get("file_path", "") or "")
    if top_uid and top_path:
        return [(top_uid, top_path)]

    pairs: list[tuple[str, str]] = []
    files = doc.get("files") or {}
    if not isinstance(files, dict):
        return pairs
    infos = files.get("file_info") or []
    if isinstance(infos, dict):
        infos = [infos]
    for info in infos:
        if not isinstance(info, dict):
            continue
        locations = info.get("locations") or []
        if isinstance(locations, dict):
            locations = [locations]
        uid = ""
        local_path = ""
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            uid = uid or str(loc.get("uid", "") or "")
            candidate = str(loc.get("location", "") or "")
            if not local_path and candidate and "://" not in candidate:
                if os.path.exists(candidate):
                    local_path = candidate
        if uid and not local_path:
            local_path = _cached_path_for_uid(uid, additional_roots)
        if uid and local_path:
            pairs.append((uid, local_path))
    return pairs


def _cached_path_for_uid(uid: str, additional_roots: list[str] | None) -> str:
    """Look ``uid`` up in DID's on-disk stores, or return ``""``.

    Isolated so a did-python import failure never breaks the ordinary
    recorded-location path: DID is a hard dependency at runtime, but this
    helper is on the fallback path and swallowing an ImportError keeps the
    upload behaviour of a doc with a live location identical.
    """
    if not uid:
        return ""
    try:
        from did.file import cached_path_for_uid
    except ImportError:  # pragma: no cover - DID is a hard runtime dep
        return ""
    try:
        return str(cached_path_for_uid(uid, additional_roots=additional_roots) or "")
    except Exception:  # noqa: BLE001 - a malformed uid must not fail the upload
        return ""


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


# uploadToNDICloud and scanForUpload were retired here to match
# VH-Lab/NDI-matlab#965, which removed both MATLAB functions in commit
# 120aabf6. Nothing in this codebase called uploadToNDICloud any longer --
# orchestration.newDataset already delegates to uploadDataset, mirroring the
# same rerouting on the MATLAB side -- and scanForUpload was called only
# from uploadToNDICloud itself and from tests/test_cloud_upload_manifest.py,
# whose whole subject was regression coverage for those two shims.
# The bridge YAML entries under the same names in
# src/ndi/cloud/ndi_matlab_python_bridge.yaml record the retirement.
