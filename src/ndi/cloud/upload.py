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
    dataset: Any | None = None,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload associated binary files for a list of documents.

    Args:
        org_id: Organisation ID.
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        dataset: The local ``ndi.dataset`` that produced *documents*. When
            given, its ``database_existbinarydoc`` is the source of truth
            for where each file actually lives on disk, and series members
            (which have no ``file_info`` entry) are enumerated from
            ``series_info[k].count``. Mirrors NDI-matlab's
            ``list_binary_files.m``.
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
        for file_uid, file_path in file_uploads_for_document(doc, dataset=dataset):
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
    dataset: Any | None = None,
) -> list[tuple[str, str]]:
    """The ``(file_uid, local_path)`` pairs to upload for one document.

    THREE SHAPES REACH THIS.

    * A manifest entry carrying top-level ``file_uid`` and ``file_path`` is
      taken as-is: legacy input from callers that already know the pair.

    * A real ``ndi.document`` alongside its owning ``dataset``: the storage-
      side path is asked for by name, via
      :meth:`ndi.dataset.database_existbinarydoc` (which is DID's
      ``exist_doc``). This mirrors NDI-matlab's
      ``+ndi/+database/+internal/list_binary_files.m`` and is what the live
      upload path always uses now. The advantage: it covers both the
      recorded-location-is-gone-after-ingest case (Waltham-Data-Science/
      NDI-python#306 -- ``did.document.Document.add_file_series`` writes the
      manifest to a tempfile, and ``add_file`` with the default
      ``delete_original=True`` removes it once ingested) AND series MEMBERS,
      which have no ``file_info`` entry and are enumerated from
      ``series_info[k].count`` (1..count, member names ``NAME_i``).

    * A raw document dict WITHOUT a dataset: the fallback reads
      ``files.file_info[].locations[].location`` and calls ``os.path.exists``.
      Kept so isolated tests and callers with no dataset in hand behave the
      way they used to. Locations already rewritten to ``ndic://`` are
      skipped there: that scheme means the file is on the cloud, which is
      the opposite of something to upload.
    """
    top_uid = str(doc.get("file_uid", "") or "")
    top_path = str(doc.get("file_path", "") or "")
    if top_uid and top_path:
        return [(top_uid, top_path)]

    if dataset is not None and callable(getattr(dataset, "database_existbinarydoc", None)):
        return _file_uploads_via_dataset(doc, dataset)

    return _file_uploads_via_recorded_location(doc)


def _file_uploads_via_dataset(
    doc: dict[str, Any],
    dataset: Any,
) -> list[tuple[str, str]]:
    """Enumerate binaries the way NDI-matlab's ``list_binary_files.m`` does.

    Ordinary files: walk ``files.file_info[i].name`` (which is what
    ``current_file_list()`` returns). For a series document, this yields the
    manifest name, and the manifest bytes live at ``<FileDir>/<manifest_uid>``
    after ingest -- exactly where ``database_existbinarydoc`` looks.

    Series members: iterate ``files.series_info[k].count`` from 1..count and
    ask for ``NAME_i``. Slots are one-based (see DID's series API), an absent
    slot is normal (a sparse series is the case the mechanism exists for),
    and the manifest is what makes each slot's uid resolvable.

    ``uid = basename(path)``: DID's file store keys files by uid, and
    ``exist_doc`` returns a path under ``<FileDir>/`` whose basename IS the
    uid. NDI-matlab's ``list_binary_files.m`` does the same
    (``fileparts(full_file_path)``).
    """
    import os

    doc_id = document_id(doc)
    if not doc_id:
        return []
    files = doc.get("files") or {}
    if not isinstance(files, dict):
        return []

    pairs: list[tuple[str, str]] = []

    file_info = files.get("file_info") or []
    if isinstance(file_info, dict):
        file_info = [file_info]
    for entry in file_info:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "") or "")
        if not name:
            continue
        found, path = dataset.database_existbinarydoc(doc_id, name)
        if not found or path is None:
            continue
        path_str = str(path)
        uid = os.path.basename(path_str)
        if uid:
            pairs.append((uid, path_str))

    series_info = files.get("series_info") or []
    if isinstance(series_info, dict):
        series_info = [series_info]
    for entry in series_info:
        if not isinstance(entry, dict):
            continue
        series_name = str(entry.get("name", "") or "")
        if not series_name:
            continue
        try:
            count = int(entry.get("count", 0) or 0)
        except (TypeError, ValueError):
            continue
        for i in range(1, count + 1):
            member_name = f"{series_name}_{i}"
            found, path = dataset.database_existbinarydoc(doc_id, member_name)
            if not found or path is None:
                continue
            path_str = str(path)
            uid = os.path.basename(path_str)
            if uid:
                pairs.append((uid, path_str))

    return pairs


def _file_uploads_via_recorded_location(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """The pre-#306 shape: read the authoring record off the doc dict.

    Kept for callers that pass a raw dict and no dataset. Never covers series
    members (they have no ``file_info`` entry), and skips a location whose
    file has been removed from disk -- both facts are what made the
    dataset-driven path necessary in the first place.
    """
    import os

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
        if uid and local_path:
            pairs.append((uid, local_path))
    return pairs


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
