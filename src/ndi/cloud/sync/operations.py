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


def _upload_id(doc: dict[str, Any]) -> str:
    """The id ``_save_downloaded_docs`` filed a downloaded document under."""
    return str(doc.get("ndiId") or doc.get("id") or "")


def _ingest_downloaded_docs(dataset: Any, saved_properties: list[dict[str, Any]]) -> None:
    """Put downloaded documents into the dataset's database.

    MATLAB's ``downloadNdiDocuments`` ends in ``database_add``. This side
    wrote the JSON to ``.ndi/documents/`` and stopped there, so a downloaded
    document was on disk but not in the database -- and therefore not a
    document the dataset would return from ``database_search``.

    Nothing noticed while the sync functions took a path, because the index
    was then the only record of what was local, and it recorded a download as
    local whether or not anything had ingested it. Now that "local" is
    measured by asking the dataset, an un-ingested download reads as absent
    and gets fetched again on every run.

    Failure here is logged, not raised: the JSON is already written, so the
    documents are recoverable, and abandoning a whole sync because one
    document would not ingest would be the worse outcome. The caller's index
    only records what actually landed, so a failure here means the next run
    tries again.
    """
    if not saved_properties:
        return
    add = getattr(dataset, "database_add", None)
    if not callable(add):
        logger.warning(
            "Downloaded %d document(s) but this dataset cannot ingest them "
            "(no database_add); they are on disk under .ndi/documents/ only.",
            len(saved_properties),
        )
        return
    from ..download import structsToNdiDocuments

    try:
        add(structsToNdiDocuments(saved_properties))
    except Exception as exc:  # noqa: BLE001 - the JSON is already written
        logger.warning(
            "Downloaded %d document(s) but could not add them to the database: %s",
            len(saved_properties),
            exc,
        )


