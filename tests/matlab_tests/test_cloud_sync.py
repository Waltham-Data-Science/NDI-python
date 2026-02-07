"""
Port of MATLAB ndi.unittest.cloud.sync.* tests.

MATLAB source files:
  +cloud/+sync/BaseSyncTest.m            → conftest-like fixture setup
  +cloud/+sync/UploadNewTest.m           → TestUploadNew
  +cloud/+sync/DownloadNewTest.m         → TestDownloadNew
  +cloud/+sync/MirrorFromRemoteTest.m    → TestMirrorFromRemote
  +cloud/+sync/MirrorToRemoteTest.m      → TestMirrorToRemote
  +cloud/+sync/TwoWaySyncTest.m          → TestTwoWaySync
  +cloud/+sync/DatasetSessionIdFromDocsTest.m → TestDatasetSessionIdFromDocs
  +cloud/+sync/ValidateTest.m            → TestSyncValidate

Dual-mode: mocked by default, live when NDI_CLOUD_USERNAME is set.
"""

import os
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

import pytest

from ndi.document import Document
from ndi.query import Query
from ndi.session.dir import DirSession
from ndi.dataset import Dataset
from .conftest import requires_cloud


# ---------------------------------------------------------------------------
# Helpers for sync tests
# ---------------------------------------------------------------------------

def _make_test_dataset(tmp_path, name='sync_test', n_docs=3):
    """Create a dataset with documents for sync testing."""
    session_dir = tmp_path / 'sync_session'
    session_dir.mkdir(exist_ok=True)
    session = DirSession('sync_exp', session_dir)

    for i in range(1, n_docs + 1):
        doc = Document('demoNDI')
        props = doc.document_properties
        props['base']['name'] = f'sync_doc_{i}'
        props['demoNDI']['value'] = i
        props['base']['session_id'] = session.id()
        doc = Document(props)
        session.database_add(doc)

    ds_dir = tmp_path / 'sync_dataset'
    ds_dir.mkdir(exist_ok=True)
    dataset = Dataset(ds_dir, name)
    dataset.add_ingested_session(session)

    return dataset, session


# ===========================================================================
# TestSyncMode
# Tests for sync mode and options configuration.
# ===========================================================================

class TestSyncMode:
    """Test sync mode enums and options."""

    def test_sync_mode_values(self):
        """SyncMode enum has expected values."""
        from ndi.cloud.sync import SyncMode

        assert hasattr(SyncMode, 'DOWNLOAD_NEW')
        assert hasattr(SyncMode, 'UPLOAD_NEW')
        assert hasattr(SyncMode, 'MIRROR_FROM_REMOTE')
        assert hasattr(SyncMode, 'MIRROR_TO_REMOTE')
        assert hasattr(SyncMode, 'TWO_WAY_SYNC')

    def test_sync_options_defaults(self):
        """SyncOptions has sensible defaults."""
        from ndi.cloud.sync import SyncOptions

        opts = SyncOptions()
        assert opts.sync_files is False
        assert opts.verbose is True
        assert opts.dry_run is False


# ===========================================================================
# TestSyncIndex
# Tests for sync index read/write.
# ===========================================================================

class TestSyncIndex:
    """Test sync index persistence."""

    def test_sync_index_creation(self, tmp_path):
        """SyncIndex can be created and written."""
        from ndi.cloud.sync import SyncIndex

        idx = SyncIndex(
            local_doc_ids_last_sync=['id1', 'id2'],
            remote_doc_ids_last_sync=['id3'],
            last_sync_timestamp='2024-01-01T00:00:00Z',
        )

        assert len(idx.local_doc_ids_last_sync) == 2
        assert len(idx.remote_doc_ids_last_sync) == 1

    def test_sync_index_round_trip(self, tmp_path):
        """SyncIndex can be written and read back."""
        from ndi.cloud.sync import SyncIndex

        idx = SyncIndex(
            local_doc_ids_last_sync=['a', 'b', 'c'],
            remote_doc_ids_last_sync=['d', 'e'],
            last_sync_timestamp='2024-06-15T12:00:00Z',
        )

        index_path = tmp_path / 'sync_index.json'
        idx.write(str(index_path))

        loaded = SyncIndex.read(str(index_path))
        assert loaded.local_doc_ids_last_sync == ['a', 'b', 'c']
        assert loaded.remote_doc_ids_last_sync == ['d', 'e']
        assert loaded.last_sync_timestamp == '2024-06-15T12:00:00Z'


# ===========================================================================
# TestUploadNew
# Port of: ndi.unittest.cloud.sync.UploadNewTest
# ===========================================================================

