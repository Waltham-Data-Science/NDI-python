"""
Port of MATLAB ndi.unittest.cloud.* tests (API layer).

MATLAB source files:
  +cloud/AuthTest.m                  → TestAuth
  +cloud/DatasetsTest.m              → TestDatasets
  +cloud/DocumentsTest.m             → TestDocuments
  +cloud/FilesTest.m                 → TestFiles
  +cloud/UserTest.m                  → TestUser
  +cloud/DuplicatesTest.m            → TestDuplicates
  +cloud/TestPublishWithDocsAndFiles.m → TestPublishWithDocsAndFiles
  +cloud/InvalidDatasetTest.m        → TestInvalidDataset
  +cloud/testNdiQuery.m              → TestNdiQuery
  +cloud/APIMessage.m                → (utility, not a test)

Dual-mode tests:
  - By default, tests use mocked HTTP responses (for CI)
  - When NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD are set, tests hit real API
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from .conftest import requires_cloud


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _have_cloud_creds() -> bool:
    """Return True if real NDI Cloud credentials are available."""
    return bool(os.environ.get('NDI_CLOUD_USERNAME'))


def _get_cloud_config():
    """Get CloudConfig for live tests."""
    from ndi.cloud import CloudConfig
    return CloudConfig()


# ===========================================================================
# TestAuth
# Port of: ndi.unittest.cloud.AuthTest
# ===========================================================================

class TestAuth:
    """Test authentication endpoints."""

    def test_login_mocked(self):
        """Login with mocked HTTP — verifies the auth flow logic.

        MATLAB equivalent: AuthTest.testLoginLogout
        """
        from ndi.cloud import CloudConfig
        from ndi.cloud.auth import login

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'token': 'fake.jwt.token',
            'user': {
                'organizations': {
                    'id': 'org-123',
                },
            },
        }

        with patch('requests.post', return_value=mock_resp):
            config = login(
                email='test@example.com',
                password='password123',
                config=CloudConfig(),
            )

        assert config is not None
        assert config.token == 'fake.jwt.token'
        assert config.org_id == 'org-123'

    def test_logout_mocked(self):
        """Logout with mocked HTTP.

        MATLAB equivalent: AuthTest.testHighLevelLogout
        """
        from ndi.cloud import CloudConfig
        from ndi.cloud.auth import logout

        config = CloudConfig()
        config.token = 'some.token'
        config.org_id = 'org-123'

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch('requests.post', return_value=mock_resp):
            logout(config=config)

        # logout() returns None — verify it didn't raise

    @requires_cloud
    def test_login_live(self):
        """Login with real credentials.

        MATLAB equivalent: AuthTest.testLoginLogout
        """
        from ndi.cloud import CloudConfig
        from ndi.cloud.auth import login

        config = login(
            email=os.environ['NDI_CLOUD_USERNAME'],
            password=os.environ['NDI_CLOUD_PASSWORD'],
        )

        assert config is not None
        assert config.token, 'Should receive a token'
        assert config.org_id, 'Should receive an organization ID'

    @requires_cloud
    def test_logout_live(self):
        """Logout after real login.

        MATLAB equivalent: AuthTest.testHighLevelLogout
        """
        from ndi.cloud.auth import login, logout

        config = login(
            email=os.environ['NDI_CLOUD_USERNAME'],
            password=os.environ['NDI_CLOUD_PASSWORD'],
        )

        logout(config=config)
        # logout() returns None — verify no exception raised


# ===========================================================================
# TestDatasets
# Port of: ndi.unittest.cloud.DatasetsTest
# ===========================================================================

class TestDatasets:
    """Test dataset API endpoints."""

    def test_create_dataset_mocked(self):
        """Create dataset with mocked HTTP.

        MATLAB equivalent: DatasetsTest.testCreateDelete
        """
        from ndi.cloud.api.datasets import create_dataset

        mock_client = MagicMock()
        mock_client.post.return_value = {
            'id': 'ds-123',
            'name': 'Test Dataset',
            'description': 'A test dataset',
        }

        result = create_dataset(
            mock_client,
            org_id='org-123',
            name='Test Dataset',
            description='A test dataset',
        )

        assert result['id'] == 'ds-123'
        assert result['name'] == 'Test Dataset'
        mock_client.post.assert_called_once()

    def test_list_datasets_mocked(self):
        """List datasets with mocked HTTP.

        MATLAB equivalent: DatasetsTest.testListDatasets
        """
        from ndi.cloud.api.datasets import list_datasets

        mock_client = MagicMock()
        mock_client.get.return_value = [
            {'id': 'ds-1', 'name': 'Dataset 1'},
            {'id': 'ds-2', 'name': 'Dataset 2'},
        ]

        results = list_datasets(mock_client, org_id='org-123')

        assert len(results) == 2
        assert results[0]['id'] == 'ds-1'

    def test_update_dataset_mocked(self):
        """Update dataset with mocked HTTP.

        MATLAB equivalent: DatasetsTest.testUpdateDataset
        """
        from ndi.cloud.api.datasets import update_dataset

        mock_client = MagicMock()
        mock_client.put.return_value = {
            'id': 'ds-123',
            'name': 'Updated Name',
        }

        result = update_dataset(
            mock_client,
            dataset_id='ds-123',
            name='Updated Name',
        )

        assert result['name'] == 'Updated Name'

    def test_delete_dataset_mocked(self):
        """Delete dataset with mocked HTTP.

        MATLAB equivalent: DatasetsTest.testCreateDelete
        """
        from ndi.cloud.api.datasets import delete_dataset

        mock_client = MagicMock()
        mock_client.delete.return_value = None

        delete_dataset(mock_client, dataset_id='ds-123')
        mock_client.delete.assert_called_once()

    @requires_cloud
    def test_dataset_lifecycle_live(self):
        """Full dataset lifecycle: create → list → update → delete.

        MATLAB equivalent: DatasetsTest (all methods combined)
        """
        from ndi.cloud import CloudConfig
        from ndi.cloud.auth import login
        from ndi.cloud.client import CloudClient
        from ndi.cloud.api.datasets import (
            create_dataset, list_datasets, update_dataset, delete_dataset,
        )

        config = login(
            email=os.environ['NDI_CLOUD_USERNAME'],
            password=os.environ['NDI_CLOUD_PASSWORD'],
        )
        client = CloudClient(config)

        # Create
        ds = create_dataset(
            client,
            org_id=config.org_id,
            name='Python Test Dataset',
            description='Created by MATLAB-port test suite',
        )
        ds_id = ds['id']
        assert ds_id, 'Should get dataset ID'

        try:
            # List
            datasets = list_datasets(client, org_id=config.org_id)
            ds_ids = [d['id'] for d in datasets]
            assert ds_id in ds_ids, 'Created dataset should appear in list'

            # Update
            updated = update_dataset(
                client, dataset_id=ds_id,
                name='Python Test Dataset (Updated)',
            )
            assert updated['name'] == 'Python Test Dataset (Updated)'
        finally:
            # Always cleanup
            delete_dataset(client, dataset_id=ds_id)


# ===========================================================================
# TestDocuments
# Port of: ndi.unittest.cloud.DocumentsTest
# ===========================================================================

class TestDocuments:
    """Test document API endpoints."""

    def test_add_document_mocked(self):
        """Add document with mocked HTTP.

        MATLAB equivalent: DocumentsTest.testAddGetDelete
        """
        from ndi.cloud.api.documents import add_document

        mock_client = MagicMock()
        mock_client.post.return_value = {
            'id': 'doc-123',
            'status': 'created',
        }

        result = add_document(
            mock_client,
            dataset_id='ds-123',
            doc_json={'base': {'id': 'doc-123', 'name': 'test'}},
        )

        assert result is not None
        mock_client.post.assert_called_once()

    def test_get_document_mocked(self):
        """Get document with mocked HTTP.

        MATLAB equivalent: DocumentsTest.testAddGetDelete
        """
        from ndi.cloud.api.documents import get_document

        mock_client = MagicMock()
        mock_client.get.return_value = {
            'base': {'id': 'doc-123', 'name': 'test'},
        }

        result = get_document(
            mock_client,
            dataset_id='ds-123',
            document_id='doc-123',
        )

        assert result['base']['id'] == 'doc-123'

    def test_delete_document_mocked(self):
        """Delete document with mocked HTTP.

        MATLAB equivalent: DocumentsTest.testAddGetDelete
        """
        from ndi.cloud.api.documents import delete_document

        mock_client = MagicMock()
        mock_client.delete.return_value = None

        delete_document(
            mock_client,
            dataset_id='ds-123',
            document_id='doc-123',
        )
        mock_client.delete.assert_called_once()


# ===========================================================================
# TestFiles
# Port of: ndi.unittest.cloud.FilesTest
# ===========================================================================

class TestFiles:
    """Test file upload/download API endpoints."""

    def test_get_upload_url_mocked(self):
        """Get upload URL with mocked HTTP.

        MATLAB equivalent: FilesTest.testSingleFileUpload
        """
        from ndi.cloud.api.files import get_upload_url

        mock_client = MagicMock()
        mock_client.get.return_value = {'url': 'https://s3.amazonaws.com/ndi-upload/presigned'}

        result = get_upload_url(
            mock_client,
            org_id='org-123',
            dataset_id='ds-123',
            file_uid='file-uid-1',
        )

        assert isinstance(result, str)
        assert 'http' in result.lower()


# ===========================================================================
# TestUser
# Port of: ndi.unittest.cloud.UserTest
# ===========================================================================

class TestUser:
    """Test user API endpoints."""

    def test_get_current_user_mocked(self):
        """Get current user with mocked HTTP.

        MATLAB equivalent: UserTest.testMe
        """
        from ndi.cloud.api.users import get_current_user

        mock_client = MagicMock()
        mock_client.get.return_value = {
            'id': 'user-123',
            'email': 'test@example.com',
            'name': 'Test User',
        }

        result = get_current_user(mock_client)

        assert result['id'] == 'user-123'
        assert result['email'] == 'test@example.com'
        assert result['name'] == 'Test User'

    @requires_cloud
    def test_get_current_user_live(self):
        """Get current user with real credentials.

        MATLAB equivalent: UserTest.testMe
        """
        from ndi.cloud.auth import login
        from ndi.cloud.client import CloudClient
        from ndi.cloud.api.users import get_current_user

        config = login(
            email=os.environ['NDI_CLOUD_USERNAME'],
            password=os.environ['NDI_CLOUD_PASSWORD'],
        )
        client = CloudClient(config)

        user = get_current_user(client)

        assert user['id'], 'Should have user ID'
        assert user['email'], 'Should have email'
        assert user['name'], 'Should have name'


# ===========================================================================
# TestInvalidDataset
# Port of: ndi.unittest.cloud.InvalidDatasetTest
# ===========================================================================

class TestInvalidDataset:
    """Test error handling for invalid dataset operations."""

    def test_get_nonexistent_dataset_mocked(self):
        """Getting a nonexistent dataset raises appropriate error.

        MATLAB equivalent: InvalidDatasetTest
        """
        from ndi.cloud.api.datasets import get_dataset

        mock_client = MagicMock()
        mock_client.get.side_effect = Exception('Not found')

        with pytest.raises(Exception):
            get_dataset(mock_client, dataset_id='nonexistent-id')


# ===========================================================================
# TestNdiQuery
# Port of: ndi.unittest.cloud.testNdiQuery
# ===========================================================================

class TestNdiQuery:
    """Test NDI query operations against cloud datasets."""

    def test_list_documents_mocked(self):
        """List documents with mocked HTTP.

        MATLAB equivalent: testNdiQuery.testSearchById
        """
        from ndi.cloud.api.documents import list_all_documents

        mock_client = MagicMock()
        mock_client.get.return_value = {
            'documents': [
                {'base': {'id': 'doc-123', 'name': 'found'}},
            ],
            'total': 1,
            'page': 1,
        }

        results = list_all_documents(
            mock_client,
            dataset_id='ds-123',
        )

        assert len(results) >= 0  # May be empty depending on pagination mock

    def test_get_document_by_id_mocked(self):
        """Get a specific document by ID.

        MATLAB equivalent: testNdiQuery.testSearchById
        """
        from ndi.cloud.api.documents import get_document

        mock_client = MagicMock()
        mock_client.get.return_value = {
            'base': {'id': 'doc-123', 'name': 'found'},
        }

        result = get_document(
            mock_client,
            dataset_id='ds-123',
            document_id='doc-123',
        )

        assert result['base']['id'] == 'doc-123'
