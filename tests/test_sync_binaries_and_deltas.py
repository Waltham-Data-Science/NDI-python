"""Two things that only became reachable once sync took a dataset.

Both follow from NDI-python#232, and neither is a consequence of the
signature change so much as something the old signature had been HIDING.

1. ``uploadFilesForDatasetDocuments`` read a document's binaries from
   top-level ``file_uid`` / ``file_path``. A real ``ndi.document`` carries
   neither -- its files live under ``files.file_info[].locations[]`` -- so
   the pass matched nothing and uploaded nothing, silently, because a
   document with no recognised file looks exactly like a document with no
   files.

2. ``twoWaySync`` read ``current_local`` and ``last_local`` from the same
   field of the same index, so ``added_local`` and ``deleted_local`` were
   empty by construction. With them went half the conflict detection and the
   whole "deleted locally, so delete it on the remote" branch.
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


@pytest.fixture(autouse=True)
def _no_bulk_settling(monkeypatch):
    monkeypatch.setattr(ops, "_settle_bulk_uploads", lambda *a, **k: None)


class _Config:
    org_id = "org-1"


class _Client:
    config = _Config()


def _document_with_file(tmp_path, doc_id, uid, filename, *, location=None):
    path = tmp_path / filename
    path.write_bytes(b"data")
    return make_document(
        doc_id,
        files={
            "file_info": [
                {
                    "name": filename,
                    "locations": [{"uid": uid, "location": location or str(path)}],
                }
            ]
        },
    )


class TestTheCanonicalDocumentShapeIsRead:
    """MATLAB counterpart: ``+ndi/+cloud/+sync/+internal/uploadFilesForDatasetDocuments.m``."""

    def test_a_real_document_yields_its_uid_and_path(self, tmp_path):
        doc = _document_with_file(tmp_path, "doc-A", "uid-A", "a.bin")
        assert upload.file_uploads_for_document(doc) == [("uid-A", str(tmp_path / "a.bin"))]

    def test_the_manifest_shape_still_works(self, tmp_path):
        """The shape that DID work must keep working."""
        path = tmp_path / "m.bin"
        path.write_bytes(b"data")
        doc = {"ndiId": "doc-A", "file_uid": "uid-A", "file_path": str(path)}
        assert upload.file_uploads_for_document(doc) == [("uid-A", str(path))]

    def test_several_files_on_one_document_all_come_back(self, tmp_path):
        for name in ("a.bin", "b.bin"):
            (tmp_path / name).write_bytes(b"data")
        doc = make_document(
            "doc-A",
            files={
                "file_info": [
                    {
                        "name": "a.bin",
                        "locations": [{"uid": "uid-a", "location": str(tmp_path / "a.bin")}],
                    },
                    {
                        "name": "b.bin",
                        "locations": [{"uid": "uid-b", "location": str(tmp_path / "b.bin")}],
                    },
                ]
            },
        )
        assert upload.file_uploads_for_document(doc) == [
            ("uid-a", str(tmp_path / "a.bin")),
            ("uid-b", str(tmp_path / "b.bin")),
        ]

    def test_a_cloud_location_is_not_something_to_upload(self, tmp_path):
        """``ndic://`` means the file is already on the cloud."""
        doc = _document_with_file(
            tmp_path, "doc-A", "uid-A", "a.bin", location=f"ndic://{CLOUD_ID}/uid-A"
        )
        assert upload.file_uploads_for_document(doc) == []

    def test_a_missing_file_is_not_offered(self, tmp_path):
        doc = make_document(
            "doc-A",
            files={
                "file_info": [
                    {
                        "name": "gone.bin",
                        "locations": [{"uid": "uid-A", "location": str(tmp_path / "gone.bin")}],
                    }
                ]
            },
        )
        assert upload.file_uploads_for_document(doc) == []

    def test_a_document_with_no_files_yields_nothing(self):
        assert upload.file_uploads_for_document(make_document("doc-A")) == []


