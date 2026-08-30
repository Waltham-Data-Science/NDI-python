"""Tests for ndi.database module."""

import shutil
import tempfile
from pathlib import Path

import pytest

from ndi import ndi_database, ndi_document, ndi_ido, ndi_query, open_database


@pytest.fixture
def temp_session():
    """Create a temporary session directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


# These fixtures build documents through ``ndi_document(type)`` rather than by
# hand.  A hand-built ``document_class`` carries only ``class_name`` and
# ``superclasses``; DID-python's validator (which ``add_docs`` now runs by
# default) requires the full contract MATLAB has always written --
# ``definition``, ``validation`` and ``property_list_name`` -- so a literal
# stands in for a document NDI itself would never create.


@pytest.fixture
def session_id():
    """A syntactically valid session id (base.session_id must be a did UID)."""
    return ndi_ido().id


@pytest.fixture
def sample_doc(session_id):
    """Create a sample document for testing."""
    return ndi_document(
        "base",
        **{
            "base.name": "test_doc",
            "base.session_id": session_id,
        },
    )


@pytest.fixture
def element_doc(session_id):
    """Create a sample element document for testing."""
    return ndi_document(
        "element",
        **{
            "base.name": "electrode1",
            "base.session_id": session_id,
            "element.type": "probe",
            "element.reference": "ground",
        },
    )


class TestDatabaseCreation:
    """Test ndi_database creation."""

    def test_create_database(self, temp_session):
        """Test creating a database (uses DID-python SQLite)."""
        db = ndi_database(temp_session)
        assert db.session_path == temp_session
        assert (temp_session / ".ndi").exists()
        assert (temp_session / ".ndi" / "did-sqlite.sqlite").exists()

    def test_create_with_custom_db_name(self, temp_session):
        """Test creating database with custom name."""
        ndi_database(temp_session, db_name=".mydb")
        assert (temp_session / ".mydb").exists()

    def test_open_database_function(self, temp_session):
        """Test open_database convenience function."""
        db = open_database(temp_session)
        assert isinstance(db, ndi_database)
        assert db.session_path == temp_session

    def test_database_repr(self, temp_session):
        """Test database string representation."""
        db = ndi_database(temp_session)
        assert "ndi_database" in repr(db)
        assert str(temp_session) in repr(db)


class TestDatabaseAdd:
    """Test ndi_database add operations."""

    def test_add_document(self, temp_session, sample_doc):
        """Test adding a document."""
        db = ndi_database(temp_session)
        result = db.add(sample_doc)
        assert result.id == sample_doc.id

    def test_add_duplicate_raises(self, temp_session, sample_doc):
        """Test that adding duplicate raises error."""
        db = ndi_database(temp_session)
        db.add(sample_doc)
        with pytest.raises(ValueError, match="already exists"):
            db.add(sample_doc)

    def test_add_many(self, temp_session):
        """Test adding multiple documents."""
        db = ndi_database(temp_session)
        docs = [ndi_document("base", **{"base.name": f"doc_{i}"}) for i in range(3)]

        added = db.add_many(docs)
        assert len(added) == 3
        assert db.numdocs() == 3


class TestDatabaseRead:
    """Test ndi_database read operations."""

    def test_read_existing(self, temp_session, sample_doc):
        """Test reading an existing document."""
        db = ndi_database(temp_session)
        db.add(sample_doc)

        result = db.read(sample_doc.id)
        assert result is not None
        assert result.id == sample_doc.id

    def test_read_nonexistent(self, temp_session):
        """Test reading nonexistent document returns None."""
        db = ndi_database(temp_session)
        result = db.read("nonexistent_id")
        assert result is None

    def test_find_by_id_alias(self, temp_session, sample_doc):
        """Test find_by_id is alias for read."""
        db = ndi_database(temp_session)
        db.add(sample_doc)

        result = db.find_by_id(sample_doc.id)
        assert result is not None
        assert result.id == sample_doc.id


class TestDatabaseImmutability:
    """Documents cannot be updated in place, and ids are not re-usable.

    ``ndi_database`` used to expose ``update()`` and ``add_or_replace()``,
    both implemented as remove-then-add under the same id. NDI-matlab's
    ``ndi.database`` has neither, and DID has no update primitive in either
    language -- ``add_docs`` takes OnDuplicate in {ignore, warn, error}, with
    no replace. DID also retires the id of a document removed from its last
    branch (DID-matlab#55), so the mechanism those methods used is now
    refused outright. They were removed rather than reimplemented.
    """

    def test_adding_a_duplicate_id_raises_and_says_what_to_do(self, temp_session, sample_doc):
        db = ndi_database(temp_session)
        db.add(sample_doc)

        with pytest.raises(ValueError) as excinfo:
            db.add(sample_doc)

        message = str(excinfo.value)
        assert sample_doc.id in message
        assert "immutable" in message

    def test_the_update_surface_is_gone(self, temp_session):
        """Pinned so neither method comes back without this decision reopening."""
        db = ndi_database(temp_session)
        assert not hasattr(db, "update")
        assert not hasattr(db, "add_or_replace")


class TestDatabaseRemove:
    """Test ndi_database remove operations."""

    def test_remove_existing(self, temp_session, sample_doc):
        """Test removing an existing document."""
        db = ndi_database(temp_session)
        db.add(sample_doc)

        result = db.remove(sample_doc)
        assert result is True
        assert db.read(sample_doc.id) is None

    def test_remove_by_id(self, temp_session, sample_doc):
        """Test removing by ID string."""
        db = ndi_database(temp_session)
        db.add(sample_doc)

        result = db.remove(sample_doc.id)
        assert result is True

    def test_remove_nonexistent(self, temp_session):
        """Test removing nonexistent returns False."""
        db = ndi_database(temp_session)
        result = db.remove("nonexistent_id")
        assert result is False


class TestDatabaseSearch:
    """Test ndi_database search operations."""

    def test_search_all(self, temp_session):
        """Test searching for all documents."""
        db = ndi_database(temp_session)

        # Add some documents
        for i in range(3):
            db.add(ndi_document("base", **{"base.name": f"doc_{i}"}))

        results = db.search()
        assert len(results) == 3

    def test_search_with_query(self, temp_session):
        """Test searching with a query."""
        db = ndi_database(temp_session)

        # Add documents with different names
        for name in ["alpha", "beta", "gamma"]:
            db.add(ndi_document("base", **{"base.name": name}))

        # Search for specific name
        query = ndi_query("base.name") == "beta"
        results = db.search(query)
        assert len(results) == 1
        assert results[0].document_properties["base"]["name"] == "beta"

    def test_search_empty_result(self, temp_session, sample_doc):
        """Test search returns empty list when no matches."""
        db = ndi_database(temp_session)
        db.add(sample_doc)

        query = ndi_query("base.name") == "nonexistent"
        results = db.search(query)
        assert results == []


class TestDatabaseCounts:
    """Test ndi_database counting operations."""

    def test_numdocs_empty(self, temp_session):
        """Test numdocs on empty database."""
        db = ndi_database(temp_session)
        assert db.numdocs() == 0

    def test_numdocs_with_docs(self, temp_session):
        """Test numdocs with documents."""
        db = ndi_database(temp_session)

        for i in range(5):
            db.add(ndi_document("base", **{"base.name": f"doc_{i}"}))

        assert db.numdocs() == 5

    def test_alldocids(self, temp_session):
        """Test getting all document IDs."""
        db = ndi_database(temp_session)
        added_ids = []

        for i in range(3):
            doc = ndi_document("base", **{"base.name": f"doc_{i}"})
            db.add(doc)
            added_ids.append(doc.id)

        all_ids = db.alldocids()
        assert len(all_ids) == 3
        for id in added_ids:
            assert id in all_ids


class TestDatabaseDependencies:
    """Test ndi_database dependency operations."""

    def test_find_dependencies(self, temp_session):
        """Test finding dependencies of a document."""
        db = ndi_database(temp_session)

        # ``syncgraph`` stands in for a generic parent/child pair: its schema
        # declares exactly one optional dependency (``syncrule_id``), so a
        # child can name a parent without dragging in required siblings.
        parent = ndi_document("base", **{"base.name": "parent"})
        db.add(parent)

        child = ndi_document("daq/syncgraph", **{"base.name": "child"})
        # ``syncrule_id`` is enumerated: syncgraph.json seeds no entry, so the
        # child grows one (``syncrule_id1``) the way ndi.syncgraph does.
        child = child.add_dependency_value_n("syncrule_id", parent.id)
        db.add(child)

        # Find child's dependencies
        deps = db.find_dependencies(child)
        assert len(deps) == 1
        assert deps[0].id == parent.id


class TestDatabaseDependsSQLite:
    """Test that depends_on is correctly stored in SQLite doc_data table."""

    def test_depends_on_bare_dict_stored_in_doc_data(self, temp_session):
        """Test that a bare dict depends_on (MATLAB-style) is stored in doc_data."""
        db = ndi_database(temp_session)

        parent = ndi_document("base", **{"base.name": "parent"})
        db.add(parent)

        # MATLAB's jsonencode unwraps a one-element cell array, so a document
        # written by MATLAB carries ``depends_on`` as a bare struct rather than
        # a list.  Written here deliberately in that shape.
        child = ndi_document("daq/syncgraph", **{"base.name": "child"})
        child.document_properties["depends_on"] = {
            "name": "syncrule_id",
            "value": parent.id,
        }
        db.add(child)

        # Verify depends_on was stored in doc_data by querying with depends_on
        from ndi.query import ndi_query

        results = db.search(ndi_query("").depends_on("syncrule_id", parent.id))
        assert len(results) == 1
        assert results[0].id == child.id


class TestDatabasePaths:
    """Test ndi_database path properties."""

    def test_database_path(self, temp_session):
        """Test database_path property points to SQLite file."""
        db = ndi_database(temp_session)
        assert db.database_path.exists()
        assert str(db.database_path).endswith("did-sqlite.sqlite")

    def test_binary_path_is_dids_file_directory(self, temp_session):
        """binary_path reports DID's FileDir, not a second store beside it.

        NDI used to keep its own ``<db>/files`` directory and name files
        ``{doc_id}_{filename}``. Since #65 files are DID's, as they already
        were in NDI-matlab, so this must agree with where DID actually puts
        them -- ``files/`` beside the database file.
        """
        db = ndi_database(temp_session)
        assert db.binary_path == Path(db._driver._db._file_dir())
        assert db.binary_path.name == "files"

    def test_the_composed_path_api_is_gone(self, temp_session):
        """``get_binary_path`` handed back a path without saying if anything
        was there, and composed it in a layout only NDI-python ever used.
        ``open_binary`` / ``exist_binary`` ask DID instead."""
        db = ndi_database(temp_session)
        assert not hasattr(db, "get_binary_path")
        assert hasattr(db, "open_binary")
        assert hasattr(db, "exist_binary")

    def test_exist_binary_is_false_for_a_document_with_no_file(self, temp_session, sample_doc):
        db = ndi_database(temp_session)
        db.add(sample_doc)
        found, path = db.exist_binary(sample_doc, "data.bin")
        assert found is False
        assert path is None


class TestDatabaseRemoveMany:
    """Test ndi_database remove_many operation."""

    def test_remove_many_by_query(self, temp_session):
        """Test removing multiple documents by query."""
        db = ndi_database(temp_session)

        # Add documents with different types
        for name, doc_type in [("a", "alpha"), ("b", "alpha"), ("c", "beta")]:
            doc = ndi_document("base", **{"base.name": name})
            # ``meta`` is not declared by base_schema.json; an undeclared extra
            # property is carried through, which is what this test queries on.
            doc.document_properties["meta"] = {"type": doc_type}
            db.add(doc)

        assert db.numdocs() == 3

        # Remove all alpha type
        query = ndi_query("meta.type") == "alpha"
        count = db.remove_many(query=query)
        assert count == 2
        assert db.numdocs() == 1
