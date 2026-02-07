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
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from .exceptions import CloudUploadError

if TYPE_CHECKING:
    from .client import CloudClient


def upload_document_collection(
    client: 'CloudClient',
    dataset_id: str,
    documents: List[Dict[str, Any]],
    only_missing: bool = True,
    max_chunk: Optional[int] = None,
) -> Dict[str, Any]:
    """Upload a list of document dicts to the cloud.

    Args:
        client: Authenticated cloud client.
        dataset_id: Cloud dataset ID.
        documents: List of document property dicts.
        only_missing: If True, skip documents already on the remote.
        max_chunk: Maximum documents per ZIP chunk (None = all at once).

    Returns:
        Report dict with ``upload_type``, ``manifest``, ``status``.
    """
    from .api import documents as docs_api

    report: Dict[str, Any] = {
        'upload_type': 'batch',
        'total': len(documents),
        'uploaded': 0,
        'skipped': 0,
        'manifest': [],
        'status': 'ok',
    }

    if only_missing:
        try:
            existing = docs_api.list_all_documents(client, dataset_id)
            existing_ids = {
                d.get('ndiId', d.get('id', ''))
                for d in existing
            }
            filtered = [
                d for d in documents
                if d.get('ndiId', d.get('id', '')) not in existing_ids
            ]
            report['skipped'] = len(documents) - len(filtered)
            documents = filtered
        except Exception:
            pass  # proceed with all

    if not documents:
        return report

    # Chunk if needed
    chunks = [documents]
    if max_chunk and max_chunk > 0:
        chunks = [
            documents[i:i + max_chunk]
            for i in range(0, len(documents), max_chunk)
        ]

    for chunk in chunks:
        for doc in chunk:
            try:
                docs_api.add_document(client, dataset_id, doc)
                report['uploaded'] += 1
                doc_id = doc.get('ndiId', doc.get('id', ''))
                report['manifest'].append(doc_id)
            except Exception as exc:
                report['status'] = 'partial'
                if report.get('errors') is None:
                    report['errors'] = []
                report['errors'].append(str(exc))

    return report


def zip_documents_for_upload(
    documents: List[Dict[str, Any]],
    dataset_id: str,
    target_dir: Optional[Path] = None,
) -> Tuple[Path, List[str]]:
    """Serialize documents to JSON and create a ZIP archive.

    Args:
        documents: Document property dicts.
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

    zip_path = target_dir / f'{dataset_id}_upload.zip'
    manifest: List[str] = []

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, doc in enumerate(documents):
            doc_id = doc.get('ndiId', doc.get('id', f'doc_{i}'))
            filename = f'{doc_id}.json'
            zf.writestr(filename, json.dumps(doc, indent=2))
            manifest.append(doc_id)

    return zip_path, manifest


def upload_files_for_documents(
    client: 'CloudClient',
    org_id: str,
    dataset_id: str,
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Upload associated binary files for a list of documents.

    For each document that has a ``file_uid`` field, obtains a
    presigned URL and uploads the file.

    Returns:
        Report dict with counts of uploaded and failed files.
    """
    from .api import files as files_api

    report: Dict[str, Any] = {
        'uploaded': 0,
        'failed': 0,
        'errors': [],
    }

    for doc in documents:
        file_uid = doc.get('file_uid', '')
        file_path = doc.get('file_path', '')
        if not file_uid or not file_path:
            continue
        try:
            url = files_api.get_upload_url(client, org_id, dataset_id, file_uid)
            files_api.put_file(url, file_path)
            report['uploaded'] += 1
        except Exception as exc:
            report['failed'] += 1
            report['errors'].append(str(exc))

    return report


def upload_single_file(
    client: 'CloudClient',
    dataset_id: str,
    file_uid: str,
    file_path: str,
    *,
    use_bulk_upload: bool = False,
) -> Tuple[bool, str]:
    """Upload a single file to the NDI cloud service.

    MATLAB equivalent: ndi.cloud.uploadSingleFile

    Args:
        client: Authenticated cloud client.
        dataset_id: The cloud dataset ID.
        file_uid: Unique ID to assign to the uploaded file.
        file_path: Local path of the file to upload.
        use_bulk_upload: If True, zip the file and use the bulk upload
            mechanism. Defaults to False.

    Returns:
        Tuple of ``(success, error_message)``.
    """
    import os
    import uuid

    from .api import files as files_api

    try:
        if use_bulk_upload:
            zip_name = f'{dataset_id}.{uuid.uuid4().hex}.zip'
            zip_path = Path(tempfile.gettempdir()) / zip_name
            try:
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(file_path, os.path.basename(file_path))
                url = files_api.get_file_collection_upload_url(
                    client, client.config.org_id, dataset_id,
                )
                files_api.put_file(url, str(zip_path))
            finally:
                if zip_path.exists():
                    zip_path.unlink()
        else:
            url = files_api.get_upload_url(
                client, client.config.org_id, dataset_id, file_uid,
            )
            files_api.put_file(url, file_path)

        return True, ''
    except Exception as exc:
        return False, str(exc)
