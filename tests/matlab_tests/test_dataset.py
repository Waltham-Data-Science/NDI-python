"""
Port of MATLAB ndi.unittest.dataset.* tests.

MATLAB source files:
  +dataset/testDatasetConstructor.m  → TestDatasetConstructor
  +dataset/testDatasetBuild.m        → TestDatasetBuild
  +dataset/testSessionList.m         → TestSessionList
  +dataset/testDeleteIngestedSession.m → TestDeleteIngestedSession
  +dataset/testUnlinkSession.m       → TestUnlinkSession
  +dataset/OldDatasetTest.m          → TestOldDataset (skipped — no example data)
  +dataset/buildDataset.m            → conftest.py build_dataset fixture
"""

import pytest

from ndi.dataset import ndi_dataset
from ndi.document import ndi_document
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir

# ---------------------------------------------------------------------------
# Helper — mirrors ndi.unittest.session.buildSession.addDocsWithFiles()
# ---------------------------------------------------------------------------


def _add_doc_with_file(session: ndi_session_dir, doc_number: int) -> None:
    """Add a demoNDI document with a file attachment to the session."""
    docname = f"doc_{doc_number}"
    filepath = session.path / docname
    filepath.write_text(docname)

    doc = ndi_document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = docname
    props["demoNDI"]["value"] = doc_number
    props["base"]["session_id"] = session.id()
    doc = ndi_document(props)
    doc = doc.add_file("filename1.ext", str(filepath))
    session.database_add(doc)


# ===========================================================================
# TestDatasetConstructor
# Port of: ndi.unittest.dataset.testDatasetConstructor
# ===========================================================================


class TestDatasetConstructor:
    """Test the constructor of ndi_dataset."""

    def test_constructor_with_reference(self, tmp_path):
        """Test ndi_dataset(path, reference) — 2-arg form.

        MATLAB equivalent: testConstructorWithEmptyDocs
        (MATLAB tests 2-arg and 3-arg; Python only has 2-arg and 1-arg.)
        """
        ds_path = tmp_path / "test_dataset"
        ds_path.mkdir()
        ds = ndi_dataset(ds_path, "test_ref")

        # Verify it's a valid ndi_dataset
        assert isinstance(ds, ndi_dataset)
        assert ds.getpath() == ds_path

        # Verify ID is non-empty string
        ds_id = ds.id()
        assert ds_id
        assert isinstance(ds_id, str)

    def test_constructor_path_only(self, tmp_path):
        """Test ndi_dataset(path) — reference derived from directory name."""
        ds_path = tmp_path / "my_dataset"
        ds_path.mkdir()
        ds = ndi_dataset(ds_path)

        assert isinstance(ds, ndi_dataset)
        assert ds.reference == "my_dataset"
        assert ds.getpath() == ds_path

        ds_id = ds.id()
        assert ds_id
        assert isinstance(ds_id, str)

    def test_two_datasets_have_different_ids(self, tmp_path):
        """Two separate datasets should have unique IDs."""
        ds1_path = tmp_path / "ds1"
        ds1_path.mkdir()
        ds1 = ndi_dataset(ds1_path, "ref1")

        ds2_path = tmp_path / "ds2"
        ds2_path.mkdir()
        ds2 = ndi_dataset(ds2_path, "ref2")

        assert ds1.id() != ds2.id()


# ===========================================================================
# TestDatasetBuild
# Port of: ndi.unittest.dataset.testDatasetBuild
# ===========================================================================


