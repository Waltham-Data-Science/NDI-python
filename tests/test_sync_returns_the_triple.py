"""The sync entry points return ``(success, errorMessage, report)``.

MATLAB's five all do::

    [success, errorMessage, report] = ndi.cloud.sync.uploadNew(ds, opts)

This side returned the report alone, so the one question a scripted caller
most wants to ask -- did it work? -- had to be reconstructed from report
fields whose names differ per mode.

WHAT MAKES ``success`` FALSE. NDI-matlab ``29546720b`` is the precedent, and
its commit message is the argument:

    "A scripted pipeline checking only `success` believed the dataset was
     mirrored when zero documents transferred."

It made a partial document upload raise rather than report a clean mirror.
The same reasoning applies to a partial DOWNLOAD, which MATLAB still calls a
success -- the silent-loss shape ``7efa0a8a0`` fixed on the index side
without revisiting the flag. So here, anything that did not transfer makes
``success`` false in either direction: stricter than MATLAB for the two
download modes, and never wrong.
"""

from __future__ import annotations

import pytest

import ndi.cloud.internal as internal
import ndi.cloud.sync.operations as ops
from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncMode, SyncOptions

from .conftest import FakeDataset, make_document

CLOUD_ID = "65a1b2c3d4e5f60718293a4b"
ALL_MODES = ["uploadNew", "downloadNew", "mirrorToRemote", "mirrorFromRemote", "twoWaySync"]