def _save_downloaded_docs(
    ds_path: Path,
    docs: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Save downloaded document JSONs to ``<dataset>/.ndi/documents/``.

    Returns ``(saved, unsaved)`` -- the NDI IDs actually written, and a
    best-effort identifier for every document the cloud returned that could
    not be stored because it carried no usable ID.

    ``unsaved`` exists because these documents are otherwise invisible. They
    do not reach ``failed`` upstream: ``downloadNdiDocuments`` decides what
    failed by whether a requested document's *api* ID came back, so one that
    arrives with a good ``_id`` but no ``ndiId`` counts as downloaded and is
    then discarded here. Dropping it silently makes the report claim a
    download that did not happen.
    """
    doc_dir = ds_path / _DOC_DIR
    doc_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    unsaved: list[str] = []
    for position, doc in enumerate(docs):
        # Not doc.get("ndiId", doc.get("id", "")): a key that is present but
        # empty beats the default, so the "id" fallback never fired.
        ndi_id = doc.get("ndiId") or doc.get("id") or ""
        if not ndi_id:
            label = str(doc.get("_id") or f"<unidentified document at position {position}>")
            logger.warning("Downloaded document %s has no ndiId; not saved", label)
            unsaved.append(label)
            continue
        (doc_dir / f"{ndi_id}.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        saved.append(ndi_id)
    return saved, unsaved


def deleteLocalDocuments(ds_path: Path, doc_ids: set[str]) -> list[str]:
    """Remove local document JSON files for the given IDs.

    MATLAB equivalent: ``ndi.cloud.sync.internal.deleteLocalDocuments``
    """
    doc_dir = ds_path / _DOC_DIR
    deleted: list[str] = []
    for doc_id in doc_ids:
        path = doc_dir / f"{doc_id}.json"
        if path.exists():
            path.unlink()
        deleted.append(doc_id)
    return deleted


def downloadNdiDocuments(
    cloud_dataset_id: str,
    ndi_to_api: dict[str, str],
    ids_to_download: set[str],
    *,
    client: CloudClient | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch documents from the cloud by NDI ID using chunked bulk download.

    MATLAB equivalent: ``ndi.cloud.sync.internal.downloadNdiDocuments``

    Returns:
        Tuple of ``(downloaded_docs, failed_ids)``.
    """
    from ..download import downloadDocumentCollection

    if not ids_to_download:
        return [], []

    # Map NDI IDs to API IDs
    api_ids = [ndi_to_api.get(ndi_id, ndi_id) for ndi_id in ids_to_download]

    try:
        docs = downloadDocumentCollection(
            cloud_dataset_id,
            doc_ids=api_ids,
            client=client,
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
        # Assign rather than setdefault: a document carrying an "ndiId" key
        # that is present but empty would keep the empty value and be
        # discarded by _save_downloaded_docs without ever reaching "failed".
        if not doc.get("ndiId"):
            doc["ndiId"] = ndi_id

    # Determine which IDs we failed to download
    failed = [
        ndi_id
        for ndi_id in ids_to_download
        if ndi_to_api.get(ndi_id, ndi_id) not in downloaded_api_ids
    ]

    # A short answer -- ask for 50 documents, get 47 -- is the shape silent
    # cloud pagination produces, and it is not an exception: the call
    # succeeds and the caller gets a shorter list. The callers keep the
    # missing IDs out of the sync index so they stay outstanding, but
    # nothing has so far said the loss happened at all.
    if failed:
        logger.warning(
            "Requested %d documents from the cloud and received %d; missing: %s",
            len(ids_to_download),
            len(ids_to_download) - len(failed),
            ", ".join(sorted(failed)[:10]) + ("..." if len(failed) > 10 else ""),
        )

    return docs, failed


# ---------------------------------------------------------------------------
# Resolving what a sync operates on
#
# THE SYNC FUNCTIONS TAKE A DATASET, NOT A PATH -- NDI-python#232.
#
# They used to take ``dataset_path: str``, and worked entirely from the sync
# index's id lists. That made a whole class of work impossible: with only ids
# in hand there is no document CONTENT to send, so every upload posted
# ``{"ndiId": doc_id}`` -- a document with no base, no class and no
# properties. The call succeeded, the remote listed the id, and no later run
# ever sent it again, because a live listing showed it present. The index
# recorded it as synced. Nothing reported a problem.
#
# MATLAB's counterparts take an ``ndi.dataset``, and so do these now. The
# dataset is the only thing that can answer "what are my documents", which is
# the question an upload has to ask.
# ---------------------------------------------------------------------------


def _dataset_path(dataset: Any) -> Path:
    """The dataset's own directory, where ``.ndi/sync/index.json`` lives."""
    if isinstance(dataset, (str, Path)):
        raise CloudSyncError(
            "The sync functions take an ndi.dataset, not a path (NDI-python#232). "
            "A path cannot supply document contents, so uploads built from one "
            "sent an id and no document. Open the dataset first -- "
            "ndi.dataset.dir(path) -- and pass that."
        )
    for name in ("getpath", "path"):
        attr = getattr(dataset, name, None)
        if attr is None:
            continue
        value = attr() if callable(attr) else attr
        if value:
            return Path(str(value))
    raise CloudSyncError("This dataset has no local path; the sync index is stored under it.")


def _resolve_cloud_dataset_id(
    dataset: Any,
    cloud_dataset_id: str,
    client: CloudClient | None,
) -> str:
    """The remote id to sync against, resolved from the dataset when absent.

    MATLAB's sync functions take no cloud id at all -- they read it from the
    dataset's ``dataset_remote`` document. Passing one stays supported, since
    a caller that has already resolved it should not pay for it twice.
    """
    if cloud_dataset_id:
        return cloud_dataset_id
    from ..internal import getCloudDatasetIdForLocalDataset

    try:
        resolved, _ = getCloudDatasetIdForLocalDataset(dataset, client=client)
    except Exception as exc:  # noqa: BLE001 - re-raised with the actionable message
        raise CloudSyncError(
            "Could not determine the cloud dataset id. Ensure the local dataset "
            f"is linked to a remote one. Original error: {exc}"
        ) from exc
    if not resolved:
        raise CloudSyncError(
            "This dataset is not linked to a cloud dataset. Upload it to NDI Cloud first."
        )
    return resolved


def _local_documents(dataset: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """``({ndi_id: properties}, {ndi_id})`` for every document in *dataset*.

    The properties dict is what an upload actually sends. Enumerating the
    dataset -- rather than reading the index's remembered id list -- is also
    what makes "local" mean the current truth: a document added since the
    last sync is local now, and the index cannot know that.

    Not wrapped in try/except: an unreadable database is not an empty
    dataset, and uploading nothing must never be the reported outcome of
    failing to look. (The same reasoning as orchestration.uploadDataset.)
    """
    from ..internal import listLocalDocuments
    from ..upload import document_id

    docs, _ids = listLocalDocuments(dataset)
    by_id: dict[str, dict[str, Any]] = {}
    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        doc_id = document_id(props)
        if doc_id:
            by_id[doc_id] = props
    return by_id, set(by_id)


def _upload_documents(
    cloud_dataset_id: str,
    documents: list[dict[str, Any]],
    *,
    client: CloudClient | None,
) -> tuple[list[str], list[str]]:
    """Send whole documents, and report ``(uploaded_ids, failed_ids)``.

    Routed through :func:`ndi.cloud.upload.uploadDocumentCollection`, which is
    the maintained producer and what MATLAB's uploadNew uses. ``only_missing``
    is off because the caller has already worked out what the remote lacks;
    asking the remote again per call would be a second full listing.
    """
    from ..upload import document_id, uploadDocumentCollection

    if not documents:
        return [], []
    report = uploadDocumentCollection(
        cloud_dataset_id, documents, only_missing=False, client=client
    )
    uploaded = [str(i) for i in report.get("manifest", []) if i]
    sent = {document_id(d) for d in documents}
    failed = sorted(i for i in sent if i and i not in set(uploaded))
    if failed:
        logger.warning(
            "%d of %d document(s) did not upload: %s",
            len(failed),
            len(documents),
            ", ".join(failed[:10]) + ("..." if len(failed) > 10 else ""),
        )
    return uploaded, failed


def _upload_binaries(
    cloud_dataset_id: str,
    documents: list[dict[str, Any]],
    options: SyncOptions,
    *,
    client: CloudClient | None,
) -> set[str]:
    """Upload each document's binaries; return the ids whose binaries failed.

    A document whose binary did not upload must not be recorded as synced:
    the remote then holds the metadata and none of the data, and a reader
    gets a 404 (NDI-matlab#805). uploadFilesForDatasetDocuments does not
    raise on a per-file failure -- it reports one -- so catching an exception
    was never going to see the ordinary case.
    """
    if not options.sync_files or not documents:
        return set()
    from ..upload import document_id, uploadFilesForDatasetDocuments

    try:
        report = uploadFilesForDatasetDocuments(
            getattr(getattr(client, "config", None), "org_id", ""),
            cloud_dataset_id,
            documents,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001
        # The whole pass fell over: nothing in it can be claimed to have
        # uploaded, so none of these documents is synced.
        logger.warning("Binary upload pass failed: %s", exc)
        return {document_id(d) for d in documents} - {""}
    failed = {str(i) for i in report.get("failed_document_ids", []) if i}
    if failed:
        logger.warning(
            "%d document(s) reached the remote without their binaries; "
            "not recording them as synced: %s",
            len(failed),
            ", ".join(sorted(failed)),
        )
    return failed


# ---------------------------------------------------------------------------
# The (success, errorMessage, report) contract
#
# MATLAB's five sync entry points all return
# ``[success, errorMessage, report]``. This side returned the report alone,
# so the one question a scripted caller most wants to ask -- did it work? --
# had to be reconstructed by inspecting report fields whose names differ per
# mode. They return the triple now.
#
# WHAT MAKES IT FALSE. MATLAB sets success=false when the body throws, and
# NDI-matlab 29546720b added the case that matters: a partial document
# upload raises rather than reporting a clean mirror, because
#
#   "A scripted pipeline checking only `success` believed the dataset was
#    mirrored when zero documents transferred."
#
# The same reasoning applies to a partial DOWNLOAD, which MATLAB still
# reports as success -- the silent-loss shape NDI-matlab 7efa0a8a0 fixed on
# the index side without revisiting the flag. So here, anything that did not
# transfer makes success false, in either direction. That is stricter than
# MATLAB for the two download modes and never wrong: a caller that wants the
# detail has the report, and one that checks only the flag is not told a
# partial sync was complete.
#
# WHAT IT DOES NOT CHANGE. MATLAB aborts on a failed upload, leaving the
# index un-advanced. These record what actually landed and advance the index
# over exactly that -- so a retry re-sends only the documents still missing,
# rather than redoing the whole mirror. success=false and a truthful index
# are not in tension; the flag reports the outcome, the index reports the
# state.
# ---------------------------------------------------------------------------


def _outcome(report: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """``(success, errorMessage, report)`` for a run that completed.

    A dry run reports the success of the dry run itself: it inspected both
    sides and changed nothing, which is what it was asked to do.
    """
    failed = [str(i) for i in (report.get("failed") or [])]
    unsaved = [str(i) for i in (report.get("unsaved_documents") or [])]
    if not failed and not unsaved:
        return True, "", report

    parts: list[str] = []
    if failed:
        shown = ", ".join(sorted(failed)[:10]) + ("..." if len(failed) > 10 else "")
        parts.append(f"{len(failed)} document(s) did not transfer: {shown}")
    if unsaved:
        parts.append(f"{len(unsaved)} downloaded document(s) could not be saved")
    return False, "; ".join(parts), report


def _failed_outcome(
    mode: str, exc: BaseException, report: dict[str, Any] | None = None
) -> tuple[bool, str, dict[str, Any]]:
    """The triple for a run that could not complete.

    The report still comes back, carrying whatever the run had recorded
    before it stopped, so a caller can see how far it got.
    """
    logger.warning("%s failed: %s", mode, exc)
    out = dict(report or {})
    out.setdefault("mode", mode)
    out.setdefault("failed", [])
    return False, str(exc), out


# ---------------------------------------------------------------------------
# Public sync operations
# ---------------------------------------------------------------------------


#: How long a sync entry point will wait for in-flight bulk uploads before
#: inventorying remote state. Deliberately far below
#: waitForAllBulkUploads' own 300s default: this is a boundary crossed on
#: every call, most of the time with nothing outstanding.
_SETTLE_TIMEOUT = 30.0


def _settle_bulk_uploads(
    cloud_dataset_id: str,
    options: SyncOptions,
    *,
    client: Any = None,
) -> None:
    """Wait for in-flight bulk uploads before inventorying remote state.

    MATLAB counterpart: NDI-matlab c425cd115 wires
    ``ndi.cloud.api.files.waitForAllBulkUploads`` into all five sync entry
    points, right after the dataset id is resolved and before the first
    remote-state inventory.

    THE RACE. A bulk upload lands as a zip that a server-side worker then
    extracts. Until it finishes, ``listFiles`` can report ``uploaded=true``
    -- the zip arrived -- while the per-file objects do not exist yet. A
    sync that inventories in that window builds its whole plan on a picture
    that is about to change, and the failures that follow look like
    intermittent cloud flakiness rather than a race.

    :func:`~ndi.cloud.api.files.waitForAllBulkUploads` was ported with a
    docstring saying callers should do exactly this; nothing did.

    Skipped under ``dry_run``: a dry run inventories to report, changes
    nothing, and should not block on someone else's upload.

    A wait that times out or reports failed jobs is logged, not raised.
    The inventory that follows is then merely as stale as it was before
    this existed, and refusing to sync at all would be a worse answer than
    proceeding with a warning.

    THE DEADLINE IS THE CALLER'S, NOT THE WAIT'S. waitForAllBulkUploads
    defaults to 300s, which is the right budget for "an extraction really is
    in flight and I want it finished". It is the wrong budget for a boundary
    every sync entry point crosses on every call, including the many that
    have no bulk upload outstanding at all. ``_SETTLE_TIMEOUT`` caps what a
    sync will spend here; a genuinely long extraction is then reported as a
    stale inventory rather than silently held.
    """
    if options.dry_run:
        return
    from ..api import files as files_api

    try:
        result = files_api.waitForAllBulkUploads(
            cloud_dataset_id, timeout=_SETTLE_TIMEOUT, client=client
        )
    except Exception as exc:  # noqa: BLE001 - a wait that fails must not stop the sync
        logger.warning("Could not wait for bulk uploads on %s: %s", cloud_dataset_id, exc)
        return
    state = (result or {}).get("state")
    if state == "unavailable":
        # No bulk-upload service to wait on. Not a sync problem, and not
        # something to warn about on every single call.
        logger.debug(
            "No bulk-upload status available for %s (%s); proceeding.",
            cloud_dataset_id,
            (result or {}).get("error", ""),
        )
        return
    if state and state != "complete":
        logger.warning(
            "Bulk uploads on %s did not settle (state=%s after %.1fs); the remote "
            "inventory that follows may be incomplete.",
            cloud_dataset_id,
            state,
            (result or {}).get("elapsed", float("nan")),
        )


def uploadNew(
    dataset: Any,
    cloud_dataset_id: str = "",
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Upload documents that exist locally but not in the cloud.

    MATLAB equivalent: ``ndi.cloud.sync.uploadNew(ndiDataset, syncOptions)``.

    Args:
        dataset: The local ``ndi.dataset``. Not a path -- see
            :func:`_dataset_path` for why.
        cloud_dataset_id: The remote to sync against. Empty resolves it from
            the dataset's ``dataset_remote`` document, as MATLAB does.
        options: Sync options; ``sync_files`` governs the binary pass.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        ``(success, errorMessage, report)``, matching MATLAB.

    "New" is *local and not on the remote*, measured against a live listing
    rather than against the index's remembered ids. That is deliberately not
    MATLAB's phrasing ("added since the last sync"): a document whose upload
    failed on an earlier run is still absent from the remote, and comparing
    against the index would consider it handled and never retry it.
    """
    from ..internal import listRemoteDocumentIds

    options = options or SyncOptions()
    # Refusing a path is a caller mistake, not a sync outcome, so it raises
    # rather than becoming success=False -- see _dataset_path.
    ds_path = _dataset_path(dataset)
    report: dict[str, Any] = {"mode": "upload_new", "failed": []}
    try:
        cloud_dataset_id = _resolve_cloud_dataset_id(dataset, cloud_dataset_id, client)
        index = SyncIndex.read(ds_path)

        _settle_bulk_uploads(cloud_dataset_id, options, client=client)

        remote_ids = listRemoteDocumentIds(cloud_dataset_id, client=client)
        remote_id_set = set(remote_ids.keys())
        documents, local_ids = _local_documents(dataset)

        new_ids = local_ids - remote_id_set

        report.update(
            {
                "new_count": len(new_ids),
                "uploaded_document_ids": [],
                "dry_run": options.dry_run,
            }
        )

        if options.dry_run:
            report["uploaded_document_ids"] = sorted(new_ids)
            return _outcome(report)

        to_send = [documents[i] for i in sorted(new_ids)]
        uploaded, failed = _upload_documents(cloud_dataset_id, to_send, client=client)

        # Binaries only for documents whose metadata actually landed. Sending a
        # file for a document the remote does not have would orphan it.
        binaries_failed = _upload_binaries(
            cloud_dataset_id,
            [documents[i] for i in uploaded if i in documents],
            options,
            client=client,
        )

        report["uploaded_document_ids"] = uploaded
        report["failed"] = sorted(set(failed) | binaries_failed)

        if options.verbose and uploaded:
            logger.info("uploadNew: uploaded %d documents", len(uploaded))

        # The remote is what it held plus what actually arrived whole. A document
        # whose binaries failed is withheld, so the index never claims a sync
        # that left the data behind.
        index.update(
            sorted(local_ids),
            sorted((remote_id_set | set(uploaded)) - binaries_failed),
        )
        index.write(ds_path)
    except Exception as exc:  # noqa: BLE001 - reported through the triple
        return _failed_outcome("upload_new", exc, report)

    return _outcome(report)


def downloadNew(
    dataset: Any,
    cloud_dataset_id: str = "",
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Download documents that exist in the cloud but not locally.

    MATLAB equivalent: ``ndi.cloud.sync.downloadNew(ndiDataset, syncOptions)``.

    Returns:
        ``(success, errorMessage, report)``, matching MATLAB.
    """
    from ..internal import listRemoteDocumentIds

    options = options or SyncOptions()
    # Refusing a path is a caller mistake, not a sync outcome, so it raises
    # rather than becoming success=False -- see _dataset_path.
    ds_path = _dataset_path(dataset)
    report: dict[str, Any] = {"mode": "download_new", "failed": []}
    try:
        cloud_dataset_id = _resolve_cloud_dataset_id(dataset, cloud_dataset_id, client)
        index = SyncIndex.read(ds_path)

        _settle_bulk_uploads(cloud_dataset_id, options, client=client)

        remote_ids = listRemoteDocumentIds(cloud_dataset_id, client=client)
        remote_id_set = set(remote_ids.keys())
        _documents, local_ids = _local_documents(dataset)

        new_ids = remote_id_set - local_ids

        report.update(
            {
                "new_count": len(new_ids),
                "downloaded_document_ids": [],
                "unsaved_documents": [],
                "dry_run": options.dry_run,
            }
        )

        if options.dry_run:
            report["downloaded_document_ids"] = sorted(new_ids)
            return _outcome(report)

        docs, failed = downloadNdiDocuments(cloud_dataset_id, remote_ids, new_ids, client=client)
        saved, unsaved = _save_downloaded_docs(ds_path, docs)
        _ingest_downloaded_docs(dataset, [d for d in docs if _upload_id(d) in set(saved)])
        report["downloaded_document_ids"] = saved
        report["failed"] = failed
        report["unsaved_documents"] = unsaved

        if options.verbose and saved:
            logger.info("downloadNew: downloaded %d documents", len(saved))

        # Update index. A document we set out to fetch but did not land on disk
        # is not synced, so it must not enter either list: recording it on the
        # remote side would make remote_doc_ids_last_sync a claim about documents
        # that were never fetched.
        not_obtained = new_ids - set(saved)
        index.update(
            sorted(local_ids | set(saved)),
            sorted(remote_id_set - not_obtained),
        )
        index.write(ds_path)
    except Exception as exc:  # noqa: BLE001 - reported through the triple
        return _failed_outcome("download_new", exc, report)

    return _outcome(report)


def mirrorToRemote(
    dataset: Any,
    cloud_dataset_id: str = "",
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Make the remote match the local state (upload new, delete remote-only).

    MATLAB equivalent: ``ndi.cloud.sync.mirrorToRemote(ndiDataset, syncOptions)``.

    Returns:
        ``(success, errorMessage, report)``, matching MATLAB.
    """
    from ..api import documents as docs_api
    from ..internal import listRemoteDocumentIds

    options = options or SyncOptions()
    # Refusing a path is a caller mistake, not a sync outcome, so it raises
    # rather than becoming success=False -- see _dataset_path.
    ds_path = _dataset_path(dataset)
    report: dict[str, Any] = {"mode": "mirror_to_remote", "failed": []}
    try:
        cloud_dataset_id = _resolve_cloud_dataset_id(dataset, cloud_dataset_id, client)
        index = SyncIndex.read(ds_path)

        _settle_bulk_uploads(cloud_dataset_id, options, client=client)

        remote_ids = listRemoteDocumentIds(cloud_dataset_id, client=client)
        remote_id_set = set(remote_ids.keys())
        documents, local_ids = _local_documents(dataset)

        to_upload = local_ids - remote_id_set
        to_delete = remote_id_set - local_ids

        report.update(
            {
                "upload_count": len(to_upload),
                "delete_count": len(to_delete),
                "uploaded_document_ids": [],
                "deleted_remote_document_ids": [],
                "dry_run": options.dry_run,
            }
        )

        # A dry run reports what it would do and changes nothing -- writing the
        # index here would record a sync that never happened. Every other mode
        # returns before its index write for the same reason.
        if options.dry_run:
            report["uploaded_document_ids"] = sorted(to_upload)
            report["deleted_remote_document_ids"] = sorted(to_delete)
            report["failed"] = []
            return _outcome(report)

        uploaded, failed_ids = _upload_documents(
            cloud_dataset_id, [documents[i] for i in sorted(to_upload)], client=client
        )
        report["uploaded_document_ids"] = uploaded
        failed: list[str] = list(failed_ids)

        for doc_id in sorted(to_delete):
            api_id = remote_ids.get(doc_id, doc_id)
            try:
                docs_api.deleteDocument(cloud_dataset_id, api_id, client=client)
                report["deleted_remote_document_ids"].append(doc_id)
            except Exception as exc:
                logger.warning("mirrorToRemote: failed to delete %s: %s", doc_id, exc)
                failed.append(doc_id)

        binaries_failed = _upload_binaries(
            cloud_dataset_id,
            [documents[i] for i in uploaded if i in documents],
            options,
            client=client,
        )

        report["failed"] = sorted(set(failed) | binaries_failed)

        if options.verbose:
            logger.info(
                "mirrorToRemote: uploaded %d, deleted %d remote",
                len(uploaded),
                len(report["deleted_remote_document_ids"]),
            )

        # The remote is what it held, plus what we actually uploaded, minus what
        # we actually deleted -- not a blanket "remote now equals local", which
        # would silently absorb every failed upload and every failed deletion.
        final_remote = (
            (remote_id_set | set(uploaded))
            - set(report["deleted_remote_document_ids"])
            - binaries_failed
        )
        index.update(sorted(local_ids), sorted(final_remote))
        index.write(ds_path)
    except Exception as exc:  # noqa: BLE001 - reported through the triple
        return _failed_outcome("mirror_to_remote", exc, report)

    return _outcome(report)


def mirrorFromRemote(
    dataset: Any,
    cloud_dataset_id: str = "",
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Make the local state match the remote (download new, delete local-only).

    MATLAB equivalent: ``ndi.cloud.sync.mirrorFromRemote(ndiDataset, syncOptions)``.

    Returns:
        ``(success, errorMessage, report)``, matching MATLAB.
    """
    from ..internal import listRemoteDocumentIds

    options = options or SyncOptions()
    # Refusing a path is a caller mistake, not a sync outcome, so it raises
    # rather than becoming success=False -- see _dataset_path.
    ds_path = _dataset_path(dataset)
    report: dict[str, Any] = {"mode": "mirror_from_remote", "failed": []}
    try:
        cloud_dataset_id = _resolve_cloud_dataset_id(dataset, cloud_dataset_id, client)
        index = SyncIndex.read(ds_path)

        _settle_bulk_uploads(cloud_dataset_id, options, client=client)

        remote_ids = listRemoteDocumentIds(cloud_dataset_id, client=client)
        remote_id_set = set(remote_ids.keys())
        _documents, local_ids = _local_documents(dataset)

        to_download = remote_id_set - local_ids
        to_delete_local = local_ids - remote_id_set

        report.update(
            {
                "download_count": len(to_download),
                "delete_local_count": len(to_delete_local),
                "downloaded_document_ids": [],
                "deleted_local_document_ids": [],
                "unsaved_documents": [],
                "dry_run": options.dry_run,
            }
        )

        if options.dry_run:
            report["downloaded_document_ids"] = sorted(to_download)
            report["deleted_local_document_ids"] = sorted(to_delete_local)
            return _outcome(report)

        # Delete local-only documents
        deleted = deleteLocalDocuments(ds_path, to_delete_local)
        report["deleted_local_document_ids"] = deleted

        # Download remote-only documents
        docs, failed = downloadNdiDocuments(
            cloud_dataset_id, remote_ids, to_download, client=client
        )
        saved, unsaved = _save_downloaded_docs(ds_path, docs)
        _ingest_downloaded_docs(dataset, [d for d in docs if _upload_id(d) in set(saved)])
        report["downloaded_document_ids"] = saved
        report["failed"] = failed
        report["unsaved_documents"] = unsaved

        if options.verbose:
            logger.info(
                "mirrorFromRemote: downloaded %d, deleted %d local",
                len(saved),
                len(deleted),
            )

        # Mirroring leaves both sides equal, but only over the documents that
        # actually landed. Recording a failed download as local was the more
        # damaging half of this: the next run computes to_download as
        # remote_id_set - local_ids, so the document would never be retried.
        not_obtained = to_download - set(saved)
        mirrored = remote_id_set - not_obtained
        index.update(sorted(mirrored), sorted(mirrored))
        index.write(ds_path)
    except Exception as exc:  # noqa: BLE001 - reported through the triple
        return _failed_outcome("mirror_from_remote", exc, report)

    return _outcome(report)


def twoWaySync(
    dataset: Any,
    cloud_dataset_id: str = "",
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Bi-directional sync with conflict detection and deletion propagation.

    MATLAB equivalent: ``ndi.cloud.sync.twoWaySync(ndiDataset, syncOptions)``.

    Compares the current local/remote state against the last sync state to
    compute deltas. Documents added on both sides since the last sync are
    flagged as conflicts and skipped. Deletions on one side are propagated to
    the other (unless the deleted doc was re-added).

    THE LOCAL DELTAS ONLY MEAN SOMETHING NOW THAT A DATASET IS PASSED. This
    function read ``current_local`` and ``last_local`` from the same field of
    the same index, so ``added_local`` and ``deleted_local`` were empty by
    construction -- and with them, half the conflict detection and the whole
    "deleted locally, so delete it on the remote" branch. There was nothing
    else it could do: with only a path, the current local state was
    unknowable. ``current_local`` now comes from the dataset and
    ``last_local`` from the index, which is the comparison the algorithm
    always described.

    Returns:
        ``(success, errorMessage, report)``, matching MATLAB.
    """
    from ..api import documents as docs_api
    from ..internal import listRemoteDocumentIds

    options = options or SyncOptions()
    # Refusing a path is a caller mistake, not a sync outcome, so it raises
    # rather than becoming success=False -- see _dataset_path.
    ds_path = _dataset_path(dataset)
    report: dict[str, Any] = {"mode": "two_way_sync", "failed": []}
    try:
        cloud_dataset_id = _resolve_cloud_dataset_id(dataset, cloud_dataset_id, client)
        index = SyncIndex.read(ds_path)

        _settle_bulk_uploads(cloud_dataset_id, options, client=client)

        # Current state: the remote from a live listing, the local from the
        # dataset itself.
        remote_ids = listRemoteDocumentIds(cloud_dataset_id, client=client)
        current_remote = set(remote_ids.keys())
        documents, current_local = _local_documents(dataset)

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
                "twoWaySync: %d documents added on both sides (skipping): %s",
                len(conflicts),
                ", ".join(sorted(conflicts)),
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

        # A document scheduled for deletion on one side must not also be sent to
        # it. Without the current local state these sets could never overlap, so
        # nothing had to say so before.
        to_upload -= to_delete_remote
        to_download -= to_delete_local

        report.update(
            {
                "upload_count": len(to_upload),
                "download_count": len(to_download),
                "delete_local_count": len(to_delete_local),
                "delete_remote_count": len(to_delete_remote),
                "conflict_count": len(conflicts),
                "conflicts": sorted(conflicts),
                "uploaded_document_ids": [],
                "downloaded_document_ids": [],
                "deleted_local_document_ids": [],
                "deleted_remote_document_ids": [],
                "unsaved_documents": [],
                "dry_run": options.dry_run,
            }
        )

        if options.dry_run:
            report["uploaded_document_ids"] = sorted(to_upload)
            report["downloaded_document_ids"] = sorted(to_download)
            report["deleted_local_document_ids"] = sorted(to_delete_local)
            report["deleted_remote_document_ids"] = sorted(to_delete_remote)
            return _outcome(report)

        failed: list[str] = []

        # 1. Delete local docs that were removed on the remote
        deleted_local_ids = deleteLocalDocuments(ds_path, to_delete_local)
        report["deleted_local_document_ids"] = deleted_local_ids

        # 2. Delete remote docs that were removed locally
        for doc_id in sorted(to_delete_remote):
            api_id = remote_ids.get(doc_id, doc_id)
            try:
                docs_api.deleteDocument(cloud_dataset_id, api_id, client=client)
                report["deleted_remote_document_ids"].append(doc_id)
            except Exception as exc:
                logger.warning("twoWaySync: failed to delete remote %s: %s", doc_id, exc)
                failed.append(doc_id)

        # 3. Upload local-only docs -- whole documents, not just their ids
        uploaded, upload_failed = _upload_documents(
            cloud_dataset_id, [documents[i] for i in sorted(to_upload)], client=client
        )
        report["uploaded_document_ids"] = uploaded
        failed.extend(upload_failed)

        binaries_failed = _upload_binaries(
            cloud_dataset_id,
            [documents[i] for i in uploaded if i in documents],
            options,
            client=client,
        )
        failed.extend(sorted(binaries_failed))

        # 4. Download remote-only docs
        docs, dl_failed = downloadNdiDocuments(
            cloud_dataset_id, remote_ids, to_download, client=client
        )
        saved, unsaved = _save_downloaded_docs(ds_path, docs)
        _ingest_downloaded_docs(dataset, [d for d in docs if _upload_id(d) in set(saved)])
        report["downloaded_document_ids"] = saved
        report["unsaved_documents"] = unsaved
        failed.extend(dl_failed)

        report["failed"] = sorted(set(failed))

        if options.verbose:
            logger.info(
                "twoWaySync: uploaded=%d downloaded=%d del_local=%d del_remote=%d conflicts=%d",
                len(report["uploaded_document_ids"]),
                len(report["downloaded_document_ids"]),
                len(report["deleted_local_document_ids"]),
                len(report["deleted_remote_document_ids"]),
                len(conflicts),
            )

        # Compute expected final state. A remote-only document we failed to
        # download drops out of the remote side too, so the next run still sees
        # it as remote work outstanding rather than as already synced.
        not_obtained = to_download - set(saved)
        final_local = (current_local | set(saved)) - set(deleted_local_ids)
        final_remote = (
            (current_remote | set(uploaded))
            - set(report["deleted_remote_document_ids"])
            - not_obtained
            - binaries_failed
        )
        index.update(sorted(final_local), sorted(final_remote))
        index.write(ds_path)
    except Exception as exc:  # noqa: BLE001 - reported through the triple
        return _failed_outcome("two_way_sync", exc, report)

    return _outcome(report)


def validate(
    dataset: Any,
    cloud_dataset_id: str,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Compare local and remote datasets to identify sync discrepancies.

    MATLAB equivalent: +cloud/+sync/validate.m

    Returns:
        Report with local_only, remote_only, common ID lists.
    """
    from ..internal import validateSync as _validate

    return _validate(dataset, cloud_dataset_id, client=client)


def sync(
    dataset: Any,
    cloud_dataset_id: str = "",
    mode: SyncMode = SyncMode.DOWNLOAD_NEW,
    options: SyncOptions | None = None,
    *,
    client: CloudClient | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Dispatch to the appropriate sync operation based on *mode*.

    Takes the same ``ndi.dataset`` the operations themselves take, and
    returns their ``(success, errorMessage, report)`` unchanged.
    """
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


def documentDifference(
    dataset: Any,
    cloud_dataset_id: str = "",
    *,
    verbose: bool = False,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Compare local and remote document presence by id.

    MATLAB equivalent: ``ndi.cloud.sync.documentDifference``

    Unlike :func:`ndi.cloud.internal.validateSync`, this compares document
    IDS ONLY -- it never downloads document contents, which is what makes it
    cheap enough to back an interactive "how many new documents are there?"
    check. It therefore does not detect content mismatches between documents
    that exist on both sides.

    Nothing is added, deleted or modified on either side.

    Args:
        dataset: The local dataset. It must be linked to a remote NDI Cloud
            dataset unless ``cloud_dataset_id`` is supplied.
        cloud_dataset_id: The remote dataset id to compare against. Empty
            resolves it from the local ``dataset_remote`` document.
        verbose: Print progress.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        A report with ``local_only_ids``, ``remote_only_ids``, ``common_ids``
        and their counts ``num_local_only``, ``num_remote_only``,
        ``num_common``.

        The three id lists are SORTED. MATLAB's ``setdiff`` returns sorted
        output, while a Python set has no order at all, so sorting is what
        makes the two ports agree and makes a given comparison reproducible
        rather than varying between runs.

    Raises:
        CloudSyncError: If the dataset is not linked to a cloud dataset and
            no id was supplied. That is a different situation from "no new
            documents" and must not be reported as a count of zero.
    """
    from ..internal import getCloudDatasetIdForLocalDataset, listLocalDocuments

    if not cloud_dataset_id:
        try:
            cloud_dataset_id, _ = getCloudDatasetIdForLocalDataset(dataset, client=client)
        except Exception as exc:  # noqa: BLE001 - re-raised with the actionable message
            raise CloudSyncError(
                "Could not retrieve the cloud dataset id. Ensure the local "
                f"dataset is linked to a remote one. Original error: {exc}"
            ) from exc
        if not cloud_dataset_id:
            raise CloudSyncError(
                "This dataset is not linked to a cloud dataset. " "Upload it to NDI Cloud first."
            )

    if verbose:
        logger.info("Comparing document presence for cloud dataset %s...", cloud_dataset_id)

    from ..internal import listRemoteDocumentIds

    _, local_ids = listLocalDocuments(dataset)
    remote_ids = listRemoteDocumentIds(cloud_dataset_id, client=client)

    local_set = set(local_ids)
    remote_set = set(remote_ids)

    report = {
        "local_only_ids": sorted(local_set - remote_set),
        "remote_only_ids": sorted(remote_set - local_set),
        "common_ids": sorted(local_set & remote_set),
    }
    report["num_local_only"] = len(report["local_only_ids"])
    report["num_remote_only"] = len(report["remote_only_ids"])
    report["num_common"] = len(report["common_ids"])

    if verbose:
        logger.info(
            "%d local-only, %d remote-only, %d common document(s).",
            report["num_local_only"],
            report["num_remote_only"],
            report["num_common"],
        )
    return report