class TestDatasetBuild:
    """Test that buildDataset fixture creates a valid ndi_dataset + ndi_session."""

    def test_setup(self, build_dataset):
        """Verify ndi_dataset and ndi_session are created and populated.

        MATLAB equivalent: testDatasetBuild.testSetup
        - ndi_dataset is ndi.dataset.dir
        - ndi_session is ndi.session.dir
        - ndi_session appears in dataset.session_list()
        - 5 demoNDI documents are present, each with readable file content
        """
        dataset, session = build_dataset

        # Check ndi_dataset existence and type
        assert dataset is not None
        assert isinstance(dataset, ndi_dataset)

        # Check ndi_session existence and type
        assert session is not None
        assert isinstance(session, ndi_session_dir)

        # ndi_session should be in dataset's session list
        refs, session_ids, *_ = dataset.session_list()
        assert session.id() in session_ids, "ndi_session ID should be in dataset session list"

        # Should find exactly 5 demoNDI documents
        q = ndi_query("").isa("demoNDI")
        docs = dataset.database_search(q)
        assert len(docs) == 5, "Should find 5 demoNDI documents in the dataset"

        # Verify content of each document
        for i in range(1, 6):
            docname = f"doc_{i}"
            found = False
            for doc in docs:
                name = doc.document_properties.get("base", {}).get("name", "")
                if name == docname:
                    found = True
                    # Read binary file associated with the document
                    fid = dataset.database_openbinarydoc(doc, "filename1.ext")
                    content = fid.read()
                    dataset.database_closebinarydoc(fid)
                    # Content may be bytes or str
                    if isinstance(content, bytes):
                        content = content.decode("utf-8")
                    assert content == docname, f"Content of {docname} should match"
                    break
            assert found, f"ndi_document {docname} should be found"


# ===========================================================================
# TestSessionList
# Port of: ndi.unittest.dataset.testSessionList
#
# MATLAB session_list() returns (refs, ids, sess_docs, dset_doc).
# Python session_list() now also returns 4 values to match.
# ===========================================================================


class TestSessionList:
    """Test the session_list method of ndi_dataset."""

    def test_session_list_outputs(self, build_dataset):
        """Verify session_list returns correct structure and values.

        MATLAB equivalent: testSessionList.testSessionListOutputs
        """
        dataset, session = build_dataset

        refs, session_ids, *_ = dataset.session_list()

        # Should have exactly 1 session
        assert len(session_ids) == 1
        assert len(refs) == 1

        # 1. Verify session_reference
        assert refs[0] == "exp_demo", "ndi_session reference should match expected value"

        # 2. Verify session_id
        assert session_ids[0] == session.id(), "ndi_session ID should match the ingested session ID"

        # 3. Verify the session_in_a_dataset document exists and is correct
        q = ndi_query("").isa("session_in_a_dataset")
        found = dataset.database_search(q)
        assert len(found) == 1, "Should find exactly one session_in_a_dataset document"

        doc = found[0]
        props = doc.document_properties.get("session_in_a_dataset", {})

        # Check session_id in the document matches
        assert (
            props.get("session_id") == session.id()
        ), "session_in_a_dataset document should have the correct session_id"

        # Check session_reference matches
        assert props.get("session_reference") == "exp_demo", "session_reference should match"

        # Check session_creator (MATLAB-compatible name)
        assert (
            props.get("session_creator") == "ndi.session.dir"
        ), "session_creator should be ndi.session.dir"


# ===========================================================================
# TestDeleteIngestedSession
# Port of: ndi.unittest.dataset.testDeleteIngestedSession
#
# NOTE: Python API differences:
# - MATLAB: deleteIngestedSession(id, 'areYouSure', true, 'askUserToConfirm', false)
# - Python: deleteIngestedSession(id, are_you_sure=True)
# - MATLAB raises specific error IDs; Python raises ValueError
# - MATLAB raises on nonexistent session; Python returns self silently
# ===========================================================================


