"""
Tests for Phase 10 Batch 2: Cloud API Layer.

Tests datasets, documents, files, users, and compute API modules.
All HTTP interactions are mocked via CloudClient fixture.
"""

from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.api import compute, datasets, documents, files, users
from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudUploadError

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """CloudClient with a mocked requests.Session."""
    cfg = CloudConfig(
        api_url="https://api.test.ndi/v1",
        token="test.jwt.token",
        org_id="org-1",
    )
    c = CloudClient(cfg)
    c._session.request = MagicMock()
    return c


def _ok(data, status=200):
    """Create a mock response with JSON body."""
    resp = MagicMock()
    resp.status_code = status
    resp.content = b"data"
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def _no_content():
    """Create a 204 no-content mock response."""
    resp = MagicMock()
    resp.status_code = 204
    resp.content = b""
    return resp


# ===========================================================================
# Datasets
# ===========================================================================


class TestDatasets:
    def test_get_dataset(self, client):
        client._session.request.return_value = _ok({"id": "ds-1", "name": "My Dataset"})
        result = datasets.get_dataset(client, "ds-1")
        assert result["id"] == "ds-1"

    def test_create_dataset(self, client):
        client._session.request.return_value = _ok({"id": "ds-new"}, status=201)
        result = datasets.create_dataset(client, "org-1", "New Dataset", "A description")
        assert result["id"] == "ds-new"
        call_args = client._session.request.call_args
        assert call_args[1]["json"]["name"] == "New Dataset"
        assert call_args[1]["json"]["description"] == "A description"

    def test_update_dataset(self, client):
        client._session.request.return_value = _ok({"id": "ds-1", "name": "Updated"})
        result = datasets.update_dataset(client, "ds-1", name="Updated")
        assert result["name"] == "Updated"

    def test_delete_dataset(self, client):
        client._session.request.return_value = _no_content()
        assert datasets.delete_dataset(client, "ds-1") is True

    def test_list_datasets(self, client):
        client._session.request.return_value = _ok(
            {
                "totalNumber": 2,
                "datasets": [{"id": "ds-1"}, {"id": "ds-2"}],
            }
        )
        result = datasets.list_datasets(client, "org-1")
        assert len(result["datasets"]) == 2

    def test_list_all_datasets_single_page(self, client):
        client._session.request.return_value = _ok(
            {
                "totalNumber": 2,
                "datasets": [{"id": "ds-1"}, {"id": "ds-2"}],
            }
        )
        result = datasets.list_all_datasets(client, "org-1")
        assert len(result) == 2

    def test_list_all_datasets_multi_page(self, client):
        page1 = _ok({"totalNumber": 3, "datasets": [{"id": "ds-1"}, {"id": "ds-2"}]})
        page2 = _ok({"totalNumber": 3, "datasets": [{"id": "ds-3"}]})
        client._session.request.side_effect = [page1, page2]
        result = datasets.list_all_datasets(client, "org-1")
        assert len(result) == 3

    def test_get_published_datasets(self, client):
        client._session.request.return_value = _ok({"datasets": [{"id": "pub-1"}]})
        result = datasets.get_published_datasets(client)
        assert len(result["datasets"]) == 1

    def test_publish_dataset(self, client):
        client._session.request.return_value = _ok({"status": "published"})
        result = datasets.publish_dataset(client, "ds-1")
        assert result["status"] == "published"

    def test_unpublish_dataset(self, client):
        client._session.request.return_value = _ok({"status": "unpublished"})
        result = datasets.unpublish_dataset(client, "ds-1")
        assert result["status"] == "unpublished"

    def test_submit_dataset(self, client):
        client._session.request.return_value = _ok({"status": "submitted"})
        result = datasets.submit_dataset(client, "ds-1")
        assert result["status"] == "submitted"

    def test_create_branch(self, client):
        client._session.request.return_value = _ok({"id": "branch-1"})
        result = datasets.create_branch(client, "ds-1")
        assert result["id"] == "branch-1"

    def test_get_branches(self, client):
        client._session.request.return_value = _ok([{"id": "b1"}, {"id": "b2"}])
        result = datasets.get_branches(client, "ds-1")
        assert len(result) == 2


