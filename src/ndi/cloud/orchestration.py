"""
ndi.cloud.orchestration - High-level dataset sync/transfer operations.

MATLAB equivalents: downloadDataset.m, uploadDataset.m, syncDataset.m,
    +upload/newDataset.m, +upload/scanForUpload.m
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import CloudClient


def download_dataset(
    client: CloudClient,
    cloud_dataset_id: str,
    target_folder: str,
    sync_files: bool = False,
    verbose: bool = False,
) -> Any:
    """Download a cloud dataset to a local folder.

    MATLAB equivalent: ndi.cloud.downloadDataset

    Args:
        client: Authenticated cloud client.
        cloud_dataset_id: Remote dataset ID.
        target_folder: Path to local directory.
        sync_files: If True, also download binary files.
        verbose: Print progress messages.

    Returns:
        An ndi.Dataset backed by the target folder.
    """
    from .api import datasets as ds_api
    from .download import (
        download_dataset_files,
        download_document_collection,
        jsons_to_documents,
    )
    from .internal import create_remote_dataset_doc

    target = Path(target_folder)
    target.mkdir(parents=True, exist_ok=True)

    # Verify dataset exists
    ds_info = ds_api.get_dataset(client, cloud_dataset_id)
    if verbose:
        name = ds_info.get("name", cloud_dataset_id)
        print(f"Downloading dataset: {name}")

    # Download all full documents via chunked bulk download
    doc_jsons = download_document_collection(
        client, cloud_dataset_id,
        progress=print if verbose else None,
    )
    if verbose:
        print(f"  Downloaded {len(doc_jsons)} documents")

    # Convert to Document objects and add to a local Dataset
    from ndi.dataset import Dataset

    dataset = Dataset(target)
    documents = jsons_to_documents(doc_jsons)
    for doc in documents:
        try:
            dataset.session.database_add(doc)
        except Exception:
            pass

    # Create remote link document
    remote_doc = create_remote_dataset_doc(cloud_dataset_id, dataset)
    try:
        dataset.session.database_add(remote_doc)
    except Exception:
        pass

    # Optionally download files
    if sync_files and doc_jsons:
        file_dir = target / ".ndi" / "files"
        report = download_dataset_files(client, cloud_dataset_id, doc_jsons, file_dir)
        if verbose:
            print(f'  Files downloaded: {report["downloaded"]}, failed: {report["failed"]}')

    if verbose:
        print("Download complete.")

    return dataset


def upload_dataset(
    client: CloudClient,
    dataset: Any,
    upload_as_new: bool = False,
    remote_name: str = "",
    sync_files: bool = True,
    verbose: bool = False,
) -> tuple[bool, str, str]:
    """Upload a local dataset to NDI Cloud.

    MATLAB equivalent: ndi.cloud.uploadDataset

    Args:
        client: Authenticated cloud client.
        dataset: Local ndi.Dataset.
        upload_as_new: If True, always create a new remote dataset.
        remote_name: Name for the remote dataset.
        sync_files: Upload binary files.
        verbose: Print progress.

    Returns:
        Tuple of ``(success, cloud_dataset_id, message)``.
    """
    from .api import datasets as ds_api
    from .internal import create_remote_dataset_doc, get_cloud_dataset_id
    from .upload import upload_document_collection, upload_files_for_documents

    # Resolve or create remote dataset
    cloud_id = ""
    if not upload_as_new:
        cloud_id, _ = get_cloud_dataset_id(client, dataset)

    if not cloud_id:
        # Create new remote dataset
        name = remote_name or getattr(dataset, "name", "Unnamed Dataset")
        org_id = client.config.org_id
        try:
            result = ds_api.create_dataset(client, org_id, name)
            cloud_id = result.get("id", result.get("_id", ""))
        except Exception as exc:
            return False, "", f"Failed to create remote dataset: {exc}"

        # Store link locally
        remote_doc = create_remote_dataset_doc(cloud_id, dataset)
        try:
            dataset.session.database_add(remote_doc)
        except Exception:
            pass

    if verbose:
        print(f"Uploading to cloud dataset: {cloud_id}")

    # Gather local documents
    from ndi.query import Query

    try:
        all_docs = dataset.session.database_search(Query(""))
    except Exception:
        all_docs = []

    doc_jsons = []
    for doc in all_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            doc_jsons.append(props)

    # Upload documents
    report = upload_document_collection(client, cloud_id, doc_jsons)
    if verbose:
        print(f'  Documents uploaded: {report["uploaded"]}, skipped: {report["skipped"]}')

    # Upload files
    if sync_files:
        file_report = upload_files_for_documents(
            client,
            client.config.org_id,
            cloud_id,
            doc_jsons,
        )
        if verbose:
            print(f'  Files uploaded: {file_report["uploaded"]}, failed: {file_report["failed"]}')

    return True, cloud_id, ""


def sync_dataset(
    client: CloudClient,
    dataset: Any,
    sync_mode: str = "download_new",
    sync_files: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synchronize a local dataset with its cloud counterpart.

    MATLAB equivalent: ndi.cloud.syncDataset

    Args:
        client: Authenticated cloud client.
        dataset: Local ndi.Dataset.
        sync_mode: One of ``'download_new'``, ``'upload_new'``,
            ``'mirror_from_remote'``, ``'mirror_to_remote'``,
            ``'two_way_sync'``.
        sync_files: Also sync binary files.
        verbose: Print progress.
        dry_run: Simulate without making changes.

    Returns:
        Report dict with counts of changes.
    """
    from .internal import get_cloud_dataset_id

    cloud_id, _ = get_cloud_dataset_id(client, dataset)
    if not cloud_id:
        return {"error": "No cloud dataset linked to this dataset"}

    report: dict[str, Any] = {
        "sync_mode": sync_mode,
        "cloud_dataset_id": cloud_id,
        "downloaded": 0,
        "uploaded": 0,
        "deleted": 0,
    }

    if sync_mode == "download_new":
        report.update(_sync_download_new(client, dataset, cloud_id, sync_files, verbose, dry_run))
    elif sync_mode == "upload_new":
        report.update(_sync_upload_new(client, dataset, cloud_id, sync_files, verbose, dry_run))
    elif sync_mode == "two_way_sync":
        report.update(_sync_download_new(client, dataset, cloud_id, sync_files, verbose, dry_run))
        report.update(_sync_upload_new(client, dataset, cloud_id, sync_files, verbose, dry_run))
    elif sync_mode in ("mirror_from_remote", "mirror_to_remote"):
        report["note"] = f"{sync_mode} delegates to full download/upload"

    return report