class TestUploadNewSendsBinariesAtAll:
    """It sent none. mirrorToRemote had a binary pass; uploadNew and
    twoWaySync did not, so "Upload New to Cloud" uploaded no data."""

    @pytest.fixture
    def uploads(self, monkeypatch):
        from ndi.cloud.api import documents as docs_api
        from ndi.cloud.api import files as files_api

        sent: list[str] = []
        monkeypatch.setattr(docs_api, "addDocument", lambda *a, **k: {"ok": True})
        monkeypatch.setattr(internal, "listRemoteDocumentIds", lambda cid, client=None: {})
        monkeypatch.setattr(
            files_api,
            "getFileUploadURL",
            lambda org, ds, uid, client=None: f"https://bucket.example.com/{uid}?sig=1",
        )
        monkeypatch.setattr(
            files_api, "putFiles", lambda url, path, **k: (sent.append(path), True)[1]
        )
        return sent

    @pytest.mark.parametrize("operation", ["uploadNew", "twoWaySync", "mirrorToRemote"])
    def test_the_binary_is_uploaded(self, tmp_path, uploads, operation):
        ds = FakeDataset(tmp_path, [_document_with_file(tmp_path, "doc-A", "uid-A", "a.bin")])

        getattr(ops, operation)(
            ds, CLOUD_ID, SyncOptions(sync_files=True, verbose=False), client=_Client()
        )

        assert uploads == [str(tmp_path / "a.bin")]

    def test_sync_files_off_sends_nothing(self, tmp_path, uploads):
        ds = FakeDataset(tmp_path, [_document_with_file(tmp_path, "doc-A", "uid-A", "a.bin")])
        ops.uploadNew(ds, CLOUD_ID, SyncOptions(sync_files=False, verbose=False), client=_Client())
        assert uploads == []


class TestTwoWaySyncLocalDeltasAreLive:
    @pytest.fixture
    def api(self, monkeypatch):
        from ndi.cloud.api import documents as docs_api

        deleted: list[str] = []
        monkeypatch.setattr(docs_api, "addDocument", lambda *a, **k: {"ok": True})
        monkeypatch.setattr(
            docs_api,
            "deleteDocument",
            lambda cid, api_id, **k: (deleted.append(api_id), {"ok": True})[1],
        )
        return deleted

    def test_a_document_deleted_locally_is_deleted_on_the_remote(self, tmp_path, monkeypatch, api):
        """``deleted_local`` was always empty, so this branch never ran."""
        index = SyncIndex()
        index.update(["kept", "removed"], ["kept", "removed"])
        index.write(tmp_path)
        monkeypatch.setattr(
            internal,
            "listRemoteDocumentIds",
            lambda cid, client=None: {"kept": "kept", "removed": "removed"},
        )
        ds = FakeDataset(tmp_path, [make_document("kept")])

        report = ops.twoWaySync(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert report["deleted_remote_document_ids"] == ["removed"]
        assert api == ["removed"]

    def test_a_document_added_on_both_sides_is_a_conflict(self, tmp_path, monkeypatch, api):
        """Conflict detection needs ``added_local``, which was always empty."""
        index = SyncIndex()
        index.update(["old"], ["old"])
        index.write(tmp_path)
        monkeypatch.setattr(
            internal,
            "listRemoteDocumentIds",
            lambda cid, client=None: {"old": "old", "both": "both"},
        )
        ds = FakeDataset(tmp_path, [make_document("old"), make_document("both")])

        report = ops.twoWaySync(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert report["conflicts"] == ["both"]
        assert report["uploaded_document_ids"] == []
        assert report["downloaded_document_ids"] == []

    def test_a_document_added_only_locally_is_uploaded(self, tmp_path, monkeypatch, api):
        index = SyncIndex()
        index.update(["old"], ["old"])
        index.write(tmp_path)
        monkeypatch.setattr(
            internal, "listRemoteDocumentIds", lambda cid, client=None: {"old": "old"}
        )
        ds = FakeDataset(tmp_path, [make_document("old"), make_document("mine")])

        report = ops.twoWaySync(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert report["uploaded_document_ids"] == ["mine"]
        assert report["deleted_remote_document_ids"] == []
