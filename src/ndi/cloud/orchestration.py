"""
ndi.cloud.orchestration - High-level dataset sync/transfer operations.

Public functions accept an optional ``client`` keyword argument.  When
omitted, a client is created automatically from environment variables.

MATLAB equivalents: downloadDataset.m, uploadDataset.m, syncDataset.m,
    +upload/newDataset.m, +upload/scanForUpload.m
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import _auto_client

if TYPE_CHECKING:
    from .client import CloudClient


@_auto_client
def downloadDataset(
    cloud_dataset_id: str,
    target_folder: str,
    sync_files: bool = False,
    verbose: bool = False,
    *,
    client: CloudClient | None = None,
) -> Any:
    """Download a cloud dataset to a local folder.

    MATLAB equivalent: ndi.cloud.downloadDataset

    Args:
        cloud_dataset_id: Remote dataset ID.
        target_folder: Path to local directory.
        sync_files: If True, also download binary files.
        verbose: Print progress messages.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        An ndi.ndi_dataset backed by the target folder.
    """
    from .api import datasets as ds_api
    from .download import (
        downloadDatasetFiles,
        downloadDocumentCollection,
        jsons2documents,
    )
    from .internal import createRemoteDatasetDoc

    # MATLAB compatibility: the actual download directory is
    # target_folder / cloud_dataset_id, matching MATLAB behaviour.
    target = Path(target_folder) / cloud_dataset_id
    target.mkdir(parents=True, exist_ok=True)

    # Verify dataset exists
    ds_info = ds_api.getDataset(cloud_dataset_id, client=client)
    if verbose:
        name = ds_info.get("name", cloud_dataset_id)
        print(f"Downloading dataset: {name}")

    # Stream the documents to disk as they download instead of holding the
    # whole collection in memory. A large dataset (e.g. 100k+ documents)
    # otherwise materializes every raw JSON dict AND every ndi_document at once,
    # which exhausts memory on a small machine. We keep only the handful of
    # dataset-identity documents in memory (the dataset is built from them) and
    # stage every bulk document to a temporary newline-delimited JSON file, then
    # stream it back in a single O(N) insert pass (bounded to one batch).
    import json

    from ndi.dataset import ndi_dataset_dir
    from ndi.document import ndi_document
    from ndi.query import ndi_query

    from .filehandler import updateFileInfoForRemoteFiles

    # Document classes that establish dataset/session identity. ndi.dataset.dir
    # derives the dataset session id and repairs/tracks sessions from these, so
    # they must be present when the dataset object is constructed; everything
    # else is bulk data that can be streamed in afterwards.
    IDENTITY_CLASSES = {
        "ndi_session",
        "ndi_dataset",
        "session",
        "dataset",
        "session_in_a_dataset",
        "dataset_session_info",
        "dataset_remote",
    }

    def _doc_classes(dj: dict) -> set:
        dc = dj.get("document_class", {}) if isinstance(dj, dict) else {}
        names = set()
        if isinstance(dc, dict):
            names.add(dc.get("class_name", ""))
            sc = dc.get("superclasses", [])
            if isinstance(sc, dict):
                sc = [sc]
            for s in sc if isinstance(sc, list) else []:
                names.add(s.get("class_name", "") if isinstance(s, dict) else str(s))
        elif isinstance(dc, list) and dc:
            names.add(dc[-1].get("class_name", "") if isinstance(dc[-1], dict) else "")
        return names

    identity_docs: list[dict] = []
    downloaded_ids: set[str] = set()
    identity_classes: dict[str, str] = {}  # id -> a class name, for missing-doc diagnostics
    bulk_path = target / "_streamed_bulk.ndjson"
    bulk_count = 0

    with open(bulk_path, "w") as bulk_f:

        def _on_chunk(chunk_docs: list) -> None:
            nonlocal bulk_count
            for dj in chunk_docs:
                if not isinstance(dj, dict):
                    continue
                if not sync_files:
                    updateFileInfoForRemoteFiles(dj, cloud_dataset_id)
                did = dj.get("base", {}).get("id", "")
                if did:
                    downloaded_ids.add(did)
                classes = _doc_classes(dj)
                if classes & IDENTITY_CLASSES:
                    identity_docs.append(dj)
                    if did:
                        identity_classes[did] = next(iter(classes & IDENTITY_CLASSES))
                else:
                    bulk_f.write(json.dumps(dj))
                    bulk_f.write("\n")
                    bulk_count += 1

        downloadDocumentCollection(
            cloud_dataset_id,
            client=client,
            progress=print if verbose else None,
            on_chunk=_on_chunk,
        )

    if verbose:
        print(
            f"  Downloaded {len(downloaded_ids)} documents "
            f"({bulk_count} bulk, streamed to disk)"
        )

    # Build the dataset from the identity documents only (mirrors MATLAB
    # ndi.dataset.dir([], datasetFolder, ndiDocuments) — identity discovery,
    # session_in_a_dataset tracking and repairDatasetSessionInfo all run here).
    dataset = ndi_dataset_dir("", target, documents=jsons2documents(identity_docs))

    # Stream the bulk documents back in, one batch at a time (O(N), one
    # existing-id fetch), then drop the staging file.
    bulk_build_failures: list[tuple[str, str]] = []

    def _bulk_stream():
        with open(bulk_path) as bf:
            for line in bf:
                line = line.strip()
                if not line:
                    continue
                try:
                    dj = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    yield ndi_document(dj)
                except Exception as exc:  # noqa: BLE001 - mirror jsons2documents resilience
                    did = dj.get("base", {}).get("id", "") if isinstance(dj, dict) else ""
                    bulk_build_failures.append((did, str(exc)))

    dataset.add_doc_failures.extend(
        dataset._session._database.add_documents_streamed(_bulk_stream())
    )
    dataset.add_doc_failures.extend(bulk_build_failures)
    try:
        bulk_path.unlink()
    except OSError:
        pass

    # Create remote link document if not already present
    existing = dataset.database_search(ndi_query("").isa("dataset_remote"))
    if not existing:
        remote_doc = createRemoteDatasetDoc(cloud_dataset_id, dataset)
        try:
            dataset._session._database.add(remote_doc)
        except FileExistsError:
            pass  # Already exists, safe to skip
        except Exception as exc:
            warnings.warn(
                f"Failed to add remote dataset link document: {exc}",
                stacklevel=2,
            )

    # Store cloud client for on-demand file fetching
    dataset.cloud_client = client

    # Optionally download files. The file-bearing documents now live in the
    # dataset; query them in batches rather than holding every doc in memory.
    if sync_files and downloaded_ids:
        file_dir = target / ".ndi" / "files"
        file_docs = [
            d.document_properties
            for d in dataset.database_search(ndi_query("").isa("base"))
            if d.document_properties.get("files", {}).get("file_info")
        ]
        report = downloadDatasetFiles(cloud_dataset_id, file_docs, file_dir, client=client)
        if verbose:
            print(f'  Files downloaded: {report["downloaded"]}, failed: {report["failed"]}')

    # Verify every downloaded document made it into the local database. The
    # local dataset may have *more* documents (session / session-in-a-dataset
    # created internally) and *fewer* of some (a dataset_session_info is
    # converted to session_in_a_dataset and removed), so only flag documents
    # that are neither present nor an expected identity supersession.
    db_ids = set(
        dataset._session._database._driver._db.get_doc_ids(
            dataset._session._database._driver._branch_id
        )
    )
    failure_reasons = {fid: reason for fid, reason in dataset.add_doc_failures if fid}

    if verbose:
        print("Download complete.")

    real_missing: list[tuple[str, str]] = []
    for did in downloaded_ids:
        if did in db_ids:
            continue
        cls = identity_classes.get(did, "")
        if cls in IDENTITY_CLASSES:
            # Expected: session/dataset identity docs are superseded on load.
            continue
        real_missing.append((did, failure_reasons.get(did, cls or "unknown")))

    if real_missing:
        lines = [
            f"Downloaded {len(downloaded_ids)} documents but "
            f"{len(real_missing)} are missing from the local dataset:"
        ]
        for doc_id, reason in real_missing[:50]:
            lines.append(f"\n  - {doc_id} ({reason})")
        if len(real_missing) > 50:
            lines.append(f"\n  ... and {len(real_missing) - 50} more")
        raise RuntimeError("".join(lines))

    return dataset


def load_dataset_from_json_dir(
    json_dir: str | Path,
    target_folder: str | Path | None = None,
    verbose: bool = False,
    cloud_dataset_id: str | None = None,
    *,
    client: CloudClient | None = None,
) -> Any:
    """Load a dataset from a directory of pre-downloaded JSON documents.

    This avoids re-downloading from the cloud when the documents have
    already been saved locally (e.g. by ``download_full_dataset``).

    Args:
        json_dir: Directory containing ``*.json`` document files.
        target_folder: Path for the local ndi_dataset. If *None*, a
            temporary directory is created next to *json_dir*.
        verbose: Print progress messages.
        cloud_dataset_id: If given, rewrite file_info locations to
            ``ndic://`` URIs so binary files can be fetched on demand.
            If *None*, auto-detect from a ``dataset_remote`` document
            in the loaded JSONs.
        client: Authenticated :class:`CloudClient` to store on the
            dataset for on-demand file fetching.

    Returns:
        An :class:`ndi.ndi_dataset` backed by the target folder.
    """
    import json as json_mod

    json_path = Path(json_dir)
    if not json_path.is_dir():
        raise FileNotFoundError(f"JSON directory not found: {json_path}")

    json_files = sorted(json_path.glob("*.json"))
    if verbose:
        print(f"Loading {len(json_files)} JSON documents from {json_path}")

    doc_jsons: list[dict] = []
    for jf in json_files:
        with open(jf) as fh:
            doc_jsons.append(json_mod.load(fh))

    if verbose:
        print(f"  Read {len(doc_jsons)} documents, bulk-inserting into Dataset...")

    # Auto-detect cloud dataset ID from dataset_remote document
    if cloud_dataset_id is None:
        for dj in doc_jsons:
            remote = dj.get("dataset_remote", {})
            if isinstance(remote, dict) and remote.get("dataset_id"):
                cloud_dataset_id = remote["dataset_id"]
                break

    # Rewrite file_info to ndic:// URIs for on-demand fetching
    if cloud_dataset_id:
        from .filehandler import updateFileInfoForRemoteFiles

        for dj in doc_jsons:
            updateFileInfoForRemoteFiles(dj, cloud_dataset_id)

    # Create ndi_dataset
    from ndi.dataset import ndi_dataset_dir

    if target_folder is None:
        target = json_path.parent / f"{json_path.name}_dataset"
    else:
        target = Path(target_folder)
    target.mkdir(parents=True, exist_ok=True)

    # Convert JSON dicts to ndi_document objects and create dataset with them
    from .download import jsons2documents as _j2d

    all_documents = _j2d(doc_jsons)
    dataset = ndi_dataset_dir("", target, documents=all_documents)
    added = len(all_documents)
    skipped = 0

    # Wire cloud client for on-demand file fetching
    if client is not None:
        dataset.cloud_client = client

    if verbose:
        print(f"  Dataset created at {target} with {added} documents ({skipped} skipped).")

    return dataset


@_auto_client
def uploadDataset(
    dataset: Any,
    upload_as_new: bool = False,
    remote_name: str = "",
    sync_files: bool = True,
    verbose: bool = False,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, str]:
    """Upload a local dataset to NDI Cloud.

    MATLAB equivalent: ndi.cloud.uploadDataset

    Args:
        dataset: Local ndi.ndi_dataset.
        upload_as_new: If True, always create a new remote dataset.
        remote_name: Name for the remote dataset.
        sync_files: Upload binary files.
        verbose: Print progress.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(success, cloud_dataset_id, message)``.
    """
    from .api import datasets as ds_api
    from .internal import createRemoteDatasetDoc, getCloudDatasetIdForLocalDataset
    from .upload import uploadDocumentCollection, uploadFilesForDatasetDocuments

    # Resolve or create remote dataset
    cloud_id = ""
    if not upload_as_new:
        cloud_id, _ = getCloudDatasetIdForLocalDataset(dataset, client=client)

    if not cloud_id:
        # Create new remote dataset
        name = remote_name or getattr(dataset, "name", "Unnamed Dataset")
        org_id = client.config.org_id
        try:
            result = ds_api.createDataset(org_id, name, client=client)
            cloud_id = result.get("id", result.get("_id", ""))
        except Exception as exc:
            return False, "", f"Failed to create remote dataset: {exc}"

        # Store link locally
        remote_doc = createRemoteDatasetDoc(cloud_id, dataset)
        try:
            dataset.session.database_add(remote_doc)
        except Exception:
            pass

    if verbose:
        print(f"Uploading to cloud dataset: {cloud_id}")

    # Gather local documents
    from ndi.query import ndi_query

    try:
        all_docs = dataset.session.database_search(ndi_query(""))
    except Exception:
        all_docs = []

    doc_jsons = []
    for doc in all_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            doc_jsons.append(props)

    # Upload documents
    report = uploadDocumentCollection(cloud_id, doc_jsons, client=client)
    if verbose:
        print(f'  Documents uploaded: {report["uploaded"]}, skipped: {report["skipped"]}')

    # Upload files
    if sync_files:
        file_report = uploadFilesForDatasetDocuments(
            dataset,
            cloud_id,
            doc_jsons,
            client=client,
        )
        if verbose:
            print(f'  Files uploaded: {file_report["uploaded"]}, failed: {file_report["failed"]}')

    return True, cloud_id, ""


@_auto_client
def syncDataset(
    dataset: Any,
    sync_mode: str = "download_new",
    sync_files: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Synchronize a local dataset with its cloud counterpart.

    MATLAB equivalent: ndi.cloud.syncDataset

    Args:
        dataset: Local ndi.ndi_dataset.
        sync_mode: One of ``'download_new'``, ``'upload_new'``,
            ``'mirror_from_remote'``, ``'mirror_to_remote'``,
            ``'two_way_sync'``.
        sync_files: Also sync binary files.
        verbose: Print progress.
        dry_run: Simulate without making changes.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Report dict with counts of changes.
    """
    from .internal import getCloudDatasetIdForLocalDataset

    cloud_id, _ = getCloudDatasetIdForLocalDataset(dataset, client=client)
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
        report.update(
            _sync_download_new(dataset, cloud_id, sync_files, verbose, dry_run, client=client)
        )
    elif sync_mode == "upload_new":
        report.update(
            _sync_upload_new(dataset, cloud_id, sync_files, verbose, dry_run, client=client)
        )
    elif sync_mode == "two_way_sync":
        report.update(
            _sync_download_new(dataset, cloud_id, sync_files, verbose, dry_run, client=client)
        )
        report.update(
            _sync_upload_new(dataset, cloud_id, sync_files, verbose, dry_run, client=client)
        )
    elif sync_mode in ("mirror_from_remote", "mirror_to_remote"):
        report["note"] = f"{sync_mode} delegates to full download/upload"

    return report


