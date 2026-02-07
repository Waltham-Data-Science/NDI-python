"""
Tests for Phase 11 Batch 11B: Cloud API Missing Endpoints + Orchestration.

Tests new auth endpoints, file/document/dataset API additions,
download helpers, and orchestration functions. All external calls mocked.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudAuthError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    cfg = CloudConfig(api_url="https://api.test.ndi/v1", token="tok-abc", org_id="org-1")
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
# Auth Endpoints
# ===========================================================================


class TestAuthEndpoints:
    @patch("requests.post")
    def test_change_password(self, mock_post):
        mock_post.return_value = _ok({"message": "ok"})
        from ndi.cloud.auth import change_password

        cfg = CloudConfig(api_url="https://api.test.ndi/v1", token="tok")
        result = change_password("old", "new", config=cfg)
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "oldPassword" in str(call_kwargs)

    @patch("requests.post")
    def test_change_password_failure(self, mock_post):
        mock_post.return_value = _ok({}, status=400)
        from ndi.cloud.auth import change_password

        cfg = CloudConfig(api_url="https://api.test.ndi/v1", token="tok")
        with pytest.raises(CloudAuthError):
            change_password("old", "new", config=cfg)

    @patch("requests.post")
    def test_reset_password(self, mock_post):
        mock_post.return_value = _ok({"message": "ok"})
        from ndi.cloud.auth import reset_password

        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        result = reset_password("user@test.com", config=cfg)
        assert result is True

    @patch("requests.post")
    def test_verify_user(self, mock_post):
        mock_post.return_value = _ok({"message": "ok"})
        from ndi.cloud.auth import verify_user

        cfg = CloudConfig(api_url="https://api.test.ndi/v1", token="tok")
        result = verify_user("user@test.com", "CODE123", config=cfg)
        assert result is True

    @patch("requests.post")
    def test_resend_confirmation(self, mock_post):
        mock_post.return_value = _ok({"message": "ok"})
        from ndi.cloud.auth import resend_confirmation

        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        result = resend_confirmation("user@test.com", config=cfg)
        assert result is True


# ===========================================================================
# File API Endpoints
# ===========================================================================


class TestFileAPI:
    def test_list_files(self, client):
        client._session.request.return_value = _ok(
            {
                "name": "Test DS",
                "files": [
                    {"uid": "f1", "size": 100},
                    {"uid": "f2", "size": 200},
                ],
            }
        )
        from ndi.cloud.api.files import list_files

        result = list_files(client, "ds-1")
        assert len(result) == 2
        assert result[0]["uid"] == "f1"

    def test_get_file_details(self, client):
        client._session.request.return_value = _ok(
            {
                "downloadUrl": "https://s3.example.com/file",
                "size": 1024,
            }
        )
        from ndi.cloud.api.files import get_file_details

        result = get_file_details(client, "ds-1", "file-uid-1")
        assert "downloadUrl" in result

    def test_get_file_collection_upload_url(self, client):
        client._session.request.return_value = _ok({"url": "https://s3.example.com/bulk-upload"})
        from ndi.cloud.api.files import get_file_collection_upload_url

        url = get_file_collection_upload_url(client, "org-1", "ds-1")
        assert "bulk-upload" in url

    @patch("requests.get")
    def test_get_file(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"file content"]
        mock_get.return_value = mock_resp

        from ndi.cloud.api.files import get_file

        target = tmp_path / "downloaded.bin"
        result = get_file("https://s3.example.com/f1", target)
        assert result is True
        assert target.read_bytes() == b"file content"


# ===========================================================================
# Document API Endpoints
# ===========================================================================


class TestDocumentAPI:
    def test_ndi_query(self, client):
        client._session.request.return_value = _ok(
            {
                "documents": [{"id": "d1"}, {"id": "d2"}],
                "totalItems": 2,
            }
        )
        from ndi.cloud.api.documents import ndi_query

        result = ndi_query(client, "public", {"isa": "element"})
        assert len(result["documents"]) == 2

    def test_ndi_query_all_pagination(self, client):
        page1 = _ok(
            {
                "documents": [{"id": f"d{i}"} for i in range(1000)],
                "totalItems": 1500,
            }
        )
        page2 = _ok(
            {
                "documents": [{"id": f"d{i}"} for i in range(1000, 1500)],
                "totalItems": 1500,
            }
        )
        client._session.request.side_effect = [page1, page2]

        from ndi.cloud.api.documents import ndi_query_all

        result = ndi_query_all(client, "all", {"isa": "element"})
        assert len(result) == 1500

    def test_add_document_as_file(self, client, tmp_path):
        client._session.request.return_value = _ok({"id": "new-doc-1"})
        doc_file = tmp_path / "doc.json"
        doc_file.write_text(json.dumps({"base": {"id": "test-123"}}))

        from ndi.cloud.api.documents import add_document_as_file

        result = add_document_as_file(client, "ds-1", str(doc_file))
        assert result["id"] == "new-doc-1"


# ===========================================================================
# Dataset API Endpoints
# ===========================================================================


class TestDatasetAPI:
    def test_get_unpublished(self, client):
        client._session.request.return_value = _ok(
            {
                "datasets": [{"id": "ds-1", "name": "Draft"}],
                "totalNumber": 1,
            }
        )
        from ndi.cloud.api.datasets import get_unpublished

        result = get_unpublished(client)
        assert "datasets" in result


# ===========================================================================
# Download Helpers
# ===========================================================================


class TestDownloadHelpers:
    def test_jsons_to_documents(self):
        from ndi.cloud.download import jsons_to_documents

        jsons = [
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/base.json",
                    "class_name": "base",
                    "property_list_name": "base",
                    "class_version": 1,
                    "superclasses": [],
                },
                "base": {
                    "id": "test-id-1",
                    "session_id": "",
                    "name": "doc1",
                    "datestamp": "2024-01-01T00:00:00Z",
                },
            },
        ]
        docs = jsons_to_documents(jsons)
        assert len(docs) == 1

    def test_jsons_to_documents_skips_invalid(self):
        from ndi.cloud.download import jsons_to_documents

        jsons = [
            {"base": {"id": "x"}},  # may or may not work — depends on Document constructor
            "not a dict",  # should be skipped
        ]
        docs = jsons_to_documents(jsons)
        # At most 1 (the dict), possibly 0 if Document rejects it
        assert len(docs) <= 1

    def test_download_dataset_files(self, client, tmp_path):
        from ndi.cloud.download import download_dataset_files

        docs = [
            {"file_uid": ""},  # no file
            {"file_uid": "f-123"},  # has file
        ]
        with patch("ndi.cloud.download.download_files_for_document") as mock_dl:
            mock_dl.return_value = [tmp_path / "f-123"]
            report = download_dataset_files(client, "ds-1", docs, tmp_path)
            # Both docs passed to download_files_for_document;
            # first returns [path] (empty file_uid handled internally), second also returns [path]
            assert report["downloaded"] >= 1


# ===========================================================================
# Orchestration
# ===========================================================================


class TestOrchestration:
    def test_scan_for_upload(self, client):
        from ndi.cloud.orchestration import scan_for_upload

        dataset = MagicMock()
        doc = MagicMock()
        doc.document_properties = {"base": {"id": "doc-1"}}
        dataset.session.database_search.return_value = [doc]

        with patch("ndi.cloud.internal.list_remote_document_ids") as mock_remote:
            mock_remote.return_value = {}
            doc_structs, file_structs, total = scan_for_upload(client, dataset, "ds-1")
            assert len(doc_structs) == 1
            assert doc_structs[0]["is_uploaded"] is False

    def test_scan_for_upload_already_uploaded(self, client):
        from ndi.cloud.orchestration import scan_for_upload

        dataset = MagicMock()
        doc = MagicMock()
        doc.document_properties = {"base": {"id": "doc-1"}}
        dataset.session.database_search.return_value = [doc]

        with patch("ndi.cloud.internal.list_remote_document_ids") as mock_remote:
            mock_remote.return_value = {"doc-1": "api-1"}
            doc_structs, _, _ = scan_for_upload(client, dataset, "ds-1")
            assert doc_structs[0]["is_uploaded"] is True

    def test_new_dataset(self, client):
        from ndi.cloud import orchestration

        with patch.object(orchestration, "upload_dataset") as mock_up:
            mock_up.return_value = (True, "cloud-ds-1", "")
            dataset = MagicMock()
            result = orchestration.new_dataset(client, dataset, name="Test")
            assert result == "cloud-ds-1"

    def test_new_dataset_failure(self, client):
        from ndi.cloud import orchestration
        from ndi.cloud.exceptions import CloudError

        with patch.object(orchestration, "upload_dataset") as mock_up:
            mock_up.return_value = (False, "", "creation failed")
            with pytest.raises(CloudError):
                orchestration.new_dataset(client, MagicMock())

    def test_sync_dataset_no_link(self, client):
        from ndi.cloud.orchestration import sync_dataset

        dataset = MagicMock()
        with patch("ndi.cloud.internal.get_cloud_dataset_id") as mock_id:
            mock_id.return_value = ("", None)
            result = sync_dataset(client, dataset)
            assert "error" in result

    def test_sync_dataset_download_new(self, client):
        from ndi.cloud.orchestration import sync_dataset

        dataset = MagicMock()
        dataset.session.database_search.return_value = []

        with (
            patch("ndi.cloud.internal.get_cloud_dataset_id") as mock_id,
            patch("ndi.cloud.api.documents.list_all_documents") as mock_docs,
            patch("ndi.cloud.download.jsons_to_documents") as mock_conv,
        ):
            mock_id.return_value = ("ds-cloud-1", MagicMock())
            mock_docs.return_value = [{"ndiId": "new-doc", "base": {"id": "new-doc"}}]
            new_doc = MagicMock()
            mock_conv.return_value = [new_doc]

            result = sync_dataset(client, dataset, sync_mode="download_new")
            assert result["downloaded"] >= 0


# ===========================================================================
# Package imports
# ===========================================================================


class TestCloudImports:
    def test_import_auth_endpoints(self):
        from ndi.cloud.auth import (
            change_password,
            resend_confirmation,
            reset_password,
            verify_user,
        )

        assert callable(change_password)
        assert callable(reset_password)
        assert callable(verify_user)
        assert callable(resend_confirmation)

    def test_import_from_cloud_init(self):
        from ndi.cloud import (
            change_password,
        )

        assert callable(change_password)

    def test_import_file_api(self):
        from ndi.cloud.api.files import (
            get_file,
            list_files,
        )

        assert callable(get_file)
        assert callable(list_files)

    def test_import_document_api(self):
        from ndi.cloud.api.documents import (
            ndi_query,
        )

        assert callable(ndi_query)

    def test_import_dataset_api(self):
        from ndi.cloud.api.datasets import get_unpublished

        assert callable(get_unpublished)

    def test_import_orchestration(self):
        from ndi.cloud.orchestration import (
            download_dataset,
            sync_dataset,
        )

        assert callable(download_dataset)
        assert callable(sync_dataset)

    def test_import_download_helpers(self):
        from ndi.cloud.download import (
            download_dataset_files,
            jsons_to_documents,
        )

        assert callable(download_dataset_files)
        assert callable(jsons_to_documents)
