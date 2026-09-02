"""
ndi.cloud.orchestration - High-level dataset sync/transfer operations.

Public functions accept an optional ``client`` keyword argument.  When
omitted, a client is created automatically from environment variables.

MATLAB equivalents: downloadDataset.m, uploadDataset.m, syncDataset.m,
    helloMatlab.m, +upload/newDataset.m, +upload/scanForUpload.m
"""

from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from .client import _auto_client

if TYPE_CHECKING:
    from .client import CloudClient

logger = logging.getLogger(__name__)


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

    # Download all full documents via chunked bulk download
    doc_jsons = downloadDocumentCollection(
        cloud_dataset_id,
        client=client,
        progress=print if verbose else None,
    )
    if verbose:
        print(f"  Downloaded {len(doc_jsons)} documents")

    # Describe the set before anything tries to store it. If a dependency
    # points outside the set, no add strategy can succeed and the problem is
    # upstream of the database entirely -- worth knowing before reading a
    # thousand lines of per-document add errors.
    from .diagnostics import document_set_report

    set_report = document_set_report(doc_jsons)

    # When not syncing files, rewrite file_info locations to ndic:// URIs
    # so binary files can be fetched on demand later.
    if not sync_files:
        from .filehandler import updateFileInfoForRemoteFiles

        for dj in doc_jsons:
            updateFileInfoForRemoteFiles(dj, cloud_dataset_id)

    # Convert to ndi_document objects and create ndi_dataset with them.
    # Mirrors MATLAB: ndi.dataset.dir([], datasetFolder, ndiDocuments)
    from ndi.dataset import ndi_dataset_dir

    documents = jsons2documents(doc_jsons)
    dataset = ndi_dataset_dir("", target, documents=documents)

    # Create remote link document if not already present
    from ndi.query import ndi_query

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

    # Optionally download files
    if sync_files and doc_jsons:
        file_dir = target / ".ndi" / "files"
        report = downloadDatasetFiles(cloud_dataset_id, doc_jsons, file_dir, client=client)
        if verbose:
            print(f'  Files downloaded: {report["downloaded"]}, failed: {report["failed"]}')

    # Verify every downloaded document made it into the local database.
    # The local dataset may have *more* documents (e.g. session and
    # session-in-a-dataset docs created internally), so we only check
    # that every remote doc ID is present locally.
    db_ids = set(
        dataset._session._database._driver._db.get_doc_ids(
            dataset._session._database._driver._branch_id
        )
    )

    missing: list[str] = []
    missing_jsons: list[dict] = []
    for dj in doc_jsons:
        did = dj.get("base", {}).get("id", "") if isinstance(dj, dict) else ""
        if did and did not in db_ids:
            missing.append(did)
            missing_jsons.append(dj)

    if verbose:
        print("Download complete.")

    if missing:
        # Print the document_class of each missing doc for diagnostics.
        # Session/dataset docs from older datasets are expected to be
        # missing (superseded by docs created locally during dataset init).
        session_dataset_types = {
            "ndi_session",
            "ndi_dataset",
            "session",
            "dataset",
            "session_in_a_dataset",
            "dataset_session_info",
        }
        real_missing: list[tuple[str, str]] = []
        for doc_id, dj in zip(missing, missing_jsons):
            doc_class = (
                dj.get("document_class", {}).get("class_name", "") if isinstance(dj, dict) else ""
            )
            superclasses = (
                dj.get("document_class", {}).get("superclasses", []) if isinstance(dj, dict) else []
            )
            all_types = {doc_class} | {
                sc.get("class_name", "") if isinstance(sc, dict) else str(sc)
                for sc in (superclasses if isinstance(superclasses, list) else [])
            }
            if all_types & session_dataset_types:
                print(
                    f"  Note: remote doc {doc_id} (class: {doc_class}) "
                    f"not in local DB — expected for session/dataset docs"
                )
            else:
                print(f"  WARNING: remote doc {doc_id} (class: {doc_class}) missing from local DB")
                real_missing.append((doc_id, doc_class))

        if real_missing:
            missing_docs_path = target / "missingDocuments.json"
            import json

            missing_docs_path.write_text(json.dumps(missing_jsons, indent=2, default=str))

            # Why each one failed, not just that it is absent. The dataset
            # constructor records the reason per document; reporting only the
            # ids left the cause invisible -- a CI failure named 501 documents
            # and nothing about what was wrong with them.
            reasons = dict(getattr(dataset, "add_doc_failures", []) or [])

            # Separate the genuine problems from the fallout.
            #
            # After a batch add is rejected, each document is retried alone,
            # and every document whose dependency sits later in the list then
            # fails too -- hundreds of ValidationDependency errors that say
            # nothing. The ones that matter name an id that is absent from the
            # whole downloaded set: no ordering could have satisfied those.
            offered_ids = {
                (dj.get("base", {}).get("id", "") if isinstance(dj, dict) else "").lower()
                for dj in doc_jsons
            }
            offered_ids.discard("")
            dangling = re.compile(r'Dependent doc ID "([^"]+)"')

            genuine: dict[str, list[str]] = {}
            fallout = 0
            distinct: dict[str, list[str]] = {}
            for doc_id, _cls in real_missing:
                reason = reasons.get(doc_id)
                if not reason:
                    continue
                distinct.setdefault(reason, []).append(doc_id)
                match = dangling.search(reason)
                if match and match.group(1).lower() in offered_ids:
                    fallout += 1  # resolvable within the batch
                else:
                    genuine.setdefault(reason, []).append(doc_id)

            lines = [
                f"Downloaded {len(doc_jsons)} documents but "
                f"{len(real_missing)} are missing from the local dataset:"
            ]
            batch_failure = getattr(dataset, "add_batch_failure", None)
            if batch_failure:
                # Everything below is fallout. The documents are validated as
                # one batch, so a single bad document rejects the whole set,
                # and the per-document retry then fails for every document
                # whose dependency sits later in the list. Lead with the one
                # reason that is not an artifact of that retry.
                lines.insert(
                    0,
                    "The batch add was rejected as a whole, so each document "
                    "was retried alone; the per-document reasons below are "
                    "mostly fallout from that retry, not independent problems."
                    f"\n\nBatch rejection: {batch_failure}\n\n",
                )
            for doc_id, doc_class in real_missing[:10]:
                reason = reasons.get(doc_id)
                suffix = f" -- {reason}" if reason else ""
                lines.append(f"\n  - {doc_id} (class: {doc_class}){suffix}")
            if len(real_missing) > 10:
                lines.append(f"\n  ... and {len(real_missing) - 10} more")
            if genuine:
                lines.append(
                    f"\n\n{len(genuine)} reason(s) name an id that is absent from the "
                    f"entire downloaded set -- no ordering could satisfy these, so "
                    f"they are the real problem:"
                )
                for reason, ids in sorted(genuine.items(), key=lambda kv: -len(kv[1]))[:20]:
                    lines.append(f"\n  [{len(ids)}x] {reason}")
            if fallout:
                lines.append(
                    f"\n\n{fallout} further document(s) failed only because the "
                    f"document they depend on was retried later; those references "
                    f"resolve within the downloaded set and are not independent "
                    f"problems."
                )
            elif distinct and not genuine:
                lines.append("\n\nDistinct failure reasons:")
                for reason, ids in sorted(distinct.items(), key=lambda kv: -len(kv[1]))[:20]:
                    lines.append(f"\n  [{len(ids)}x] {reason}")
            elif real_missing:
                lines.append(
                    "\n\nNo failure reason was recorded for any of these -- they "
                    "were not rejected on the way in, so they never reached the "
                    "database at all."
                )
            lines.append(f"\nFull JSON of missing documents written to:\n  {missing_docs_path}")
            lines.append("\n\n" + set_report)

            # What the add stage did with it, so the two halves can be
            # compared: offered, stored, and how many of each class survived.
            lines.append(
                f"\n\n=== add stage ===\n"
                f"  documents offered:    {len(documents)}\n"
                f"  ids in database:      {len(db_ids)}\n"
                f"  add_doc_failures:     {len(getattr(dataset, 'add_doc_failures', []) or [])}"
            )
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
        print(f"  Read {len(doc_jsons)} documents, bulk-inserting into ndi_dataset...")

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
        print(f"  ndi_dataset created at {target} with {added} documents ({skipped} skipped).")

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

    # MATLAB refuses to upload a dataset that is not fully ingested, and it is
    # the FIRST thing uploadDataset.m does (line 53). This had no counterpart
    # here for a simpler reason than oversight: ndi_dataset had no isIngested()
    # to call (issue #136). A dataset with linked sessions uploaded happily,
    # and whatever lived outside the dataset directory silently did not go --
    # the remote dataset then looks complete and is not.
    #
    # Asked by duck typing rather than isinstance: uploadDataset takes Any,
    # and a caller passing a stand-in dataset should not be blocked by a
    # method it never claimed to have.
    is_ingested = getattr(dataset, "isIngested", None)
    if callable(is_ingested) and not is_ingested():
        return (
            False,
            "",
            "Dataset is not fully ingested. All sessions must be ingested " "before uploading.",
        )

    # Resolve or create remote dataset
    cloud_id = ""
    if not upload_as_new:
        cloud_id, _ = getCloudDatasetIdForLocalDataset(dataset, client=client)

    if not cloud_id:
        # Create new remote dataset
        name = remote_name or getattr(dataset, "name", "Unnamed ndi_dataset")
        org_id = client.config.org_id
        try:
            result = ds_api.createDataset(org_id, name, client=client)
            cloud_id = result.get("id", result.get("_id", ""))
        except Exception as exc:
            return False, "", f"Failed to create remote dataset: {exc}"

        # Store link locally. MATLAB: ndiDataset.database_add(remoteDatasetDoc)
        # (uploadDataset.m:91). Reported, never swallowed: without this
        # document the dataset does not know it has been uploaded, so the next
        # upload creates a SECOND remote dataset. Returning success with the
        # link missing is what made that duplication silent.
        remote_doc = createRemoteDatasetDoc(cloud_id, dataset)
        try:
            dataset.database_add(remote_doc)
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            return (
                False,
                cloud_id,
                f"Remote dataset {cloud_id} was created, but the local "
                f"dataset_remote link could not be written: {exc}. Re-running "
                "the upload would create a second remote dataset -- write the "
                "link or remove the remote dataset before retrying.",
            )

    if verbose:
        print(f"Uploading to cloud dataset: {cloud_id}")

    # Gather local documents
    from ndi.query import ndi_query

    # MATLAB: ndiDataset.database_search(ndi.query('','isa','base'))
    # (uploadDataset.m:96). Two separate mistakes lived on this line: it went
    # through `dataset.session`, which ndi_dataset does not have, and it used
    # a bare ndi_query(""), which matches no documents at all. Either one on
    # its own uploads an empty dataset while reporting success.
    #
    # Not wrapped: an unreadable database is not an empty dataset, and
    # uploading nothing must never be the reported outcome of failing to look.
    all_docs = dataset.database_search(ndi_query("").isa("base"))

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
            client.config.org_id,
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


