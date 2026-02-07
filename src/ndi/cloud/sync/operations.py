"""
ndi.cloud.sync.operations - High-level sync operations.

Each function compares local and remote document sets using the
:class:`SyncIndex` and delegates to upload/download helpers.

MATLAB equivalents: +ndi/+cloud/+sync/*.m
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .mode import SyncMode, SyncOptions
from .index import SyncIndex
from ..exceptions import CloudSyncError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..client import CloudClient


def upload_new(
    client: 'CloudClient',
    dataset_path: str,
    cloud_dataset_id: str,
    options: Optional[SyncOptions] = None,
) -> Dict[str, Any]:
    """Upload documents that exist locally but not in the cloud.

    Reads the sync index to determine which docs are new, uploads
    them, and updates the index.
    """
    from pathlib import Path
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

    report: Dict[str, Any] = {
        'mode': 'upload_new',
        'new_count': len(new_ids),
        'uploaded': [],
        'dry_run': options.dry_run,
    }

    if options.dry_run:
        report['uploaded'] = list(new_ids)
        return report

    failed: List[str] = []
    for doc_id in new_ids:
        try:
            docs_api.add_document(client, cloud_dataset_id, {'ndiId': doc_id})
            report['uploaded'].append(doc_id)
        except Exception as exc:
            logger.warning('Failed to upload %s: %s', doc_id, exc)
            failed.append(doc_id)
    report['failed'] = failed

    # Update index
    index.update(
        list(local_ids),
        list(remote_id_set | set(report['uploaded'])),
    )
    index.write(ds_path)

    return report


def download_new(
    client: 'CloudClient',
    dataset_path: str,
    cloud_dataset_id: str,
    options: Optional[SyncOptions] = None,
) -> Dict[str, Any]:
    """Download documents that exist in the cloud but not locally."""
    from pathlib import Path
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())
    local_ids = set(index.local_doc_ids_last_sync)

    new_ids = remote_id_set - local_ids

    report: Dict[str, Any] = {
        'mode': 'download_new',
        'new_count': len(new_ids),
        'downloaded': [],
        'dry_run': options.dry_run,
    }

    if options.dry_run:
        report['downloaded'] = list(new_ids)
        return report

    for doc_id in new_ids:
        report['downloaded'].append(doc_id)

    # Update index
    index.update(
        list(local_ids | set(report['downloaded'])),
        list(remote_id_set),
    )
    index.write(ds_path)

    return report


def mirror_to_remote(
    client: 'CloudClient',
    dataset_path: str,
    cloud_dataset_id: str,
    options: Optional[SyncOptions] = None,
) -> Dict[str, Any]:
    """Make the remote match the local state (upload new, delete remote-only)."""
    from pathlib import Path
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

    report: Dict[str, Any] = {
        'mode': 'mirror_to_remote',
        'upload_count': len(to_upload),
        'delete_count': len(to_delete),
        'dry_run': options.dry_run,
    }

    failed: List[str] = []
    if not options.dry_run:
        for doc_id in to_upload:
            try:
                docs_api.add_document(client, cloud_dataset_id, {'ndiId': doc_id})
            except Exception as exc:
                logger.warning('mirror_to_remote: failed to upload %s: %s', doc_id, exc)
                failed.append(doc_id)
        for doc_id in to_delete:
            api_id = remote_ids.get(doc_id, doc_id)
            try:
                docs_api.delete_document(client, cloud_dataset_id, api_id)
            except Exception as exc:
                logger.warning('mirror_to_remote: failed to delete %s: %s', doc_id, exc)
                failed.append(doc_id)
    report['failed'] = failed

    index.update(list(local_ids), list(local_ids))
    index.write(ds_path)

    return report


def mirror_from_remote(
    client: 'CloudClient',
    dataset_path: str,
    cloud_dataset_id: str,
    options: Optional[SyncOptions] = None,
) -> Dict[str, Any]:
    """Make the local state match the remote (download new, delete local-only)."""
    from pathlib import Path
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())
    local_ids = set(index.local_doc_ids_last_sync)

    to_download = remote_id_set - local_ids
    to_delete_local = local_ids - remote_id_set

    report: Dict[str, Any] = {
        'mode': 'mirror_from_remote',
        'download_count': len(to_download),
        'delete_local_count': len(to_delete_local),
        'dry_run': options.dry_run,
    }

    index.update(list(remote_id_set), list(remote_id_set))
    index.write(ds_path)

    return report


def two_way_sync(
    client: 'CloudClient',
    dataset_path: str,
    cloud_dataset_id: str,
    options: Optional[SyncOptions] = None,
) -> Dict[str, Any]:
    """Bi-directional sync: upload local-only, download remote-only."""
    from pathlib import Path
    from ..api import documents as docs_api
    from ..internal import list_remote_document_ids

    options = options or SyncOptions()
    ds_path = Path(dataset_path)
    index = SyncIndex.read(ds_path)

    remote_ids = list_remote_document_ids(client, cloud_dataset_id)
    remote_id_set = set(remote_ids.keys())
    local_ids = set(index.local_doc_ids_last_sync)

    to_upload = local_ids - remote_id_set
    to_download = remote_id_set - local_ids

    report: Dict[str, Any] = {
        'mode': 'two_way_sync',
        'upload_count': len(to_upload),
        'download_count': len(to_download),
        'dry_run': options.dry_run,
    }

    failed: List[str] = []
    if not options.dry_run:
        for doc_id in to_upload:
            try:
                docs_api.add_document(client, cloud_dataset_id, {'ndiId': doc_id})
            except Exception as exc:
                logger.warning('two_way_sync: failed to upload %s: %s', doc_id, exc)
                failed.append(doc_id)
    report['failed'] = failed

    merged = local_ids | remote_id_set
    index.update(list(merged), list(merged))
    index.write(ds_path)

    return report


def validate_sync(
    client: 'CloudClient',
    dataset: Any,
    cloud_dataset_id: str,
) -> Dict[str, Any]:
    """Compare local and remote datasets to identify sync discrepancies.

    MATLAB equivalent: +cloud/+sync/validate.m

    Returns:
        Report with local_only, remote_only, common ID lists.
    """
    from ..internal import validate_sync as _validate
    return _validate(client, dataset, cloud_dataset_id)


def sync(
    client: 'CloudClient',
    dataset_path: str,
    cloud_dataset_id: str,
    mode: SyncMode,
    options: Optional[SyncOptions] = None,
) -> Dict[str, Any]:
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
        raise CloudSyncError(f'Unknown sync mode: {mode}')
    return handler(client, dataset_path, cloud_dataset_id, options)
