"""
Tests for Phase 10 Batch 3: Sync Engine + Upload/Download.

Tests SyncMode, SyncOptions, SyncIndex, upload/download orchestration,
sync operations, and internal utilities.
"""

import json
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.download import download_document_collection
from ndi.cloud.internal import list_remote_document_ids
from ndi.cloud.sync.index import SyncIndex
from ndi.cloud.sync.mode import SyncMode, SyncOptions
from ndi.cloud.sync.operations import (
    download_new,
    mirror_from_remote,
    mirror_to_remote,
    sync,
    two_way_sync,
    upload_new,
)
from ndi.cloud.upload import (
    upload_document_collection,
    zip_documents_for_upload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    cfg = CloudConfig(api_url="https://api.test.ndi/v1", token="tok", org_id="org-1")
    c = CloudClient(cfg)
    c._session.request = MagicMock()
    return c


def _ok(data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b"data"
    resp.json.return_value = data
    resp.text = str(data)
    return resp


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
# Upload orchestration
# ===========================================================================


class TestUploadDocCollection:
    def test_upload_all(self, client):
        # Mock list_all_documents for only_missing check
        client._session.request.side_effect = [
            _ok({"totalNumber": 0, "documents": []}),  # list (page 1)
            _ok({"id": "new-1"}, 201),  # add doc 1
            _ok({"id": "new-2"}, 201),  # add doc 2
        ]
        docs = [{"ndiId": "n1"}, {"ndiId": "n2"}]
        report = upload_document_collection(client, "ds-1", docs)
        assert report["uploaded"] == 2
        assert report["status"] == "ok"

    def test_upload_skips_existing(self, client):
        client._session.request.side_effect = [
            _ok({"totalNumber": 1, "documents": [{"ndiId": "n1", "id": "n1"}]}),
            _ok({"id": "new"}, 201),
        ]
        docs = [{"ndiId": "n1"}, {"ndiId": "n2"}]
        report = upload_document_collection(client, "ds-1", docs)
        assert report["skipped"] == 1
        assert report["uploaded"] == 1

    def test_upload_empty_list(self, client):
        report = upload_document_collection(client, "ds-1", [], only_missing=False)
        assert report["uploaded"] == 0


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
# Download orchestration
# ===========================================================================


class TestDownloadDocCollection:
    def test_download_specific_ids(self, client):
        client._session.request.side_effect = [
            _ok({"id": "d1", "type": "base"}),
            _ok({"id": "d2", "type": "probe"}),
        ]
        result = download_document_collection(client, "ds-1", doc_ids=["d1", "d2"])
        assert len(result) == 2
        assert result[0]["id"] == "d1"

    def test_download_all(self, client):
        client._session.request.return_value = _ok(
            {
                "totalNumber": 2,
                "documents": [{"id": "d1"}, {"id": "d2"}],
            }
        )
        result = download_document_collection(client, "ds-1")
        assert len(result) == 2


# ===========================================================================
# Sync operations
# ===========================================================================


class TestSyncOperations:
    @patch("ndi.cloud.internal.list_remote_document_ids")
    def test_upload_new_dry_run(self, mock_remote, client, tmp_path):
        mock_remote.return_value = {"r1": "api-r1"}
        idx = SyncIndex()
        idx.update(["r1", "local-only"], ["r1"])
        idx.write(tmp_path)

        report = upload_new(
            client,
            str(tmp_path),
            "cloud-ds",
            options=SyncOptions(dry_run=True),
        )
        assert report["dry_run"] is True
        assert report["new_count"] == 1

    @patch("ndi.cloud.internal.list_remote_document_ids")
    def test_download_new_dry_run(self, mock_remote, client, tmp_path):
        mock_remote.return_value = {"r1": "api-r1", "r2": "api-r2"}
        idx = SyncIndex()
        idx.update(["r1"], ["r1"])
        idx.write(tmp_path)

        report = download_new(
            client,
            str(tmp_path),
            "cloud-ds",
            options=SyncOptions(dry_run=True),
        )
        assert report["new_count"] == 1

    @patch("ndi.cloud.internal.list_remote_document_ids")
    def test_mirror_to_remote(self, mock_remote, client, tmp_path):
        mock_remote.return_value = {"r1": "api-r1", "r-extra": "api-extra"}
        idx = SyncIndex()
        idx.update(["r1", "local-new"], ["r1", "r-extra"])
        idx.write(tmp_path)

        # Mock the add and delete calls
        client._session.request.side_effect = [
            _ok({"id": "new"}, 201),  # add
            MagicMock(status_code=204, content=b""),  # delete
        ]

        report = mirror_to_remote(client, str(tmp_path), "cloud-ds")
        assert report["upload_count"] == 1
        assert report["delete_count"] == 1

    @patch("ndi.cloud.internal.list_remote_document_ids")
    def test_mirror_from_remote(self, mock_remote, client, tmp_path):
        mock_remote.return_value = {"r1": "a1", "r2": "a2"}
        idx = SyncIndex()
        idx.update(["r1", "local-only"], ["r1"])
        idx.write(tmp_path)

        report = mirror_from_remote(client, str(tmp_path), "cloud-ds")
        assert report["download_count"] == 1
        assert report["delete_local_count"] == 1

    @patch("ndi.cloud.internal.list_remote_document_ids")
    def test_two_way_sync(self, mock_remote, client, tmp_path):
        mock_remote.return_value = {"shared": "a1", "remote-only": "a2"}
        idx = SyncIndex()
        idx.update(["shared", "local-only"], ["shared"])
        idx.write(tmp_path)

        client._session.request.return_value = _ok({"id": "new"}, 201)

        report = two_way_sync(client, str(tmp_path), "cloud-ds")
        assert report["upload_count"] == 1
        assert report["download_count"] == 1

    def test_sync_dispatch(self, client, tmp_path):
        """sync() dispatches to the correct handler."""
        with patch("ndi.cloud.sync.operations.upload_new") as mock_up:
            mock_up.return_value = {"mode": "upload_new"}
            result = sync(client, str(tmp_path), "ds", SyncMode.UPLOAD_NEW)
            assert result["mode"] == "upload_new"
            mock_up.assert_called_once()

    def test_sync_updates_index(self, client, tmp_path):
        """After a sync, index file should exist."""
        with patch("ndi.cloud.internal.list_remote_document_ids") as mock_remote:
            mock_remote.return_value = {}
            idx = SyncIndex()
            idx.update([], [])
            idx.write(tmp_path)

            download_new(client, str(tmp_path), "ds")
            loaded = SyncIndex.read(tmp_path)
            assert loaded.last_sync_timestamp != ""


# ===========================================================================
# Internal utilities
# ===========================================================================


class TestInternal:
    def test_list_remote_document_ids(self, client):
        client._session.request.return_value = _ok(
            {
                "totalNumber": 2,
                "documents": [
                    {"ndiId": "ndi-1", "id": "api-1"},
                    {"ndiId": "ndi-2", "id": "api-2"},
                ],
            }
        )
        result = list_remote_document_ids(client, "ds-1")
        assert result == {"ndi-1": "api-1", "ndi-2": "api-2"}

    def test_list_remote_document_ids_empty(self, client):
        client._session.request.return_value = _ok(
            {
                "totalNumber": 0,
                "documents": [],
            }
        )
        result = list_remote_document_ids(client, "ds-1")
        assert result == {}


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