# ---------------------------------------------------------------------------
# helloMatlab -- the end-to-end MATLAB BYOL check
# ---------------------------------------------------------------------------

#: The pipeline helloMatlab runs. Its verify stage boots an EC2 instance,
#: runs ``matlab -batch "ver"`` there under the caller's BYOL licence, and
#: writes the License Manager's own words back into the session document.
HELLO_MATLAB_PIPELINE_ID = "hello-matlab-v1"

#: Statuses that end the poll loop. Read on both the session and its verify
#: stage: MATLAB checks ABORTED only on the session, but an aborted stage is
#: not a state to keep waiting on either, so the same set covers both.
_STAGE_SUCCESS = "COMPLETED"
_STAGE_FAILURE = ("FAILED", "ABORTED")


class HelloMatlabResult(NamedTuple):
    """What :func:`helloMatlab` reports back.

    A NamedTuple so it unpacks in MATLAB's output order --
    ``success, sessionId, statusMessage, sessionDoc = helloMatlab()``
    mirrors ``[success, sessionId, statusMessage, sessionDoc] =
    ndi.cloud.helloMatlab()`` -- while still reading as
    ``result.statusMessage`` in Python.
    """

    success: bool
    sessionId: str  # noqa: N815 - MATLAB's output name, per bridge Rule 3
    statusMessage: str  # noqa: N815
    sessionDoc: dict[str, Any]  # noqa: N815


