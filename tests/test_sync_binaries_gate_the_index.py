"""A document whose binary never uploaded is not a synced document.

MATLAB counterpart: ``+ndi/+cloud/+sync/uploadNew.m`` and
``+ndi/+cloud/+upload/zipForUpload.m``, NDI-matlab ``8c31a8f28``
(NDI-matlab#805).

MATLAB's ``uploadNew`` discarded the return codes from both the document
upload and the binary upload and then wrote the sync index anyway, so a
document could be recorded as uploaded with its binary never sent. Every
downstream reader -- export, mirror, ``twoWaySync`` -- then gets a 404,
and nothing in the index says to try again.

Two thirds of that already held here. ``uploadNew`` and ``mirrorToRemote``
record only the IDs whose ``addDocument`` actually returned, so a failed
metadata upload never enters the index, and ``filesNotYetUploaded`` reads
the remote's ``uploaded`` flag rather than assuming a listed file arrived.

The binary half did not. ``mirrorToRemote`` uploaded files inside a
``try``/``except`` that logged and moved on -- and
``uploadFilesForDatasetDocuments`` does not raise on a per-file failure, it
returns a count, so the except clause could not see the ordinary case at
all. The documents went into the index as synced regardless.
"""

from __future__ import annotations

import pytest

import ndi.cloud.internal as internal
import ndi.cloud.sync.operations as ops
import ndi.cloud.upload as upload
from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncOptions

from .conftest import FakeDataset, make_document

CLOUD_ID = "65a1b2c3d4e5f60718293a4b"


class _Config:
    org_id = "org-1"


class _Client:
    config = _Config()


def _dataset(tmp_path, doc_ids):
    """A dataset holding documents that each carry one binary on disk."""
    documents = []
    for doc_id in doc_ids:
        (tmp_path / f"{doc_id}.bin").write_bytes(b"data")
        documents.append(
            make_document(
                doc_id,
                file_uid=f"uid-{doc_id}",
                file_path=str(tmp_path / f"{doc_id}.bin"),
            )
        )
    index = SyncIndex.read(tmp_path)
    index.update(list(doc_ids), [])
    index.write(tmp_path)
    return FakeDataset(tmp_path, documents)


@pytest.fixture(autouse=True)
def no_bulk_settling(monkeypatch):
    """Every sync entry point waits for outstanding bulk uploads first. That
    wait has its own test file; here it would only be a network to mock."""
    monkeypatch.setattr(ops, "_settle_bulk_uploads", lambda *a, **k: None)


@pytest.fixture
def empty_remote(monkeypatch):
    monkeypatch.setattr(internal, "listRemoteDocumentIds", lambda cid, client=None: {})


