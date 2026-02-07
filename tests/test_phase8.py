"""
Tests for Phase 8: ndi.subject, ndi.element_timeseries, ndi.neuron, ndi.dataset

316 existing tests + Phase 8 tests.
"""

import pytest

from ndi import (
    Dataset,
    DirSession,
    Document,
    Element,
    ElementTimeseries,
    Neuron,
    Query,
    Subject,
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
    """Create a DirSession for testing."""
    session_path = temp_dir / "session1"
    session_path.mkdir(parents=True, exist_ok=True)
    return DirSession("TestSession", session_path)


@pytest.fixture
def session2(temp_dir):
    """Create a second DirSession for testing."""
    session_path = temp_dir / "session2"
    session_path.mkdir(parents=True, exist_ok=True)
    return DirSession("TestSession2", session_path)


# ===========================================================================
# Subject Tests
# ===========================================================================


class TestSubjectCreation:
    """Test Subject construction."""

    def test_create_subject(self):
        """Test basic subject creation."""
        s = Subject("mouse23@vhlab.org", "Laboratory mouse")
        assert s.local_identifier == "mouse23@vhlab.org"
        assert s.description == "Laboratory mouse"
        assert s.id  # Should have an auto-generated ID

    def test_create_subject_empty_description(self):
        """Test creating subject with empty description."""
        s = Subject("rat1@lab.org", "")
        assert s.local_identifier == "rat1@lab.org"
        assert s.description == ""

    def test_create_subject_invalid_no_at(self):
        """Test that subject without '@' raises ValueError."""
        with pytest.raises(ValueError, match="must contain '@'"):
            Subject("mouse23", "no at sign")

    def test_create_subject_invalid_spaces(self):
        """Test that subject with spaces raises ValueError."""
        with pytest.raises(ValueError, match="cannot contain spaces"):
            Subject("mouse 23@lab.org", "has spaces")

    def test_create_subject_empty_identifier_ok(self):
        """Test that empty identifier doesn't raise."""
        s = Subject("", "")
        assert s.local_identifier == ""

    def test_subject_repr(self):
        """Test string representation."""
        s = Subject("mouse23@vhlab.org", "Lab mouse")
        assert "mouse23@vhlab.org" in repr(s)

    def test_subject_equality(self):
        """Test subject equality by local_identifier."""
        s1 = Subject("mouse23@vhlab.org", "Mouse A")
        s2 = Subject("mouse23@vhlab.org", "Mouse B")
        s3 = Subject("rat1@lab.org", "Rat")
        assert s1 == s2
        assert s1 != s3


class TestSubjectValidation:
    """Test Subject validation."""

    def test_valid_identifier(self):
        """Test valid identifier."""
        valid, msg = Subject.is_valid_local_identifier("mouse@lab.org")
        assert valid
        assert msg == ""

    def test_invalid_no_at(self):
        """Test invalid identifier without @."""
        valid, msg = Subject.is_valid_local_identifier("mouselaborg")
        assert not valid
        assert "@" in msg

    def test_invalid_spaces(self):
        """Test invalid identifier with spaces."""
        valid, msg = Subject.is_valid_local_identifier("mouse @lab.org")
        assert not valid
        assert "spaces" in msg

    def test_invalid_empty(self):
        """Test invalid empty identifier."""
        valid, msg = Subject.is_valid_local_identifier("")
        assert not valid
        assert "empty" in msg

    def test_invalid_non_string(self):
        """Test invalid non-string identifier."""
        valid, msg = Subject.is_valid_local_identifier(123)
        assert not valid


class TestSubjectDocument:
    """Test Subject document operations."""

    def test_newdocument(self):
        """Test creating a subject document."""
        s = Subject("mouse23@vhlab.org", "Lab mouse")
        try:
            doc = s.newdocument()
            assert doc is not None
            assert doc.doc_class() == "subject"
            props = doc.document_properties
            assert props["subject"]["local_identifier"] == "mouse23@vhlab.org"
            assert props["subject"]["description"] == "Lab mouse"
        except FileNotFoundError:
            pytest.skip("Subject schema not available")

    def test_searchquery(self):
        """Test creating a search query for subject."""
        s = Subject("mouse23@vhlab.org", "Lab mouse")
        q = s.searchquery()
        assert q is not None

    def test_load_from_session(self, session):
        """Test loading subject from session."""
        try:
            s1 = Subject("mouse23@vhlab.org", "Lab mouse")
            doc = s1.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            # Load from session + document
            s2 = Subject(session, doc)
            assert s2.local_identifier == "mouse23@vhlab.org"
            assert s2.description == "Lab mouse"
        except FileNotFoundError:
            pytest.skip("Subject schema not available")

    def test_load_from_session_by_id(self, session):
        """Test loading subject from session by document ID."""
        try:
            s1 = Subject("mouse23@vhlab.org", "Lab mouse")
            doc = s1.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            # Load from session + doc_id
            s2 = Subject(session, doc.id)
            assert s2.local_identifier == "mouse23@vhlab.org"
        except FileNotFoundError:
            pytest.skip("Subject schema not available")

    def test_does_subjectstring_match(self, session):
        """Test does_subjectstring_match_session_document."""
        try:
            s = Subject("mouse23@vhlab.org", "Lab mouse")
            doc = s.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            found, sid = Subject.does_subjectstring_match_session_document(
                session, "mouse23@vhlab.org"
            )
            assert found
            assert sid == doc.id
        except FileNotFoundError:
            pytest.skip("Subject schema not available")

    def test_does_subjectstring_not_found(self, session):
        """Test subject string not found."""
        found, sid = Subject.does_subjectstring_match_session_document(
            session, "nonexistent@lab.org"
        )
        assert not found
        assert sid is None

    def test_does_subjectstring_make_if_missing(self, session):
        """Test making subject if missing."""
        try:
            found, sid = Subject.does_subjectstring_match_session_document(
                session, "newmouse@lab.org", make_if_missing=True
            )
            assert found
            assert sid is not None
        except FileNotFoundError:
            pytest.skip("Subject schema not available")


# ===========================================================================
# ElementTimeseries Tests
# ===========================================================================


class TestElementTimeseries:
    """Test ElementTimeseries class."""

    def test_create_timeseries_element(self, session):
        """Test creating a timeseries element."""
        ts = ElementTimeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        assert ts.name == "signal1"
        assert ts.reference == 1
        assert ts.type == "voltage"

    def test_is_subclass_of_element(self):
        """Test that ElementTimeseries is a subclass of Element."""
        assert issubclass(ElementTimeseries, Element)

    def test_repr(self, session):
        """Test string representation."""
        ts = ElementTimeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        assert "ElementTimeseries" in repr(ts)
        assert "signal1" in repr(ts)

    def test_readtimeseries_empty(self, session):
        """Test reading from element with no data."""
        ts = ElementTimeseries(
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
        ts = ElementTimeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        assert ts.samplerate() == 0.0

    def test_readtimeseries_no_session(self):
        """Test that readtimeseries without session raises."""
        ts = ElementTimeseries(
            name="signal1",
            reference=1,
            type="voltage",
        )
        with pytest.raises(ValueError, match="Session required"):
            ts.readtimeseries(1)


# ===========================================================================
# Neuron Tests
# ===========================================================================


class TestNeuron:
    """Test Neuron class."""

    def test_create_neuron(self, session):
        """Test creating a neuron."""
        n = Neuron(
            session=session,
            name="neuron1",
            reference=1,
        )
        assert n.name == "neuron1"
        assert n.reference == 1
        assert n.type == "neuron"

    def test_is_subclass_of_element_timeseries(self):
        """Test that Neuron is a subclass of ElementTimeseries."""
        assert issubclass(Neuron, ElementTimeseries)
        assert issubclass(Neuron, Element)

    def test_repr(self, session):
        """Test string representation."""
        n = Neuron(session=session, name="neuron1", reference=1)
        assert "Neuron" in repr(n)
        assert "neuron1" in repr(n)

    def test_neuron_type_forced(self, session):
        """Test that neuron type is always 'neuron'."""
        n = Neuron(session=session, name="neuron1", reference=1)
        assert n.type == "neuron"

    def test_epochsetname(self, session):
        """Test neuron epoch set name."""
        n = Neuron(session=session, name="neuron1", reference=1)
        assert "neuron" in n.epochsetname().lower()

    def test_issyncgraphroot(self, session):
        """Test that neurons are not sync graph roots."""
        n = Neuron(session=session, name="neuron1", reference=1)
        assert n.issyncgraphroot() is False

    def test_neuron_with_underlying(self, session):
        """Test neuron with underlying element."""
        probe = Element(
            session=session,
            name="electrode1",
            reference=1,
            type="n-trode",
        )
        n = Neuron(
            session=session,
            name="neuron1",
            reference=1,
            underlying_element=probe,
        )
        assert n.underlying_element is probe

    def test_neuron_newdocument(self, session):
        """Test creating neuron document."""
        n = Neuron(session=session, name="neuron1", reference=1)
        doc = n.newdocument()
        assert doc is not None
        props = doc.document_properties
        assert props["element"]["type"] == "neuron"
        assert props["element"]["name"] == "neuron1"

    def test_neuron_searchquery(self, session):
        """Test neuron search query."""
        n = Neuron(session=session, name="neuron1", reference=1)
        q = n.searchquery()
        assert q is not None

    def test_neuron_subject_id(self, session):
        """Test neuron with subject ID."""
        n = Neuron(
            session=session,
            name="neuron1",
            reference=1,
            subject_id="test_subject_id",
        )
        assert n.subject_id == "test_subject_id"


# ===========================================================================
# Dataset Tests
# ===========================================================================


class TestDatasetCreation:
    """Test Dataset creation."""

    def test_create_dataset(self, temp_dir):
        """Test creating a new dataset."""
        ds = Dataset(temp_dir / "dataset1", "MyDataset")
        assert ds.reference == "MyDataset"
        assert ds.getpath() == temp_dir / "dataset1"

    def test_create_dataset_auto_reference(self, temp_dir):
        """Test dataset with auto-generated reference."""
        ds = Dataset(temp_dir / "experiment_2026")
        assert ds.reference == "experiment_2026"

    def test_dataset_id(self, temp_dir):
        """Test that dataset has a unique ID."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        assert ds.id()
        assert len(ds.id()) > 0

    def test_dataset_repr(self, temp_dir):
        """Test dataset string representation."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        assert "Dataset" in repr(ds)
        assert "Test" in repr(ds)


class TestDatasetSessions:
    """Test Dataset session management."""

    def test_add_linked_session(self, temp_dir, session):
        """Test adding a linked session."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        sessions = ds.session_list()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == session.id()
        assert sessions[0]["is_linked"] is True

    def test_add_multiple_sessions(self, temp_dir, session, session2):
        """Test adding multiple sessions."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)
        ds.add_linked_session(session2)

        sessions = ds.session_list()
        assert len(sessions) == 2

    def test_add_duplicate_session(self, temp_dir, session):
        """Test that adding same session twice doesn't duplicate."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)
        ds.add_linked_session(session)

        sessions = ds.session_list()
        assert len(sessions) == 1

    def test_add_ingested_session(self, temp_dir, session):
        """Test ingesting a session."""
        # Add a document to the source session first
        doc = Document("base")
        doc.set_session_id(session.id())
        session.database_add(doc)

        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_ingested_session(session)

        sessions = ds.session_list()
        assert len(sessions) == 1
        assert sessions[0]["is_linked"] is False

    def test_unlink_session(self, temp_dir, session):
        """Test unlinking a session."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)
        assert len(ds.session_list()) == 1

        ds.unlink_session(session.id())
        assert len(ds.session_list()) == 0

    def test_unlink_nonexistent(self, temp_dir):
        """Test unlinking a session that doesn't exist (no error)."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.unlink_session("nonexistent_id")  # Should not raise

    def test_session_list_empty(self, temp_dir):
        """Test session list on empty dataset."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        assert ds.session_list() == []

    def test_session_list_details(self, temp_dir, session):
        """Test session list returns correct details."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        sessions = ds.session_list()
        assert len(sessions) == 1
        entry = sessions[0]
        assert "session_id" in entry
        assert "session_reference" in entry
        assert "is_linked" in entry
        assert "document_id" in entry


class TestDatasetDatabase:
    """Test Dataset database operations."""

    def test_database_add_search(self, temp_dir):
        """Test adding and searching documents in dataset."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        doc = Document("base")
        ds.database_add(doc)

        results = ds.database_search(Query("base.id") == doc.id)
        assert len(results) == 1
        assert results[0].id == doc.id

    def test_database_rm(self, temp_dir):
        """Test removing documents from dataset."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        doc = Document("base")
        ds.database_add(doc)

        ds.database_rm(doc)
        results = ds.database_search(Query("base.id") == doc.id)
        assert len(results) == 0


class TestDatasetIngestion:
    """Test Dataset ingestion and deletion."""

    def test_delete_ingested_session_requires_confirmation(self, temp_dir, session):
        """Test that deleting ingested session requires confirmation."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_ingested_session(session)

        with pytest.raises(ValueError, match="are_you_sure"):
            ds.delete_ingested_session(session.id())

    def test_delete_ingested_session(self, temp_dir, session):
        """Test deleting an ingested session."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_ingested_session(session)
        assert len(ds.session_list()) == 1

        ds.delete_ingested_session(session.id(), are_you_sure=True)
        assert len(ds.session_list()) == 0

    def test_delete_linked_session_raises(self, temp_dir, session):
        """Test that deleting a linked session raises error."""
        ds = Dataset(temp_dir / "dataset1", "Test")
        ds.add_linked_session(session)

        with pytest.raises(ValueError, match="linked"):
            ds.delete_ingested_session(session.id(), are_you_sure=True)


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestPhase8Integration:
    """Integration tests combining Phase 8 classes."""

    def test_subject_in_session(self, session):
        """Test creating and storing a subject in a session."""
        try:
            s = Subject("mouse23@vhlab.org", "C57BL/6 mouse")
            doc = s.newdocument()
            doc.set_session_id(session.id())
            session.database_add(doc)

            # Search for it
            q = s.searchquery()
            results = session.database_search(q)
            assert len(results) >= 1
        except FileNotFoundError:
            pytest.skip("Subject schema not available")

    def test_neuron_with_subject(self, session):
        """Test creating a neuron element associated with a subject."""
        try:
            s = Subject("mouse23@vhlab.org", "Lab mouse")
            sdoc = s.newdocument()
            sdoc.set_session_id(session.id())
            session.database_add(sdoc)

            n = Neuron(
                session=session,
                name="neuron1",
                reference=1,
                subject_id=sdoc.id,
            )
            ndoc = n.newdocument()
            session.database_add(ndoc)

            # Verify neuron document
            results = session.database_search(Query("base.id") == ndoc.id)
            assert len(results) == 1
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_dataset_with_sessions_and_subjects(self, temp_dir, session, session2):
        """Test full dataset workflow with sessions and subjects."""
        try:
            # Add subjects to sessions
            s1 = Subject("mouse1@lab.org", "Mouse 1")
            s1doc = s1.newdocument()
            s1doc.set_session_id(session.id())
            session.database_add(s1doc)

            s2 = Subject("mouse2@lab.org", "Mouse 2")
            s2doc = s2.newdocument()
            s2doc.set_session_id(session2.id())
            session2.database_add(s2doc)

            # Create dataset
            ds = Dataset(temp_dir / "experiment", "Full Experiment")
            ds.add_linked_session(session)
            ds.add_linked_session(session2)

            # Verify
            sessions = ds.session_list()
            assert len(sessions) == 2
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_element_timeseries_inheritance(self, session):
        """Test that ElementTimeseries properly inherits Element behavior."""
        ts = ElementTimeseries(
            session=session,
            name="signal1",
            reference=1,
            type="voltage",
        )
        # Should have Element properties
        assert ts.name == "signal1"
        assert ts.elementstring() == "signal1 | 1"

        # Should have DocumentService methods
        doc = ts.newdocument()
        assert doc is not None
        assert doc.document_properties["element"]["name"] == "signal1"

    def test_neuron_inherits_timeseries(self, session):
        """Test that Neuron has timeseries capabilities."""
        n = Neuron(session=session, name="neuron1", reference=1)

        # Should have readtimeseries
        assert hasattr(n, "readtimeseries")
        assert hasattr(n, "samplerate")
        assert hasattr(n, "addepoch")

        # Test readtimeseries returns empty data
        data, times, ref = n.readtimeseries(1)
        assert len(data) == 0