def _session_id_from(answer: Any) -> str:
    """The session id in a POST /compute/start response.

    The API has answered with both spellings, so accept either rather
    than reporting "no sessionId" for a session that was in fact started
    and is now billing.
    """
    for key in ("sessionId", "id"):
        value = _read_field(answer, key)
        if value:
            return value
    return ""


def _read_field(source: Any, name: str, default: str = "") -> str:
    """A string field of a response body, whatever shape it arrived in."""
    if hasattr(source, "get"):
        value = source.get(name)
        if value not in (None, "", [], {}):
            return str(value)
    return default


def _verify_stage(session_doc: Any) -> dict[str, Any]:
    """The ``history.verify`` sub-document, or an empty one."""
    history = session_doc.get("history") if hasattr(session_doc, "get") else None
    if isinstance(history, dict):
        verify = history.get("verify")
        if isinstance(verify, dict):
            return verify
    return {}


def _hello_matlab_verdict(session_status: str, stage_status: str) -> bool | None:
    """True (done), False (failed), or None (still running).

    Kept separate from the polling so the terminal-state rule can be
    tested without a clock or a network: this is the decision that
    determines whether a 20-minute wait ends at minute one.
    """
    if stage_status == _STAGE_SUCCESS or session_status == _STAGE_SUCCESS:
        return True
    if stage_status in _STAGE_FAILURE or session_status in _STAGE_FAILURE:
        return False
    return None


