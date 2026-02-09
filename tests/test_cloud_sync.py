"""
Tests for cloud sync structural components.

Tests SyncMode, SyncOptions, SyncIndex, and zip_documents_for_upload.
These test local data structures and file I/O — no cloud API calls needed.
"""

import json
import zipfile

from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncMode, SyncOptions
from ndi.cloud.upload import zip_documents_for_upload

# ===========================================================================
# SyncMode & SyncOptions
# ===========================================================================


class TestSyncMode:
    def test_enum_values(self):
        assert SyncMode.DOWNLOAD_NEW.value == "download_new"
        assert SyncMode.UPLOAD_NEW.value == "upload_new"
        assert SyncMode.MIRROR_FROM_REMOTE.value == "mirror_from_remote"
        assert SyncMode.MIRROR_TO_REMOTE.value == "mirror_to_remote"
        assert SyncMode.TWO_WAY_SYNC.value == "two_way_sync"

    def test_all_modes(self):
        assert len(SyncMode) == 5


class TestSyncOptions:
    def test_defaults(self):
        opts = SyncOptions()
        assert opts.sync_files is False
        assert opts.verbose is True
        assert opts.dry_run is False
        assert opts.file_upload_strategy == "batch"

    def test_override(self):
        opts = SyncOptions(sync_files=True, dry_run=True, verbose=False)
        assert opts.sync_files is True
        assert opts.dry_run is True
        assert opts.verbose is False


# ===========================================================================
# SyncIndex
# ===========================================================================


class TestSyncIndex:
    def test_default_empty(self):
        idx = SyncIndex()
        assert idx.local_doc_ids_last_sync == []
        assert idx.remote_doc_ids_last_sync == []
        assert idx.last_sync_timestamp == ""

    def test_write_and_read(self, tmp_path):
        idx = SyncIndex()
        idx.update(["local-1", "local-2"], ["remote-1"])
        idx.write(tmp_path)

        loaded = SyncIndex.read(tmp_path)
        assert loaded.local_doc_ids_last_sync == ["local-1", "local-2"]
        assert loaded.remote_doc_ids_last_sync == ["remote-1"]
        assert loaded.last_sync_timestamp != ""

    def test_read_nonexistent(self, tmp_path):
        idx = SyncIndex.read(tmp_path)
        assert idx.local_doc_ids_last_sync == []

    def test_write_creates_directory(self, tmp_path):
        ds_path = tmp_path / "nested" / "dataset"
        ds_path.mkdir(parents=True)
        idx = SyncIndex()
        idx.update(["a"], ["b"])
        idx.write(ds_path)
        assert (ds_path / ".ndi" / "sync" / "index.json").exists()

    def test_update_sets_timestamp(self):
        idx = SyncIndex()
        idx.update(["x"], ["y"])
        assert idx.last_sync_timestamp != ""
        assert "T" in idx.last_sync_timestamp  # ISO format

    def test_json_roundtrip(self, tmp_path):
        idx = SyncIndex()
        idx.update(["d1", "d2"], ["r1", "r2", "r3"])
        idx.write(tmp_path)

        raw = json.loads((tmp_path / ".ndi" / "sync" / "index.json").read_text())
        assert len(raw["local_doc_ids_last_sync"]) == 2
        assert len(raw["remote_doc_ids_last_sync"]) == 3


# ===========================================================================
# Zip documents for upload
# ===========================================================================


class TestZipDocuments:
    def test_creates_zip(self, tmp_path):
        docs = [{"ndiId": "doc-1", "type": "base"}, {"ndiId": "doc-2", "type": "probe"}]
        zip_path, manifest = zip_documents_for_upload(docs, "ds-1", tmp_path)
        assert zip_path.exists()
        assert len(manifest) == 2
        assert "doc-1" in manifest

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "doc-1.json" in names
            assert "doc-2.json" in names

    def test_zip_content_is_valid_json(self, tmp_path):
        docs = [{"ndiId": "x", "data": [1, 2, 3]}]
        zip_path, _ = zip_documents_for_upload(docs, "ds-1", tmp_path)
        with zipfile.ZipFile(zip_path) as zf:
            content = json.loads(zf.read("x.json"))
            assert content["data"] == [1, 2, 3]


# ===========================================================================
# Package imports
# ===========================================================================


class TestSyncImports:
    def test_import_sync_from_cloud(self):
        from ndi.cloud.sync import SyncIndex, SyncMode, SyncOptions

        assert SyncMode is not None
        assert SyncOptions is not None
        assert SyncIndex is not None

    def test_import_sync_operations(self):
        from ndi.cloud.sync import download_new, sync, upload_new

        assert callable(upload_new)
        assert callable(download_new)
        assert callable(sync)

    def test_import_upload(self):
        from ndi.cloud.upload import upload_document_collection, zip_documents_for_upload

        assert callable(upload_document_collection)
        assert callable(zip_documents_for_upload)

    def test_import_download(self):
        from ndi.cloud.download import download_document_collection

        assert callable(download_document_collection)
