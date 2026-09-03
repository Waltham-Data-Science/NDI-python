"""
The sync index must not advance past failures -- NDI-python issue #101 (4).

``<dataset>/.ndi/sync/index.json`` is a record of what sync accomplished.
Recording a document that was never fetched (or never uploaded, or never
deleted) makes the index a false statement, and in ``mirrorFromRemote`` it
was actively harmful: the next run computes ``to_download`` as
``remote_id_set - local_ids``, so a failed download recorded as local would
never be retried.
"""

import ndi.cloud.internal as internal
import ndi.cloud.sync.operations as ops
from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncOptions


def _fake_remote(monkeypatch, ids):
    """listRemoteDocumentIds returns {ndi_id: api_id}."""
    monkeypatch.setattr(
        internal,
        "listRemoteDocumentIds",
        lambda cloud_id, client=None: {i: i for i in ids},
    )


def _downloads_that_fail(monkeypatch, succeed):
    """Every requested ID resolves; only those in *succeed* come back."""
    succeed = set(succeed)

    def fake_download(cloud_id, ndi_to_api, ids_to_download, *, client=None):
        got = sorted(set(ids_to_download) & succeed)
        missing = sorted(set(ids_to_download) - succeed)
        return [{"ndiId": i, "id": i} for i in got], missing

    monkeypatch.setattr(ops, "downloadNdiDocuments", fake_download)


def _seed_index(tmp_path, local, remote):
    idx = SyncIndex()
    idx.update(list(local), list(remote))
    idx.write(tmp_path)


