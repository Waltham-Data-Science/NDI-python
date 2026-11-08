"""
ndi.cloud.session_writer - add documents straight to a session of an NDI Cloud dataset.

MATLAB equivalents: +ndi/+cloud/+upload/SessionWriter.m and
+ndi/+cloud/+upload/CurlSender.m

:class:`SessionWriter` stands in for an ``ndi.session`` that lives in an NDI
Cloud dataset, so a document builder that writes to a session (the
lightsheet builders: ``fromOMEZarr``, ``fromSPIM``, ``makePyramid``) can write
to the cloud instead, with no local session or dataset in between.

:class:`ThreadSender` is the Python counterpart of MATLAB's ``CurlSender``:
MATLAB cannot send files concurrently without blocking, so it starts one
background ``curl --parallel`` per batch. Python PUTs the batch from a
thread pool (``requests``), with the same interface: it starts at once,
``wait(timeout)`` returns ``(ok, msg, failed)``, ``stop()`` and ``delete()``.

The MATLAB method names, argument order and semantics are kept (camelCase,
as the lightsheet builders call them); MATLAB's name-value options are
keyword-only arguments with camelCase names.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import tempfile
import threading
import time
import weakref
import zipfile
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass
from typing import Any

from .exceptions import CloudUploadError

__all__ = [
    "SessionWriter",
    "SessionWriterError",
    "ThreadSender",
    "CachedBinaryFile",
]

#: Sleep used between retries; a module attribute so tests can replace it.
_sleep: Callable[[float], None] = time.sleep


class SessionWriterError(CloudUploadError):
    """A SessionWriter failure, carrying MATLAB's error identifier.

    Attributes:
        identifier: The MATLAB identifier for the same failure, e.g.
            ``"NDI:cloud:SessionWriter:uploadNotVerified"``, so a caller can
            tell the cases apart the way MATLAB code reads ``ME.identifier``.
    """

    def __init__(self, identifier: str, message: str):
        super().__init__(message)
        self.identifier = identifier


@dataclass(frozen=True)
class CachedBinaryFile:
    """What :meth:`SessionWriter.database_openbinarydoc` returns.

    MATLAB returns ``struct('fullpathfilename', P)``; the lightsheet builders
    read ``f.fullpathfilename``. ``close`` does nothing (there is nothing
    open), so code written for a session's file object may call it.
    """

    fullpathfilename: str

    @property
    def name(self) -> str:
        """The local path, as a Python file object's ``name`` gives it."""
        return self.fullpathfilename

    def close(self) -> None:
        """Nothing to close."""


# ---------------------------------------------------------------------------
# ThreadSender -- MATLAB's CurlSender, from a thread pool
# ---------------------------------------------------------------------------

_UID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class ThreadSender:
    """Send a batch of files to pre-signed upload URLs in the background.

    MATLAB equivalent: ndi.cloud.upload.CurlSender (ported differently)

    ``S = ThreadSender(urls, paths, crcs, uids, folder, parallel=N)`` PUTs
    ``paths[i]`` to the pre-signed URL ``urls[i]``, signed with the CRC-32
    ``crcs[i]`` (:func:`ndi.fun.file.crc32`; ``""`` for none), *N* at a time
    (default 4), from a thread pool: the call returns at once and the caller
    carries on while the files go up.

    Each transfer is retried on a transient error (a lost connection, a 5xx
    or 429 answer) up to three times, as curl's ``--retry 3`` does, and gives
    up after 30 s connecting or 120 s with no data, as curl's stall limits
    do, so a send always ends.

    ``ok, msg, failed = S.wait(timeoutSeconds)``: *ok* is True when every uid
    got a 2xx answer; *failed* lists the uids that did not. Nothing is
    assumed from a good status: SessionWriter still checks each file's
    CRC-32 with NDI Cloud.

    ``S.delete()`` stops a send still running and removes the files named in
    *deleteAfter* (a zip made for the send).

    Args:
        urls: Pre-signed https upload URLs, one per file.
        paths: Local files, one per URL.
        crcs: CRC-32 per file ("" for none).
        uids: File uids, one per file (named in *failed*).
        folder: Kept for CurlSender's argument order (curl's config and log
            files go there); a thread pool needs none.
        parallel: Files sent at once. Default 4.
        deleteAfter: Files to remove on :meth:`delete`.
        session: Optional ``requests.Session``-like object (with ``put``)
            used by every thread instead of one session per thread. Tests
            pass a fake.
    """

    def __init__(
        self,
        urls: Sequence[str],
        paths: Sequence[str],
        crcs: Sequence[str],
        uids: Sequence[str],
        folder: str = "",
        *,
        parallel: int = 4,
        deleteAfter: Sequence[str] = (),
        session: Any = None,
    ):
        del folder
        n = len(paths)
        if len(urls) != n or len(crcs) != n or len(uids) != n:
            raise ValueError("URLS, PATHS, CRCS and UIDS must have one entry per file.")
        if int(parallel) < 1:
            raise ValueError("parallel must be a positive integer.")
        from .api._validators import assert_safe_transfer_url

        self.uids: list[str] = [str(u) for u in uids]
        self.deleteAfter: list[str] = [str(p) for p in deleteAfter]
        for i in range(n):
            assert_safe_transfer_url(str(urls[i]), what=f"upload URL {i + 1}")
            if not _UID_PATTERN.match(self.uids[i]):
                raise ValueError(f"Unexpected file uid '{self.uids[i]}'.")
        self._session = session
        self._local = threading.local()
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._status: dict[str, int] = {}
        self._errors: dict[str, str] = {}
        pool = ThreadPoolExecutor(max_workers=int(parallel), thread_name_prefix="ndi-upload")
        self._futures = [
            pool.submit(
                self._send_one, str(urls[i]), str(paths[i]), str(crcs[i] or ""), self.uids[i]
            )
            for i in range(n)
        ]
        pool.shutdown(wait=False)
        self._pool = pool

    # -- sending ------------------------------------------------------------

    def _http(self) -> Any:
        if self._session is not None:
            return self._session
        s = getattr(self._local, "session", None)
        if s is None:
            import requests

            s = requests.Session()
            self._local.session = s
        return s

    def _send_one(self, url: str, path: str, crc: str, uid: str) -> None:
        headers = {"Content-Type": "application/octet-stream", "Accept-Encoding": "identity"}
        if crc:
            headers["x-amz-checksum-crc32"] = crc
        wait = 1.0
        for attempt in range(4):
            if self._stopped.is_set():
                self._record(uid, 0, "stopped")
                return
            code, err = 0, ""
            try:
                with open(path, "rb") as fh:
                    resp = self._http().put(url, data=fh, headers=headers, timeout=(30, 120))
                code = int(getattr(resp, "status_code", 0) or 0)
                if not 200 <= code < 300:
                    err = f"HTTP {code}: {str(getattr(resp, 'text', ''))[:200]}"
            except Exception as exc:  # a lost connection, a stall, a missing file
                err = str(exc) or type(exc).__name__
            transient = code == 0 or code == 429 or code >= 500
            if not err or not transient or attempt == 3 or not os.path.isfile(path):
                self._record(uid, code, err)
                return
            _sleep(wait)
            wait *= 2

    def _record(self, uid: str, code: int, err: str) -> None:
        with self._lock:
            self._status[uid] = code
            if err:
                self._errors[uid] = err

    # -- CurlSender's interface ---------------------------------------------

    def isDone(self) -> bool:
        """Has every transfer finished (or been abandoned)?"""
        return all(f.done() for f in self._futures)

    def wait(self, timeoutSeconds: float | None = None) -> tuple[bool, str, list[str]]:
        """Wait for the send (stopping it after *timeoutSeconds*), then report.

        Returns ``(ok, msg, failed)``: *failed* lists the uids that did not
        get a 2xx answer.
        """
        timeout = (
            None if timeoutSeconds is None or timeoutSeconds == float("inf") else timeoutSeconds
        )
        _done, not_done = futures_wait(self._futures, timeout=timeout)
        finished = not not_done
        if not finished:
            self.stop()
        with self._lock:
            status = dict(self._status)
            errors = dict(self._errors)
        failed = [u for u in self.uids if not 200 <= status.get(u, 0) < 300]
        ok = finished and not failed
        msg = ""
        if not ok:
            if not finished:
                msg = f"the send did not finish within {timeoutSeconds:g} s"
            else:
                msg = f"{len(failed)} of {len(self.uids)} file(s) not sent"
            first = next((errors[u] for u in failed if u in errors), "")
            if first:
                msg = f"{msg} ({first[:300]})"
        return ok, msg, failed

    def stop(self) -> None:
        """End a send that is still running: nothing more is started.

        A PUT already in progress cannot be interrupted from another thread;
        it ends by itself (it is bounded by its timeouts) and its result is
        ignored.
        """
        self._stopped.set()
        for f in self._futures:
            f.cancel()

    def delete(self) -> None:
        """Stop the send and remove the files named in deleteAfter."""
        try:
            self.stop()
        except Exception:
            pass
        for p in self.deleteAfter:
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, dict):
        return [x]
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _props(doc: Any) -> dict:
    if isinstance(doc, dict):
        return doc
    return doc.document_properties


