"""
ndi.cloud.upload - Upload orchestration for NDI Cloud.

Provides batch (ZIP) and serial upload modes for document collections,
plus presigned-URL file uploads.

MATLAB equivalents: +ndi/+cloud/+upload/*.m, uploadSingleFile.m
"""

from __future__ import annotations

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
    wait_for_ingestion: bool = True,
    ingestion_timeout: float = 300.0,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload a list of document dicts to the cloud.

    MATLAB equivalent: +ndi/+cloud/+upload/uploadDocumentCollection.m

    By default the documents go up in bulk: each chunk is written as one
    JSON array, zipped (:func:`zip_documents_for_upload`) and PUT to the URL
    from :func:`ndi.cloud.api.documents.getBulkUploadURL`. If the environment
    variable ``NDI_CLOUD_UPLOAD_NO_ZIP`` is ``'true'``, they are sent one at
    a time with :func:`ndi.cloud.api.documents.addDocument` instead.

    Args:
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        only_missing: If True, skip documents already on the remote.
        max_chunk: Maximum documents per chunk. ``None`` (default) reads the
            preference ``Cloud.Upload.Max_Document_Batch_Count``; ``0`` or a
            negative value means all at once.
        wait_for_ingestion: If True (default), a bulk upload does not return
            until the server lists the uploaded documents, or until
            *ingestion_timeout* elapses. A bulk upload returns once each zip
            is stored, before the server has ingested it, so without this a
            listing made straight afterwards can miss documents. Serial
            uploads are not affected.
        ingestion_timeout: Seconds to wait for ingestion. Default 300. A
            timeout is logged as a warning and does not change ``status``.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with ``upload_type`` (``'batch'`` or ``'serial'``),
        ``total``, ``uploaded``, ``skipped``, ``manifest`` (ids of the
        documents sent), ``status`` (``'ok'`` or ``'partial'``) and, on a
        failure, ``errors``. When a bulk upload waited for ingestion,
        ``ingestion`` holds the result of
        :func:`ndi.cloud.api.documents.waitForDocumentCount`.
    """
    import os

    from .api import documents as docs_api

    serial = os.environ.get("NDI_CLOUD_UPLOAD_NO_ZIP", "").lower() in ("true", "1", "yes")

    report: dict[str, Any] = {
        "upload_type": "serial" if serial else "batch",
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
    if max_chunk is None:
        from .. import preferences

        max_chunk = int(preferences.get("Cloud.Upload.Max_Document_Batch_Count"))
    chunks = [documents]
    if max_chunk and max_chunk > 0:
        chunks = [documents[i : i + max_chunk] for i in range(0, len(documents), max_chunk)]

    def _fail(message: str) -> None:
        report["status"] = "partial"
        report.setdefault("errors", []).append(message)

    if serial:
        for chunk in chunks:
            for doc in chunk:
                try:
                    docs_api.addDocument(dataset_id, doc, client=client)
                    report["uploaded"] += 1
                    report["manifest"].append(document_id(doc))
                except Exception as exc:
                    _fail(str(exc))
        return report

    from .api import files as files_api

    # The server's count before this upload, so the ingestion wait below
    # knows what count to expect. None skips the wait.
    count_before: int | None = None
    if wait_for_ingestion:
        try:
            count_before = int(docs_api.countDocuments(dataset_id, client=client))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not read the document count of %s (%s); not waiting for ingestion",
                dataset_id,
                exc,
            )

    for n, chunk in enumerate(chunks, start=1):
        zip_path: Path | None = None
        try:
            zip_path, id_manifest = zip_documents_for_upload(chunk, dataset_id)
            url = docs_api.getBulkUploadURL(dataset_id, client=client)
            if not url:
                raise RuntimeError("no bulk upload URL returned")
            files_api.putFiles(url, str(zip_path))
            report["uploaded"] += len(id_manifest)
            report["manifest"].extend(id_manifest)
        except Exception as exc:  # noqa: BLE001 - reported per batch
            _fail(f"Batch {n} ({len(chunk)} documents): {exc}")
        finally:
            if zip_path is not None and zip_path.exists():
                zip_path.unlink()

    # A stored zip is not yet an ingested one, and bulk document uploads have
    # no job to wait on, so wait for the server's document count to take in
    # every document from the batches that were stored. The server adds a new
    # document for each one uploaded, even one whose id it already lists, so
    # the count grows by exactly that many.
    if count_before is not None and report["uploaded"] > 0:
        expected = count_before + report["uploaded"]
        try:
            ingestion = docs_api.waitForDocumentCount(
                dataset_id, expected, timeout=ingestion_timeout, client=client
            )
        except Exception as exc:  # noqa: BLE001
            ingestion = {
                "state": "error",
                "count": float("nan"),
                "expectedCount": expected,
                "elapsed": float("nan"),
                "message": str(exc),
            }
        report["ingestion"] = ingestion
        if ingestion.get("state") != "complete":
            logger.warning(
                "Dataset %s lists %s of the %d documents expected after this upload "
                "(state: %s). The upload succeeded; the server may still be ingesting "
                "the rest.",
                dataset_id,
                ingestion.get("count"),
                expected,
                ingestion.get("state"),
            )

    return report


def zip_documents_for_upload(
    documents: list[dict[str, Any]],
    dataset_id: str,
    *,
    target_folder: str | Path | None = None,
) -> tuple[Path, list[str]]:
    """Write documents as one JSON array and zip it for a bulk upload.

    MATLAB equivalent: +ndi/+cloud/+upload/+internal/zip_documents_for_upload.m

    The archive holds a single ``.json`` file: the documents' properties as a
    JSON array, encoded with :func:`did.datastructures.json_encode_nan` so NaN
    and Infinity survive, as MATLAB's ``did.datastructures.jsonencodenan``
    does. The zip is named ``<dataset_id>.<random>.zip`` so concurrent uploads
    do not collide.

    Args:
        documents: Document property dicts.
        dataset_id: Cloud dataset ID (used in the zip's name).
        target_folder: Where to write the zip. Defaults to the system's
            temporary folder.

    Returns:
        ``(zip_path, id_manifest)``: the zip's path, which the caller must
        delete, and the ids of the documents in it, in order.
    """
    import uuid

    from did.datastructures import json_encode_nan

    folder = Path(target_folder) if target_folder is not None else Path(tempfile.gettempdir())
    json_text = json_encode_nan(list(documents))
    id_manifest = [document_id(doc) for doc in documents]
    zip_path = folder / f"{dataset_id}.{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{uuid.uuid4().hex}.json", json_text)
    return zip_path, id_manifest


def zipForUpload(
    file_manifest: list[dict[str, Any]],
    dataset_id: str,
    *,
    org_id: str = "",
    size_limit: float | None = None,
    number_retries: int = 3,
    completion_timeout: float = 300.0,
    retry_pause: float = 5.0,
    verbose: bool = False,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload binary files to the cloud in zip batches of at most *size_limit* bytes.

    MATLAB equivalent: +ndi/+cloud/+upload/zipForUpload.m

    Files are packed greedily in the order given: a batch closes when the next
    file would take it past *size_limit*, and the next batch starts with that
    file. A single file larger than *size_limit* still goes up, alone in its
    own batch (the first file of a batch is always accepted). Each batch is
    zipped to a temporary file, sent to the URL from
    :func:`ndi.cloud.api.files.getFileCollectionUploadURL`, and deleted.

    Each zip entry is named by the file's uid, which is how NDI Cloud keys the
    extracted file.

    Unlike MATLAB's version, which returns only success and a message, this
    reports which documents' files did not make it, because the sync callers
    must keep those documents out of the sync index (NDI-matlab#805). A batch
    counts as failed if its URL could not be obtained, its zip could not be
    built or sent after *number_retries* attempts, or the server's extraction
    job did not reach ``'complete'`` within *completion_timeout* seconds. All
    batches are sent before any extraction job is waited on, so the server
    unpacks earlier batches while later ones are still uploading.

    Args:
        file_manifest: Entries with ``file_uid``, ``file_path``, and optionally
            ``document_id`` and ``bytes`` (looked up on disk when absent).
        dataset_id: Cloud dataset ID.
        org_id: Organisation ID. Defaults to the organization that owns
            *dataset_id*, read from the dataset record.
        size_limit: Maximum batch size in bytes. ``None`` (default) reads the
            preference ``Cloud.Upload.Max_File_Batch_Size``.
        number_retries: Attempts at getting the upload URL and at the PUT.
        completion_timeout: Seconds to wait for each batch's server-side
            extraction job.
        retry_pause: Seconds between retry attempts.
        verbose: Print progress.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with ``uploaded`` and ``failed`` (file counts), ``errors``,
        ``failed_document_ids``, and ``batches`` (number of zips sent).
    """
    import os
    import time
    import uuid

    from .api import files as files_api

    if size_limit is None:
        from .. import preferences

        size_limit = float(preferences.get("Cloud.Upload.Max_File_Batch_Size"))
    if size_limit <= 0:
        raise ValueError(f"size_limit must be positive (got {size_limit!r})")

    report: dict[str, Any] = {
        "uploaded": 0,
        "failed": 0,
        "errors": [],
        "failed_document_ids": [],
        "batches": 0,
    }
    if file_manifest and not org_id:
        from .internal import _datasetOrganizationId

        org_id = _datasetOrganizationId(dataset_id, client=client)

    def _fail(batch: list[dict[str, Any]], message: str) -> None:
        report["failed"] += len(batch)
        report["errors"].append(message)
        for entry in batch:
            doc_id = str(entry.get("document_id", "") or "")
            if doc_id and doc_id not in report["failed_document_ids"]:
                report["failed_document_ids"].append(doc_id)

    def _size(entry: dict[str, Any]) -> int:
        if entry.get("bytes") is not None:
            return int(entry["bytes"])
        try:
            return os.path.getsize(entry["file_path"])
        except OSError:
            # Missing at sizing time: let it fail inside its batch's zip step,
            # where it is reported, rather than silently dropping it.
            return 0

    # Greedy single-pass packing, same as MATLAB's cursor loop.
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0
    for entry in file_manifest:
        fb = _size(entry)
        if current and current_size + fb > size_limit:
            batches.append(current)
            current, current_size = [], 0
        current.append(entry)
        current_size += fb
    if current:
        batches.append(current)

    if verbose:
        print(
            f"Beginning upload process. {len(file_manifest)} files to upload "
            f"in {len(batches)} batch(es)."
        )

    pending_jobs: list[tuple[str, list[dict[str, Any]]]] = []
    for n, batch in enumerate(batches, start=1):
        zip_path = Path(tempfile.gettempdir()) / f"{dataset_id}.{uuid.uuid4().hex}.zip"
        try:
            try:
                if verbose:
                    total_mb = sum(_size(e) for e in batch) / 1e6
                    print(
                        f"Zipping batch {n} of {len(batches)}: {len(batch)} files ({total_mb:.2f} MB)..."
                    )
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for entry in batch:
                        zf.write(entry["file_path"], str(entry["file_uid"]))
            except Exception as exc:  # noqa: BLE001 - reported per batch
                _fail(batch, f"Batch {n}: could not build zip: {exc}")
                continue

            info: dict[str, Any] = {}
            last_exc: Exception | None = None
            for attempt in range(max(1, number_retries)):
                try:
                    info = files_api.getFileCollectionUploadURL(org_id, dataset_id, client=client)
                    if info.get("url"):
                        break
                    last_exc = RuntimeError("no upload URL returned")
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                if attempt + 1 < number_retries:
                    time.sleep(retry_pause)
            if not info.get("url"):
                _fail(batch, f"Batch {n}: could not get upload URL: {last_exc}")
                continue

            sent = False
            for attempt in range(max(1, number_retries)):
                try:
                    files_api.putFiles(info["url"], str(zip_path))
                    sent = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if verbose:
                        print(
                            f"Attempt {attempt + 1} of {number_retries} to upload batch {n} failed."
                        )
                    if attempt + 1 < number_retries:
                        time.sleep(retry_pause)
            if not sent:
                _fail(batch, f"Batch {n}: upload failed: {last_exc}")
                continue

            report["batches"] += 1
            job_id = str(info.get("jobId", "") or "")
            if job_id:
                pending_jobs.append((job_id, batch))
            else:
                # Older servers return no job id: the PUT succeeding is all
                # there is to go on.
                report["uploaded"] += len(batch)
        finally:
            if zip_path.exists():
                zip_path.unlink()

    for job_id, batch in pending_jobs:
        try:
            final = files_api.waitForBulkUpload(job_id, timeout=completion_timeout, client=client)
            state = final.get("state", "") if hasattr(final, "get") else ""
        except Exception as exc:  # noqa: BLE001
            state = f"error ({exc})"
        if state == "complete":
            report["uploaded"] += len(batch)
        else:
            _fail(batch, f"Bulk upload job {job_id} ended in state {state!r}")

    if verbose:
        print(
            f"Upload process finished. {report['uploaded']} files uploaded, "
            f"{report['failed']} failed."
        )
    return report


def uploadFilesForDatasetDocuments(
    org_id: str,
    dataset_id: str,
    documents: list[dict[str, Any]],
    *,
    dataset: Any | None = None,
    file_upload_strategy: str = "batch",
    file_batch_size_limit: float | None = None,
    verbose: bool = False,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload associated binary files for a list of documents.

    Args:
        org_id: Organisation ID -- the organization that owns *dataset_id*.
            ``""`` looks it up from the dataset record, as MATLAB's
            file-upload calls do.
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        dataset: The local ``ndi.dataset`` that produced *documents*. When
            given, its ``database_existbinarydoc`` is the source of truth
            for where each file actually lives on disk, and series members
            (which have no ``file_info`` entry) are enumerated from
            ``series_info[k].count``. Mirrors NDI-matlab's
            ``list_binary_files.m``.
        file_upload_strategy: ``'batch'`` (default) packs the files into zip
            batches and sends them with :func:`zipForUpload`; ``'serial'``
            sends each file on its own signed URL. Mirrors MATLAB's
            ``FileUploadStrategy``.
        file_batch_size_limit: Maximum size in bytes of each zip batch.
            ``None`` (default) uses the preference
            ``Cloud.Upload.Max_File_Batch_Size``. Ignored for ``'serial'``.
        verbose: Print progress.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with counts of uploaded and failed files.
    """
    import os

    from .api import files as files_api

    if file_upload_strategy not in ("batch", "serial"):
        raise ValueError(
            f"file_upload_strategy must be 'batch' or 'serial' (got {file_upload_strategy!r})"
        )

    if file_upload_strategy == "batch":
        manifest: list[dict[str, Any]] = []
        for doc in documents:
            doc_id = document_id(doc)
            for file_uid, file_path in file_uploads_for_document(doc, dataset=dataset):
                try:
                    size = os.path.getsize(file_path)
                except OSError:
                    size = 0
                manifest.append(
                    {
                        "document_id": doc_id,
                        "file_uid": file_uid,
                        "file_path": file_path,
                        "bytes": size,
                    }
                )
        if not manifest:
            return {"uploaded": 0, "failed": 0, "errors": [], "failed_document_ids": []}
        report = zipForUpload(
            manifest,
            dataset_id,
            org_id=org_id,
            size_limit=file_batch_size_limit,
            verbose=verbose,
            client=client,
        )
        report.pop("batches", None)
        return report

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
                if not org_id:
                    from .internal import _datasetOrganizationId

                    org_id = _datasetOrganizationId(dataset_id, client=client)
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
    checksum: bool = True,
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
        checksum: If True (default), compute the file's CRC-32
            (:func:`ndi.fun.file.crc32`) and send it with the single-file
            upload, so S3 rejects a corrupted upload and NDI Cloud records
            the file's ``crc32``. Ignored for bulk uploads, whose zip entries
            carry their own CRC-32.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(success, error_message)``.
    """
    import os
    import uuid

    from .api import files as files_api
    from .internal import _datasetOrganizationId

    try:
        # The dataset's own organization, as MATLAB's GetFileUploadURL reads
        # it: a user in several organizations has no single one to assume.
        org_id = _datasetOrganizationId(dataset_id, client=client)
        if use_bulk_upload:
            zip_name = f"{dataset_id}.{uuid.uuid4().hex}.zip"
            zip_path = Path(tempfile.gettempdir()) / zip_name
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(file_path, os.path.basename(file_path))
                info = files_api.getFileCollectionUploadURL(
                    org_id,
                    dataset_id,
                    client=client,
                )
                # getFileCollectionUploadURL returns {"url", "jobId"}, not a
                # bare URL; passing the dict to putFiles failed validation.
                files_api.putFiles(info["url"], str(zip_path), job_id=info.get("jobId", ""))
            finally:
                if zip_path.exists():
                    zip_path.unlink()
        else:
            checksum_crc32 = ""
            if checksum:
                from ..fun.file import crc32

                checksum_crc32 = crc32(file_path)
            url = files_api.getFileUploadURL(
                org_id,
                dataset_id,
                file_uid,
                checksum_crc32=checksum_crc32,
                client=client,
            )
            files_api.putFiles(url, file_path, checksum_crc32=checksum_crc32)

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
