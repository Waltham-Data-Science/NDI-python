"""
Tests for cloud functions that had zero or mock-only test coverage.

Covers:
- upload_files_for_documents (upload.py)
- upload_single_file (upload.py) — expanded beyond test_phase2_gaps
- bulk_upload (api/documents.py)
- create_remote_dataset_doc (internal.py)
- get_cloud_dataset_id (internal.py)
- download_files_for_document (download.py)
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# =========================================================================
# upload_files_for_documents
# =========================================================================

class TestUploadFilesForDocuments:
    """Tests for ndi.cloud.upload.upload_files_for_documents."""

    def test_no_file_uid_skips(self):
        """Documents without file_uid are silently skipped."""
        from ndi.cloud.upload import upload_files_for_documents

        client = MagicMock()
        docs = [{'id': 'doc1'}, {'id': 'doc2', 'file_uid': ''}]
        report = upload_files_for_documents(client, 'org1', 'ds1', docs)
        assert report['uploaded'] == 0
        assert report['failed'] == 0

    def test_uploads_docs_with_file_uid(self):
        """Documents with file_uid and file_path trigger upload."""
        from ndi.cloud.upload import upload_files_for_documents

        client = MagicMock()
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(b'test data')
            file_path = f.name

        docs = [
            {'id': 'doc1', 'file_uid': 'uid1', 'file_path': file_path},
            {'id': 'doc2', 'file_uid': 'uid2', 'file_path': file_path},
        ]

        with patch('ndi.cloud.api.files.get_upload_url', return_value='https://s3.example.com/upload'):
            with patch('ndi.cloud.api.files.put_file', return_value=True):
                report = upload_files_for_documents(client, 'org1', 'ds1', docs)

        assert report['uploaded'] == 2
        assert report['failed'] == 0
        Path(file_path).unlink(missing_ok=True)

    def test_upload_failure_increments_failed(self):
        """Failed uploads increment the failed counter."""
        from ndi.cloud.upload import upload_files_for_documents

        client = MagicMock()
        docs = [{'id': 'doc1', 'file_uid': 'uid1', 'file_path': '/nonexistent'}]

        with patch('ndi.cloud.api.files.get_upload_url', side_effect=Exception('bad')):
            report = upload_files_for_documents(client, 'org1', 'ds1', docs)

        assert report['failed'] == 1
        assert report['uploaded'] == 0
        assert len(report['errors']) == 1

    def test_mixed_docs(self):
        """Mix of docs with and without file_uid."""
        from ndi.cloud.upload import upload_files_for_documents

        client = MagicMock()
        docs = [
            {'id': 'doc1'},
            {'id': 'doc2', 'file_uid': 'uid2', 'file_path': '/tmp/f'},
            {'id': 'doc3', 'file_uid': '', 'file_path': '/tmp/f'},
        ]

        with patch('ndi.cloud.api.files.get_upload_url', return_value='https://s3/up'):
            with patch('ndi.cloud.api.files.put_file', return_value=True):
                report = upload_files_for_documents(client, 'org1', 'ds1', docs)

        # Only doc2 has both file_uid and file_path
        assert report['uploaded'] == 1


# =========================================================================
# upload_single_file
# =========================================================================

class TestUploadSingleFile:
    """Tests for ndi.cloud.upload.upload_single_file."""

    def _make_client(self):
        client = MagicMock()
        client.config = MagicMock()
        client.config.org_id = 'org-123'
        return client

    def test_direct_upload_success(self):
        """Direct (non-bulk) upload succeeds."""
        from ndi.cloud.upload import upload_single_file

        client = self._make_client()
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(b'hello')
            fpath = f.name

        with patch('ndi.cloud.api.files.get_upload_url', return_value='https://s3/u') as mock_url:
            with patch('ndi.cloud.api.files.put_file', return_value=True):
                ok, err = upload_single_file(client, 'ds1', 'uid1', fpath)

        assert ok is True
        assert err == ''
        # Verify org_id was passed
        mock_url.assert_called_once_with(client, 'org-123', 'ds1', 'uid1')
        Path(fpath).unlink(missing_ok=True)

    def test_bulk_upload_success(self):
        """Bulk upload creates zip and uses collection URL."""
        from ndi.cloud.upload import upload_single_file

        client = self._make_client()
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(b'data')
            fpath = f.name

        with patch('ndi.cloud.api.files.get_file_collection_upload_url', return_value='https://s3/bulk') as mock_url:
            with patch('ndi.cloud.api.files.put_file', return_value=True):
                ok, err = upload_single_file(
                    client, 'ds1', 'uid1', fpath, use_bulk_upload=True,
                )

        assert ok is True
        assert err == ''
        mock_url.assert_called_once_with(client, 'org-123', 'ds1')
        Path(fpath).unlink(missing_ok=True)

    def test_upload_failure_returns_error(self):
        """Failed upload returns (False, error_message)."""
        from ndi.cloud.upload import upload_single_file

        client = self._make_client()

        with patch('ndi.cloud.api.files.get_upload_url', side_effect=Exception('network error')):
            ok, err = upload_single_file(client, 'ds1', 'uid1', '/nonexistent')

        assert ok is False
        assert 'network error' in err


# =========================================================================
# bulk_upload (api/documents.py)
# =========================================================================

class TestBulkUpload:
    """Tests for ndi.cloud.api.documents.bulk_upload."""

    def test_bulk_upload_calls_post(self):
        """bulk_upload sends POST to bulk-upload endpoint."""
        from ndi.cloud.api.documents import bulk_upload

        client = MagicMock()
        client.post.return_value = {'status': 'ok', 'uploaded': 5}

        result = bulk_upload(client, 'ds1', '/tmp/docs.zip')

        client.post.assert_called_once()
        call_args = client.post.call_args
        assert 'bulk-upload' in call_args[0][0]
        assert result['status'] == 'ok'

    def test_bulk_upload_passes_zip_path(self):
        """bulk_upload passes the zip path as data."""
        from ndi.cloud.api.documents import bulk_upload

        client = MagicMock()
        client.post.return_value = {}

        bulk_upload(client, 'ds1', '/path/to/archive.zip')

        call_kwargs = client.post.call_args[1]
        assert call_kwargs['data'] == '/path/to/archive.zip'


# =========================================================================
# create_remote_dataset_doc
# =========================================================================

class TestCreateRemoteDatasetDoc:
    """Tests for ndi.cloud.internal.create_remote_dataset_doc."""

    def test_creates_document_with_correct_type(self):
        """Creates a dataset_remote Document."""
        from ndi.cloud.internal import create_remote_dataset_doc
        from ndi.document import Document

        dataset = MagicMock()
        doc = create_remote_dataset_doc('cloud-abc-123', dataset)

        assert isinstance(doc, Document)
        props = doc.document_properties
        assert props['document_class']['class_name'] == 'dataset_remote'

    def test_sets_dataset_id_field(self):
        """The dataset_id field is set to the cloud dataset ID."""
        from ndi.cloud.internal import create_remote_dataset_doc

        doc = create_remote_dataset_doc('cloud-abc-123', MagicMock())
        props = doc.document_properties
        assert props['dataset_remote']['dataset_id'] == 'cloud-abc-123'


# =========================================================================
# get_cloud_dataset_id
# =========================================================================

class TestGetCloudDatasetId:
    """Tests for ndi.cloud.internal.get_cloud_dataset_id."""

    def test_returns_id_from_remote_doc(self):
        """Extracts cloud dataset ID from a dataset_remote document."""
        from ndi.cloud.internal import get_cloud_dataset_id
        from ndi.document import Document

        # Create a real dataset_remote doc with the ID set
        remote_doc = Document('dataset_remote')
        remote_doc._set_nested_property('dataset_remote.dataset_id', 'cloud-xyz')

        # Mock the dataset's database.search to return our doc
        dataset = MagicMock()
        dataset.database.search.return_value = [remote_doc]

        client = MagicMock()
        cloud_id, doc = get_cloud_dataset_id(client, dataset)

        assert cloud_id == 'cloud-xyz'
        assert doc is remote_doc

    def test_returns_empty_when_no_remote_doc(self):
        """Returns ('', None) when no dataset_remote document exists."""
        from ndi.cloud.internal import get_cloud_dataset_id

        dataset = MagicMock()
        dataset.database.search.return_value = []

        client = MagicMock()
        cloud_id, doc = get_cloud_dataset_id(client, dataset)

        assert cloud_id == ''
        assert doc is None

    def test_returns_empty_on_exception(self):
        """Returns ('', None) on database error."""
        from ndi.cloud.internal import get_cloud_dataset_id

        dataset = MagicMock()
        dataset.database.search.side_effect = RuntimeError('db error')

        client = MagicMock()
        cloud_id, doc = get_cloud_dataset_id(client, dataset)

        assert cloud_id == ''
        assert doc is None


# =========================================================================
# download_files_for_document
# =========================================================================

class TestDownloadFilesForDocument:
    """Tests for ndi.cloud.download.download_files_for_document."""

    def _make_client(self):
        client = MagicMock()
        client.config = MagicMock()
        client.config.org_id = 'org-123'
        return client

    def test_no_file_uid_returns_empty(self):
        """Document without file_uid returns empty list."""
        from ndi.cloud.download import download_files_for_document

        client = self._make_client()
        with tempfile.TemporaryDirectory() as td:
            result = download_files_for_document(
                client, 'ds1', {'id': 'doc1'}, Path(td),
            )
        assert result == []

    def test_downloads_file_on_success(self):
        """Successful download writes file to target_dir."""
        from ndi.cloud.download import download_files_for_document

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'file contents here'

        with tempfile.TemporaryDirectory() as td:
            with patch('ndi.cloud.api.files.get_upload_url', return_value='https://s3/dl'):
                with patch('requests.get', return_value=mock_resp):
                    result = download_files_for_document(
                        client, 'ds1', {'file_uid': 'uid-abc'}, Path(td),
                    )

            assert len(result) == 1
            assert result[0].name == 'uid-abc'
            assert result[0].read_bytes() == b'file contents here'

    def test_empty_url_returns_empty(self):
        """Empty presigned URL returns empty list."""
        from ndi.cloud.download import download_files_for_document

        client = self._make_client()

        with tempfile.TemporaryDirectory() as td:
            with patch('ndi.cloud.api.files.get_upload_url', return_value=''):
                result = download_files_for_document(
                    client, 'ds1', {'file_uid': 'uid-abc'}, Path(td),
                )
        assert result == []

    def test_http_error_returns_empty(self):
        """Non-200 response returns empty list."""
        from ndi.cloud.download import download_files_for_document

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with tempfile.TemporaryDirectory() as td:
            with patch('ndi.cloud.api.files.get_upload_url', return_value='https://s3/dl'):
                with patch('requests.get', return_value=mock_resp):
                    result = download_files_for_document(
                        client, 'ds1', {'file_uid': 'uid-abc'}, Path(td),
                    )
        assert result == []


# =========================================================================
# Roundtrip: create_remote_dataset_doc -> get_cloud_dataset_id
# =========================================================================

class TestRemoteDocRoundtrip:
    """Test that create and read use the same field name."""

    def test_create_then_get_roundtrip(self):
        """create_remote_dataset_doc -> get_cloud_dataset_id roundtrip."""
        from ndi.cloud.internal import create_remote_dataset_doc, get_cloud_dataset_id

        doc = create_remote_dataset_doc('cloud-roundtrip-id', MagicMock())

        # Simulate database returning this doc
        dataset = MagicMock()
        dataset.database.search.return_value = [doc]

        client = MagicMock()
        cloud_id, returned_doc = get_cloud_dataset_id(client, dataset)

        assert cloud_id == 'cloud-roundtrip-id'
        assert returned_doc is doc