def _doc_id(doc: Any) -> str:
    """The id of an ndi_document (``id`` property), a DID document (``id()``),
    a property dict, or an id string."""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return str(doc.get("base", {}).get("id", ""))
    i = doc.id
    return str(i() if callable(i) else i)


def _class_name(doc: Any) -> str:
    return str(_props(doc).get("document_class", {}).get("class_name", ""))


def _series_info_of(doc: Any) -> list[dict]:
    files = _props(doc).get("files")
    if not isinstance(files, dict):
        return []
    return [s for s in _as_list(files.get("series_info")) if isinstance(s, dict)]


def _is_ingested_file(loc: dict) -> bool:
    """A location whose bytes a local session would copy in: those are the
    ones to send. A URL reference stays a reference."""
    return bool(loc.get("ingest")) and str(loc.get("location_type", "")).strip().lower() == "file"


def _describe(answer: Any) -> str:
    if isinstance(answer, dict) and "message" in answer:
        return str(answer["message"])
    if isinstance(answer, str):
        return answer
    msg = getattr(answer, "message", None)
    if msg is not None:
        return str(msg)
    try:
        import json

        return json.dumps(answer)
    except Exception:
        return type(answer).__name__


def _stripped(doc: Any) -> dict:
    """The document's JSON as a local session would store it: a deep copy
    with every series' ingest_locations emptied."""
    from did.document import Document

    return Document.strip_series_ingest_locations(copy.deepcopy(_props(doc)))


def _is_empty_session_id(sid: str) -> bool:
    if not sid:
        return True
    from ..session.session_base import empty_id

    return sid == empty_id()


