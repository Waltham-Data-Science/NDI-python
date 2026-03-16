"""
Tests for Phase 8: ndi.subject, ndi.element_timeseries, ndi.neuron, ndi.dataset

316 existing tests + Phase 8 tests.
"""

import pytest

from ndi import (
    ndi_dataset,
    ndi_session_dir,
    ndi_document,
    ndi_element,
    ndi_element_timeseries,
    ndi_neuron,
    ndi_query,
    ndi_subject,
)

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temp directory for tests."""
    return tmp_path


@pytest.fixture
def session(temp_dir):
    """Create a ndi_session_dir for testing."""
    session_path = temp_dir / "session1"
    session_path.mkdir(parents=True, exist_ok=True)
    return ndi_session_dir("TestSession", session_path)


@pytest.fixture
def session2(temp_dir):
    """Create a second ndi_session_dir for testing."""
    session_path = temp_dir / "session2"
    session_path.mkdir(parents=True, exist_ok=True)
    return ndi_session_dir("TestSession2", session_path)


# ===========================================================================
# ndi_subject Tests
# ===========================================================================


class TestSubjectCreation:
    """Test ndi_subject construction."""

    def test_create_subject(self):
        """Test basic subject creation."""
        s = ndi_subject("mouse23@vhlab.org", "Laboratory mouse")
        assert s.local_identifier == "mouse23@vhlab.org"
        assert s.description == "Laboratory mouse"
        assert s.id  # Should have an auto-generated ID

    def test_create_subject_empty_description(self):
        """Test creating subject with empty description."""
        s = ndi_subject("rat1@lab.org", "")
        assert s.local_identifier == "rat1@lab.org"
        assert s.description == ""

    def test_create_subject_invalid_no_at(self):
        """Test that subject without '@' raises ValueError."""
        with pytest.raises(ValueError, match="must contain '@'"):
            ndi_subject("mouse23", "no at sign")

    def test_create_subject_invalid_spaces(self):
        """Test that subject with spaces raises ValueError."""
        with pytest.raises(ValueError, match="cannot contain spaces"):
            ndi_subject("mouse 23@lab.org", "has spaces")

    def test_create_subject_empty_identifier_ok(self):
        """Test that empty identifier doesn't raise."""
        s = ndi_subject("", "")
        assert s.local_identifier == ""

    def test_subject_repr(self):
        """Test string representation."""
        s = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
        assert "mouse23@vhlab.org" in repr(s)

    def test_subject_equality(self):
        """Test subject equality by local_identifier."""
        s1 = ndi_subject("mouse23@vhlab.org", "Mouse A")
        s2 = ndi_subject("mouse23@vhlab.org", "Mouse B")
        s3 = ndi_subject("rat1@lab.org", "Rat")
        assert s1 == s2
        assert s1 != s3


class TestSubjectValidation:
    """Test ndi_subject validation."""

    def test_valid_identifier(self):
        """Test valid identifier."""
        valid, msg = ndi_subject.is_valid_local_identifier("mouse@lab.org")
        assert valid
        assert msg == ""

    def test_invalid_no_at(self):
        """Test invalid identifier without @."""
        valid, msg = ndi_subject.is_valid_local_identifier("mouselaborg")
        assert not valid
        assert "@" in msg

    def test_invalid_spaces(self):
        """Test invalid identifier with spaces."""
        valid, msg = ndi_subject.is_valid_local_identifier("mouse @lab.org")
        assert not valid
        assert "spaces" in msg

    def test_invalid_empty(self):
        """Test invalid empty identifier."""
        valid, msg = ndi_subject.is_valid_local_identifier("")
        assert not valid
        assert "empty" in msg

    def test_invalid_non_string(self):
        """Test invalid non-string identifier."""
        valid, msg = ndi_subject.is_valid_local_identifier(123)
        assert not valid


