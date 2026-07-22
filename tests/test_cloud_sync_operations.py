"""
Behavioral tests for the rebuilt cloud sync operations (audit C1, C2, C4 and
the locked decision to make twoWaySync strictly additive).

The sync ops are exercised against an in-memory fake dataset (so local state
comes from the dataset database, not the sync index) with the cloud API seams
mocked. No network or AWS access is required.
"""

from __future__ import annotations

import pytest

from ndi.cloud.sync import operations as ops
from ndi.cloud.sync.mode import SyncMode, SyncOptions
from ndi.document import ndi_document


def _doc(doc_id: str, files: list | None = None) -> ndi_document:
    """Build a minimal local document with a fixed base.id."""
    props: dict = {"base": {"id": doc_id}}
    if files is not None:
        props["files"] = {"file_info": files}
    return ndi_document(props)


class FakeDataset:
    """In-memory stand-in for ndi.dataset exposing the methods the sync ops use."""

    def __init__(self, path):
        self._path = path
        self._docs: dict[str, ndi_document] = {}

    def getpath(self):
        return self._path

    def database_search(self, query):  # noqa: ARG002 - query ignored (isa base)
        return list(self._docs.values())

    def database_add(self, document):
        did = document.document_properties["base"]["id"]
        if did in self._docs:
            # Real ndi_database.add re-raises a duplicate as ValueError.
            raise ValueError(f"ndi_document with ID {did} already exists.")
        self._docs[did] = document

    def database_rm(self, doc_or_id, error_if_not_found=True):
        did = (
            doc_or_id if isinstance(doc_or_id, str) else doc_or_id.document_properties["base"]["id"]
        )
        if did in self._docs:
            del self._docs[did]
        elif error_if_not_found:
            raise FileNotFoundError(did)

    def database_existbinarydoc(self, doc_or_id, filename):
        return False, None


class FakeRemote:
    """In-memory cloud document store keyed by NDI id."""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def api_id(self, ndi_id: str) -> str:
        return f"api_{ndi_id}"

    def list_ids(self, cloud_id, *, client=None):
        return {ndi_id: self.api_id(ndi_id) for ndi_id in self.docs}

    def upload(self, cloud_id, documents, only_missing=True, *, client=None):
        manifest = []
        for props in documents:
            ndi_id = props.get("base", {}).get("id", "")
            self.docs[ndi_id] = props
            manifest.append(ndi_id)
        return {"status": "ok", "manifest": manifest, "uploaded": len(manifest), "skipped": 0}

    def download(self, cloud_id, doc_ids=None, *, client=None, **kwargs):
        api_to_ndi = {self.api_id(n): n for n in self.docs}
        out = []
        for api_id in doc_ids or []:
            ndi_id = api_to_ndi.get(api_id)
            if ndi_id is None:
                continue
            doc = dict(self.docs[ndi_id])
            doc["_id"] = api_id
            doc["ndiId"] = ndi_id
            out.append(doc)
        return out


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """A fake dataset + fake remote with the cloud seams patched in."""
    dataset = FakeDataset(tmp_path)
    remote = FakeRemote()
    monkeypatch.setattr("ndi.cloud.internal.listRemoteDocumentIds", remote.list_ids)
    monkeypatch.setattr("ndi.cloud.upload.uploadDocumentCollection", remote.upload)
    monkeypatch.setattr("ndi.cloud.download.downloadDocumentCollection", remote.download)
    return dataset, remote