# ===========================================================================
# Documents
# ===========================================================================


class TestDocuments:
    def test_get_document(self, client):
        client._session.request.return_value = _ok({"id": "doc-1", "type": "base"})
        result = documents.get_document(client, "ds-1", "doc-1")
        assert result["id"] == "doc-1"

    def test_add_document(self, client):
        client._session.request.return_value = _ok({"id": "doc-new"}, status=201)
        result = documents.add_document(client, "ds-1", {"type": "base"})
        assert result["id"] == "doc-new"

    def test_update_document(self, client):
        client._session.request.return_value = _ok({"id": "doc-1", "updated": True})
        result = documents.update_document(client, "ds-1", "doc-1", {"name": "new"})
        assert result["updated"] is True

    def test_delete_document(self, client):
        client._session.request.return_value = _no_content()
        assert documents.delete_document(client, "ds-1", "doc-1") is True

    def test_list_documents(self, client):
        client._session.request.return_value = _ok(
            {
                "totalNumber": 5,
                "documents": [{"id": f"doc-{i}"} for i in range(5)],
            }
        )
        result = documents.list_documents(client, "ds-1")
        assert result["totalNumber"] == 5

    def test_list_all_documents_multi_page(self, client):
        page1 = _ok({"totalNumber": 3, "documents": [{"id": "d1"}, {"id": "d2"}]})
        page2 = _ok({"totalNumber": 3, "documents": [{"id": "d3"}]})
        client._session.request.side_effect = [page1, page2]
        result = documents.list_all_documents(client, "ds-1")
        assert len(result) == 3

    def test_get_document_count(self, client):
        client._session.request.return_value = _ok({"totalNumber": 42, "documents": []})
        assert documents.get_document_count(client, "ds-1") == 42

    def test_get_bulk_upload_url(self, client):
        client._session.request.return_value = _ok({"url": "https://s3.presigned/upload"})
        url = documents.get_bulk_upload_url(client, "ds-1")
        assert "presigned" in url

    def test_get_bulk_download_url(self, client):
        client._session.request.return_value = _ok({"url": "https://s3.presigned/download"})
        url = documents.get_bulk_download_url(client, "ds-1", ["doc-1", "doc-2"])
        assert "presigned" in url

    def test_bulk_delete(self, client):
        client._session.request.return_value = _ok({"deleted": 3})
        result = documents.bulk_delete(client, "ds-1", ["d1", "d2", "d3"])
        assert result["deleted"] == 3


# ===========================================================================
# Files
# ===========================================================================


class TestFiles:
    def test_get_upload_url(self, client):
        client._session.request.return_value = _ok({"url": "https://s3.upload"})
        url = files.get_upload_url(client, "org-1", "ds-1", "file-uid-1")
        assert url == "https://s3.upload"

    def test_get_bulk_upload_url(self, client):
        client._session.request.return_value = _ok({"url": "https://s3.bulk-upload"})
        url = files.get_bulk_upload_url(client, "org-1", "ds-1")
        assert url == "https://s3.bulk-upload"

    @patch("requests.put")
    def test_put_file(self, mock_put, tmp_path):
        mock_put.return_value = MagicMock(status_code=200)
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        assert files.put_file("https://s3.upload", f) is True

    @patch("requests.put")
    def test_put_file_failure(self, mock_put, tmp_path):
        mock_put.return_value = MagicMock(status_code=500, text="Server Error")
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        with pytest.raises(CloudUploadError):
            files.put_file("https://s3.upload", f)

    @patch("requests.put")
    def test_put_file_bytes(self, mock_put):
        mock_put.return_value = MagicMock(status_code=200)
        assert files.put_file_bytes("https://s3.upload", b"data") is True

    @patch("requests.put")
    def test_put_file_bytes_failure(self, mock_put):
        mock_put.return_value = MagicMock(status_code=403, text="Forbidden")
        with pytest.raises(CloudUploadError):
            files.put_file_bytes("https://s3.upload", b"data")


