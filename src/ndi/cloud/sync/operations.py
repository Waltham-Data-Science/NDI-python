"""
ndi.cloud.sync.operations - High-level sync operations.

Each function compares local and remote document sets using the
:class:`SyncIndex` and delegates to upload/download helpers.

MATLAB equivalents: +ndi/+cloud/+sync/*.m
"""

from __future__ import annotations

import json
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
# Internal helpers for local document storage
# ---------------------------------------------------------------------------

_DOC_DIR = ".ndi" / Path("documents")


def _save_downloaded_docs(
    ds_path: Path,
    docs: list[dict[str, Any]],
) -> list[str]:
    """Save downloaded document JSONs to ``<dataset>/.ndi/documents/``."""
    doc_dir = ds_path / _DOC_DIR
    doc_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for doc in docs:
        ndi_id = doc.get("ndiId", doc.get("id", ""))
        if not ndi_id:
            continue
        (doc_dir / f"{ndi_id}.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        saved.append(ndi_id)
    return saved


def _delete_local_docs(ds_path: Path, doc_ids: set[str]) -> list[str]:
    """Remove local document JSON files for the given IDs."""
    doc_dir = ds_path / _DOC_DIR
    deleted: list[str] = []
    for doc_id in doc_ids:
        path = doc_dir / f"{doc_id}.json"
        if path.exists():
            path.unlink()
        deleted.append(doc_id)
    return deleted


def _download_docs_by_ids(
    client: CloudClient,
    cloud_dataset_id: str,
    ndi_to_api: dict[str, str],
    ids_to_download: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch documents from the cloud by NDI ID using chunked bulk download.

    Returns (downloaded_docs, failed_ids).
    """
    from ..download import download_document_collection

    if not ids_to_download:
        return [], []

    # Map NDI IDs to API IDs
    api_ids = [ndi_to_api.get(ndi_id, ndi_id) for ndi_id in ids_to_download]

    try:
        docs = download_document_collection(
            client, cloud_dataset_id, doc_ids=api_ids,
        )
    except Exception as exc:
        logger.warning("Bulk download failed: %s", exc)
        return [], list(ids_to_download)

    # Set ndiId on downloaded docs and track which ones we got
    downloaded_api_ids: set[str] = set()
    for doc in docs:
        api_id = doc.get("_id", doc.get("id", ""))
        downloaded_api_ids.add(api_id)

    # Build reverse map: api_id → ndi_id
    api_to_ndi = {v: k for k, v in ndi_to_api.items()}
    for doc in docs:
        api_id = doc.get("_id", doc.get("id", ""))
        ndi_id = api_to_ndi.get(api_id, api_id)
        doc.setdefault("ndiId", ndi_id)

    # Determine which IDs we failed to download
    failed = [
        ndi_id for ndi_id in ids_to_download
        if ndi_to_api.get(ndi_id, ndi_id) not in downloaded_api_ids
    ]

    return docs, failed


# ---------------------------------------------------------------------------
# Public sync operations
# ---------------------------------------------------------------------------


def upload_new(
    client: CloudClient,
    dataset_path: str,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
) -> dict[str, Any]:
    """Upload documents that exist locally but not in the cloud.

    Reads the sync index to determine which docs are new, uploads
    them, and updates the index.
    """
    from ..api import documents as docs_api
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    # Get remote doc IDs
    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())

    # Get local doc IDs (from index — actual local enumeration deferred)
    local_ids = set(index.local_doc_ids_last_sync)

    # New = in local but not in remote (since last sync)
    new_ids = local_ids - remote_id_set

    report: dict[str, Any] = {
        "mode": "upload_new",
        "new_count": len(new_ids),
        "uploaded": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["uploaded"] = list(new_ids)
        return report

    failed: list[str] = []
    for doc_id in new_ids:
        try:
            docs_api.add_document(client, cloud_dataset_id, {"ndiId": doc_id})
            report["uploaded"].append(doc_id)
        except Exception as exc:
            logger.warning("Failed to upload %s: %s", doc_id, exc)
            failed.append(doc_id)
    report["failed"] = failed

    # Update index
    index.update(
        list(local_ids),
        list(remote_id_set | set(report["uploaded"])),
    )
    index.write(ds_path)

    return report


def download_new(
    client: CloudClient,
    dataset_path: str,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
) -> dict[str, Any]:
    """Download documents that exist in the cloud but not locally."""
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())
    local_ids = set(index.local_doc_ids_last_sync)

    new_ids = remote_id_set - local_ids

    report: dict[str, Any] = {
        "mode": "download_new",
        "new_count": len(new_ids),
        "downloaded": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["downloaded"] = list(new_ids)
        return report

    # Actually fetch documents from the cloud
    docs, failed = _download_docs_by_ids(client, cloud_dataset_id, remote_ids, new_ids)
    saved = _save_downloaded_docs(ds_path, docs)
    report["downloaded"] = saved
    report["failed"] = failed

    if options.verbose and saved:
        logger.info("download_new: downloaded %d documents", len(saved))

    # Update index
    index.update(
        list(local_ids | set(saved)),
        list(remote_id_set),
    )
    index.write(ds_path)

    return report


def mirror_to_remote(
    client: CloudClient,
    dataset_path: str,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
) -> dict[str, Any]:
    """Make the remote match the local state (upload new, delete remote-only)."""
    from ..api import documents as docs_api
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())
    local_ids = set(index.local_doc_ids_last_sync)

    to_upload = local_ids - remote_id_set
    to_delete = remote_id_set - local_ids

    report: dict[str, Any] = {
        "mode": "mirror_to_remote",
        "upload_count": len(to_upload),
        "delete_count": len(to_delete),
        "uploaded": [],
        "deleted": [],
        "dry_run": options.dry_run,
    }

    failed: list[str] = []
    if not options.dry_run:
        for doc_id in to_upload:
            try:
                docs_api.add_document(client, cloud_dataset_id, {"ndiId": doc_id})
                report["uploaded"].append(doc_id)
            except Exception as exc:
                logger.warning("mirror_to_remote: failed to upload %s: %s", doc_id, exc)
                failed.append(doc_id)
        for doc_id in to_delete:
            api_id = remote_ids.get(doc_id, doc_id)
            try:
                docs_api.delete_document(client, cloud_dataset_id, api_id)
                report["deleted"].append(doc_id)
            except Exception as exc:
                logger.warning("mirror_to_remote: failed to delete %s: %s", doc_id, exc)
                failed.append(doc_id)

        # Upload associated files if requested
        if options.sync_files and report["uploaded"]:
            try:
                from ..upload import upload_files_for_documents

                doc_dir = ds_path / _DOC_DIR
                doc_dicts = []
                for doc_id in report["uploaded"]:
                    doc_file = doc_dir / f"{doc_id}.json"
                    if doc_file.exists():
                        doc_dicts.append(json.loads(doc_file.read_text(encoding="utf-8")))
                if doc_dicts:
                    upload_files_for_documents(
                        client,
                        client.config.org_id,
                        cloud_dataset_id,
                        doc_dicts,
                    )
            except Exception as exc:
                logger.warning("mirror_to_remote: file upload failed: %s", exc)

    report["failed"] = failed

    index.update(list(local_ids), list(local_ids))
    index.write(ds_path)

    return report


def mirror_from_remote(
    client: CloudClient,
    dataset_path: str,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
) -> dict[str, Any]:
    """Make the local state match the remote (download new, delete local-only)."""
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())
    local_ids = set(index.local_doc_ids_last_sync)

    to_download = remote_id_set - local_ids
    to_delete_local = local_ids - remote_id_set

    report: dict[str, Any] = {
        "mode": "mirror_from_remote",
        "download_count": len(to_download),
        "delete_local_count": len(to_delete_local),
        "downloaded": [],
        "deleted_local": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["downloaded"] = list(to_download)
        report["deleted_local"] = list(to_delete_local)
        return report

    # Delete local-only documents
    deleted = _delete_local_docs(ds_path, to_delete_local)
    report["deleted_local"] = deleted

    # Download remote-only documents
    docs, failed = _download_docs_by_ids(client, cloud_dataset_id, remote_ids, to_download)
    saved = _save_downloaded_docs(ds_path, docs)
    report["downloaded"] = saved
    report["failed"] = failed

    if options.verbose:
        logger.info(
            "mirror_from_remote: downloaded %d, deleted %d local",
            len(saved),
            len(deleted),
        )

    index.update(list(remote_id_set), list(remote_id_set))
    index.write(ds_path)

    return report


def two_way_sync(
    client: CloudClient,
    dataset_path: str,
    cloud_dataset_id: str,
    options: SyncOptions | None = None,
) -> dict[str, Any]:
    """Bi-directional sync with conflict detection and deletion propagation.

    Compares the current local/remote state against the last sync state
    to compute deltas.  Documents added on both sides since the last sync
    are flagged as conflicts and skipped.  Deletions on one side are
    propagated to the other (unless the deleted doc was re-added).
    """
    from ..api import documents as docs_api
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    # Current state
    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    current_remote = set(remote_ids.keys())
    current_local = set(index.local_doc_ids_last_sync)

    # Last sync state
    last_local = set(index.local_doc_ids_last_sync)
    last_remote = set(index.remote_doc_ids_last_sync)

    # Compute deltas
    added_local = current_local - last_local
    added_remote = current_remote - last_remote
    deleted_local = last_local - current_local
    deleted_remote = last_remote - current_remote

    # Conflict detection: docs added on both sides since last sync
    conflicts = added_local & added_remote
    if conflicts and options.verbose:
        logger.warning(
            "two_way_sync: %d documents added on both sides (skipping): %s",
            len(conflicts),
            conflicts,
        )

    # What to upload: in local but not remote (excluding conflicts)
    to_upload = (current_local - current_remote) - conflicts

    # What to download: in remote but not local (excluding conflicts)
    to_download = (current_remote - current_local) - conflicts

    # Deletion propagation:
    # If deleted on remote, delete locally (unless just added locally)
    to_delete_local = deleted_remote - added_local
    # If deleted on local, delete from remote (unless just added remotely)
    to_delete_remote = deleted_local - added_remote

    report: dict[str, Any] = {
        "mode": "two_way_sync",
        "upload_count": len(to_upload),
        "download_count": len(to_download),
        "delete_local_count": len(to_delete_local),
        "delete_remote_count": len(to_delete_remote),
        "conflict_count": len(conflicts),
        "conflicts": list(conflicts),
        "uploaded": [],
        "downloaded": [],
        "deleted_local": [],
        "deleted_remote": [],
        "failed": [],
        "dry_run": options.dry_run,
    }

    if options.dry_run:
        report["uploaded"] = list(to_upload)
        report["downloaded"] = list(to_download)
        report["deleted_local"] = list(to_delete_local)
        report["deleted_remote"] = list(to_delete_remote)
        return report

    failed: list[str] = []

    # 1. Delete local docs that were removed on the remote
    deleted_local_ids = _delete_local_docs(ds_path, to_delete_local)
    report["deleted_local"] = deleted_local_ids

    # 2. Delete remote docs that were removed locally
    for doc_id in to_delete_remote:
        api_id = remote_ids.get(doc_id, doc_id)
        try:
            docs_api.delete_document(client, cloud_dataset_id, api_id)
            report["deleted_remote"].append(doc_id)
        except Exception as exc:
            logger.warning("two_way_sync: failed to delete remote %s: %s", doc_id, exc)
            failed.append(doc_id)

    # 3. Upload local-only docs
    for doc_id in to_upload:
        try:
            docs_api.add_document(client, cloud_dataset_id, {"ndiId": doc_id})
            report["uploaded"].append(doc_id)
        except Exception as exc:
            logger.warning("two_way_sync: failed to upload %s: %s", doc_id, exc)
            failed.append(doc_id)

    # 4. Download remote-only docs
    docs, dl_failed = _download_docs_by_ids(client, cloud_dataset_id, remote_ids, to_download)
    saved = _save_downloaded_docs(ds_path, docs)
    report["downloaded"] = saved
    failed.extend(dl_failed)

    report["failed"] = failed

    if options.verbose:
        logger.info(
            "two_way_sync: uploaded=%d downloaded=%d " "del_local=%d del_remote=%d conflicts=%d",
            len(report["uploaded"]),
            len(report["downloaded"]),
            len(report["deleted_local"]),
            len(report["deleted_remote"]),
            len(conflicts),
        )

    # Compute expected final state
    final_local = (current_local | set(saved)) - set(deleted_local_ids)
    final_remote = (current_remote | set(report["uploaded"])) - set(report["deleted_remote"])
    index.update(list(final_local), list(final_remote))
    index.write(ds_path)

    return report


def validate_sync(
    client: CloudClient,
    dataset: Any,
    cloud_dataset_id: str,
) -> dict[str, Any]:
    """Compare local and remote datasets to identify sync discrepancies.

    MATLAB equivalent: +cloud/+sync/validate.m

    Returns:
        Report with local_only, remote_only, common ID lists.
    """
    from ..internal import validate_sync as _validate

    return _validate(client, dataset, cloud_dataset_id)


def sync(
    client: CloudClient,
    dataset_path: str,
    cloud_dataset_id: str,
    mode: SyncMode,
    options: SyncOptions | None = None,
) -> dict[str, Any]:
    """Dispatch to the appropriate sync operation based on *mode*."""
    dispatch = {
        SyncMode.UPLOAD_NEW: upload_new,
        SyncMode.DOWNLOAD_NEW: download_new,
        SyncMode.MIRROR_TO_REMOTE: mirror_to_remote,
        SyncMode.MIRROR_FROM_REMOTE: mirror_from_remote,
        SyncMode.TWO_WAY_SYNC: two_way_sync,
    }
    handler = dispatch.get(mode)
    if handler is None:
        raise CloudSyncError(f"Unknown sync mode: {mode}")
    return handler(client, dataset_path, cloud_dataset_id, options)