class TestSubjectDocument:
    """Test ndi_subject document operations."""

    def test_newdocument(self):
        """Test creating a subject document."""
        s = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
        try:
            doc = s.newdocument()
            assert doc is not None
            assert doc.doc_class() == "subject"
            props = doc.document_properties
            assert props["subject"]["local_identifier"] == "mouse23@vhlab.org"
            assert props["subject"]["description"] == "ndi_gui_Lab mouse"
        except FileNotFoundError:
            pytest.skip("ndi_subject schema not available")

    def test_searchquery(self):
        """Test creating a search query for subject."""
        s = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
        q = s.searchquery()
        assert q is not None

    def test_load_from_session(self, session):
        """Test loading subject from session."""
        try:
            s1 = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
            doc = s1.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            # Load from session + document
            s2 = ndi_subject(session, doc)
            assert s2.local_identifier == "mouse23@vhlab.org"
            assert s2.description == "ndi_gui_Lab mouse"
        except FileNotFoundError:
            pytest.skip("ndi_subject schema not available")

    def test_load_from_session_by_id(self, session):
        """Test loading subject from session by document ID."""
        try:
            s1 = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
            doc = s1.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            # Load from session + doc_id
            s2 = ndi_subject(session, doc.id)
            assert s2.local_identifier == "mouse23@vhlab.org"
        except FileNotFoundError:
            pytest.skip("ndi_subject schema not available")

    def test_does_subjectstring_match(self, session):
        """Test does_subjectstring_match_session_document."""
        try:
            s = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
            doc = s.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            found, sid = ndi_subject.does_subjectstring_match_session_document(
                session, "mouse23@vhlab.org"
            )
            assert found
            assert sid == doc.id
        except FileNotFoundError:
            pytest.skip("ndi_subject schema not available")

    def test_does_subjectstring_not_found(self, session):
        """Test subject string not found."""
        found, sid = ndi_subject.does_subjectstring_match_session_document(
            session, "nonexistent@lab.org"
        )
        assert not found
        assert sid is None

    def test_does_subjectstring_make_if_missing(self, session):
        """Test making subject if missing."""
        try:
            found, sid = ndi_subject.does_subjectstring_match_session_document(
                session, "newmouse@lab.org", make_if_missing=True
            )
            assert found
            assert sid is not None
        except FileNotFoundError:
            pytest.skip("ndi_subject schema not available")


# ===========================================================================
# ndi_element_timeseries Tests
# ===========================================================================


class TestElementTimeseries:
    """Test ndi_element_timeseries class."""

    def test_create_timeseries_element(self, session):
        """Test creating a timeseries element."""
        ts = ndi_element_timeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        assert ts.name == "signal1"
        assert ts.reference == 1
        assert ts.type == "voltage"

    def test_is_subclass_of_element(self):
        """Test that ndi_element_timeseries is a subclass of ndi_element."""
        assert issubclass(ndi_element_timeseries, ndi_element)

    def test_repr(self, session):
        """Test string representation."""
        ts = ndi_element_timeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        assert "ndi_element_timeseries" in repr(ts)
        assert "signal1" in repr(ts)

    def test_readtimeseries_empty(self, session):
        """Test reading from element with no data."""
        ts = ndi_element_timeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        data, times, ref = ts.readtimeseries(1)
        assert len(data) == 0
        assert len(times) == 0

    def test_samplerate_default(self, session):
        """Test default sample rate."""
        ts = ndi_element_timeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        assert ts.samplerate() == 0.0

    def test_readtimeseries_no_session(self):
        """Test that readtimeseries without session raises."""
        ts = ndi_element_timeseries(
            name="signal1",
            reference=1,
            type="voltage",
        )
        with pytest.raises(ValueError, match="ndi_session required"):
            ts.readtimeseries(1)


# ===========================================================================
# ndi_neuron Tests
# ===========================================================================