# ===========================================================================
# Users
# ===========================================================================


class TestUsers:
    def test_create_user(self, client):
        client._session.request.return_value = _ok({"id": "user-new"}, status=201)
        result = users.create_user(client, "new@test.com", "New User", "pass123")
        assert result["id"] == "user-new"
        body = client._session.request.call_args[1]["json"]
        assert body["email"] == "new@test.com"

    def test_get_current_user(self, client):
        client._session.request.return_value = _ok(
            {
                "id": "user-me",
                "email": "me@test.com",
                "organizations": [{"id": "org-1"}],
            }
        )
        result = users.get_current_user(client)
        assert result["email"] == "me@test.com"

    def test_get_user(self, client):
        client._session.request.return_value = _ok({"id": "user-42", "name": "Alice"})
        result = users.get_user(client, "user-42")
        assert result["name"] == "Alice"


# ===========================================================================
# Compute
# ===========================================================================


class TestCompute:
    def test_start_session(self, client):
        client._session.request.return_value = _ok({"sessionId": "sess-1", "status": "running"})
        result = compute.start_session(client, "pipeline-1")
        assert result["sessionId"] == "sess-1"
        body = client._session.request.call_args[1]["json"]
        assert body["pipelineId"] == "pipeline-1"

    def test_start_session_with_params(self, client):
        client._session.request.return_value = _ok({"sessionId": "sess-2"})
        compute.start_session(client, "pipe-1", input_params={"key": "val"})
        body = client._session.request.call_args[1]["json"]
        assert body["inputParameters"] == {"key": "val"}

    def test_get_session_status(self, client):
        client._session.request.return_value = _ok({"sessionId": "s-1", "status": "complete"})
        result = compute.get_session_status(client, "s-1")
        assert result["status"] == "complete"

    def test_trigger_stage(self, client):
        client._session.request.return_value = _ok({"status": "triggered"})
        result = compute.trigger_stage(client, "s-1", "stage-2")
        assert result["status"] == "triggered"

    def test_finalize_session(self, client):
        client._session.request.return_value = _ok({"status": "finalized"})
        result = compute.finalize_session(client, "s-1")
        assert result["status"] == "finalized"

    def test_abort_session(self, client):
        client._session.request.return_value = _ok({"status": "aborted"})
        assert compute.abort_session(client, "s-1") is True

    def test_list_sessions(self, client):
        client._session.request.return_value = _ok(
            {
                "sessions": [{"id": "s-1"}, {"id": "s-2"}],
            }
        )
        result = compute.list_sessions(client)
        assert len(result) == 2

    def test_list_sessions_direct_list(self, client):
        client._session.request.return_value = _ok([{"id": "s-1"}])
        result = compute.list_sessions(client)
        assert len(result) == 1


# ===========================================================================
# Package-level imports
# ===========================================================================


class TestAPIImports:
    def test_import_api_subpackage(self):
        from ndi.cloud import api

        assert hasattr(api, "datasets")
        assert hasattr(api, "documents")
        assert hasattr(api, "files")
        assert hasattr(api, "users")
        assert hasattr(api, "compute")

    def test_import_individual_modules(self):
        from ndi.cloud.api import compute as c
        from ndi.cloud.api import datasets as ds
        from ndi.cloud.api import documents as doc
        from ndi.cloud.api import files as f
        from ndi.cloud.api import users as u

        assert callable(ds.get_dataset)
        assert callable(doc.get_document)
        assert callable(f.get_upload_url)
        assert callable(u.get_current_user)
        assert callable(c.start_session)