@pytest.fixture
def documents_upload(monkeypatch):
    from ndi.cloud.api import documents as docs_api

    monkeypatch.setattr(docs_api, "addDocument", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(docs_api, "deleteDocument", lambda *a, **k: {"ok": True})


def _binaries(monkeypatch, failing):
    """Fail getFileUploadURL for the named documents' UIDs."""
    from ndi.cloud.api import files as files_api

    failing_uids = {f"uid-{d}" for d in failing}

    def _url(org, ds, uid, client=None):
        if uid in failing_uids:
            raise RuntimeError(f"S3 refused {uid}")
        return "https://bucket.example.com/put?sig=1"

    monkeypatch.setattr(files_api, "getFileUploadURL", _url)
    monkeypatch.setattr(files_api, "putFiles", lambda *a, **k: True)


class TestTheFileReportNamesTheDocuments:
    """A count cannot be acted on; the caller needs the IDs."""

    def test_a_failed_binary_names_its_document(self, monkeypatch, tmp_path):
        _binaries(monkeypatch, {"b"})
        docs = [
            {"ndiId": "a", "file_uid": "uid-a", "file_path": str(tmp_path / "a")},
            {"ndiId": "b", "file_uid": "uid-b", "file_path": str(tmp_path / "b")},
        ]
        (tmp_path / "a").write_bytes(b"x")
        (tmp_path / "b").write_bytes(b"x")
        report = upload.uploadFilesForDatasetDocuments("org-1", CLOUD_ID, docs, client=_Client())
        assert report["uploaded"] == 1
        assert report["failed"] == 1
        assert report["failed_document_ids"] == ["b"]

    def test_a_clean_run_names_nobody(self, monkeypatch, tmp_path):
        _binaries(monkeypatch, set())
        (tmp_path / "a").write_bytes(b"x")
        report = upload.uploadFilesForDatasetDocuments(
            "org-1",
            CLOUD_ID,
            [{"ndiId": "a", "file_uid": "uid-a", "file_path": str(tmp_path / "a")}],
            client=_Client(),
        )
        assert report["failed_document_ids"] == []

    def test_a_document_identified_only_by_base_id_is_still_named(self, monkeypatch, tmp_path):
        """Documents arrive here both ways -- from the cloud with an ndiId,
        from disk with base.id -- and an unnamed failure is one the caller
        cannot exclude."""
        _binaries(monkeypatch, {"c"})
        (tmp_path / "c").write_bytes(b"x")
        report = upload.uploadFilesForDatasetDocuments(
            "org-1",
            CLOUD_ID,
            [{"base": {"id": "c"}, "file_uid": "uid-c", "file_path": str(tmp_path / "c")}],
            client=_Client(),
        )
        assert report["failed_document_ids"] == ["c"]


class TestMirrorToRemoteWithholdsThem:
    def test_a_document_whose_binary_failed_is_not_in_the_index(
        self, monkeypatch, tmp_path, empty_remote, documents_upload
    ):
        ds = _dataset(tmp_path, ["a", "b"])
        _binaries(monkeypatch, {"b"})

        report = ops.mirrorToRemote(ds, CLOUD_ID, SyncOptions(sync_files=True), client=_Client())

        assert sorted(report["uploaded_document_ids"]) == ["a", "b"]
        assert report["failed"] == ["b"]
        assert set(SyncIndex.read(tmp_path).remote_doc_ids_last_sync) == {"a"}

    def test_a_clean_run_records_both(self, monkeypatch, tmp_path, empty_remote, documents_upload):
        ds = _dataset(tmp_path, ["a", "b"])
        _binaries(monkeypatch, set())

        report = ops.mirrorToRemote(ds, CLOUD_ID, SyncOptions(sync_files=True), client=_Client())

        assert report["failed"] == []
        assert set(SyncIndex.read(tmp_path).remote_doc_ids_last_sync) == {"a", "b"}

    def test_the_whole_file_pass_falling_over_withholds_everything(
        self, monkeypatch, tmp_path, empty_remote, documents_upload
    ):
        """Not one file failing -- the call itself raising. Nothing in that
        batch can be claimed to have uploaded."""
        ds = _dataset(tmp_path, ["a", "b"])

        def _boom(*a, **k):
            raise RuntimeError("connection reset")

        monkeypatch.setattr(upload, "uploadFilesForDatasetDocuments", _boom)

        report = ops.mirrorToRemote(ds, CLOUD_ID, SyncOptions(sync_files=True), client=_Client())

        assert sorted(report["failed"]) == ["a", "b"]
        assert SyncIndex.read(tmp_path).remote_doc_ids_last_sync == []

    def test_the_failure_is_logged_with_its_document_ids(
        self, monkeypatch, tmp_path, empty_remote, documents_upload, caplog
    ):
        ds = _dataset(tmp_path, ["a", "b"])
        _binaries(monkeypatch, {"b"})
        with caplog.at_level("WARNING", logger="ndi.cloud.sync.operations"):
            ops.mirrorToRemote(ds, CLOUD_ID, SyncOptions(sync_files=True), client=_Client())
        assert "without" in caplog.text
        assert "b" in caplog.text

    def test_without_sync_files_nothing_changes(
        self, monkeypatch, tmp_path, empty_remote, documents_upload
    ):
        """sync_files=False means binaries were never part of the promise, so
        the documents are as synced as they were asked to be."""
        ds = _dataset(tmp_path, ["a", "b"])
        _binaries(monkeypatch, {"a", "b"})

        report = ops.mirrorToRemote(ds, CLOUD_ID, SyncOptions(sync_files=False), client=_Client())

        assert report["failed"] == []
        assert set(SyncIndex.read(tmp_path).remote_doc_ids_last_sync) == {"a", "b"}