class TestNeuron:
    """Test ndi_neuron class."""

    def test_create_neuron(self, session):
        """Test creating a neuron."""
        n = ndi_neuron(
            session=session,
            name="neuron1",
            reference=1,
        )
        assert n.name == "neuron1"
        assert n.reference == 1
        assert n.type == "neuron"

    def test_is_subclass_of_element_timeseries(self):
        """Test that ndi_neuron is a subclass of ndi_element_timeseries."""
        assert issubclass(ndi_neuron, ndi_element_timeseries)
        assert issubclass(ndi_neuron, ndi_element)

    def test_repr(self, session):
        """Test string representation."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)
        assert "ndi_neuron" in repr(n)
        assert "neuron1" in repr(n)

    def test_neuron_type_forced(self, session):
        """Test that neuron type is always 'neuron'."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)
        assert n.type == "neuron"

    def test_epochsetname(self, session):
        """Test neuron epoch set name."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)
        assert "neuron" in n.epochsetname().lower()

    def test_issyncgraphroot(self, session):
        """Test that neurons are not sync graph roots."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)
        assert n.issyncgraphroot() is False

    def test_neuron_with_underlying(self, session):
        """Test neuron with underlying element."""
        probe = ndi_element(
            session=session,
            name="electrode1",
            reference=1,
            type="n-trode",
        )
        n = ndi_neuron(
            session=session,
            name="neuron1",
            reference=1,
            underlying_element=probe,
        )
        assert n.underlying_element is probe

    def test_neuron_newdocument(self, session):
        """Test creating neuron document."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)
        doc = n.newdocument()
        assert doc is not None
        props = doc.document_properties
        assert props["element"]["type"] == "neuron"
        assert props["element"]["name"] == "neuron1"

    def test_neuron_searchquery(self, session):
        """Test neuron search query."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)
        q = n.searchquery()
        assert q is not None

    def test_neuron_subject_id(self, session):
        """Test neuron with subject ID."""
        n = ndi_neuron(
            session=session,
            name="neuron1",
            reference=1,
            subject_id="test_subject_id",
        )
        assert n.subject_id == "test_subject_id"


# ===========================================================================
# ndi_dataset Tests
# ===========================================================================


class TestDatasetCreation:
    """Test ndi_dataset creation."""

    def test_create_dataset(self, temp_dir):
        """Test creating a new dataset."""
        ds = ndi_dataset(temp_dir / "dataset1", "MyDataset")
        assert ds.reference == "MyDataset"
        assert ds.getpath() == temp_dir / "dataset1"

    def test_create_dataset_auto_reference(self, temp_dir):
        """Test dataset with auto-generated reference."""
        ds = ndi_dataset(temp_dir / "experiment_2026")
        assert ds.reference == "experiment_2026"

    def test_dataset_id(self, temp_dir):
        """Test that dataset has a unique ID."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        assert ds.id()
        assert len(ds.id()) > 0

    def test_dataset_repr(self, temp_dir):
        """Test dataset string representation."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        assert "ndi_dataset" in repr(ds)
        assert "Test" in repr(ds)


class TestDatasetSessions:
    """Test ndi_dataset session management."""

    def test_add_linked_session(self, temp_dir, session):
        """Test adding a linked session."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 1
        assert session_ids[0] == session.id()

    def test_add_multiple_sessions(self, temp_dir, session, session2):
        """Test adding multiple sessions."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)
        ds.add_linked_session(session2)

        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 2

    def test_add_duplicate_session(self, temp_dir, session):
        """Test that adding same session twice raises ValueError."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        with pytest.raises(ValueError, match="already part of"):
            ds.add_linked_session(session)

        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 1

    def test_add_ingested_session(self, temp_dir, session):
        """Test ingesting a session."""
        # Add a document to the source session first
        doc = ndi_document("base")
        doc.set_session_id(session.id())
        session.database_add(doc)

        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_ingested_session(session)

        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 1

    def test_unlink_session(self, temp_dir, session):
        """Test unlinking a session."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)
        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 1

        ds.unlink_session(session.id(), are_you_sure=True)
        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 0

    def test_unlink_nonexistent(self, temp_dir):
        """Test unlinking a nonexistent session raises ValueError."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        with pytest.raises(ValueError, match="not found"):
            ds.unlink_session("nonexistent_id", are_you_sure=True)

    def test_unlink_requires_confirmation(self, temp_dir, session):
        """Test that unlinking requires are_you_sure=True."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)
        with pytest.raises(ValueError, match="are_you_sure"):
            ds.unlink_session(session.id())

    def test_session_list_empty(self, temp_dir):
        """Test session list on empty dataset."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        refs, session_ids, *_ = ds.session_list()
        assert refs == []
        assert session_ids == []

    def test_session_list_details(self, temp_dir, session):
        """Test session list returns refs and ids."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 1
        assert len(refs) == 1
        assert isinstance(refs[0], str)
        assert isinstance(session_ids[0], str)