class TestDeleteIngestedSession:
    """Test the deleteIngestedSession method of ndi_dataset."""

    def test_delete_success(self, build_dataset):
        """Delete ingested session and verify it's removed.

        MATLAB equivalent: testDeleteIngestedSession.testDeleteSuccess
        """
        dataset, session = build_dataset
        session_id = session.id()

        # Verify session exists initially
        refs, session_ids, *_ = dataset.session_list()
        assert session_id in session_ids, "ndi_session ID should be in dataset"

        # Verify documents exist
        q = ndi_query("base.session_id") == session_id
        docs = dataset.database_search(q)
        assert len(docs) > 0, "ndi_session documents should exist"

        # Delete the session
        dataset.deleteIngestedSession(session_id, are_you_sure=True)

        # Verify session is removed from list
        refs_after, ids_after, *_ = dataset.session_list()
        assert session_id not in ids_after, "ndi_session ID should NOT be in dataset after deletion"

        # Verify documents are removed
        docs_after = dataset.database_search(q)
        assert len(docs_after) == 0, "ndi_session documents should be gone after deletion"

    def test_delete_not_confirmed(self, build_dataset):
        """Deleting without are_you_sure=True raises ValueError.

        MATLAB equivalent: testDeleteIngestedSession.testDeleteNotConfirmed
        (MATLAB error ID: ndi:dataset:deleteIngestedSession:notConfirmed)
        """
        dataset, session = build_dataset
        session_id = session.id()

        with pytest.raises(ValueError):
            dataset.deleteIngestedSession(session_id, are_you_sure=False)

        # Verify session still exists
        refs, session_ids, *_ = dataset.session_list()
        assert (
            session_id in session_ids
        ), "ndi_session ID should still be in dataset after failed delete"

    def test_delete_linked_session_error(self, build_dataset, tmp_path):
        """Deleting a linked session raises ValueError.

        MATLAB equivalent: testDeleteIngestedSession.testDeleteLinkedSession
        (MATLAB error ID: ndi:dataset:deleteIngestedSession:isLinked)
        """
        dataset, _ = build_dataset

        # Create and link a separate session
        linked_dir = tmp_path / "linked_session"
        linked_dir.mkdir()
        linked_session = ndi_session_dir("linked_ref", linked_dir)

        dataset.add_linked_session(linked_session)

        # Verify it was added
        refs, session_ids, *_ = dataset.session_list()
        assert linked_session.id() in session_ids

        # Attempt to delete a linked session — should fail
        with pytest.raises(ValueError, match="linked"):
            dataset.deleteIngestedSession(linked_session.id(), are_you_sure=True)

    def test_delete_nonexistent_session(self, build_dataset):
        """Deleting a nonexistent session raises ValueError.

        MATLAB equivalent: testDeleteIngestedSession.testDeleteNotFound
        (MATLAB error ID: ndi:dataset:deleteIngestedSession:notFound)
        """
        dataset, _ = build_dataset
        with pytest.raises(ValueError, match="not found"):
            dataset.deleteIngestedSession("fake_id_xyz", are_you_sure=True)


# ===========================================================================
# TestUnlinkSession
# Port of: ndi.unittest.dataset.testUnlinkSession
#
# MATLAB: unlink_session(id, 'areYouSure', true, 'askUserToConfirm', false, ...)
# Python: unlink_session(id, are_you_sure=True)
# Both require confirmation and only allow unlinking linked sessions.
# ===========================================================================


