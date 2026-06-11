"""
ndi.cloud.sync.operations - High-level sync operations.

Each function enumerates the local document set from the dataset's own
database (not from the sync index) and the remote set from the cloud,
computes the delta, and delegates to the upload/download helpers. The
sync index records the last-synced state so incremental syncs only move
new documents.

MATLAB equivalents: +ndi/+cloud/+sync/*.m

Deletion policy (matches MATLAB): the additive modes ``uploadNew``,
``downloadNew`` and ``twoWaySync`` never delete documents on either side.
Only the explicit mirror modes (``mirrorToRemote``, ``mirrorFromRemote``)
delete documents that are absent from the authoritative side.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import CloudSyncError
from .index import SyncIndex
from .mode import SyncMode, SyncOptions

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..client import CloudClient


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dataset_path(dataset: Any) -> Path:
    """Return the on-disk root of *dataset* (where ``.ndi/sync`` lives)."""
    path = dataset.getpath()
    return Path(path)


def _document_props(doc: Any) -> dict[str, Any]:
    """Return a document's property dict whether it is an object or a dict."""
    props = doc.document_properties if hasattr(doc, "document_properties") else doc
    return props if isinstance(props, dict) else {}


def _ndi_id(doc: Any) -> str:
    """Return the NDI document id (``base.id``) of a local document."""
    return _document_props(doc).get("base", {}).get("id", "")


