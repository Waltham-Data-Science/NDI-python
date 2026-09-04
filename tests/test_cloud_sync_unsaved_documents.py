"""
A document the cloud returns must never vanish -- VH-Lab/NDI-matlab#916.

``_save_downloaded_docs`` skipped any document without a usable ``ndiId``
with a bare ``continue``: not written, not logged, and not in the report's
``failed`` list. It did not even count as a failed download, because
``downloadNdiDocuments`` decides what failed by whether the requested *api*
ID came back -- so a document arriving with a good ``_id`` but a blank
``ndiId`` was counted as downloaded and then discarded one call later. The
report said "1 new document" and accounted for it nowhere.
"""

import ndi.cloud.download as download_module
import ndi.cloud.internal as internal
import ndi.cloud.sync.operations as ops
from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncOptions


def _remote(monkeypatch, ndi_to_api):
    monkeypatch.setattr(
        internal, "listRemoteDocumentIds", lambda cid, client=None: dict(ndi_to_api)
    )


def _collection_returns(monkeypatch, docs):
    monkeypatch.setattr(
        download_module,
        "downloadDocumentCollection",
        lambda cloud_id, doc_ids=None, client=None: [dict(d) for d in docs],
    )


class TestSaveDownloadedDocs:
    def test_a_document_with_no_id_at_all_is_reported_not_dropped(self, tmp_path):
        saved, unsaved = ops._save_downloaded_docs(tmp_path, [{"payload": "orphan"}])
        assert saved == []
        assert len(unsaved) == 1
        assert "position 0" in unsaved[0]

    def test_an_unsaveable_document_is_labelled_by_its_api_id(self, tmp_path):
        saved, unsaved = ops._save_downloaded_docs(tmp_path, [{"_id": "api-A", "ndiId": ""}])
        assert saved == []
        assert unsaved == ["api-A"]

    def test_a_blank_ndiid_falls_back_to_id(self, tmp_path):
        """doc.get("ndiId", doc.get("id", "")) never reached the fallback,
        because a present-but-empty key beats the default."""
        saved, unsaved = ops._save_downloaded_docs(tmp_path, [{"ndiId": "", "id": "doc-A"}])
        assert saved == ["doc-A"]
        assert unsaved == []

    def test_good_documents_are_unaffected(self, tmp_path):
        saved, unsaved = ops._save_downloaded_docs(
            tmp_path, [{"ndiId": "doc-A"}, {"ndiId": "doc-B"}]
        )
        assert saved == ["doc-A", "doc-B"]
        assert unsaved == []
        doc_dir = tmp_path / ".ndi" / "documents"
        assert sorted(p.name for p in doc_dir.iterdir()) == ["doc-A.json", "doc-B.json"]

    def test_it_warns_so_the_loss_is_visible_in_the_log(self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            ops._save_downloaded_docs(tmp_path, [{"_id": "api-A", "ndiId": ""}])
        assert "api-A" in caplog.text


class TestDownloadNdiDocumentsRepairsBlankIds:
    def test_a_blank_ndiid_is_repaired_from_the_api_map(self, monkeypatch):
        """The original setdefault could not overwrite a present-but-empty
        key, which is what created the unsaveable document."""
        _collection_returns(monkeypatch, [{"_id": "api-A", "ndiId": ""}])
        docs, failed = ops.downloadNdiDocuments("cloud-1", {"doc-A": "api-A"}, {"doc-A"})
        assert failed == []
        assert docs[0]["ndiId"] == "doc-A"

    def test_a_real_ndiid_is_left_alone(self, monkeypatch):
        _collection_returns(monkeypatch, [{"_id": "api-A", "ndiId": "already-set"}])
        docs, _ = ops.downloadNdiDocuments("cloud-1", {"doc-A": "api-A"}, {"doc-A"})
        assert docs[0]["ndiId"] == "already-set"


class TestTheDocumentIsNoLongerLostEndToEnd:
    def test_downloadnew_now_saves_the_document_it_used_to_drop(self, tmp_path, monkeypatch):
        """The exact reproduction from the issue: valid _id, blank ndiId."""
        SyncIndex().write(tmp_path)
        _remote(monkeypatch, {"doc-A": "api-A"})
        _collection_returns(monkeypatch, [{"_id": "api-A", "ndiId": "", "payload": "data"}])

        report = ops.downloadNew(str(tmp_path), "cloud-1", SyncOptions(verbose=False))

        assert report["new_count"] == 1
        assert report["downloaded_document_ids"] == ["doc-A"]
        assert report["failed"] == []
        assert report["unsaved_documents"] == []
        assert (tmp_path / ".ndi" / "documents" / "doc-A.json").exists()
        assert SyncIndex.read(tmp_path).local_doc_ids_last_sync == ["doc-A"]

    def test_a_truly_unidentifiable_document_is_surfaced_in_the_report(self, tmp_path, monkeypatch):
        """Nothing maps it back to a requested ID, so it cannot be saved --
        but the report must say so rather than claiming a clean run."""
        SyncIndex().write(tmp_path)
        _remote(monkeypatch, {"doc-A": "api-A"})
        _collection_returns(monkeypatch, [{"payload": "no identifiers at all"}])

        report = ops.downloadNew(str(tmp_path), "cloud-1", SyncOptions(verbose=False))

        assert report["downloaded_document_ids"] == []
        assert report["failed"] == ["doc-A"]  # its api id never came back
        assert len(report["unsaved_documents"]) == 1
        # And the index records nothing, so the next run retries doc-A.
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == []
        assert idx.remote_doc_ids_last_sync == []

    def test_every_download_mode_exposes_the_key(self, tmp_path, monkeypatch):
        SyncIndex().write(tmp_path)
        _remote(monkeypatch, {"doc-A": "api-A"})
        _collection_returns(monkeypatch, [{"_id": "api-A", "ndiId": "doc-A"}])
        for fn in (ops.downloadNew, ops.mirrorFromRemote, ops.twoWaySync):
            report = fn(str(tmp_path), "cloud-1", SyncOptions(verbose=False))
            assert "unsaved_documents" in report, fn.__name__