@pytest.fixture(autouse=True)
def _no_bulk_settling(monkeypatch):
    monkeypatch.setattr(ops, "_settle_bulk_uploads", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _quiet_api(monkeypatch):
    from ndi.cloud.api import documents as docs_api

    monkeypatch.setattr(docs_api, "addDocument", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(docs_api, "deleteDocument", lambda *a, **k: {"ok": True})


def _remote(monkeypatch, ids=()):
    monkeypatch.setattr(
        internal, "listRemoteDocumentIds", lambda cid, client=None: {i: i for i in ids}
    )


class TestTheShapeIsTheSameEverywhere:
    @pytest.mark.parametrize("operation", ALL_MODES)
    def test_a_clean_run_returns_true_and_no_message(self, tmp_path, monkeypatch, operation):
        _remote(monkeypatch, [])
        ds = FakeDataset(tmp_path, [make_document("doc-A")])

        success, message, report = getattr(ops, operation)(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert success is True
        assert message == ""
        assert isinstance(report, dict) and report["mode"]

    @pytest.mark.parametrize("operation", ALL_MODES)
    def test_a_dry_run_succeeds(self, tmp_path, monkeypatch, operation):
        """It inspected both sides and changed nothing, which is what it was
        asked to do."""
        _remote(monkeypatch, ["remote-only"])
        ds = FakeDataset(tmp_path, [make_document("local-only")])

        success, message, report = getattr(ops, operation)(
            ds, CLOUD_ID, SyncOptions(dry_run=True, verbose=False)
        )

        assert success is True
        assert message == ""
        assert report["dry_run"] is True


class TestAPartialUploadIsNotASuccess:
    """NDI-matlab 29546720b, stated as an assertion."""

    @pytest.fixture
    def one_document_fails(self, monkeypatch):
        from ndi.cloud.api import documents as docs_api

        def add(cloud_id, doc, *, client=None):
            if doc["base"]["id"] == "bad":
                raise RuntimeError("server rejected it")
            return {"ok": True}

        monkeypatch.setattr(docs_api, "addDocument", add)

    @pytest.mark.parametrize("operation", ["uploadNew", "mirrorToRemote", "twoWaySync"])
    def test_success_is_false_and_the_message_says_the_index_was_not_updated(
        self, tmp_path, monkeypatch, one_document_fails, operation
    ):
        _remote(monkeypatch, [])
        ds = FakeDataset(tmp_path, [make_document("good"), make_document("bad")])

        success, message, report = getattr(ops, operation)(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert success is False
        assert "sync index not updated" in message
        assert report["failed"] == ["bad"]
        # The report still says what DID move -- a partial result is not no result.
        assert report["uploaded_document_ids"] == ["good"]

    @pytest.mark.parametrize("operation", ["uploadNew", "mirrorToRemote", "twoWaySync"])
    def test_the_index_is_not_written(self, tmp_path, monkeypatch, one_document_fails, operation):
        """MATLAB aborts before its index write: uploadNew returns early with
        "sync index not updated", and the two mirrors raise
        NDI:Cloud:Sync:UploadIncomplete so every later phase is skipped."""
        _remote(monkeypatch, [])
        seed = SyncIndex()
        seed.update(["seeded"], ["seeded"])
        seed.write(tmp_path)
        ds = FakeDataset(tmp_path, [make_document("good"), make_document("bad")])

        success, _msg, _report = getattr(ops, operation)(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert success is False
        after = SyncIndex.read(tmp_path)
        assert after.local_doc_ids_last_sync == ["seeded"]
        assert after.remote_doc_ids_last_sync == ["seeded"]

    def test_the_remote_deletions_are_skipped_too(self, tmp_path, monkeypatch, one_document_fails):
        """mirrorToRemote's deletions come after its upload in MATLAB, so the
        raise skips them. Deleting the remote's copies while the local ones
        have not all arrived is how a half-finished mirror loses documents
        outright."""
        from ndi.cloud.api import documents as docs_api

        _remote(monkeypatch, ["remote-only"])
        deleted: list[str] = []
        monkeypatch.setattr(
            docs_api,
            "deleteDocument",
            lambda cid, api_id, **k: (deleted.append(api_id), {"ok": True})[1],
        )
        ds = FakeDataset(tmp_path, [make_document("good"), make_document("bad")])

        success, _msg, _report = ops.mirrorToRemote(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert success is False
        assert deleted == []


class TestAPartialDownloadIsNotASuccessEither:
    """Stricter than MATLAB, and for the reason MATLAB fixed on the upload
    side: a caller checking only the flag must not be told a short download
    was a complete one."""

    @pytest.mark.parametrize("operation", ["downloadNew", "mirrorFromRemote", "twoWaySync"])
    def test_a_missing_document_makes_it_false(self, tmp_path, monkeypatch, operation):
        _remote(monkeypatch, ["arrives", "does-not"])
        monkeypatch.setattr(
            ops,
            "downloadNdiDocuments",
            lambda cid, ndi_to_api, ids, *, client=None: (
                [{**make_document("arrives"), "ndiId": "arrives"}],
                ["does-not"],
            ),
        )
        ds = FakeDataset(tmp_path)

        success, message, report = getattr(ops, operation)(ds, CLOUD_ID, SyncOptions(verbose=False))

        assert success is False
        assert "does-not" in message
        assert report["downloaded_document_ids"] == ["arrives"]

    def test_a_document_that_could_not_be_saved_counts_too(self, tmp_path, monkeypatch):
        """It arrived and was then dropped, which is a loss like any other."""
        _remote(monkeypatch, ["doc-A"])
        monkeypatch.setattr(
            ops,
            "downloadNdiDocuments",
            lambda cid, ndi_to_api, ids, *, client=None: (
                [{"_id": "api-A", "payload": "no usable id"}],
                [],
            ),
        )

        success, message, _report = ops.downloadNew(
            FakeDataset(tmp_path), CLOUD_ID, SyncOptions(verbose=False)
        )

        assert success is False
        assert "could not be saved" in message


class TestAFailureThatStopsTheRun:
    def test_an_api_error_comes_back_through_the_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            internal,
            "listRemoteDocumentIds",
            lambda cid, client=None: (_ for _ in ()).throw(RuntimeError("cloud is down")),
        )

        success, message, report = ops.uploadNew(
            FakeDataset(tmp_path), CLOUD_ID, SyncOptions(verbose=False)
        )

        assert success is False
        assert message == "cloud is down"
        assert report["mode"] == "upload_new"

    def test_a_caller_mistake_still_raises(self, tmp_path):
        """Passing a path is a bug in the caller, not an outcome of a sync.
        Swallowing it into success=False would make every misuse look like a
        cloud problem."""
        from ndi.cloud.exceptions import CloudSyncError

        with pytest.raises(CloudSyncError, match="take an ndi.dataset, not a path"):
            ops.uploadNew(str(tmp_path), CLOUD_ID, SyncOptions(verbose=False))


class TestTheDispatcherPassesItThrough:
    def test_sync_returns_the_same_triple(self, tmp_path, monkeypatch):
        _remote(monkeypatch, [])
        ds = FakeDataset(tmp_path, [make_document("doc-A")])

        success, message, report = ops.sync(
            ds, CLOUD_ID, SyncMode.UPLOAD_NEW, SyncOptions(verbose=False)
        )

        assert (success, message) == (True, "")
        assert report["uploaded_document_ids"] == ["doc-A"]


class TestTheGuiReportsAPartialSyncAsAFailure:
    """The pane used to infer the outcome from report fields, so a sync that
    moved three of fifty documents was announced as a success."""

    def test_a_partial_sync_is_not_announced_as_done(self, monkeypatch):
        import ndi.cloud.sync as sync_module
        import ndi.gui.nav.datasets_cloud as dc

        monkeypatch.setattr(dc, "resolve_cloud_target", lambda ds: "cid")
        monkeypatch.setattr(
            sync_module,
            "uploadNew",
            lambda ds, cid: (False, "1 document(s) did not transfer: bad", {"uploaded": ["good"]}),
            raising=False,
        )

        result = dc.sync_dataset(object(), "upload_new")

        assert result.ok is False
        assert result.icon == "error"
        assert "did not transfer" in result.message
        # and it still says what moved
        assert "1 document uploaded" in result.message

    def test_a_clean_sync_still_reads_as_success(self, monkeypatch):
        import ndi.cloud.sync as sync_module
        import ndi.gui.nav.datasets_cloud as dc

        monkeypatch.setattr(dc, "resolve_cloud_target", lambda ds: "cid")
        monkeypatch.setattr(
            sync_module, "uploadNew", lambda ds, cid: (True, "", {"uploaded": ["a"]}), raising=False
        )

        result = dc.sync_dataset(object(), "upload_new")

        assert result.ok is True
        assert result.icon == "success"