@_auto_client
def newDataset(
    dataset: Any,
    name: str = "",
    *,
    client: CloudClient | None = None,
) -> str:
    """Create a new remote dataset and upload contents.

    MATLAB equivalent: +cloud/+upload/newDataset.m

    Returns:
        The cloud dataset ID.
    """
    success, cloud_id, msg = uploadDataset(
        dataset,
        upload_as_new=True,
        remote_name=name,
        verbose=False,
        client=client,
    )
    if not success:
        from .exceptions import CloudError

        raise CloudError(f"Failed to create new cloud dataset: {msg}")
    return cloud_id


# Re-export from upload module (MATLAB: ndi.cloud.upload.scanForUpload)
from .upload import scanForUpload  # noqa: F401

# ---------------------------------------------------------------------------
# Private sync helpers
# ---------------------------------------------------------------------------


def _sync_download_new(
    dataset: Any,
    cloud_id: str,
    sync_files: bool,
    verbose: bool,
    dry_run: bool,
    *,
    client: CloudClient | None = None,
) -> dict[str, int]:
    """Download documents that exist remotely but not locally."""
    from .api import documents as docs_api
    from .download import jsons2documents

    remote_docs = docs_api.listDatasetDocumentsAll(cloud_id, client=client).data

    # Find local IDs
    from ndi.query import ndi_query

    try:
        local_docs = dataset.session.database_search(ndi_query(""))
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

    documents = jsons2documents(new_docs)
    added = 0
    failures: list[tuple[str, str]] = []
    for doc in documents:
        try:
            dataset.session.database_add(doc)
            added += 1
        except Exception as exc:
            doc_id = getattr(doc, "id", None) or "<unknown>"
            failures.append((str(doc_id), str(exc)))
    conversion_lost = len(new_docs) - len(documents)
    total_lost = conversion_lost + len(failures)
    if total_lost > 0:
        failure_details = "\n".join(f"  - {doc_id}: {err}" for doc_id, err in failures[:20])
        extra = f"\n  ... and {len(failures) - 20} more" if len(failures) > 20 else ""
        parts = []
        if conversion_lost > 0:
            parts.append(f"{conversion_lost} failed JSON-to-document conversion")
        if failures:
            parts.append(f"{len(failures)} failed to add to database:\n{failure_details}{extra}")
        raise RuntimeError(
            f"Sync downloaded {len(new_docs)} documents but only {added} "
            f"were added. {total_lost} documents lost: " + "; ".join(parts)
        )

    return {"downloaded": added}


def _sync_upload_new(
    dataset: Any,
    cloud_id: str,
    sync_files: bool,
    verbose: bool,
    dry_run: bool,
    *,
    client: CloudClient | None = None,
) -> dict[str, int]:
    """Upload documents that exist locally but not remotely."""
    from .internal import listRemoteDocumentIds
    from .upload import uploadDocumentCollection

    remote_ids = listRemoteDocumentIds(cloud_id, client=client)

    from ndi.query import ndi_query

    try:
        local_docs = dataset.session.database_search(ndi_query(""))
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

    report = uploadDocumentCollection(cloud_id, new_jsons, only_missing=False, client=client)
    return {"uploaded": report.get("uploaded", 0)}