class TestUnlinkSession:
    """Test the unlink_session method of ndi_dataset."""

    def test_unlink_linked_session(self, tmp_path):
        """Unlink a linked session and verify it's removed from the dataset.

        MATLAB equivalent: testUnlinkSession.testUnlinkLinkedSession
        """
        # Create session with docs
        session_dir = tmp_path / "sess_unlink"
        session_dir.mkdir()
        session = ndi_session_dir("exp_unlink", session_dir)
        _add_doc_with_file(session, 1)

        # Create dataset
        ds_dir = tmp_path / "ds_unlink"
        ds_dir.mkdir()
        dataset = ndi_dataset(ds_dir, "ds_unlink")
        dataset.add_linked_session(session)

        # Verify session is linked
        refs, session_ids, *_ = dataset.session_list()
        assert len(session_ids) == 1
        assert session_ids[0] == session.id()

        # Unlink
        dataset.unlink_session(session.id(), are_you_sure=True)

        # Verify session is gone from dataset
        refs_after, ids_after, *_ = dataset.session_list()
        assert len(ids_after) == 0, "ndi_session list should be empty after unlink"

        # ndi_session files should still exist
        assert (
            session.path / ".ndi"
        ).exists(), "ndi_session .ndi directory should still exist after unlink"

    def test_unlink_ingested_session_error(self, tmp_path):
        """Unlinking an ingested session raises ValueError.

        MATLAB equivalent: testUnlinkSession.testUnlinkIngestedSessionError
        """
        # Create session
        session_dir = tmp_path / "sess_ing"
        session_dir.mkdir()
        session = ndi_session_dir("exp_ing", session_dir)
        _add_doc_with_file(session, 1)

        # Create dataset, ingest
        ds_dir = tmp_path / "ds_ing"
        ds_dir.mkdir()
        dataset = ndi_dataset(ds_dir, "ds_ing")
        dataset.add_ingested_session(session)

        session_id = session.id()

        # Unlinking an ingested session should raise
        with pytest.raises(ValueError, match="INGESTED"):
            dataset.unlink_session(session_id, are_you_sure=True)

    def test_unlink_nonexistent_session(self, tmp_path):
        """Unlinking a nonexistent session raises ValueError.

        MATLAB equivalent: testUnlinkSession.testUnlinkNotFoundError
        """
        ds_dir = tmp_path / "ds_empty"
        ds_dir.mkdir()
        dataset = ndi_dataset(ds_dir, "ds_empty")

        with pytest.raises(ValueError, match="not found"):
            dataset.unlink_session("nonexistent_id", are_you_sure=True)

    def test_unlink_not_confirmed(self, tmp_path):
        """Unlinking without are_you_sure raises ValueError.

        MATLAB equivalent: testUnlinkSession.testUnlinkNotConfirmedError
        """
        session_dir = tmp_path / "sess_conf"
        session_dir.mkdir()
        session = ndi_session_dir("exp_conf", session_dir)

        ds_dir = tmp_path / "ds_conf"
        ds_dir.mkdir()
        dataset = ndi_dataset(ds_dir, "ds_conf")
        dataset.add_linked_session(session)

        with pytest.raises(ValueError, match="are_you_sure"):
            dataset.unlink_session(session.id())


# ===========================================================================
# TestOldDataset
# Port of: ndi.unittest.dataset.OldDatasetTest
#
# MATLAB test opens example_datasets/oldDataset from ndi.toolboxdir.
# Python repo does not have this example dataset, so we skip this test
# and create a synthetic equivalent.
# ===========================================================================


class TestOldDataset:
    """Test opening a pre-existing dataset (backward compatibility)."""

    def test_open_existing_dataset(self, tmp_path):
        """Create a dataset, close it, reopen, and verify contents.

        MATLAB equivalent: OldDatasetTest.testOldDataset
        (Adapted: MATLAB opens a shipped example; we create + reopen.)
        """
        # 1. Create a dataset with an ingested session
        session_dir = tmp_path / "old_session"
        session_dir.mkdir()
        session = ndi_session_dir("old_exp", session_dir)
        _add_doc_with_file(session, 1)
        _add_doc_with_file(session, 2)

        ds_dir = tmp_path / "old_dataset"
        ds_dir.mkdir()
        dataset = ndi_dataset(ds_dir, "old_ds")
        dataset.add_ingested_session(session)

        # Remember the IDs
        original_ds_id = dataset.id()
        original_session_id = session.id()

        # 2. "Close" by discarding references
        del dataset
        del session

        # 3. Reopen the dataset from path only
        reopened = ndi_dataset(ds_dir)
        assert reopened.id() == original_ds_id, "Reopened dataset should have same ID"

        # 4. Verify session list
        refs, session_ids, *_ = reopened.session_list()
        assert len(session_ids) >= 1, "Reopened dataset should have at least 1 session"
        assert (
            original_session_id in session_ids
        ), "Original session should still be in the reopened dataset"

        # 5. Verify documents are still accessible
        q = ndi_query("").isa("demoNDI")
        docs = reopened.database_search(q)
        assert len(docs) == 2, "Should find 2 demoNDI documents"
