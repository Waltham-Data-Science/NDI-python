"""
Tests for cloud sync structural components.

Tests SyncMode, SyncOptions, SyncIndex, zip_documents_for_upload,
CloudClient.from_env(), and the _auto_client decorator.
These test local data structures and file I/O — no cloud API calls needed.
"""

import json
import zipfile
from unittest.mock import MagicMock, patch

import pytest

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


# ===========================================================================
# CloudClient.from_env() and _auto_client decorator
# ===========================================================================


class TestFromEnv:
    @patch("ndi.cloud.auth.authenticate")
    @patch("ndi.cloud.config.CloudConfig.from_env")
    def test_from_env_creates_client(self, mock_config_from_env, mock_authenticate):
        from ndi.cloud.client import CloudClient

        mock_config = MagicMock()
        mock_config.api_url = "https://api.example.com"
        mock_config_from_env.return_value = mock_config
        mock_authenticate.return_value = "fake-token"

        client = CloudClient.from_env()

        assert isinstance(client, CloudClient)
        assert client.config is mock_config
        mock_authenticate.assert_called_once_with(mock_config)
        assert mock_config.token == "fake-token"

    @patch("ndi.cloud.auth.authenticate")
    @patch("ndi.cloud.config.CloudConfig.from_env")
    def test_from_env_raises_on_auth_failure(self, mock_config_from_env, mock_authenticate):
        from ndi.cloud.client import CloudClient
        from ndi.cloud.exceptions import CloudAuthError

        mock_config = MagicMock()
        mock_config_from_env.return_value = mock_config
        mock_authenticate.side_effect = CloudAuthError("No credentials")

        with pytest.raises(CloudAuthError):
            CloudClient.from_env()


class TestAutoClient:
    def test_passthrough_with_explicit_client(self):
        """When a CloudClient is passed, it should be used directly."""
        from ndi.cloud.client import CloudClient, _auto_client

        mock_client = MagicMock(spec=CloudClient)
        calls = []

        @_auto_client
        def my_func(client, arg1):
            calls.append((client, arg1))
            return "ok"

        result = my_func(mock_client, "hello")
        assert result == "ok"
        assert calls == [(mock_client, "hello")]

    def test_passthrough_with_keyword_client(self):
        """When client is passed as keyword, it should be used directly."""
        from ndi.cloud.client import CloudClient, _auto_client

        mock_client = MagicMock(spec=CloudClient)
        calls = []

        @_auto_client
        def my_func(client, arg1):
            calls.append((client, arg1))
            return "ok"

        result = my_func("hello", client=mock_client)
        assert result == "ok"
        assert calls == [(mock_client, "hello")]

    @patch("ndi.cloud.client.CloudClient.from_env")
    def test_auto_creates_client_when_omitted(self, mock_from_env):
        """When no client is passed, one should be created from env."""
        from ndi.cloud.client import CloudClient, _auto_client

        auto_client = MagicMock(spec=CloudClient)
        mock_from_env.return_value = auto_client
        calls = []

        @_auto_client
        def my_func(client, arg1):
            calls.append((client, arg1))
            return "ok"

        result = my_func("hello")
        assert result == "ok"
        assert calls == [(auto_client, "hello")]
        mock_from_env.assert_called_once()

    @patch("ndi.cloud.client.CloudClient.from_env")
    def test_auto_creates_client_when_keyword_none(self, mock_from_env):
        """When client=None is passed, one should be created from env."""
        from ndi.cloud.client import CloudClient, _auto_client

        auto_client = MagicMock(spec=CloudClient)
        mock_from_env.return_value = auto_client
        calls = []

        @_auto_client
        def my_func(client, arg1):
            calls.append((client, arg1))
            return "ok"

        result = my_func("hello", client=None)
        assert result == "ok"
        assert calls[0][0] is auto_client
        mock_from_env.assert_called_once()

    def test_preserves_function_name(self):
        """Decorator should preserve the original function name."""
        from ndi.cloud.client import _auto_client

        @_auto_client
        def get_dataset(client, dataset_id):
            """My docstring."""
            pass

        assert get_dataset.__name__ == "get_dataset"
        assert get_dataset.__doc__ == "My docstring."

    @patch("ndi.cloud.client.CloudClient.from_env")
    def test_api_function_without_client(self, mock_from_env):
        """Real API function should work without explicit client."""
        from ndi.cloud.client import CloudClient

        mock_client = MagicMock(spec=CloudClient)
        mock_client.get.return_value = {"_id": "abc", "name": "Test"}
        mock_from_env.return_value = mock_client

        from ndi.cloud.api.datasets import get_dataset

        result = get_dataset("abc-123")
        assert result == {"_id": "abc", "name": "Test"}
        mock_client.get.assert_called_once()

    def test_api_function_with_explicit_client(self):
        """Real API function should work with explicit client."""
        from ndi.cloud.client import CloudClient

        mock_client = MagicMock(spec=CloudClient)
        mock_client.get.return_value = {"_id": "abc", "name": "Test"}

        from ndi.cloud.api.datasets import get_dataset

        result = get_dataset(mock_client, "abc-123")
        assert result == {"_id": "abc", "name": "Test"}
        mock_client.get.assert_called_once()