class TestDatasetDatabase:
    """Test ndi_dataset database operations."""

    def test_database_add_search(self, temp_dir):
        """Test adding and searching documents in dataset."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        doc = ndi_document("base")
        ds.database_add(doc)

        results = ds.database_search(ndi_query("base.id") == doc.id)
        assert len(results) == 1
        assert results[0].id == doc.id

    def test_database_rm(self, temp_dir):
        """Test removing documents from dataset."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        doc = ndi_document("base")
        ds.database_add(doc)

        ds.database_rm(doc)
        results = ds.database_search(ndi_query("base.id") == doc.id)
        assert len(results) == 0


class TestDatasetIngestion:
    """Test ndi_dataset ingestion and deletion."""

    def test_deleteIngestedSession_requires_confirmation(self, temp_dir, session):
        """Test that deleting ingested session requires confirmation."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_ingested_session(session)

        with pytest.raises(ValueError, match="are_you_sure"):
            ds.deleteIngestedSession(session.id())

    def test_deleteIngestedSession(self, temp_dir, session):
        """Test deleting an ingested session."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_ingested_session(session)
        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 1

        ds.deleteIngestedSession(session.id(), are_you_sure=True)
        refs, session_ids, *_ = ds.session_list()
        assert len(session_ids) == 0

    def test_delete_linked_session_raises(self, temp_dir, session):
        """Test that deleting a linked session raises error."""
        ds = ndi_dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        with pytest.raises(ValueError, match="linked"):
            ds.deleteIngestedSession(session.id(), are_you_sure=True)


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestPhase8Integration:
    """Integration tests combining Phase 8 classes."""

    def test_subject_in_session(self, session):
        """Test creating and storing a subject in a session."""
        try:
            s = ndi_subject("mouse23@vhlab.org", "C57BL/6 mouse")
            doc = s.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            # Search for it
            q = s.searchquery()
            results = session.database_search(q)
            assert len(results) >= 1
        except FileNotFoundError:
            pytest.skip("ndi_subject schema not available")

    def test_neuron_with_subject(self, session):
        """Test creating a neuron element associated with a subject."""
        try:
            s = ndi_subject("mouse23@vhlab.org", "ndi_gui_Lab mouse")
            sdoc = s.newdocument()
            sdoc.set_session_id(session.id())
            session.database_add(sdoc)

            n = ndi_neuron(
                session=session,
                name="neuron1",
                reference=1,
                subject_id=sdoc.id,
            )
            ndoc = n.newdocument()
            session.database_add(ndoc)

            # Verify neuron document
            results = session.database_search(ndi_query("base.id") == ndoc.id)
            assert len(results) == 1
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_dataset_with_sessions_and_subjects(self, temp_dir, session, session2):
        """Test full dataset workflow with sessions and subjects."""
        try:
            # Add subjects to sessions
            s1 = ndi_subject("mouse1@lab.org", "Mouse 1")
            s1doc = s1.newdocument()
            s1doc.set_session_id(session.id())
            session.database_add(s1doc)

            s2 = ndi_subject("mouse2@lab.org", "Mouse 2")
            s2doc = s2.newdocument()
            s2doc.set_session_id(session2.id())
            session2.database_add(s2doc)

            # Create dataset
            ds = ndi_dataset(temp_dir / "experiment", "Full Experiment")
            ds.add_linked_session(session)
            ds.add_linked_session(session2)

            # Verify
            refs, session_ids, *_ = ds.session_list()
            assert len(session_ids) == 2
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_element_timeseries_inheritance(self, session):
        """Test that ndi_element_timeseries properly inherits ndi_element behavior."""
        ts = ndi_element_timeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        # Should have ndi_element properties
        assert ts.name == "signal1"
        assert ts.elementstring() == "signal1 | 1"

        # Should have ndi_documentservice methods
        doc = ts.newdocument()
        assert doc is not None
        assert doc.document_properties["element"]["name"] == "signal1"

    def test_neuron_inherits_timeseries(self, session):
        """Test that ndi_neuron has timeseries capabilities."""
        n = ndi_neuron(session=session, name="neuron1", reference=1)

        # Should have readtimeseries
        assert hasattr(n, "readtimeseries")
        assert hasattr(n, "samplerate")
        assert hasattr(n, "addepoch")

        # Test readtimeseries returns empty data
        data, times, ref = n.readtimeseries(1)
        assert len(data) == 0