class TestUploadNewC1:
    def test_uploads_full_documents_not_stubs(self, wired):
        """C1: uploadNew must send full document bodies, not {'ndiId': id} stubs."""
        dataset, remote = wired
        dataset._docs["local-1"] = _doc("local-1")
        dataset._docs["local-2"] = _doc("local-2")

        report = ops.uploadNew(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert set(remote.docs.keys()) == {"local-1", "local-2"}
        # Uploaded payloads carry the real document_properties (base.id), not a stub.
        for ndi_id, props in remote.docs.items():
            assert props["base"]["id"] == ndi_id
            assert set(props.keys()) != {"ndiId"}
        assert sorted(report["uploaded_document_ids"]) == ["local-1", "local-2"]

    def test_local_state_from_dataset_not_index(self, wired):
        """C1: a freshly-added local doc (absent from the sync index) is uploaded."""
        dataset, remote = wired
        # Index file does not yet exist; the only source of local truth is the DB.
        dataset._docs["fresh"] = _doc("fresh")

        ops.uploadNew(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert "fresh" in remote.docs

    def test_dry_run_uploads_nothing(self, wired):
        dataset, remote = wired
        dataset._docs["a"] = _doc("a")
        report = ops.uploadNew(dataset, "cloud-ds", SyncOptions(verbose=False, dry_run=True))
        assert remote.docs == {}
        assert report["uploaded_document_ids"] == ["a"]

    def test_failed_upload_does_not_advance_index(self, wired, monkeypatch):
        """If uploadDocumentCollection reports failure, the sync index must NOT
        record the docs as synced — otherwise they'd never be retried."""
        dataset, remote = wired
        dataset._docs["a"] = _doc("a")

        def failing_upload(cloud_id, documents, only_missing=True, *, client=None):
            return {"status": "partial", "manifest": [], "uploaded": 0, "errors": ["boom"]}

        monkeypatch.setattr("ndi.cloud.upload.uploadDocumentCollection", failing_upload)
        report = ops.uploadNew(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert report["status"] == "partial"
        # Index file must not have been written (no successful sync recorded).
        assert not (dataset._path / ".ndi" / "sync" / "index.json").exists()


class TestDownloadNewC4:
    def test_downloaded_docs_go_into_database(self, wired):
        """C4: downloaded docs must be added via database_add (searchable),
        not dropped as raw JSON in .ndi/documents/."""
        dataset, remote = wired
        remote.docs["remote-1"] = {"base": {"id": "remote-1"}}

        report = ops.downloadNew(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert "remote-1" in dataset._docs  # in the database
        assert report["downloaded_document_ids"] == ["remote-1"]
        # No legacy JSON cache directory was created.
        assert not (dataset._path / ".ndi" / "documents").exists()

    def test_dry_run_downloads_nothing(self, wired):
        dataset, remote = wired
        remote.docs["r"] = {"base": {"id": "r"}}
        ops.downloadNew(dataset, "cloud-ds", SyncOptions(verbose=False, dry_run=True))
        assert "r" not in dataset._docs

    def test_resync_existing_doc_counts_as_present(self, wired):
        """C4 idempotency: a re-downloaded doc already in the DB (which raises
        ValueError on add) is reported as present, not a failure."""
        dataset, remote = wired
        remote.docs["dup"] = {"base": {"id": "dup"}}
        dataset._docs["dup"] = _doc("dup")  # already in the local DB

        # Force it to look new by leaving the index empty; ingest must tolerate
        # the duplicate-add ValueError and still count it as downloaded.
        added = ops._ingest_documents(dataset, [{"base": {"id": "dup"}, "_id": "api_dup"}])
        assert added == ["dup"]


class TestTwoWaySyncAdditive:
    def test_uploads_and_downloads_but_never_deletes(self, wired):
        """Locked decision: twoWaySync is strictly additive. A document deleted
        on the remote must NOT be deleted locally, and vice versa."""
        dataset, remote = wired
        # local-only doc -> should be uploaded
        dataset._docs["L"] = _doc("L")
        # remote-only doc -> should be downloaded
        remote.docs["R"] = {"base": {"id": "R"}}
        # a doc deleted on the remote but still present locally
        dataset._docs["deleted_on_remote"] = _doc("deleted_on_remote")
        # a doc deleted locally but still present on the remote
        remote.docs["deleted_on_local"] = {"base": {"id": "deleted_on_local"}}

        # Seed the sync index so both "deleted_*" ids count as known-at-last-sync.
        from ndi.cloud.sync.index import SyncIndex

        idx = SyncIndex()
        idx.update(
            ["L", "deleted_on_remote", "deleted_on_local"],
            ["R", "deleted_on_remote", "deleted_on_local"],
        )
        idx.write(dataset._path)

        ops.twoWaySync(dataset, "cloud-ds", SyncOptions(verbose=False))

        # Additions happened both directions.
        assert "L" in remote.docs
        assert "R" in dataset._docs
        # NOTHING was deleted on either side.
        assert "deleted_on_remote" in dataset._docs
        assert "deleted_on_local" in remote.docs


class TestMirrorModesDelete:
    def test_mirror_from_remote_deletes_local_only(self, wired):
        dataset, remote = wired
        dataset._docs["local-only"] = _doc("local-only")
        remote.docs["shared"] = {"base": {"id": "shared"}}
        dataset._docs["shared"] = _doc("shared")

        report = ops.mirrorFromRemote(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert "local-only" not in dataset._docs  # deleted via database_rm
        assert "local-only" in report["deleted_local_document_ids"]
        assert "shared" in dataset._docs

    def test_mirror_to_remote_deletes_remote_only(self, wired):
        dataset, remote = wired
        remote.docs["remote-only"] = {"base": {"id": "remote-only"}}
        dataset._docs["local"] = _doc("local")

        captured = []
        import ndi.cloud.api.documents as docs_api

        def fake_delete(cloud_id, api_id, *, client=None):
            captured.append(api_id)
            for ndi_id in list(remote.docs):
                if remote.api_id(ndi_id) == api_id:
                    del remote.docs[ndi_id]

        import unittest.mock as mock

        with mock.patch.object(docs_api, "deleteDocument", fake_delete):
            report = ops.mirrorToRemote(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert "remote-only" not in remote.docs
        assert "remote-only" in report["deleted_remote_document_ids"]
        assert "local" in remote.docs  # uploaded


class TestDeleteLocalDocuments:
    def test_uses_database_rm(self, tmp_path):
        dataset = FakeDataset(tmp_path)
        dataset._docs["a"] = _doc("a")
        dataset._docs["b"] = _doc("b")

        deleted = ops.deleteLocalDocuments(dataset, ["a"])

        assert deleted == ["a"]
        assert "a" not in dataset._docs
        assert "b" in dataset._docs


class TestSyncDispatch:
    def test_sync_routes_to_handler(self, wired):
        dataset, remote = wired
        dataset._docs["x"] = _doc("x")
        ops.sync(dataset, "cloud-ds", SyncMode.UPLOAD_NEW, SyncOptions(verbose=False))
        assert "x" in remote.docs

    def test_index_written_camelcase_after_sync(self, wired):
        import json

        dataset, remote = wired
        dataset._docs["x"] = _doc("x")
        ops.uploadNew(dataset, "cloud-ds", SyncOptions(verbose=False))
        raw = json.loads((dataset._path / ".ndi" / "sync" / "index.json").read_text())
        assert "localDocumentIdsLastSync" in raw
        assert raw["localDocumentIdsLastSync"] == ["x"]


class TestDownloadFailuresDoNotAdvanceIndex:
    """A partial download must set status='partial' and leave the sync index
    unadvanced, so the un-downloaded documents are re-fetched next sync instead
    of being permanently treated as already-synced (silent local loss)."""

    @staticmethod
    def _partial_download(*_args, **_kwargs):
        # One doc arrives, one id is reported failed.
        return [{"base": {"id": "remote-1"}, "_id": "api_remote-1"}], ["remote-2"]

    def _index_path(self, dataset):
        return dataset._path / ".ndi" / "sync" / "index.json"

    def test_downloadNew_partial_does_not_advance_index(self, wired, monkeypatch):
        dataset, remote = wired
        remote.docs["remote-1"] = {"base": {"id": "remote-1"}}
        remote.docs["remote-2"] = {"base": {"id": "remote-2"}}

        monkeypatch.setattr(ops, "downloadNdiDocuments", self._partial_download)
        report = ops.downloadNew(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert report["status"] == "partial"
        assert report["failed"] == ["remote-2"]
        assert not self._index_path(dataset).exists()

    def test_mirrorFromRemote_partial_does_not_advance_index(self, wired, monkeypatch):
        dataset, remote = wired
        remote.docs["remote-1"] = {"base": {"id": "remote-1"}}
        remote.docs["remote-2"] = {"base": {"id": "remote-2"}}

        monkeypatch.setattr(ops, "downloadNdiDocuments", self._partial_download)
        report = ops.mirrorFromRemote(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert report["status"] == "partial"
        assert report["failed"] == ["remote-2"]
        assert not self._index_path(dataset).exists()

    def test_twoWaySync_partial_download_does_not_advance_index(self, wired, monkeypatch):
        dataset, remote = wired
        # A local doc to upload cleanly, and remote docs to download.
        dataset._docs["local-1"] = _doc("local-1")
        remote.docs["remote-1"] = {"base": {"id": "remote-1"}}
        remote.docs["remote-2"] = {"base": {"id": "remote-2"}}

        # Upload phase succeeds (default fake remote); only the download fails.
        monkeypatch.setattr(ops, "downloadNdiDocuments", self._partial_download)
        report = ops.twoWaySync(dataset, "cloud-ds", SyncOptions(verbose=False))

        assert report["status"] == "partial"
        assert report["failed"] == ["remote-2"]
        assert not self._index_path(dataset).exists()


class TestSyncIndexPersistence:
    """SyncIndex.write must be atomic (no zero-byte window) and not depend on
    module-level fcntl; SyncIndex.read must tolerate a corrupt index."""

    def test_write_is_atomic_no_zero_byte_window(self, tmp_path):
        from ndi.cloud.sync.index import SyncIndex

        idx = SyncIndex()
        idx.update(["l1", "l2"], ["r1", "r2"])
        idx.write(tmp_path)
        index_file = tmp_path / ".ndi" / "sync" / "index.json"
        assert index_file.exists()
        assert index_file.stat().st_size > 0
        # Overwrite in place: still non-empty and valid, and no leftover temp files.
        idx.update(["l3"], ["r3"])
        idx.write(tmp_path)
        back = SyncIndex.read(tmp_path)
        assert back.remote_doc_ids_last_sync == ["r3"]
        leftovers = list((tmp_path / ".ndi" / "sync").glob(".index.*.tmp"))
        assert leftovers == []

    def test_read_tolerates_corrupt_json(self, tmp_path):
        from ndi.cloud.sync.index import SyncIndex

        d = tmp_path / ".ndi" / "sync"
        d.mkdir(parents=True)
        (d / "index.json").write_text("")  # zero-byte / corrupt
        idx = SyncIndex.read(tmp_path)
        assert idx.remote_doc_ids_last_sync == []
        (d / "index.json").write_text("{ not json")
        assert SyncIndex.read(tmp_path).local_doc_ids_last_sync == []

    def test_index_module_imports_without_fcntl(self, monkeypatch):
        import builtins
        import importlib

        real_import = builtins.__import__

        def _no_fcntl(name, *args, **kwargs):
            if name == "fcntl":
                raise ImportError("no fcntl on this platform")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_fcntl)
        import ndi.cloud.sync.index as index_mod

        importlib.reload(index_mod)
        # Round-trips fine with fcntl unavailable.
        assert index_mod.SyncIndex().remote_doc_ids_last_sync == []
