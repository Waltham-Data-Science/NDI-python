"""
Port of MATLAB ndi.unittest.session.* tests.

MATLAB source files:
  +session/buildSession.m              → conftest.py fixtures
  +session/TestDeleteSession.m         → TestDeleteSession
  +session/testIsIngestedInDataset.m   → TestIsIngestedInDataset
  +session/buildSessionNDRAxon.m       → skipped (DAQ-reader variant)
  +session/buildSessionNDRIntan.m      → skipped (DAQ-reader variant)
"""

import pytest

from ndi.dataset import Dataset
from ndi.document import Document
from ndi.query import Query
from ndi.session.dir import DirSession

# ===========================================================================
# TestDeleteSession
# Port of: ndi.unittest.session.TestDeleteSession
# ===========================================================================


class TestDeleteSession:
    """Test deletion of session data structures."""

    def test_delete_no_confirm(self, tmp_path):
        """Calling delete with are_you_sure=False should NOT delete.

        MATLAB equivalent: TestDeleteSession.testDeleteNoConfirm
        """
        session_dir = tmp_path / "del_session"
        session_dir.mkdir()
        session = DirSession("del_test", session_dir)

        ndi_dir = session_dir / ".ndi"
        assert ndi_dir.exists(), ".ndi directory should exist before delete"

        # Not confirmed — should not delete
        result = session.delete_session_data_structures(are_you_sure=False, ask_user=False)

        assert ndi_dir.exists(), ".ndi directory should still exist after unconfirmed delete"
        assert result is not None, "Should return self (not deleted)"

    def test_delete_confirm(self, tmp_path):
        """Calling delete with are_you_sure=True should delete .ndi dir.

        MATLAB equivalent: TestDeleteSession.testDeleteConfirm
        """
        session_dir = tmp_path / "del_session"
        session_dir.mkdir()
        session = DirSession("del_test", session_dir)

        ndi_dir = session_dir / ".ndi"
        assert ndi_dir.exists(), ".ndi directory should exist before delete"

        session.delete_session_data_structures(are_you_sure=True, ask_user=False)

        assert not ndi_dir.exists(), ".ndi directory should be gone after confirmed delete"

    def test_delete_preserves_data_files(self, tmp_path):
        """Deleting session structures should NOT remove user data files.

        MATLAB equivalent: TestDeleteSession.testDeleteConfirm (extended)
        """
        session_dir = tmp_path / "del_session"
        session_dir.mkdir()
        session = DirSession("del_test", session_dir)

        # Create a user data file
        data_file = session_dir / "my_data.txt"
        data_file.write_text("important data")

        session.delete_session_data_structures(are_you_sure=True, ask_user=False)

        assert data_file.exists(), "User data files should be preserved"
        assert data_file.read_text() == "important data"


# ===========================================================================
# TestIsIngestedInDataset
# Port of: ndi.unittest.session.testIsIngestedInDataset
#
# NOTE: Python does not have a direct session.is_ingested_in_dataset()
# method. This test verifies the equivalent behavior by checking the
# dataset's session_list.
# ===========================================================================


class TestIsIngestedInDataset:
    """Test session ingestion detection."""

    def test_standalone_session_not_in_dataset(self, tmp_path):
        """A standalone session is not ingested in any dataset.

        MATLAB equivalent: testIsIngestedInDataset.testIsIngestedInDatasetLogic (part 1)
        """
        session_dir = tmp_path / "standalone"
        session_dir.mkdir()
        session = DirSession("standalone", session_dir)

        # Create a dataset without the session
        ds_dir = tmp_path / "ds_empty"
        ds_dir.mkdir()
        dataset = Dataset(ds_dir, "ds_empty")

        sessions = dataset.session_list()
        session_ids = [s["session_id"] for s in sessions]
        assert session.id() not in session_ids, "Standalone session should not be in dataset"

    def test_ingested_session_in_dataset(self, tmp_path):
        """An ingested session appears in the dataset session list.

        MATLAB equivalent: testIsIngestedInDataset.testIsIngestedInDatasetLogic (part 2)
        """
        # Create session with a doc
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        session = DirSession("exp", session_dir)

        doc = Document("demoNDI")
        props = doc.document_properties
        props["base"]["name"] = "test_doc"
        props["demoNDI"]["value"] = 42
        props["base"]["session_id"] = session.id()
        doc = Document(props)
        session.database_add(doc)

        # Create dataset and ingest
        ds_dir = tmp_path / "ds"
        ds_dir.mkdir()
        dataset = Dataset(ds_dir, "ds")
        dataset.add_ingested_session(session)

        sessions = dataset.session_list()
        session_ids = [s["session_id"] for s in sessions]
        assert session.id() in session_ids, "Ingested session should appear in dataset session list"

        # Also verify the document was ingested
        q = Query("").isa("demoNDI")
        docs = dataset.database_search(q)
        assert len(docs) == 1
        assert docs[0].document_properties["base"]["name"] == "test_doc"

    def test_linked_session_in_dataset(self, tmp_path):
        """A linked session appears in the dataset session list as linked."""
        session_dir = tmp_path / "linked_sess"
        session_dir.mkdir()
        session = DirSession("linked", session_dir)

        ds_dir = tmp_path / "ds_link"
        ds_dir.mkdir()
        dataset = Dataset(ds_dir, "ds_link")
        dataset.add_linked_session(session)

        sessions = dataset.session_list()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == session.id()
        assert sessions[0]["is_linked"] is True


# ===========================================================================
# TestSessionBasics
# Port of: ndi.unittest.session.buildSession (verification tests)
# ===========================================================================


class TestSessionBasics:
    """Test basic session creation and properties."""

    def test_session_creation(self, tmp_path):
        """DirSession can be created with reference and path."""
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        session = DirSession("my_session", session_dir)

        assert session.reference == "my_session"
        assert session.path == session_dir
        assert session.id()  # non-empty
        assert isinstance(session.id(), str)

    def test_session_has_ndi_directory(self, tmp_path):
        """DirSession creates a .ndi directory for database storage."""
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        DirSession("my_session", session_dir)

        ndi_dir = session_dir / ".ndi"
        assert ndi_dir.exists(), ".ndi directory should be created"

    def test_session_reopens_with_same_id(self, tmp_path):
        """Reopening a session from the same path gives the same ID."""
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        s1 = DirSession("my_session", session_dir)
        original_id = s1.id()

        # Reopen
        s2 = DirSession("my_session", session_dir)
        assert s2.id() == original_id, "Reopened session should have same ID"

    def test_session_requires_existing_directory(self, tmp_path):
        """DirSession raises ValueError for non-existent path."""
        nonexistent = tmp_path / "does_not_exist"

        with pytest.raises(ValueError):
            DirSession("bad_session", nonexistent)

    def test_newdocument(self, tmp_path):
        """Session.newdocument() creates a document with session_id set."""
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        session = DirSession("my_session", session_dir)

        doc = session.newdocument(
            "demoNDI",
            **{
                "base.name": "test",
                "demoNDI.value": 99,
            },
        )

        assert doc.session_id == session.id(), "newdocument should set session_id"
        assert doc.document_properties["base"]["name"] == "test"

    def test_creator_args(self, tmp_path):
        """DirSession.creator_args() returns the construction arguments."""
        session_dir = tmp_path / "sess"
        session_dir.mkdir()
        session = DirSession("my_session", session_dir)

        args = session.creator_args()
        assert len(args) >= 2
        assert args[0] == "my_session"
        assert str(session_dir) in str(args[1])