def _stop_sender(batch: Any) -> None:
    """Stop and forget a batch's background send, if it has one."""
    sender = batch.get("sender") if isinstance(batch, dict) else None
    if sender is None:
        return
    for name in ("delete", "stop"):
        fn = getattr(sender, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            return


def _finalize(outstanding: list, cache_dir: str, keep: bool) -> None:
    for batch in outstanding:
        _stop_sender(batch)
    outstanding.clear()
    if not keep and cache_dir and os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# SessionWriter
# ---------------------------------------------------------------------------


class SessionWriter:
    """Add documents straight to a session of an NDI Cloud dataset.

    MATLAB equivalent: ndi.cloud.upload.SessionWriter

    ``W = SessionWriter(cloudDatasetId, sessionId)`` stands in for an
    ``ndi.session`` that lives in an NDI Cloud dataset::

        W = SessionWriter(cloud_dataset_id, session_id)
        ...  # a builder calls W.newdocument / W.database_add / W.declare ...
        report = W.commit()

    A DOCUMENT GOES TO A SESSION, NOT TO A DATASET. *sessionId* must be the
    id of a session in the dataset (one of its ``session_in_a_dataset``
    records); the constructor refuses anything else. Every document added
    gets that id as ``base.session_id``. :meth:`listSessions` lists the
    sessions a dataset has.

    WHAT IT DEPENDS ON MUST ALREADY BE THERE. A document's dependencies must
    be documents added through this writer or documents already in the
    cloud dataset; a ``subject_id`` must name a subject in this same session
    (:meth:`requireSubject`). Both are checked before any file is sent.

    FILES FIRST, CHECKED, THEN DOCUMENTS. :meth:`database_add` sends the
    document's files and file-series members at once, each under the uid
    DID gave it, then asks NDI Cloud for each file's recorded CRC-32 and
    compares it with the local one (or the size, when the cloud recorded no
    checksum). A file that is missing or differs is sent again on its own;
    one still wrong after that is an error. The document itself is held
    back until :meth:`commit`.

    STREAMING A FILE SERIES. A document whose series is built over hours is
    :meth:`declare`-d (uploaded at once with every member's uid in its
    manifest) and its members sent in batches (:meth:`streamMembers`). Each
    batch is checked at that document's next call, while the next is
    built; its local copies are deleted once it checks out unless retained
    (:meth:`releaseMembers` frees those). A file NDI Cloud has not recorded
    within *recordWait* seconds is rechecked at later batches and settled
    before COMMIT. :meth:`commit` checks that every declared member arrived.
    A resumed run uses :meth:`adopt` and :meth:`missingMembers`.

    SENDING IN THE BACKGROUND. A batch is sent from a thread pool
    (:class:`ThreadSender`), *parallelUploads* files at a time, while the
    caller builds the next batch; it is waited for when it is checked.
    With *parallelUploads* 1 the files are sent one by one (or, for at
    least *bulkThreshold* files, in zip batches), waiting.

    Keyword arguments (MATLAB's name-value options):
        verbose: print progress lines. Default True.
        zipBatches: send each batch of two or more files as one uncompressed
            zip through the bulk upload. Default: the preference
            ``Cloud.Upload.Send_Batches_As_Zip`` (False).
        parallelUploads: files a batch sends at once, in the background.
            Default: the preference ``Cloud.Upload.Parallel_Uploads`` (4).
        bulkThreshold: without a background send, a batch of at least this
            many files goes in zip batches rather than one by one. Default 20.
        recordWait: seconds a batch's check waits for NDI Cloud to record its
            files (default 15); later ones are rechecked later.
        uploadTimeout: seconds to wait for NDI Cloud to record one batch.
            None (default) scales with the number and size of the files.
        cacheDir: where local copies are kept. Default: a new temp folder.
        keepLocalCopies: keep *cacheDir* after commit (and on delete).
        retrySeconds: how long a failing cloud call is retried, waits growing
            from 2 s to 60 s. Default 1800. 0 retries nothing.
        onUpload: called with each document once it is in the cloud.
        api: the cloud calls to use (a dict; see :meth:`defaultApi`). Tests
            pass a fake.

    Public attributes (MATLAB's read-only properties): ``cloudDatasetId``,
    ``sessionId``, ``sessionReference``, ``cacheDir``, ``report`` (a dict
    with ``documents``, ``files``, ``bytes``, ``resent``, ``documentIds``),
    ``committed`` and ``timing`` (a dict of seconds spent: ``urls``,
    ``stage``, ``send``, ``verify``).
    """

    def __init__(
        self,
        cloudDatasetId: str,
        sessionId: str,
        *,
        verbose: bool = True,
        bulkThreshold: float = 20,
        uploadTimeout: float | None = None,
        parallelUploads: int | None = None,
        zipBatches: bool | None = None,
        cacheDir: str = "",
        keepLocalCopies: bool = False,
        retrySeconds: float = 1800,
        recordWait: float = 15,
        onUpload: Callable[[Any], None] | None = None,
        api: dict[str, Callable[..., Any]] | None = None,
    ):
        if not cloudDatasetId:
            raise ValueError("cloudDatasetId must be nonempty.")
        if not sessionId:
            raise ValueError("sessionId must be nonempty.")
        if bulkThreshold <= 0:
            raise ValueError("bulkThreshold must be positive.")
        if uploadTimeout is not None and uploadTimeout <= 0:
            raise ValueError("uploadTimeout must be positive.")
        if retrySeconds < 0:
            raise ValueError("retrySeconds must be nonnegative.")
        if recordWait <= 0:
            raise ValueError("recordWait must be positive.")
        if parallelUploads is not None and (
            int(parallelUploads) != parallelUploads or parallelUploads < 1
        ):
            raise ValueError("parallelUploads must be a positive integer.")

        if api is None:
            api = SessionWriter.defaultApi()
        api = _add_retries(dict(api), retrySeconds)

        # Public (MATLAB SetAccess = private).
        self.cloudDatasetId: str = str(cloudDatasetId)
        self.sessionId: str = ""
        self.sessionReference: str = ""
        self.cacheDir: str = ""
        self.report: dict[str, Any] = {
            "documents": 0,
            "files": 0,
            "bytes": 0,
            "resent": 0,
            "documentIds": [],
        }
        self.committed: bool = False
        self.timing: dict[str, float] = {"urls": 0.0, "stage": 0.0, "send": 0.0, "verify": 0.0}

        # Private.
        self._api = api
        self._onUpload = onUpload
        self._verbose = bool(verbose)
        self._bulkThreshold = float(bulkThreshold)
        self._uploadTimeout = uploadTimeout
        self._recordWait = float(recordWait)
        if parallelUploads is None:
            value: Any = 4
            try:
                from .. import preferences

                value = preferences.get("Cloud.Upload.Parallel_Uploads")
            except Exception:
                value = 4
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = 4
            if not value >= 1:
                value = 4
            self._parallelUploads = int(round(value))
        else:
            self._parallelUploads = int(parallelUploads)
        if zipBatches is None:
            try:
                from .. import preferences

                self._zipBatches = bool(preferences.get("Cloud.Upload.Send_Batches_As_Zip"))
            except Exception:
                self._zipBatches = False
        else:
            self._zipBatches = bool(zipBatches)
        self._keepLocalCopies = bool(keepLocalCopies)
        self._pendingDocs: list[Any] = []
        self._knownIds: set[str] = set()
        self._cloudIds: set[str] = set()
        self._fileUids: dict[str, str] = {}  # 'docid|filename' -> uid
        self._outstanding: list[dict] = []
        self._lagging: list[dict] = []
        self._warnedUrls = False
        self._declaredUids: dict[str, list[str]] = {}
        self._retainedPaths: dict[str, list[str]] = {}
        self._replaceAtCommit: list[Any] = []
        self._fresh: set[str] = set()
        self._checkedDocs: set[str] = set()

        sessions = SessionWriter.listSessions(self.cloudDatasetId, api=api)
        match = next((s for s in sessions if s["session_id"] == sessionId), None)
        if match is None:
            if not sessions:
                have = "It has no sessions."
            else:
                have = (
                    "Its sessions: "
                    + ", ".join(f"{s['session_reference']} ({s['session_id']})" for s in sessions)
                    + "."
                )
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:noSuchSession",
                f"{sessionId} is not a session of cloud dataset {cloudDatasetId}. Documents go "
                f"to a session in a dataset, not to the dataset itself. {have}",
            )
        self.sessionId = str(sessionId)
        self.sessionReference = str(match["session_reference"])

        self.cacheDir = str(cacheDir or "")
        if not self.cacheDir:
            from ..ido import ndi_ido

            self.cacheDir = os.path.join(tempfile.gettempdir(), f"ndi-cloud-session-{ndi_ido().id}")
        os.makedirs(self.cacheDir, exist_ok=True)
        # MATLAB's delete runs when the handle goes away; so does this.
        self._finalizer = weakref.finalize(
            self, _finalize, self._outstanding, self.cacheDir, self._keepLocalCopies
        )

    def __enter__(self) -> SessionWriter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.delete()

    def delete(self) -> None:
        """Stop sends still running and remove the cache (unless kept).

        MATLAB's destructor; also run when the writer is garbage-collected
        and on leaving a ``with`` block.
        """
        self._finalizer()

    # -- the part of ndi.session the builders use ---------------------------

    def id(self) -> str:
        """The id of the cloud session documents are added to."""
        return self.sessionId

    def newdocument(self, document_type: str = "base", **properties: Any) -> Any:
        """A new ndi_document in this session (as ndi.session/newdocument)."""
        from ..document import ndi_document

        properties["base.session_id"] = self.sessionId
        return ndi_document(document_type, **properties)

    def requireSubject(self, subjectId: str) -> None:
        """Error unless *subjectId* is a subject document in this session."""
        from ..query import ndi_query

        subjectId = str(subjectId)
        q = ndi_query("base.id", "exact_string", subjectId) & ndi_query("", "isa", "subject")
        docs = self._api["findDocuments"](self.cloudDatasetId, q)
        if not docs:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:noSubject",
                f"There is no subject {subjectId} in cloud dataset {self.cloudDatasetId}. Add "
                f"the subject to session {self.sessionReference} first.",
            )
        where = str(docs[0].get("base", {}).get("session_id", ""))
        if where != self.sessionId:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:subjectInOtherSession",
                f"Subject {subjectId} belongs to session {where}, not to session "
                f"{self.sessionReference} ({self.sessionId}). A document must depend on a "
                f"subject of its own session.",
            )
        self._cloudIds.add(subjectId)

    def requireDocument(self, docId: str) -> None:
        """Error unless *docId* was added here or is in the cloud dataset."""
        from ..query import ndi_query

        docId = str(docId)
        if docId in self._knownIds or docId in self._cloudIds:
            return
        docs = self._api["findDocuments"](
            self.cloudDatasetId, ndi_query("base.id", "exact_string", docId)
        )
        if not docs:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:missingDependency",
                f"Document {docId} is not in cloud dataset {self.cloudDatasetId}.",
            )
        self._cloudIds.add(docId)

    def database_add(self, document: Any) -> SessionWriter:
        """Send a document's files now, and hold the document for COMMIT.

        Like ndi.session/database_add, a document with no session id is
        given this one and a document from another session is refused.
        *document* may be a list.
        """
        if self.committed:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:alreadyCommitted",
                "This writer has already committed; make a new one.",
            )
        docs = list(document) if isinstance(document, (list, tuple)) else [document]
        for d in docs:
            self._addOne(d)
        return self

    def database_openbinarydoc(self, document: Any, filename: str) -> CachedBinaryFile:
        """The local copy of a file this writer sent.

        Returns a :class:`CachedBinaryFile` whose ``fullpathfilename`` is
        what the lightsheet builders read. A file no longer cached is
        downloaded first.
        """
        docId = _doc_id(document)
        key = f"{docId}|{filename}"
        if key not in self._fileUids:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:noSuchFile",
                f"No file {filename} was added through this writer for document {docId}.",
            )
        uid = self._fileUids[key]
        p = os.path.join(self.cacheDir, uid)
        if os.path.isfile(p) and uid not in self._fresh and docId not in self._checkedDocs:
            # Left by an earlier run (a resumed job): check it first.
            self._checkCachedCopies(docId)
        if not os.path.isfile(p):
            ok, msg = self._api["downloadFile"](self.cloudDatasetId, uid, p)
            if not ok or not os.path.isfile(p):
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:downloadFailed",
                    f"Could not download {filename} ({uid}) from the cloud: {_describe(msg)}",
                )
            self._fresh.add(uid)
        return CachedBinaryFile(p)

    def database_closebinarydoc(self, *args: Any) -> None:
        """Nothing to close; see database_openbinarydoc."""

    def commit(self) -> dict[str, Any]:
        """Finish: check what is outstanding, then upload the held documents.

        Batches still being checked are checked; the documents held by
        database_add are uploaded in the order added, as the JSON a local
        session would store (series member paths stripped). Every series
        member a declared document promises must then be in the cloud, or
        this is an error. Last, documents handed to replaceOnCommit replace
        their earlier versions. Returns :attr:`report`.
        """
        if self.committed:
            return self.report
        self._verifyOutstanding()
        self._flushPending()
        self._checkDeclaredMembers()
        for doc in self._replaceAtCommit:
            ok, answer = self._api["updateDocument"](
                self.cloudDatasetId, _doc_id(doc), _stripped(doc)
            )
            if not ok:
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:updateFailed",
                    f"Every file is in cloud dataset {self.cloudDatasetId}, but document "
                    f"{_doc_id(doc)} could not be updated to its final version: "
                    f"{_describe(answer)}",
                )
        self._replaceAtCommit = []
        self.committed = True
        self._say(
            f"Done: {self.report['documents']} document(s), {self.report['files']} file(s), "
            f"{self.report['bytes'] / 1e6:.1f} MB."
        )
        if not self._keepLocalCopies and os.path.isdir(self.cacheDir):
            shutil.rmtree(self.cacheDir, ignore_errors=True)
        return self.report

    # -- streaming ------------------------------------------------------------

    def declare(self, doc: Any) -> None:
        """Upload a document now, before its series members exist.

        DOC's ordinary files (a series' manifest among them) are sent and
        checked first, then DOC itself. Documents still held by
        database_add go up before it, in order. Its series members are
        recorded as promised; send them with streamMembers. COMMIT checks
        that all arrived.
        """
        if self.committed:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:alreadyCommitted",
                "This writer has already committed; make a new one.",
            )
        doc = self._ownSession(doc)
        self._checkDependencies(doc)
        self._flushPending()
        entries = SessionWriter._filesOf(doc, False)
        if entries:
            self._verifyBatch(self._stageAndSend(doc, entries, True))
        self._registerSeries(doc)
        self._addNow(doc, 1, 1)
        self._knownIds.add(_doc_id(doc))

    def adopt(self, doc: Any) -> None:
        """Take on a document an earlier run already put in the cloud.

        For resuming: DOC (as it was declared or added, series member uids
        included) is treated as uploaded -- a dependency other documents
        may name and, if it has a series, a declared document whose members
        streamMembers may send and COMMIT will check. Nothing is uploaded.
        """
        doc = self._ownSession(doc)
        self._registerSeries(doc)
        self._knownIds.add(_doc_id(doc))

    def missingMembers(self, doc: Any, seriesName: str) -> list[int]:
        """The members of a declared series the cloud does not have yet.

        Returns the one-based member indices whose uid the dataset does not
        report as uploaded. A resumed run builds only these.
        """
        si = next((s for s in _series_info_of(doc) if str(s.get("name")) == seriesName), None)
        if si is None:
            return []
        locs = [L for L in _as_list(si.get("ingest_locations")) if isinstance(L, dict)]
        if not locs:
            return []
        uids = [str(L.get("uid", "")) for L in locs]
        ok, answer = self._api["lookupFiles"](self.cloudDatasetId, uids)
        if not ok:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:lookupFailed",
                f"Could not look up files in cloud dataset {self.cloudDatasetId}: "
                f"{_describe(answer)}",
            )
        have = {str(r.get("uid")) for r in _rows(answer) if r.get("uploaded")}
        return [int(L["index"]) for L, u in zip(locs, uids) if u not in have]

    def streamMembers(
        self,
        doc: Any,
        seriesName: str,
        indices: Sequence[int],
        paths: Sequence[str],
        retain: bool = False,
    ) -> None:
        """Send some members of a declared document's series.

        ``paths[i]`` holds member ``indices[i]`` (one-based) of *seriesName*;
        it is moved into the cache and sent under the uid DOC's manifest gave
        that member. The batch is checked against the cloud at the NEXT call
        for this document (or at releaseMembers / commit). Once checked, the
        local copies are deleted, unless *retain*, in which case they stay
        readable through database_openbinarydoc until releaseMembers.
        """
        indices = [int(i) for i in _as_list(indices)]
        paths = [str(p) for p in _as_list(paths)]
        n = len(indices)
        if n == 0:
            # Nothing new: just check what is outstanding.
            self._verifyOutstanding()
            return
        if len(paths) != n:
            raise ValueError("INDICES and PATHS must have one entry per member.")
        docId = _doc_id(doc)
        entries = []
        for i in range(n):
            name = f"{seriesName}_{indices[i]}"
            key = f"{docId}|{name}"
            if key not in self._fileUids:
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:notDeclared",
                    f"Member {name} of document {docId} was not declared. DECLARE the "
                    f"document, with its whole series, first.",
                )
            entries.append(
                {"name": name, "uid": self._fileUids[key], "path": paths[i], "deleteOriginal": True}
            )
        self._outstanding.append(self._stageAndSend(doc, entries, bool(retain)))
        # Check this document's earlier batch, which has had the time since
        # its call to go up. Other documents' batches wait for their own next
        # call; a backstop keeps the number in flight bounded.
        k = 0
        while k < len(self._outstanding) - 1:
            if self._outstanding[k]["docId"] == docId or len(self._outstanding) > 8:
                batch = self._outstanding.pop(k)
                self._verifyBatch(batch)
            else:
                k += 1

    def releaseMembers(self, doc: Any) -> None:
        """Delete the local copies streamMembers kept for DOC."""
        self._verifyOutstanding()
        docId = _doc_id(doc)
        kept = self._retainedPaths.pop(docId, None)
        for p in kept or []:
            if os.path.isfile(p):
                os.remove(p)

    def replaceOnCommit(self, doc: Any) -> None:
        """At COMMIT, replace the cloud copy of DOC with this version.

        For a document uploaded early that should change once the work is
        done -- a pyramid labelled "(uploading)" until every chunk is in.
        """
        self._replaceAtCommit.append(doc)

    # -- private ---------------------------------------------------------------

    def _addOne(self, doc: Any) -> None:
        doc = self._ownSession(doc)
        self._checkDependencies(doc)
        entries = SessionWriter._filesOf(doc, True)
        if entries:
            # Kept locally until COMMIT: a builder may read them back.
            self._verifyBatch(self._stageAndSend(doc, entries, True))
        self._pendingDocs.append(doc)
        self._knownIds.add(_doc_id(doc))

    def _ownSession(self, doc: Any) -> Any:
        """As ndi.session/database_add: no session id gets this one, another
        session's is refused."""
        base = _props(doc).setdefault("base", {})
        sid = str(base.get("session_id", "") or "")
        if _is_empty_session_id(sid):
            base["session_id"] = self.sessionId
        elif sid != self.sessionId:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:wrongSession",
                f"Document {_doc_id(doc)} belongs to session {sid}, not to {self.sessionId}.",
            )
        return doc

    def _registerSeries(self, doc: Any) -> None:
        """Record a document's series member uids as promised (declare, adopt)."""
        docId = _doc_id(doc)
        promised: list[str] = []
        for si in _series_info_of(doc):
            for L in _as_list(si.get("ingest_locations")):
                if not isinstance(L, dict):
                    continue
                uid = str(L.get("uid", ""))
                self._fileUids[f"{docId}|{si.get('name')}_{int(L['index'])}"] = uid
                promised.append(uid)
        self._declaredUids[docId] = promised

    def _addNow(self, doc: Any, k: int, n: int) -> None:
        """Upload one document's JSON (series member paths stripped)."""
        ok, answer = self._api["addDocument"](self.cloudDatasetId, _stripped(doc))
        if not ok:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:addDocumentFailed",
                f"Could not add document {_doc_id(doc)} ({_class_name(doc)}) to cloud dataset "
                f"{self.cloudDatasetId}: {_describe(answer)}. {k - 1} of {n} documents were "
                f"added before it.",
            )
        self.report["documents"] += 1
        self.report["documentIds"].append(_doc_id(doc))
        if self._onUpload is not None:
            self._onUpload(doc)

    def _flushPending(self) -> None:
        """Upload the documents database_add held, in order."""
        n = len(self._pendingDocs)
        if n == 0:
            return
        self._say(
            f"Adding {n} document(s) to session {self.sessionReference} of cloud dataset "
            f"{self.cloudDatasetId} ..."
        )
        for k, doc in enumerate(self._pendingDocs, start=1):
            self._addNow(doc, k, n)
        self._pendingDocs = []

    def _verifyOutstanding(self) -> None:
        while self._outstanding:
            batch = self._outstanding.pop(0)
            self._verifyBatch(batch)
        self._checkLagging(True)

    def _checkLagging(self, force: bool) -> None:
        """Settle files the cloud had not recorded yet.

        Those now recorded with the right CRC-32 are done (their local copies
        deleted unless retained). One with the wrong bytes, or still missing
        after its upload timeout -- or, with FORCE, still missing after
        waiting out that timeout -- is sent again and must then check out.
        """
        if not self._lagging:
            return
        L = self._lagging
        uids = [x["uid"] for x in L]
        now = time.monotonic()
        wait = 0.0
        if force:
            wait = max(1.0, max(x["timeout"] - (now - x["since"]) for x in L))
        bad, late = self._unverified(uids, [x["bytes"] for x in L], [x["crc"] for x in L], wait)
        now = time.monotonic()
        expired = [now - x["since"] >= x["timeout"] for x in L]
        redo = [bad[i] and ((not late[i]) or expired[i] or force) for i in range(len(L))]
        if any(redo):
            idx = [i for i in range(len(L)) if redo[i]]
            self._say(
                f"{len(idx)} file(s) not recorded correctly by the cloud in time; sending "
                f"them again."
            )
            for i in idx:
                ok, msg = self._api["uploadSingleFile"](self.cloudDatasetId, uids[i], L[i]["path"])
                if not ok:
                    self._say(f"Sending {uids[i]} again failed ({_describe(msg)}).")
            self.report["resent"] += len(idx)
            stillBad, _ = self._unverified(
                [uids[i] for i in idx],
                [L[i]["bytes"] for i in idx],
                [L[i]["crc"] for i in idx],
                max(L[i]["timeout"] for i in idx),
            )
            if any(stillBad):
                first = idx[stillBad.index(True)]
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:uploadNotVerified",
                    f"{sum(stillBad)} file(s) of {L[first]['label']} could not be verified in "
                    f"cloud dataset {self.cloudDatasetId} after sending them twice (first: "
                    f"{uids[first]}, local {L[first]['path']}).",
                )
        settled = [(not bad[i]) or redo[i] for i in range(len(L))]
        for i in range(len(L)):
            if settled[i] and not L[i]["retain"] and os.path.isfile(L[i]["path"]):
                os.remove(L[i]["path"])
        self._lagging = [L[i] for i in range(len(L)) if not settled[i]]

    def _checkDeclaredMembers(self) -> None:
        """Every member a declared document promises must be in the cloud."""
        for docId, uids in self._declaredUids.items():
            if not uids:
                continue
            ok, answer = self._api["lookupFiles"](self.cloudDatasetId, uids)
            if not ok:
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:lookupFailed",
                    f"Could not look up files in cloud dataset {self.cloudDatasetId}: "
                    f"{_describe(answer)}",
                )
            have = {str(r.get("uid")) for r in _rows(answer) if r.get("uploaded")}
            nMissing = len(set(uids) - have)
            if nMissing > 0:
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:membersMissing",
                    f"{nMissing} of the {len(uids)} series members document {docId} declares "
                    f"are not in cloud dataset {self.cloudDatasetId}.",
                )

    def _checkDependencies(self, doc: Any) -> None:
        for dep in _as_list(_props(doc).get("depends_on")):
            if not isinstance(dep, dict):
                continue
            value = str(dep.get("value", "") or "")
            if not value or value in self._knownIds or value in self._cloudIds:
                continue
            if dep.get("name") == "subject_id":
                self.requireSubject(value)
            else:
                self.requireDocument(value)

    def _stageAndSend(self, doc: Any, entries: list[dict], retain: bool) -> dict:
        """Move ENTRIES into the cache under their uids and send them.

        In the background (each file CRC-32-signed) when it can; otherwise
        zip batches for many files, or one by one. Returns what _verifyBatch
        needs; nothing is checked here.
        """
        from ..fun.file import crc32

        n = len(entries)
        t0 = time.monotonic()
        paths = [self._stage(e) for e in entries]
        nbytes = [os.path.getsize(p) for p in paths]
        crcs = [crc32(p) for p in paths]
        self.timing["stage"] += time.monotonic() - t0
        uids = [e["uid"] for e in entries]
        label = f"{_class_name(doc)} {_doc_id(doc)}"
        sending = os.path.join(self.cacheDir, "sending")
        sender = None
        how = ""
        if self._zipBatches and n >= 2 and "startZipSend" in self._api:
            t0 = time.monotonic()
            try:
                sender = self._api["startZipSend"](self.cloudDatasetId, uids, paths, sending)
            except Exception as exc:
                self._say(f"Could not send the batch as a zip ({exc}); sending its files.")
                sender = None
            self.timing["stage"] += time.monotonic() - t0
            if sender is not None:
                how = " (as one zip, in the background)"
        if sender is None:
            sender = self._startBackgroundSend(uids, paths, crcs)
            if sender is not None:
                how = f" ({self._parallelUploads} at a time, in the background)"
        mb = sum(nbytes) / 1e6
        if sender is not None:
            self._say(f"Sending {n} file(s), {mb:.1f} MB, for {label}{how} ...")
        elif n >= self._bulkThreshold:
            self._say(f"Sending {n} file(s), {mb:.1f} MB, for {label} (in zip batches) ...")
            t0 = time.monotonic()
            ok, msg = self._api["uploadFileBatch"](self.cloudDatasetId, paths, nbytes)
            self.timing["send"] += time.monotonic() - t0
            if not ok:
                # Not fatal yet: whatever did not arrive is sent again one by
                # one when the batch is checked.
                self._say(f"A zip batch failed ({_describe(msg)}); checking what arrived.")
        else:
            self._say(f"Sending {n} file(s), {mb:.1f} MB, for {label} ...")
            t0 = time.monotonic()
            for i in range(n):
                ok, msg = self._api["uploadSingleFile"](self.cloudDatasetId, uids[i], paths[i])
                if not ok:
                    self._say(f"Sending {uids[i]} failed ({_describe(msg)}); will retry.")
            self.timing["send"] += time.monotonic() - t0
        return {
            "docId": _doc_id(doc),
            "label": label,
            "names": [e["name"] for e in entries],
            "uids": uids,
            "paths": paths,
            "bytes": nbytes,
            "crcs": crcs,
            "retain": retain,
            "sender": sender,
        }

    def _startBackgroundSend(self, uids: list[str], paths: list[str], crcs: list[str]) -> Any:
        """Start a background send of a batch, or None.

        None when the API cannot (a fake without it, parallelUploads 1) or a
        signed upload URL could not be had; the caller then sends the files
        one by one.
        """
        if (
            self._parallelUploads < 2
            or "startSend" not in self._api
            or "uploadURL" not in self._api
        ):
            return None
        n = len(uids)
        urls: list[str] = [""] * n
        sending = os.path.join(self.cacheDir, "sending")
        t0 = time.monotonic()
        try:
            got = False
            if "uploadURLs" in self._api:
                # All at once (ndi.cloud.signed_upload_urls.signedUploadURLs).
                try:
                    got, many, why = self._api["uploadURLs"](
                        self.cloudDatasetId, uids, crcs, sending, 8
                    )
                except Exception as exc:
                    got, many, why = False, [], str(exc)
                if got:
                    urls = [str(u) for u in many]
                elif not self._warnedUrls:
                    self._say(
                        f"Asking for upload URLs all at once did not work ({_describe(why)}); "
                        f"asking one at a time."
                    )
                    self._warnedUrls = True
            if not got:
                for i in range(n):
                    ok, url = self._api["uploadURL"](self.cloudDatasetId, uids[i], crcs[i])
                    if not ok:
                        self._say(
                            f"Could not get an upload URL for {uids[i]} ({_describe(url)}); "
                            f"sending one by one."
                        )
                        return None
                    urls[i] = str(url)
        finally:
            self.timing["urls"] += time.monotonic() - t0
        try:
            return self._api["startSend"](urls, paths, crcs, uids, sending, self._parallelUploads)
        except Exception as exc:
            self._say(f"Could not start a background send ({exc}); sending one by one.")
            return None

    def _verifyBatch(self, batch: dict) -> None:
        """Check a sent batch against the cloud, resend what is wrong.

        A file that is missing or whose CRC-32 (or size) differs is sent
        again on its own; one still wrong after that is an error. Then the
        batch's local copies are deleted unless it is retained.
        """
        uids, paths = batch["uids"], batch["paths"]
        nbytes, crcs = batch["bytes"], batch["crcs"]
        n = len(uids)
        timeout = self._uploadTimeout
        if timeout is None:
            timeout = max(120.0, 30 + 0.05 * n + sum(nbytes) / 5e6)
        failedNow = [False] * n
        sender = batch.get("sender")
        if sender is not None:
            # Sent in the background: let it finish first.
            t0 = time.monotonic()
            ok, msg, failed = sender.wait(max(600.0, sum(nbytes) / 1e5))
            self.timing["send"] += time.monotonic() - t0
            _stop_sender(batch)
            if not ok:
                # The files the send names as not sent will not turn up:
                # send them again now. A failed zip (uid 'zip') means all.
                failed = [str(f) for f in _as_list(failed)]
                if "zip" in failed:
                    failedNow = [True] * n
                else:
                    failedNow = [u in failed for u in uids]
                self._say(
                    f"The background send of {batch['label']} reported a problem "
                    f"({_describe(msg)}); sending {sum(failedNow)} file(s) again, checking the "
                    f"rest."
                )
        t0 = time.monotonic()
        try:
            for i in range(n):
                if failedNow[i]:
                    okOne, msgOne = self._api["uploadSingleFile"](
                        self.cloudDatasetId, uids[i], paths[i]
                    )
                    if not okOne:
                        self._say(f"Sending {uids[i]} again failed ({_describe(msgOne)}).")
            self.report["resent"] += sum(failedNow)
            self._checkLagging(False)
            # NDI Cloud records a stored file a moment later, now and then
            # minutes later. Wait RECORDWAIT for that, not the whole timeout:
            # what is still unrecorded is checked again at later batches.
            quick = min(timeout, self._recordWait)
            bad, late = self._unverified(uids, nbytes, crcs, quick)
            deferred = [False] * n
            if quick < timeout and any(late):
                deferred = list(late)
                since = time.monotonic()
                for i in range(n):
                    if late[i]:
                        self._lagging.append(
                            {
                                "uid": uids[i],
                                "path": paths[i],
                                "bytes": nbytes[i],
                                "crc": crcs[i],
                                "retain": batch["retain"],
                                "since": since,
                                "timeout": timeout,
                                "label": batch["label"],
                            }
                        )
                bad = [bad[i] and not late[i] for i in range(n)]
            if any(bad):
                idx = [i for i in range(n) if bad[i]]
                self._say(
                    f"{len(idx)} of {n} file(s) missing or different in the cloud; sending them "
                    f"again."
                )
                for i in idx:
                    ok, msg = self._api["uploadSingleFile"](self.cloudDatasetId, uids[i], paths[i])
                    if not ok:
                        self._say(f"Sending {uids[i]} again failed ({_describe(msg)}).")
                self.report["resent"] += len(idx)
                stillBad, _ = self._unverified(
                    [uids[i] for i in idx],
                    [nbytes[i] for i in idx],
                    [crcs[i] for i in idx],
                    timeout,
                )
                if any(stillBad):
                    first = idx[stillBad.index(True)]
                    raise SessionWriterError(
                        "NDI:cloud:SessionWriter:uploadNotVerified",
                        f"{sum(stillBad)} file(s) of {batch['label']} could not be verified in "
                        f"cloud dataset {self.cloudDatasetId} after sending them twice (first: "
                        f"{uids[first]}, local {paths[first]}).",
                    )
        finally:
            self.timing["verify"] += time.monotonic() - t0

        for i in range(n):
            self._fileUids[f"{batch['docId']}|{batch['names'][i]}"] = uids[i]
        self.report["files"] += n
        self.report["bytes"] += sum(nbytes)

        if batch["retain"]:
            self._retainedPaths.setdefault(batch["docId"], []).extend(paths)
        else:
            for i in range(n):
                if not deferred[i] and os.path.isfile(paths[i]):
                    os.remove(paths[i])

    def _unverified(
        self, uids: list[str], nbytes: list[int], crcs: list[str], timeout: float
    ) -> tuple[list[bool], list[bool]]:
        """True for each uid the cloud lacks or holds different bytes for.

        LATE: of those, the ones the cloud has not recorded as uploaded at
        all (rather than recorded with other bytes). TIMEOUT 0 asks once,
        without waiting.
        """
        if timeout > 0:
            self._api["waitForFileUpload"](self.cloudDatasetId, uids, timeout)
        ok, answer = self._api["lookupFiles"](self.cloudDatasetId, uids)
        if not ok:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:lookupFailed",
                f"Could not look up uploaded files in cloud dataset {self.cloudDatasetId}: "
                f"{_describe(answer)}",
            )
        rows = {}
        for r in _rows(answer):
            rows.setdefault(str(r.get("uid")), r)
        bad = [True] * len(uids)
        late = [True] * len(uids)
        for i, u in enumerate(uids):
            r = rows.get(u)
            if r is None or not r.get("uploaded"):
                continue
            late[i] = False
            cloudCrc = str(r.get("crc32") or "")
            if not cloudCrc:
                bad[i] = float(r.get("size") or 0) != float(nbytes[i])
            else:
                bad[i] = cloudCrc != crcs[i]
        return bad, late

    def _checkCachedCopies(self, docId: str) -> None:
        """The cached files of DOCID an earlier run left, against the cloud.

        A cached file this writer did not write is from an earlier run of a
        resumed job; a power cut can leave one present but short. So, once
        per document, each one's size is compared with the size NDI Cloud
        recorded for that uid; a file that differs, or that the cloud does
        not have, is deleted, and is downloaded when it is read.
        """
        self._checkedDocs.add(docId)
        prefix = f"{docId}|"
        uids: list[str] = []
        sizes: list[int] = []
        for key, u in self._fileUids.items():
            if not key.startswith(prefix):
                continue
            pu = os.path.join(self.cacheDir, u)
            if u not in self._fresh and os.path.isfile(pu):
                uids.append(u)
                sizes.append(os.path.getsize(pu))
        nBad = 0
        for s in range(0, len(uids), 1000):
            part = range(s, min(s + 1000, len(uids)))
            ok, answer = self._api["lookupFiles"](self.cloudDatasetId, [uids[i] for i in part])
            rows = {}
            if ok and isinstance(answer, dict):
                for r in _rows(answer):
                    rows.setdefault(str(r.get("uid")), r)
            for i in part:
                r = rows.get(uids[i])
                good = (
                    r is not None
                    and bool(r.get("uploaded"))
                    and float(r.get("size") or -1) == float(sizes[i])
                )
                if good:
                    self._fresh.add(uids[i])
                else:
                    # Unknown to the cloud, a lookup that failed, or the
                    # wrong size: fetch it again when it is read.
                    try:
                        os.remove(os.path.join(self.cacheDir, uids[i]))
                    except OSError:
                        pass
                    nBad += 1
        if nBad > 0:
            self._say(
                f"{nBad} cached file(s) of {docId} from an earlier run did not match the "
                f"cloud; they will be downloaded when read."
            )

    def _stage(self, entry: dict) -> str:
        """Put one file into the cache under its uid.

        A file already cached under the uid stays only if there is no new
        one to take its place (one an earlier run left is replaced).
        """
        p = os.path.join(self.cacheDir, entry["uid"])
        src = str(entry["path"])
        if os.path.isfile(p) and (
            os.path.abspath(src) == os.path.abspath(p) or not os.path.isfile(src)
        ):
            return p
        if not os.path.isfile(src):
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:fileNotFound",
                f"File {entry['name']} ({entry['uid']}) is not at {src}.",
            )
        try:
            if entry["deleteOriginal"]:
                shutil.move(src, p)
            else:
                shutil.copyfile(src, p)
        except OSError as exc:
            raise SessionWriterError(
                "NDI:cloud:SessionWriter:stageFailed", f"Could not copy {src} to {p}: {exc}"
            ) from exc
        self._fresh.add(entry["uid"])
        return p

    def _say(self, message: str) -> None:
        if self._verbose:
            print(f"[SessionWriter] {message}", flush=True)

    # -- static ------------------------------------------------------------------

    @staticmethod
    def writeStoredZip(zipPath: str, paths: Sequence[str], names: Sequence[str]) -> None:
        """A zip of PATHS as NAMES, without compressing them.

        The chunks are compressed already; deflating them again would cost
        CPU per batch for nothing. Entries are written ZIP_STORED.
        """
        with zipfile.ZipFile(zipPath, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for p, name in zip(paths, names):
                z.write(str(p), arcname=str(name))

    @staticmethod
    def listSessions(cloudDatasetId: str, *, api: dict | None = None) -> list[dict[str, str]]:
        """The sessions in a cloud dataset.

        Returns a list of dicts with keys ``session_id`` and
        ``session_reference``, from the dataset's ``session_in_a_dataset``
        documents (and an older dataset's ``dataset_session_info``).
        """
        from ..query import ndi_query

        if api is None:
            api = SessionWriter.defaultApi()
        sessions: list[dict[str, str]] = []
        for d in api["findDocuments"](cloudDatasetId, ndi_query("", "isa", "session_in_a_dataset")):
            s = d.get("session_in_a_dataset", {})
            sessions.append(
                {
                    "session_id": str(s.get("session_id", "")),
                    "session_reference": str(s.get("session_reference", "")),
                }
            )
        for d in api["findDocuments"](cloudDatasetId, ndi_query("", "isa", "dataset_session_info")):
            info = d.get("dataset_session_info", {}).get("dataset_session_info", [])
            for item in _as_list(info):
                for s in _as_list(item):
                    if isinstance(s, dict):
                        sessions.append(
                            {
                                "session_id": str(s.get("session_id", "")),
                                "session_reference": str(s.get("session_reference", "")),
                            }
                        )
        seen: set[str] = set()
        unique = []
        for s in sessions:
            if s["session_id"] not in seen:
                seen.add(s["session_id"])
                unique.append(s)
        return unique

    @staticmethod
    def listSubjects(
        cloudDatasetId: str, sessionId: str, *, api: dict | None = None
    ) -> list[dict[str, str]]:
        """The subjects in one session of a cloud dataset.

        Returns a list of dicts with keys ``id`` and ``local_identifier``.
        """
        from ..query import ndi_query

        if api is None:
            api = SessionWriter.defaultApi()
        q = ndi_query("", "isa", "subject") & ndi_query(
            "base.session_id", "exact_string", sessionId
        )
        return [
            {
                "id": str(d.get("base", {}).get("id", "")),
                "local_identifier": str(d.get("subject", {}).get("local_identifier", "")),
            }
            for d in api["findDocuments"](cloudDatasetId, q)
        ]

    @staticmethod
    def defaultApi(*, client: Any = None) -> dict[str, Callable[..., Any]]:
        """The NDI Cloud calls a SessionWriter makes.

        A dict of callables (MATLAB: a struct of function handles), each
        answering as MATLAB's does:

        * ``findDocuments(datasetId, query)`` -> list of document property dicts
        * ``addDocument(datasetId, props)`` -> ``(ok, answer)``
        * ``uploadSingleFile(datasetId, uid, path)`` -> ``(ok, msg)`` (CRC-32 signed)
        * ``uploadFileBatch(datasetId, paths, bytes)`` -> ``(ok, msg)`` (zip batches)
        * ``uploadURL(datasetId, uid, crc)`` -> ``(ok, url)`` (signed for CRC)
        * ``uploadURLs(datasetId, uids, crcs, folder, n)`` -> ``(ok, urls, msg)``
        * ``startSend(urls, paths, crcs, uids, folder, n)`` -> a sender with
          ``wait(timeout) -> (ok, msg, failed)`` (:class:`ThreadSender`)
        * ``startZipSend(datasetId, uids, paths, folder)`` -> a sender for one
          zip of the files through the bulk upload
        * ``waitForFileUpload(datasetId, uids, timeout)`` -> ``(ok, answer)``
        * ``lookupFiles(datasetId, uids)`` -> ``(ok, answer)``
        * ``downloadFile(datasetId, uid, path)`` -> ``(ok, msg)``
        * ``updateDocument(datasetId, ndiId, props)`` -> ``(ok, answer)``

        Args:
            client: An authenticated CloudClient for every call. Default: one
                made from the environment at the first call, and reused.
        """
        holder: dict[str, Any] = {"client": client}
        lock = threading.Lock()

        def get_client() -> Any:
            with lock:
                if holder["client"] is None:
                    from .client import CloudClient

                    holder["client"] = CloudClient.from_env()
                return holder["client"]

        orgs: dict[str, str] = {}

        def org_of(d: str) -> str:
            if d not in orgs:
                from .internal import _datasetOrganizationId

                orgs[d] = _datasetOrganizationId(d, client=get_client())
            return orgs[d]

        def pair(fn: Callable[[], Any]) -> tuple[bool, Any]:
            try:
                return True, fn()
            except Exception as exc:
                return False, {"message": str(exc)}

        def find_documents(d: str, q: Any) -> list[dict]:
            from .api import documents as docs_api

            try:
                hits = docs_api.ndiqueryAll(str(d), q, client=get_client())
            except Exception as exc:
                raise SessionWriterError(
                    "NDI:cloud:SessionWriter:queryFailed",
                    f"Could not search cloud dataset {d}: {exc}",
                ) from exc
            hits = list(getattr(hits, "data", hits) or [])
            ids = [str(h.get("id")) for h in hits if isinstance(h, dict) and h.get("id")]
            out: list[dict] = []
            for first in range(0, len(ids), 500):
                try:
                    fetched = docs_api.bulkFetch(
                        str(d), ids[first : first + 500], client=get_client()
                    )
                except Exception as exc:
                    raise SessionWriterError(
                        "NDI:cloud:SessionWriter:fetchFailed",
                        f"Could not read documents from cloud dataset {d}: {exc}",
                    ) from exc
                out.extend(f.get("data", {}) for f in fetched if isinstance(f, dict))
            return out

        def add_document(d: str, props: dict) -> tuple[bool, Any]:
            from .api import documents as docs_api

            return pair(lambda: docs_api.addDocument(str(d), props, client=get_client()))

        def upload_single_file(d: str, uid: str, p: str) -> tuple[bool, str]:
            from .upload import uploadSingleFile

            return uploadSingleFile(str(d), str(uid), str(p), checksum=True, client=get_client())

        def upload_file_batch(d: str, paths: list[str], nbytes: list[int]) -> tuple[bool, str]:
            from .upload import zipForUpload

            manifest = [
                {"file_uid": os.path.basename(p), "file_path": p, "bytes": b}
                for p, b in zip(paths, nbytes)
            ]
            try:
                r = zipForUpload(manifest, str(d), client=get_client())
            except Exception as exc:
                return False, str(exc)
            return (not r.get("failed")), "; ".join(str(e) for e in r.get("errors", []))

        def upload_url(d: str, uid: str, crc: str) -> tuple[bool, Any]:
            from .api import files as files_api

            return pair(
                lambda: files_api.getFileUploadURL(
                    org_of(str(d)),
                    str(d),
                    str(uid),
                    checksum_crc32=str(crc or ""),
                    client=get_client(),
                )
            )

        def upload_urls(
            d: str, uids: list[str], crcs: list[str], folder: str, n: int
        ) -> tuple[bool, list[str], str]:
            from .signed_upload_urls import signedUploadURLs

            return signedUploadURLs(str(d), uids, crcs, folder, parallel=n, client=get_client())

        def start_send(urls, paths, crcs, uids, folder, n) -> ThreadSender:
            return ThreadSender(urls, paths, crcs, uids, folder, parallel=n)

        def start_zip_send(d: str, uids: list[str], paths: list[str], folder: str) -> ThreadSender:
            from ..ido import ndi_ido
            from .api import files as files_api

            os.makedirs(folder, exist_ok=True)
            zip_path = os.path.join(folder, f"batch-{ndi_ido().id}.zip")
            SessionWriter.writeStoredZip(zip_path, paths, uids)
            try:
                info = files_api.getFileCollectionUploadURL(
                    org_of(str(d)), str(d), client=get_client()
                )
                url = str(info.get("url", ""))
                if not url:
                    raise SessionWriterError(
                        "NDI:cloud:SessionWriter:noBulkURL", "No bulk upload URL came back."
                    )
                return ThreadSender(
                    [url], [zip_path], [""], ["zip"], folder, parallel=1, deleteAfter=[zip_path]
                )
            except Exception:
                if os.path.isfile(zip_path):
                    os.remove(zip_path)
                raise

        def lookup_files(d: str, uids: list[str]) -> tuple[bool, Any]:
            from .api import files as files_api

            return pair(lambda: files_api.lookupFiles(str(d), list(uids), client=get_client()))

        def wait_for_file_upload(d: str, uids: list[str], timeout: float) -> tuple[bool, Any]:
            from .api import files as files_api

            try:
                answer = files_api.waitForFileUpload(
                    str(d), list(uids), timeout=float(timeout), client=get_client()
                )
            except Exception as exc:
                return False, str(exc)
            return answer.get("state") == "complete", answer

        def download_file(d: str, uid: str, p: str) -> tuple[bool, str]:
            from .api import files as files_api

            try:
                details = files_api.getFileDetails(str(d), str(uid), client=get_client())
                url = str(details.get("downloadUrl", "") if isinstance(details, dict) else "")
                if not url:
                    return False, "no download URL"
                err: dict = {}
                if files_api.getFile(url, p, error_out=err):
                    return True, ""
                return False, _describe(err) if err else "download failed"
            except Exception as exc:
                return False, str(exc)

        def update_document(d: str, ndiId: str, props: dict) -> tuple[bool, Any]:
            from ..query import ndi_query
            from .api import documents as docs_api

            try:
                hits = docs_api.ndiqueryAll(
                    str(d), ndi_query("base.id", "exact_string", str(ndiId)), client=get_client()
                )
            except Exception as exc:
                return False, {"message": str(exc)}
            hits = list(getattr(hits, "data", hits) or [])
            if not hits:
                return False, {"message": f"document {ndiId} not found"}
            return pair(
                lambda: docs_api.updateDocument(
                    str(d), str(hits[0]["id"]), props, client=get_client()
                )
            )

        return {
            "findDocuments": find_documents,
            "addDocument": add_document,
            "uploadSingleFile": upload_single_file,
            "uploadFileBatch": upload_file_batch,
            "uploadURL": upload_url,
            "uploadURLs": upload_urls,
            "startSend": start_send,
            "startZipSend": start_zip_send,
            "waitForFileUpload": wait_for_file_upload,
            "lookupFiles": lookup_files,
            "downloadFile": download_file,
            "updateDocument": update_document,
        }

    # MATLAB's private _filesOf is a static method too.
    @staticmethod
    def _filesOf(doc: Any, includeMembers: bool) -> list[dict]:
        """The files (and, if INCLUDEMEMBERS, series members) a document
        carries for ingestion."""
        entries: list[dict] = []
        files = _props(doc).get("files")
        if not isinstance(files, dict):
            return entries
        for fi in _as_list(files.get("file_info")):
            if not isinstance(fi, dict):
                continue
            for L in _as_list(fi.get("locations")):
                if isinstance(L, dict) and _is_ingested_file(L):
                    entries.append(
                        {
                            "name": str(fi.get("name", "")),
                            "uid": str(L.get("uid", "")),
                            "path": str(L.get("location", "")),
                            "deleteOriginal": bool(L.get("delete_original")),
                        }
                    )
        if includeMembers:
            for si in _series_info_of(doc):
                locs = [L for L in _as_list(si.get("ingest_locations")) if isinstance(L, dict)]
                if not locs:
                    n_present = si.get("n_present")
                    if isinstance(n_present, (int, float)) and n_present > 0:
                        raise SessionWriterError(
                            "NDI:cloud:SessionWriter:membersNotLocatable",
                            f"Document {_doc_id(doc)} declares {int(n_present)} members of "
                            f"file series {si.get('name')} but records where none of them are.",
                        )
                    continue
                stem = str(si.get("name", ""))
                for L in locs:
                    if _is_ingested_file(L):
                        entries.append(
                            {
                                "name": f"{stem}_{int(L['index'])}",
                                "uid": str(L.get("uid", "")),
                                "path": str(L.get("location", "")),
                                "deleteOriginal": bool(L.get("delete_original")),
                            }
                        )
        return entries


def _rows(answer: Any) -> list[dict]:
    """The ``files`` rows of a lookupFiles answer."""
    if not isinstance(answer, dict):
        return []
    return [r for r in _as_list(answer.get("files")) if isinstance(r, dict)]


# ---------------------------------------------------------------------------
# Retries (MATLAB's addRetries / retryPair / retryOne / retryAdd)
# ---------------------------------------------------------------------------


def _add_retries(api: dict, seconds: float) -> dict:
    """Wrap each cloud call so a failure is retried for up to SECONDS.

    A long upload meets a dropped connection or a server hiccup sooner or
    later; this rides one out instead of failing hours of work.
    waitForFileUpload is left alone: it already waits, and its timeout is an
    answer.
    """
    if seconds <= 0:
        return api
    raw = dict(api)
    for name in (
        "uploadSingleFile",
        "uploadFileBatch",
        "uploadURL",
        "lookupFiles",
        "downloadFile",
        "updateDocument",
    ):
        if name in raw:
            api[name] = _retry_pair(raw[name], seconds, name)
    if "findDocuments" in raw:
        api["findDocuments"] = _retry_one(raw["findDocuments"], seconds)
    if "addDocument" in raw:
        api["addDocument"] = _retry_add(raw, seconds)
    return api


def _retry_pair(fn: Callable, seconds: float, name: str) -> Callable:
    def call(*args: Any) -> tuple[bool, Any]:
        t0 = time.monotonic()
        wait = 2.0
        while True:
            try:
                ok, answer = fn(*args)
            except Exception as exc:
                ok, answer = False, {"message": str(exc)}
            if ok or time.monotonic() - t0 + wait > seconds:
                return ok, answer
            print(
                f"[SessionWriter] {name} failed ({_describe(answer)}); trying again in "
                f"{wait:g} s.",
                flush=True,
            )
            _sleep(wait)
            wait = min(60.0, 2 * wait)

    return call


def _retry_one(fn: Callable, seconds: float) -> Callable:
    def call(*args: Any) -> Any:
        t0 = time.monotonic()
        wait = 2.0
        while True:
            try:
                return fn(*args)
            except Exception as exc:
                if time.monotonic() - t0 + wait > seconds:
                    raise
                print(
                    f"[SessionWriter] a cloud search failed ({exc}); trying again in {wait:g} s.",
                    flush=True,
                )
            _sleep(wait)
            wait = min(60.0, 2 * wait)

    return call


def _retry_add(raw: dict, seconds: float) -> Callable:
    """addDocument, retried -- but only after asking whether the last try
    arrived anyway, so a lost reply never becomes a duplicate document."""

    def call(d: str, props: dict) -> tuple[bool, Any]:
        from ..query import ndi_query

        t0 = time.monotonic()
        wait = 2.0
        doc_id = ""
        try:
            doc_id = str(props["base"]["id"])
        except Exception:
            pass
        while True:
            try:
                ok, answer = raw["addDocument"](d, props)
            except Exception as exc:
                ok, answer = False, {"message": str(exc)}
            if ok or time.monotonic() - t0 + wait > seconds:
                return ok, answer
            print(
                f"[SessionWriter] addDocument failed ({_describe(answer)}); trying again in "
                f"{wait:g} s.",
                flush=True,
            )
            _sleep(wait)
            wait = min(60.0, 2 * wait)
            if doc_id:
                try:
                    if raw["findDocuments"](d, ndi_query("base.id", "exact_string", doc_id)):
                        return True, {"message": "already there"}
                except Exception:
                    pass

    return call