def new_dataset(
    client: CloudClient,
    dataset: Any,
    name: str = "",
) -> str:
    """Create a new remote dataset and upload contents.

    MATLAB equivalent: +cloud/+upload/newDataset.m

    Returns:
        The cloud dataset ID.
    """
    success, cloud_id, msg = upload_dataset(
        client,
        dataset,
        upload_as_new=True,
        remote_name=name,
        verbose=False,
    )
    if not success:
        from .exceptions import CloudError

        raise CloudError(f"Failed to create new cloud dataset: {msg}")
    return cloud_id


def scan_for_upload(
    client: CloudClient,
    dataset: Any,
    cloud_dataset_id: str,
) -> tuple[list[dict], list[dict], float]:
    """Scan local documents/files to determine what needs uploading.

    MATLAB equivalent: +cloud/+upload/scanForUpload.m

    Returns:
        Tuple of (doc_structs, file_structs, total_size_kb).
    """
    from ndi.query import Query

    from .internal import list_remote_document_ids

    # Get local documents
    try:
        all_docs = dataset.session.database_search(Query(""))
    except Exception:
        all_docs = []

    # Get remote IDs
    remote_ids = {}
    if cloud_dataset_id:
        try:
            remote_ids = list_remote_document_ids(client, cloud_dataset_id)
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

        # Check for associated files
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


# ---------------------------------------------------------------------------
# Private sync helpers
# ---------------------------------------------------------------------------


def _sync_download_new(
    client: CloudClient,
    dataset: Any,
    cloud_id: str,
    sync_files: bool,
    verbose: bool,
    dry_run: bool,
) -> dict[str, int]:
    """Download documents that exist remotely but not locally."""
    from .api import documents as docs_api
    from .download import jsons_to_documents

    remote_docs = docs_api.list_all_documents(client, cloud_id)

    # Find local IDs
    from ndi.query import Query

    try:
        local_docs = dataset.session.database_search(Query(""))
    except Exception:
        local_docs = []

    local_ids = set()
    for ld in local_docs:
        p = ld.document_properties if hasattr(ld, "document_properties") else ld
        if isinstance(p, dict):
            local_ids.add(p.get("base", {}).get("id", ""))

    # Filter to new docs
    new_docs = [rd for rd in remote_docs if rd.get("ndiId", rd.get("id", "")) not in local_ids]

    if verbose:
        print(f"  New remote docs to download: {len(new_docs)}")

    if dry_run:
        return {"downloaded": len(new_docs)}

    documents = jsons_to_documents(new_docs)
    added = 0
    for doc in documents:
        try:
            dataset.session.database_add(doc)
            added += 1
        except Exception:
            pass

    return {"downloaded": added}


def _sync_upload_new(
    client: CloudClient,
    dataset: Any,
    cloud_id: str,
    sync_files: bool,
    verbose: bool,
    dry_run: bool,
) -> dict[str, int]:
    """Upload documents that exist locally but not remotely."""
    from .internal import list_remote_document_ids
    from .upload import upload_document_collection

    remote_ids = list_remote_document_ids(client, cloud_id)

    from ndi.query import Query

    try:
        local_docs = dataset.session.database_search(Query(""))
    except Exception:
        local_docs = []

    new_jsons = []
    for ld in local_docs:
        p = ld.document_properties if hasattr(ld, "document_properties") else ld
        if isinstance(p, dict):
            doc_id = p.get("base", {}).get("id", "")
            if doc_id not in remote_ids:
                new_jsons.append(p)

    if verbose:
        print(f"  New local docs to upload: {len(new_jsons)}")

    if dry_run:
        return {"uploaded": len(new_jsons)}

    report = upload_document_collection(client, cloud_id, new_jsons, only_missing=False)
    return {"uploaded": report.get("uploaded", 0)}