def downloadNdiDocuments(
    cloud_dataset_id: str,
    ndi_to_api: dict[str, str],
    ids_to_download: set[str] | list[str],
    *,
    client: CloudClient | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch full document bodies from the cloud by NDI ID.

    MATLAB equivalent: ``ndi.cloud.sync.internal.downloadNdiDocuments``

    Returns:
        Tuple of ``(downloaded_docs, failed_ids)`` where *downloaded_docs*
        are full document-property dicts (the bulk-download payload).
    """
    from ..download import downloadDocumentCollection

    ids_to_download = list(ids_to_download)
    if not ids_to_download:
        return [], []

    api_ids = [ndi_to_api.get(ndi_id, ndi_id) for ndi_id in ids_to_download]

    try:
        docs = downloadDocumentCollection(cloud_dataset_id, doc_ids=api_ids, client=client)
    except Exception as exc:
        logger.warning("Bulk download failed: %s", exc)
        return [], list(ids_to_download)

    api_to_ndi = {v: k for k, v in ndi_to_api.items()}
    downloaded_api_ids: set[str] = set()
    for doc in docs:
        api_id = doc.get("_id", doc.get("id", ""))
        downloaded_api_ids.add(api_id)
        ndi_id = api_to_ndi.get(api_id, api_id)
        doc.setdefault("ndiId", ndi_id)

    failed = [
        ndi_id
        for ndi_id in ids_to_download
        if ndi_to_api.get(ndi_id, ndi_id) not in downloaded_api_ids
    ]
    return docs, failed


def _ingest_documents(dataset: Any, docs: list[dict[str, Any]]) -> list[str]:
    """Convert downloaded JSON document bodies into the dataset database.

    Audit C4: downloaded documents must be added through ``database_add`` so
    that ``database_search`` can find them, not dropped as raw JSON files.
    Returns the NDI ids actually added (idempotent re-adds are counted).
    """
    from ..download import jsons2documents

    if not docs:
        return []

    documents = jsons2documents(docs)
    added: list[str] = []
    for doc in documents:
        ndi_id = _ndi_id(doc)
        try:
            dataset.database_add(doc)
            added.append(ndi_id)
        except FileExistsError:
            # Document already present locally (re-sync) — treat as present.
            added.append(ndi_id)
        except ValueError as exc:
            # ndi_database.add re-raises a duplicate as ValueError("... already
            # exists ..."); a re-sync of an existing document is not a failure.
            if "already exists" in str(exc).lower():
                added.append(ndi_id)
            else:
                logger.warning("Failed to add downloaded document %s: %s", ndi_id, exc)
        except Exception as exc:
            logger.warning("Failed to add downloaded document %s: %s", ndi_id, exc)
    return added


def deleteLocalDocuments(dataset: Any, doc_ids: set[str] | list[str]) -> list[str]:
    """Remove documents from the local dataset database by NDI id.

    MATLAB equivalent: ``ndi.cloud.sync.internal.deleteLocalDocuments``

    Audit C4: deletes real database documents via ``database_rm``, not a
    side JSON cache. Used only by ``mirrorFromRemote``.
    """
    deleted: list[str] = []
    for doc_id in doc_ids:
        try:
            dataset.database_rm(doc_id, error_if_not_found=False)
            deleted.append(doc_id)
        except Exception as exc:
            logger.warning("Failed to delete local document %s: %s", doc_id, exc)
    return deleted


def _upload_documents(
    cloud_dataset_id: str,
    documents: list[Any],
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload full document bodies to the cloud (audit C1: not id stubs)."""
    from ..upload import uploadDocumentCollection

    doc_props = [_document_props(d) for d in documents]
    doc_props = [d for d in doc_props if d]
    return uploadDocumentCollection(cloud_dataset_id, doc_props, only_missing=True, client=client)


def _remote_ndi_ids(
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> dict[str, str]:
    """Return the current remote ``ndiId -> apiId`` map."""
    from ..internal import listRemoteDocumentIds

    return listRemoteDocumentIds(cloud_dataset_id, client=client)


def _local_documents(dataset: Any) -> tuple[list[Any], list[str]]:
    """Return ``(documents, ndi_ids)`` enumerated from the dataset database."""
    from ..internal import listLocalDocuments

    return listLocalDocuments(dataset)


def _upload_files(
    dataset: Any,
    cloud_dataset_id: str,
    documents: list[Any],
    options: SyncOptions,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload the binary files associated with *documents*.

    Returns a report dict ``{"uploaded", "failed", "errors"}``; a non-zero
    ``failed`` count signals the caller not to advance the sync index (so the
    documents whose binaries failed are re-tried on the next sync).
    """
    from ..upload import uploadFilesForDatasetDocuments

    try:
        return uploadFilesForDatasetDocuments(
            dataset,
            cloud_dataset_id,
            [_document_props(d) for d in documents],
            file_upload_strategy=options.file_upload_strategy,
            client=client,
        )
    except Exception as exc:
        logger.warning("File upload failed: %s", exc)
        return {"uploaded": 0, "failed": 1, "errors": [str(exc)]}


def _upload_ok(upload_report: dict[str, Any], file_report: dict[str, Any] | None) -> bool:
    """Return True iff every document (and any requested file) uploaded.

    Mirrors MATLAB's issue-805 guard: if any document or binary upload failed,
    the sync index must NOT be advanced past those documents, or the next sync
    would treat them as already-synced and never retry (silent remote loss).
    """
    if upload_report.get("status") not in ("ok", "none", None):
        return False
    if file_report is not None and file_report.get("failed", 0) > 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Public sync operations
# ---------------------------------------------------------------------------


def uploadNew(
    dataset: Any,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Upload documents that exist locally but not on the remote.

    MATLAB equivalent: ``ndi.cloud.sync.uploadNew``. Additive: never deletes.
    """
    options = options or SyncOptions()
    ds_path = _dataset_path(dataset)
    index = SyncIndex.read(ds_path)

    remote_last_sync = set(index.remote_doc_ids_last_sync)
    local_docs, local_ids = _local_documents(dataset)

    # New = present locally but not recorded on the remote at last sync.
    new_ids = set(local_ids) - remote_last_sync
    docs_to_upload = [d for d, i in zip(local_docs, local_ids) if i in new_ids]

    report: dict[str, Any] = {
        "mode": "upload_new",
        "upload_count": len(new_ids),
        "uploaded_document_ids": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["uploaded_document_ids"] = list(new_ids)
        return report

    if docs_to_upload:
        upload_report = _upload_documents(cloud_dataset_id, docs_to_upload, client=client)
        report["uploaded_document_ids"] = upload_report.get("manifest", [])
        report["upload_report"] = upload_report
        file_report = None
        if options.sync_files:
            file_report = _upload_files(
                dataset, cloud_dataset_id, docs_to_upload, options, client=client
            )
            report["file_report"] = file_report
        if not _upload_ok(upload_report, file_report):
            # Leave the index unchanged so failed documents are retried.
            report["status"] = "partial"
            return report

    # Record current local + freshly-listed remote state.
    remote_now = _remote_ndi_ids(cloud_dataset_id, client=client)
    index.update(local_ids, list(remote_now.keys()))
    index.write(ds_path)
    return report


def downloadNew(
    dataset: Any,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Download documents that exist on the remote but not in the last sync.

    MATLAB equivalent: ``ndi.cloud.sync.downloadNew``. Additive: never deletes.
    """
    options = options or SyncOptions()
    ds_path = _dataset_path(dataset)
    index = SyncIndex.read(ds_path)

    remote_last_sync = set(index.remote_doc_ids_last_sync)
    remote_now = _remote_ndi_ids(cloud_dataset_id, client=client)
    new_ids = set(remote_now.keys()) - remote_last_sync

    report: dict[str, Any] = {
        "mode": "download_new",
        "download_count": len(new_ids),
        "downloaded_document_ids": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["downloaded_document_ids"] = list(new_ids)
        return report

    docs, failed = downloadNdiDocuments(cloud_dataset_id, remote_now, new_ids, client=client)
    added = _ingest_documents(dataset, docs)
    report["downloaded_document_ids"] = added
    report["failed"] = failed

    _, local_now = _local_documents(dataset)
    index.update(local_now, list(remote_now.keys()))
    index.write(ds_path)
    return report


def mirrorToRemote(
    dataset: Any,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Make the remote a mirror of the local dataset.

    MATLAB equivalent: ``ndi.cloud.sync.mirrorToRemote``. Uploads local-only
    documents and deletes remote documents that are absent locally.
    """
    from ..api import documents as docs_api

    options = options or SyncOptions()
    ds_path = _dataset_path(dataset)
    index = SyncIndex.read(ds_path)

    local_docs, local_ids = _local_documents(dataset)
    local_id_set = set(local_ids)
    remote_now = _remote_ndi_ids(cloud_dataset_id, client=client)

    to_upload = local_id_set - set(remote_now.keys())
    to_delete = set(remote_now.keys()) - local_id_set
    docs_to_upload = [d for d, i in zip(local_docs, local_ids) if i in to_upload]

    report: dict[str, Any] = {
        "mode": "mirror_to_remote",
        "upload_count": len(to_upload),
        "delete_count": len(to_delete),
        "uploaded_document_ids": [],
        "deleted_remote_document_ids": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["uploaded_document_ids"] = list(to_upload)
        report["deleted_remote_document_ids"] = list(to_delete)
        return report

    failed: list[str] = []
    upload_clean = True
    if docs_to_upload:
        upload_report = _upload_documents(cloud_dataset_id, docs_to_upload, client=client)
        report["uploaded_document_ids"] = upload_report.get("manifest", [])
        report["upload_report"] = upload_report
        file_report = None
        if options.sync_files:
            file_report = _upload_files(
                dataset, cloud_dataset_id, docs_to_upload, options, client=client
            )
            report["file_report"] = file_report
        upload_clean = _upload_ok(upload_report, file_report)

    for ndi_id in to_delete:
        api_id = remote_now.get(ndi_id, ndi_id)
        try:
            docs_api.deleteDocument(cloud_dataset_id, api_id, client=client)
            report["deleted_remote_document_ids"].append(ndi_id)
        except Exception as exc:
            logger.warning("mirrorToRemote: failed to delete remote %s: %s", ndi_id, exc)
            failed.append(ndi_id)
    report["failed"] = failed

    if not upload_clean or failed:
        # Don't advance the index if any upload or deletion failed.
        report["status"] = "partial"
        return report

    remote_after = _remote_ndi_ids(cloud_dataset_id, client=client)
    index.update(local_ids, list(remote_after.keys()))
    index.write(ds_path)
    return report


def mirrorFromRemote(
    dataset: Any,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Make the local dataset a mirror of the remote.

    MATLAB equivalent: ``ndi.cloud.sync.mirrorFromRemote``. Downloads
    remote-only documents and deletes local documents absent on the remote.
    """
    options = options or SyncOptions()
    ds_path = _dataset_path(dataset)
    index = SyncIndex.read(ds_path)

    _, local_ids = _local_documents(dataset)
    local_id_set = set(local_ids)
    remote_now = _remote_ndi_ids(cloud_dataset_id, client=client)
    remote_id_set = set(remote_now.keys())

    to_download = remote_id_set - local_id_set
    to_delete_local = local_id_set - remote_id_set

    report: dict[str, Any] = {
        "mode": "mirror_from_remote",
        "download_count": len(to_download),
        "delete_local_count": len(to_delete_local),
        "downloaded_document_ids": [],
        "deleted_local_document_ids": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["downloaded_document_ids"] = list(to_download)
        report["deleted_local_document_ids"] = list(to_delete_local)
        return report

    docs, failed = downloadNdiDocuments(cloud_dataset_id, remote_now, to_download, client=client)
    report["downloaded_document_ids"] = _ingest_documents(dataset, docs)
    report["failed"] = failed
    report["deleted_local_document_ids"] = deleteLocalDocuments(dataset, to_delete_local)

    _, local_after = _local_documents(dataset)
    index.update(local_after, list(remote_id_set))
    index.write(ds_path)
    return report


def twoWaySync(
    dataset: Any,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Bidirectional **additive** synchronization.

    MATLAB equivalent: ``ndi.cloud.sync.twoWaySync``. Uploads documents
    present only locally and downloads documents present only on the remote.
    It never deletes documents on either side — MATLAB's twoWaySync is
    strictly additive, so a remote (or local) deletion is NOT propagated.
    """
    options = options or SyncOptions()
    ds_path = _dataset_path(dataset)
    index = SyncIndex.read(ds_path)

    local_docs, local_ids = _local_documents(dataset)
    local_id_set = set(local_ids)
    remote_now = _remote_ndi_ids(cloud_dataset_id, client=client)
    remote_id_set = set(remote_now.keys())

    to_upload = local_id_set - remote_id_set
    to_download = remote_id_set - local_id_set
    docs_to_upload = [d for d, i in zip(local_docs, local_ids) if i in to_upload]

    report: dict[str, Any] = {
        "mode": "two_way_sync",
        "upload_count": len(to_upload),
        "download_count": len(to_download),
        "uploaded_document_ids": [],
        "downloaded_document_ids": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["uploaded_document_ids"] = list(to_upload)
        report["downloaded_document_ids"] = list(to_download)
        return report

    # Phase 1: upload local-only documents.
    upload_clean = True
    if docs_to_upload:
        upload_report = _upload_documents(cloud_dataset_id, docs_to_upload, client=client)
        report["uploaded_document_ids"] = upload_report.get("manifest", [])
        report["upload_report"] = upload_report
        file_report = None
        if options.sync_files:
            file_report = _upload_files(
                dataset, cloud_dataset_id, docs_to_upload, options, client=client
            )
            report["file_report"] = file_report
        upload_clean = _upload_ok(upload_report, file_report)

    # Phase 2: download remote-only documents (re-list remote after upload).
    remote_after_upload = _remote_ndi_ids(cloud_dataset_id, client=client)
    to_download = set(remote_after_upload.keys()) - local_id_set
    docs, failed = downloadNdiDocuments(
        cloud_dataset_id, remote_after_upload, to_download, client=client
    )
    report["downloaded_document_ids"] = _ingest_documents(dataset, docs)
    report["failed"] = failed

    # Phase 3: record the final state of both sides — but only if the upload
    # phase fully succeeded, so failed documents are retried next sync.
    if not upload_clean:
        report["status"] = "partial"
        return report
    _, local_after = _local_documents(dataset)
    remote_final = _remote_ndi_ids(cloud_dataset_id, client=client)
    index.update(local_after, list(remote_final.keys()))
    index.write(ds_path)
    return report


def validate(
    dataset: Any,
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Compare local and remote datasets to identify sync discrepancies.

    MATLAB equivalent: ``ndi.cloud.sync.validate``.

    Returns:
        Report dict with ``local_only_ids``, ``remote_only_ids``,
        ``common_ids``, ``local_count`` and ``remote_count``. (Content-hash
        comparison of the common ids — MATLAB validate.m's mismatch detection
        — is not yet implemented; this compares id sets only.)
    """
    from ..internal import validateSync as _validate

    return _validate(dataset, cloud_dataset_id, client=client)


def sync(
    dataset: Any,
    cloud_dataset_id: str,
    mode: SyncMode,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Dispatch to the appropriate sync operation based on *mode*."""
    dispatch = {
        SyncMode.UPLOAD_NEW: uploadNew,
        SyncMode.DOWNLOAD_NEW: downloadNew,
        SyncMode.MIRROR_TO_REMOTE: mirrorToRemote,
        SyncMode.MIRROR_FROM_REMOTE: mirrorFromRemote,
        SyncMode.TWO_WAY_SYNC: twoWaySync,
    }
    handler = dispatch.get(mode)
    if handler is None:
        raise CloudSyncError(f"Unknown sync mode: {mode}")
    return handler(dataset, cloud_dataset_id, options, client=client)