class TestDownloadNew:
    def test_a_failed_download_is_recorded_on_neither_side(self, tmp_path, monkeypatch):
        _seed_index(tmp_path, [], [])
        _fake_remote(monkeypatch, ["ok-1", "broken-1"])
        _downloads_that_fail(monkeypatch, succeed=["ok-1"])

        report = ops.downloadNew(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        assert report["downloaded_document_ids"] == ["ok-1"]
        assert report["failed"] == ["broken-1"]

        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["ok-1"]
        assert "broken-1" not in idx.remote_doc_ids_last_sync
        assert idx.remote_doc_ids_last_sync == ["ok-1"]

    def test_a_successful_run_records_everything(self, tmp_path, monkeypatch):
        _seed_index(tmp_path, [], [])
        _fake_remote(monkeypatch, ["a", "b"])
        _downloads_that_fail(monkeypatch, succeed=["a", "b"])

        ops.downloadNew(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        idx = SyncIndex.read(tmp_path)
        assert sorted(idx.local_doc_ids_last_sync) == ["a", "b"]
        assert sorted(idx.remote_doc_ids_last_sync) == ["a", "b"]

    def test_remote_documents_already_local_stay_recorded(self, tmp_path, monkeypatch):
        """Excluding failures must not also drop documents that were never
        part of this run because we already had them."""
        _seed_index(tmp_path, ["have-it"], ["have-it"])
        _fake_remote(monkeypatch, ["have-it", "broken-1"])
        _downloads_that_fail(monkeypatch, succeed=[])

        ops.downloadNew(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        idx = SyncIndex.read(tmp_path)
        assert idx.remote_doc_ids_last_sync == ["have-it"]
        assert idx.local_doc_ids_last_sync == ["have-it"]


class TestMirrorFromRemote:
    def test_a_failed_download_is_retried_on_the_next_run(self, tmp_path, monkeypatch):
        """The bug: recording it as local made ``to_download`` empty next
        time, so the document was silently never fetched again."""
        _seed_index(tmp_path, [], [])
        _fake_remote(monkeypatch, ["ok-1", "broken-1"])
        _downloads_that_fail(monkeypatch, succeed=["ok-1"])

        ops.mirrorFromRemote(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["ok-1"]

        # Second run: the remote is unchanged and the download now works.
        _downloads_that_fail(monkeypatch, succeed=["ok-1", "broken-1"])
        report = ops.mirrorFromRemote(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        assert report["download_count"] == 1
        assert report["downloaded_document_ids"] == ["broken-1"]
        assert sorted(SyncIndex.read(tmp_path).local_doc_ids_last_sync) == ["broken-1", "ok-1"]

    def test_local_only_documents_are_still_deleted_and_dropped(self, tmp_path, monkeypatch):
        _seed_index(tmp_path, ["gone", "stays"], ["gone", "stays"])
        _fake_remote(monkeypatch, ["stays"])
        _downloads_that_fail(monkeypatch, succeed=[])

        report = ops.mirrorFromRemote(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        assert report["deleted_local_document_ids"] == ["gone"]
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["stays"]
        assert idx.remote_doc_ids_last_sync == ["stays"]


class TestMirrorToRemote:
    def _uploads_that_fail(self, monkeypatch, succeed):
        succeed = set(succeed)

        class FakeDocsApi:
            @staticmethod
            def addDocument(cloud_id, doc, *, client=None):
                if doc["ndiId"] not in succeed:
                    raise RuntimeError("upload rejected")

            @staticmethod
            def deleteDocument(cloud_id, api_id, *, client=None):
                if api_id not in succeed:
                    raise RuntimeError("delete rejected")

        import ndi.cloud.api.documents as docs_api

        for name in ("addDocument", "deleteDocument"):
            monkeypatch.setattr(docs_api, name, getattr(FakeDocsApi, name))

    def test_a_failed_upload_is_not_recorded_as_remote(self, tmp_path, monkeypatch):
        _seed_index(tmp_path, ["ok-1", "broken-1"], [])
        _fake_remote(monkeypatch, [])
        self._uploads_that_fail(monkeypatch, succeed=["ok-1"])

        report = ops.mirrorToRemote(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        assert report["uploaded_document_ids"] == ["ok-1"]
        assert report["failed"] == ["broken-1"]

        idx = SyncIndex.read(tmp_path)
        assert idx.remote_doc_ids_last_sync == ["ok-1"]
        assert sorted(idx.local_doc_ids_last_sync) == ["broken-1", "ok-1"]

    def test_a_failed_remote_deletion_stays_on_the_remote_side(self, tmp_path, monkeypatch):
        """The document is still up there. Forgetting it means the next run
        would not try to delete it again."""
        _seed_index(tmp_path, ["mine"], ["mine", "undeletable"])
        _fake_remote(monkeypatch, ["mine", "undeletable"])
        self._uploads_that_fail(monkeypatch, succeed=["mine"])

        report = ops.mirrorToRemote(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        assert report["deleted_remote_document_ids"] == []
        assert report["failed"] == ["undeletable"]
        assert sorted(SyncIndex.read(tmp_path).remote_doc_ids_last_sync) == [
            "mine",
            "undeletable",
        ]

    def test_a_dry_run_does_not_write_the_index(self, tmp_path, monkeypatch):
        """Every other mode returns before its index write on a dry run;
        this one did not, so --dry-run recorded a sync that never happened."""
        _seed_index(tmp_path, ["a"], ["a"])
        before = (tmp_path / ".ndi" / "sync" / "index.json").read_text()

        _fake_remote(monkeypatch, ["a", "remote-only"])

        def must_not_run(*args, **kwargs):  # pragma: no cover - asserted by not raising
            raise AssertionError("a dry run must not call the cloud API")

        import ndi.cloud.api.documents as docs_api

        monkeypatch.setattr(docs_api, "addDocument", must_not_run)
        monkeypatch.setattr(docs_api, "deleteDocument", must_not_run)

        report = ops.mirrorToRemote(
            str(tmp_path), "cloud-1", SyncOptions(dry_run=True, verbose=False)
        )
        assert report["dry_run"] is True
        assert report["deleted_remote_document_ids"] == ["remote-only"]
        assert (tmp_path / ".ndi" / "sync" / "index.json").read_text() == before


class TestTwoWaySync:
    def test_a_failed_download_leaves_remote_work_outstanding(self, tmp_path, monkeypatch):
        _seed_index(tmp_path, [], [])
        _fake_remote(monkeypatch, ["ok-1", "broken-1"])
        _downloads_that_fail(monkeypatch, succeed=["ok-1"])

        report = ops.twoWaySync(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
        assert report["downloaded_document_ids"] == ["ok-1"]

        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == ["ok-1"]
        assert idx.remote_doc_ids_last_sync == ["ok-1"]
