"""A sync upload sends the document, not just its id -- NDI-python#232.

All three upload-side sync operations posted this::

    docs_api.addDocument(cloud_dataset_id, {"ndiId": doc_id}, client=client)

``addDocument`` POSTs its second argument as the request body, so what
reached the cloud was a document with one field: no ``base``, no
``document_class``, none of its properties. The call SUCCEEDED. The remote
then listed the id, so every later ``listRemoteDocumentIds`` saw it as
present and no run ever sent it again; the sync index recorded it as synced;
nothing reported a problem. A dataset "uploaded" this way is metadata-shaped
holes on the cloud.

The operations could not have done better: they took ``dataset_path: str``
and worked from the sync index's id lists, and an id list has no document
contents in it. They take an ``ndi.dataset`` now, which is the only thing
that can answer "what are my documents".

These are the tests that would have failed against the old code. Every one
of them asserts on the BODY that reached the API.
"""

from __future__ import annotations

import pytest

import ndi.cloud.internal as internal
import ndi.cloud.sync.operations as ops
from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncOptions

from .conftest import FakeDataset, make_document

CLOUD_ID = "65a1b2c3d4e5f60718293a4b"


@pytest.fixture(autouse=True)
def _no_bulk_settling(monkeypatch):
    monkeypatch.setattr(ops, "_settle_bulk_uploads", lambda *a, **k: None)


@pytest.fixture
def posted(monkeypatch):
    """Every document body handed to addDocument, in order."""
    from ndi.cloud.api import documents as docs_api

    bodies: list[dict] = []

    def record(cloud_id, doc, *, client=None):
        bodies.append(doc)
        return {"ok": True}

    monkeypatch.setattr(docs_api, "addDocument", record)
    monkeypatch.setattr(docs_api, "deleteDocument", lambda *a, **k: {"ok": True})
    return bodies


def _remote(monkeypatch, ids=()):
    monkeypatch.setattr(
        internal, "listRemoteDocumentIds", lambda cid, client=None: {i: i for i in ids}
    )


def _dataset_with(tmp_path, *doc_ids, **extra):
    return FakeDataset(tmp_path, [make_document(i, **extra) for i in doc_ids])