def _start_failure_message(exc: Exception) -> str:
    """Say why POST /compute/start refused, in the server's own terms.

    The two refusals a caller will actually hit are
    ``MATLAB_LICENSE_REQUIRED`` (no BYOL licence registered for the
    release the pipeline asks for) and ``MATLAB_LICENSE_DECRYPT_FAILED``.
    Both arrive as an HTTP 400 whose body names the code and the required
    release, and both are fixed by the caller rather than by retrying --
    so the fix belongs in the message, not in the raw payload.
    """
    body = getattr(exc, "response_body", None)
    code = _read_field(body, "code")
    if code:
        required = _read_field(body, "requiredRelease")
        if code == "MATLAB_LICENSE_REQUIRED":
            return (
                f"MATLAB_LICENSE_REQUIRED (need release {required}); register one via "
                "ndi.cloud.api.users.allocateMatlabLicenseMac + setMatlabLicense"
            )
        if code == "MATLAB_LICENSE_DECRYPT_FAILED":
            return f"MATLAB_LICENSE_DECRYPT_FAILED for {required}: {_read_field(body, 'error')}"
        return f"{code}: {_read_field(body, 'message')}"
    message = _read_field(body, "message")
    if message:
        return message
    return str(exc)


@_auto_client
def helloMatlab(
    *,
    timeout_seconds: float = 1200.0,
    poll_interval_seconds: float = 10.0,
    verbose: bool = True,
    client: CloudClient | None = None,
) -> HelloMatlabResult:
    """Check that this user's MATLAB BYOL registration works on NDI Cloud.

    MATLAB equivalent: ndi.cloud.helloMatlab

    Starts the ``hello-matlab-v1`` compute pipeline, then polls
    ``GET /compute/{sessionId}`` until its verify stage reaches a
    terminal state, and returns the message MATLAB wrote back from the
    EC2 instance.  This is the end-to-end check: it exercises the
    licence registration, the pipeline, the instance, and the status
    handler that carries MATLAB's answer home.

    Args:
        timeout_seconds: Hard cap on polling.  The stage has its own
            15-minute watchdog, so the 20-minute default lets the
            stage's own failure be the one reported.
        poll_interval_seconds: Seconds between status polls.
        verbose: Print one line per status *change* (not per poll).
        client: Authenticated cloud client (auto-created if omitted, which
            is what performs the ``ndi.cloud.authenticate()`` step MATLAB
            does explicitly).

    Returns:
        :class:`HelloMatlabResult` -- ``success`` is True only if the
        verify stage reached COMPLETED.  ``statusMessage`` carries the
        License Manager string on success or failure, or the reason the
        API refused to start a session at all.  ``sessionDoc`` is the
        final session document, or the start-call error payload.

    Prerequisite: a registered BYOL licence matching the pipeline's
    ``requiresMatlabRelease``.  Register one with
    :func:`ndi.cloud.api.users.allocateMatlabLicenseMac` and
    :func:`ndi.cloud.api.users.setMatlabLicense`.  Without one the API
    refuses the start call with ``MATLAB_LICENSE_REQUIRED``, which this
    function reports directly rather than as a raw HTTP 400.

    See also: ndi.cloud.api.compute.startSession,
        ndi.cloud.api.compute.getSessionStatus,
        ndi.cloud.api.users.getMatlabLicense
    """
    import time

    from .api import compute as compute_api
    from .exceptions import CloudError

    if verbose:
        print(f"helloMatlab: starting pipeline {HELLO_MATLAB_PIPELINE_ID} ...")

    try:
        answer = compute_api.startSession(HELLO_MATLAB_PIPELINE_ID, client=client)
    except CloudError as exc:
        message = _start_failure_message(exc)
        if verbose:
            print(f"helloMatlab: start failed -- {message}")
        body = getattr(exc, "response_body", None)
        return HelloMatlabResult(False, "", message, body if isinstance(body, dict) else {})

    session_id = _session_id_from(answer)
    if not session_id:
        # A started session with an unreadable id is worse than a failed
        # start: it is billing and nothing here can abort it. Say so.
        return HelloMatlabResult(
            False,
            "",
            "start response had no sessionId",
            dict(answer) if hasattr(answer, "keys") else {},
        )

    if verbose:
        print(f"helloMatlab: session {session_id} started; polling verify stage...")

    deadline = time.monotonic() + timeout_seconds
    session_doc: dict[str, Any] = {}
    last_line = ""

    while True:
        if time.monotonic() > deadline:
            return HelloMatlabResult(
                False,
                session_id,
                f"polling timed out after {timeout_seconds:g} seconds",
                session_doc,
            )

        try:
            status = compute_api.getSessionStatus(session_id, client=client)
        except CloudError as exc:
            # A transient API hiccup should not end a run that is minutes
            # into a billed EC2 instance, so keep polling -- but say what
            # happened, because a status call failing every time until the
            # deadline is a different problem from a slow pipeline, and
            # silence cannot tell them apart.
            logger.warning("helloMatlab: status poll failed, retrying: %s", exc)
            time.sleep(poll_interval_seconds)
            continue

        session_doc = dict(status) if hasattr(status, "keys") else {}
        session_status = _read_field(session_doc, "status")
        verify = _verify_stage(session_doc)
        stage_status = _read_field(verify, "status")
        stage_message = _read_field(verify, "statusMessage")

        if verbose:
            line = (
                f"session={session_status} stage={stage_status} "
                f"instance={_read_field(verify, 'awsResourceId')} :: {stage_message}"
            )
            if line != last_line:
                print(f"  {line}")
                last_line = line

        verdict = _hello_matlab_verdict(session_status, stage_status)
        if verdict is not None:
            return HelloMatlabResult(verdict, session_id, stage_message, session_doc)

        time.sleep(poll_interval_seconds)


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

    # Same fix as uploadDataset: dataset.database_search, and isa("base")
    # rather than a bare query that matches nothing. Reported as an empty
    # local side, this made every remote document look new.
    local_docs = dataset.database_search(ndi_query("").isa("base"))

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
            dataset.database_add(doc)
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

    # Same fix as uploadDataset: dataset.database_search, and isa("base")
    # rather than a bare query that matches nothing. Reported as an empty
    # local side, this made every remote document look new.
    local_docs = dataset.database_search(ndi_query("").isa("base"))

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