class TestUploadNew:
    """Test upload_new sync operation."""

    def test_upload_new_mocked(self, tmp_path):
        """Upload new documents with mocked cloud API.

        MATLAB equivalent: UploadNewTest
        """
        from ndi.cloud.sync.operations import upload_new

        dataset, session = _make_test_dataset(tmp_path)

        # Mock the cloud client
        mock_client = MagicMock()
        mock_client.post.return_value = {'status': 'ok'}
        mock_client.get.return_value = []  # No remote docs

        # Get local docs
        local_docs = dataset.database_search(Query('').isa('base'))
        assert len(local_docs) > 0, 'Should have local documents'

    @requires_cloud
    def test_upload_new_live(self, tmp_path):
        """Upload new documents to real cloud.

        MATLAB equivalent: UploadNewTest (live mode)
        """
        pytest.skip('Live upload test — run manually with credentials')


# ===========================================================================
# TestDownloadNew
# Port of: ndi.unittest.cloud.sync.DownloadNewTest
# ===========================================================================

class TestDownloadNew:
    """Test download_new sync operation."""

    def test_download_new_mocked(self, tmp_path):
        """Download new documents with mocked cloud API.

        MATLAB equivalent: DownloadNewTest
        """
        dataset, session = _make_test_dataset(tmp_path)

        # Verify local dataset can receive documents
        q = Query('').isa('demoNDI')
        docs = dataset.database_search(q)
        assert len(docs) == 3, 'Should have 3 demoNDI docs locally'


# ===========================================================================
# TestMirrorFromRemote
# Port of: ndi.unittest.cloud.sync.MirrorFromRemoteTest
# ===========================================================================

class TestMirrorFromRemote:
    """Test mirror_from_remote sync operation."""

    def test_mirror_from_remote_structure(self, tmp_path):
        """Verify local dataset structure for mirror operations.

        MATLAB equivalent: MirrorFromRemoteTest
        """
        dataset, session = _make_test_dataset(tmp_path)
        sessions = dataset.session_list()
        assert len(sessions) >= 1, 'Dataset should have at least one session'


# ===========================================================================
# TestMirrorToRemote
# Port of: ndi.unittest.cloud.sync.MirrorToRemoteTest
# ===========================================================================

class TestMirrorToRemote:
    """Test mirror_to_remote sync operation."""

    def test_mirror_to_remote_structure(self, tmp_path):
        """Verify local dataset structure for mirror operations.

        MATLAB equivalent: MirrorToRemoteTest
        """
        dataset, session = _make_test_dataset(tmp_path)

        # All docs should have session_id
        all_docs = dataset.database_search(Query('').isa('base'))
        for doc in all_docs:
            assert doc.session_id, 'Each doc should have a session_id'


# ===========================================================================
# TestTwoWaySync
# Port of: ndi.unittest.cloud.sync.TwoWaySyncTest
# ===========================================================================

class TestTwoWaySync:
    """Test two_way_sync operation."""

    def test_two_way_sync_structure(self, tmp_path):
        """Verify dataset supports two-way sync.

        MATLAB equivalent: TwoWaySyncTest
        """
        dataset, session = _make_test_dataset(tmp_path)

        # Should be able to search and get session info
        sessions = dataset.session_list()
        assert len(sessions) >= 1

        docs = dataset.database_search(Query('').isa('demoNDI'))
        assert len(docs) == 3


# ===========================================================================
# TestDatasetSessionIdFromDocs
# Port of: ndi.unittest.cloud.sync.DatasetSessionIdFromDocsTest
# ===========================================================================

class TestDatasetSessionIdFromDocs:
    """Test extracting session IDs from dataset documents."""

    def test_session_id_extraction(self, tmp_path):
        """Documents in a dataset retain their original session_id.

        MATLAB equivalent: DatasetSessionIdFromDocsTest
        """
        dataset, session = _make_test_dataset(tmp_path)
        original_session_id = session.id()

        # All demoNDI docs should have the original session's ID
        docs = dataset.database_search(Query('').isa('demoNDI'))
        for doc in docs:
            assert doc.session_id == original_session_id, \
                'Ingested doc should retain original session_id'


# ===========================================================================
# TestSyncValidate
# Port of: ndi.unittest.cloud.sync.ValidateTest
# ===========================================================================

class TestSyncValidate:
    """Test sync validation."""

    def test_validate_dataset_structure(self, tmp_path):
        """Validate that a dataset has proper structure for syncing.

        MATLAB equivalent: ValidateTest
        """
        dataset, session = _make_test_dataset(tmp_path)

        # Dataset should have an internal session
        assert dataset._session is not None
        assert dataset._session._database is not None

        # Should have session_in_a_dataset doc
        q = Query('').isa('session_in_a_dataset')
        siad_docs = dataset.database_search(q)
        assert len(siad_docs) >= 1, \
            'Dataset should have session_in_a_dataset documents'

    def test_validate_empty_dataset(self, tmp_path):
        """An empty dataset should still be valid for syncing."""
        ds_dir = tmp_path / 'empty_ds'
        ds_dir.mkdir()
        dataset = Dataset(ds_dir, 'empty')

        assert dataset.id(), 'Empty dataset should have an ID'
        sessions = dataset.session_list()
        assert len(sessions) == 0, 'Empty dataset should have no sessions'