class TestTheDocumentItselfIsSent:
    """The bug, stated as an assertion, for each of the three upload paths."""

    @pytest.mark.parametrize("operation", ["uploadNew", "mirrorToRemote", "twoWaySync"])
    def test_the_body_is_the_document_not_an_id(self, tmp_path, monkeypatch, posted, operation):
        _remote(monkeypatch, [])
        ds = _dataset_with(tmp_path, "doc-A")

        getattr(ops, operation)(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert len(posted) == 1
        body = posted[0]
        assert body == make_document("doc-A")
        # The shape of the old bug, named so a regression is unmistakable.
        assert body != {"ndiId": "doc-A"}
        assert "base" in body and body["base"]["id"] == "doc-A"
        assert "document_class" in body

    def test_every_property_survives(self, tmp_path, monkeypatch, posted):
        """Not just base -- whatever the document carries is what is sent."""
        _remote(monkeypatch, [])
        ds = FakeDataset(
            tmp_path,
            [make_document("doc-A", subject={"local_identifier": "mouse-1"}, extra=[1, 2, 3])],
        )

        ops.uploadNew(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert posted[0]["subject"] == {"local_identifier": "mouse-1"}
        assert posted[0]["extra"] == [1, 2, 3]

    def test_only_the_documents_the_remote_lacks_are_sent(self, tmp_path, monkeypatch, posted):
        _remote(monkeypatch, ["have-it"])
        ds = _dataset_with(tmp_path, "have-it", "new-one")

        report = ops.uploadNew(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert [b["base"]["id"] for b in posted] == ["new-one"]
        assert report["uploaded_document_ids"] == ["new-one"]


class TestLocalMeansTheDatasetNowConsultsItself:
    """ "Local" used to mean "whatever the index last wrote down"."""

    def test_a_document_added_since_the_last_sync_is_found(self, tmp_path, monkeypatch, posted):
        """The index says the last sync saw nothing; the dataset has one.
        Reading the index would upload nothing at all."""
        SyncIndex().write(tmp_path)
        _remote(monkeypatch, [])
        ds = _dataset_with(tmp_path, "added-later")

        report = ops.uploadNew(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert report["uploaded_document_ids"] == ["added-later"]
        assert [b["base"]["id"] for b in posted] == ["added-later"]

    def test_a_failed_upload_is_retried_next_run(self, tmp_path, monkeypatch):
        """Selection is against a live remote listing, not the index, so a
        document that failed before is still missing and still sent."""
        from ndi.cloud.api import documents as docs_api

        _remote(monkeypatch, [])
        ds = _dataset_with(tmp_path, "flaky")
        monkeypatch.setattr(
            docs_api,
            "addDocument",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rejected")),
        )
        first = ops.uploadNew(ds, CLOUD_ID, SyncOptions(verbose=False))
        assert first["uploaded_document_ids"] == []
        assert first["failed"] == ["flaky"]

        sent: list[dict] = []
        monkeypatch.setattr(
            docs_api, "addDocument", lambda cid, doc, **k: (sent.append(doc), {"ok": True})[1]
        )
        second = ops.uploadNew(ds, CLOUD_ID, SyncOptions(verbose=False))
        assert second["uploaded_document_ids"] == ["flaky"]
        assert [d["base"]["id"] for d in sent] == ["flaky"]


class TestAPathIsRefusedWithTheReason:
    """The old signature took a path. Failing loudly beats half-working:
    a path cannot supply document contents, which is the whole bug."""

    @pytest.mark.parametrize(
        "operation",
        ["uploadNew", "downloadNew", "mirrorToRemote", "mirrorFromRemote", "twoWaySync"],
    )
    def test_passing_a_path_says_what_to_do_instead(self, tmp_path, operation):
        from ndi.cloud.exceptions import CloudSyncError

        with pytest.raises(CloudSyncError, match="take an ndi.dataset, not a path"):
            getattr(ops, operation)(str(tmp_path), CLOUD_ID, SyncOptions(verbose=False))

    def test_a_pathlib_path_is_refused_too(self, tmp_path):
        from ndi.cloud.exceptions import CloudSyncError

        with pytest.raises(CloudSyncError, match="NDI-python#232"):
            ops.uploadNew(tmp_path, CLOUD_ID, SyncOptions(verbose=False))


class TestTheCloudIdIsResolvedLikeMatlab:
    """MATLAB's sync functions take no cloud id -- they read it from the
    dataset's dataset_remote document. Passing one stays supported."""

    def test_an_empty_id_is_resolved_from_the_dataset(self, tmp_path, monkeypatch, posted):
        monkeypatch.setattr(
            internal, "getCloudDatasetIdForLocalDataset", lambda ds, client=None: (CLOUD_ID, {})
        )
        seen: list[str] = []
        monkeypatch.setattr(
            internal,
            "listRemoteDocumentIds",
            lambda cid, client=None: (seen.append(cid), {})[1],
        )
        ops.uploadNew(_dataset_with(tmp_path, "doc-A"), options=SyncOptions(verbose=False))
        assert seen == [CLOUD_ID]

    def test_an_unlinked_dataset_says_so(self, tmp_path, monkeypatch):
        from ndi.cloud.exceptions import CloudSyncError

        monkeypatch.setattr(
            internal, "getCloudDatasetIdForLocalDataset", lambda ds, client=None: ("", None)
        )
        with pytest.raises(CloudSyncError, match="not linked to a cloud dataset"):
            ops.uploadNew(_dataset_with(tmp_path, "doc-A"), options=SyncOptions(verbose=False))
