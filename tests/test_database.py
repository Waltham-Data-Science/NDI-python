"""Tests for ndi.database module."""

import pytest
import tempfile
import shutil
from pathlib import Path

from ndi import Database, Document, Query, Ido, open_database
from ndi.common import timestamp


@pytest.fixture
def temp_session():
    """Create a temporary session directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_doc():
    """Create a sample document for testing."""
    ido = Ido()
    return Document({
        'base': {
            'id': ido.id,
            'datestamp': timestamp(),
            'name': 'test_doc',
            'session_id': 'session_123'
        },
        'document_class': {
            'class_name': 'base',
            'superclasses': []
        }
    })


@pytest.fixture
def element_doc():
    """Create a sample element document for testing."""
    ido = Ido()
    return Document({
        'base': {
            'id': ido.id,
            'datestamp': timestamp(),
            'name': 'electrode1',
            'session_id': 'session_123'
        },
        'document_class': {
            'class_name': 'element',
            'superclasses': [{'definition': '$NDIDOCUMENTPATH/base.json'}]
        },
        'element': {
            'type': 'probe',
            'reference': 'ground'
        }
    })


class TestDatabaseCreation:
    """Test Database creation."""

    def test_create_database(self, temp_session):
        """Test creating a database (uses DID-python SQLite)."""
        db = Database(temp_session)
        assert db.session_path == temp_session
        assert (temp_session / '.ndi').exists()
        assert (temp_session / '.ndi' / 'ndi.db').exists()

    def test_create_with_custom_db_name(self, temp_session):
        """Test creating database with custom name."""
        db = Database(temp_session, db_name='.mydb')
        assert (temp_session / '.mydb').exists()

    def test_open_database_function(self, temp_session):
        """Test open_database convenience function."""
        db = open_database(temp_session)
        assert isinstance(db, Database)
        assert db.session_path == temp_session

    def test_database_repr(self, temp_session):
        """Test database string representation."""
        db = Database(temp_session)
        assert "Database" in repr(db)
        assert str(temp_session) in repr(db)


class TestDatabaseAdd:
    """Test Database add operations."""

    def test_add_document(self, temp_session, sample_doc):
        """Test adding a document."""
        db = Database(temp_session)
        result = db.add(sample_doc)
        assert result.id == sample_doc.id

    def test_add_duplicate_raises(self, temp_session, sample_doc):
        """Test that adding duplicate raises error."""
        db = Database(temp_session)
        db.add(sample_doc)
        with pytest.raises(ValueError, match="already exists"):
            db.add(sample_doc)

    def test_add_many(self, temp_session):
        """Test adding multiple documents."""
        db = Database(temp_session)
        docs = []
        for i in range(3):
            ido = Ido()
            doc = Document({
                'base': {
                    'id': ido.id,
                    'datestamp': timestamp(),
                    'name': f'doc_{i}',
                    'session_id': ''
                },
                'document_class': {'class_name': 'base', 'superclasses': []}
            })
            docs.append(doc)

        added = db.add_many(docs)
        assert len(added) == 3
        assert db.numdocs() == 3


class TestDatabaseRead:
    """Test Database read operations."""

    def test_read_existing(self, temp_session, sample_doc):
        """Test reading an existing document."""
        db = Database(temp_session)
        db.add(sample_doc)

        result = db.read(sample_doc.id)
        assert result is not None
        assert result.id == sample_doc.id

    def test_read_nonexistent(self, temp_session):
        """Test reading nonexistent document returns None."""
        db = Database(temp_session)
        result = db.read('nonexistent_id')
        assert result is None

    def test_find_by_id_alias(self, temp_session, sample_doc):
        """Test find_by_id is alias for read."""
        db = Database(temp_session)
        db.add(sample_doc)

        result = db.find_by_id(sample_doc.id)
        assert result is not None
        assert result.id == sample_doc.id


class TestDatabaseUpdate:
    """Test Database update operations."""

    def test_update_existing(self, temp_session, sample_doc):
        """Test updating an existing document."""
        db = Database(temp_session)
        db.add(sample_doc)

        # Modify and update
        sample_doc = sample_doc.setproperties(**{'base.name': 'updated_name'})
        result = db.update(sample_doc)
        assert result.document_properties['base']['name'] == 'updated_name'

        # Verify persisted
        reread = db.read(sample_doc.id)
        assert reread.document_properties['base']['name'] == 'updated_name'

    def test_update_nonexistent_raises(self, temp_session, sample_doc):
        """Test updating nonexistent document raises error."""
        db = Database(temp_session)
        with pytest.raises(ValueError, match="not found"):
            db.update(sample_doc)


class TestDatabaseRemove:
    """Test Database remove operations."""

    def test_remove_existing(self, temp_session, sample_doc):
        """Test removing an existing document."""
        db = Database(temp_session)
        db.add(sample_doc)

        result = db.remove(sample_doc)
        assert result is True
        assert db.read(sample_doc.id) is None

    def test_remove_by_id(self, temp_session, sample_doc):
        """Test removing by ID string."""
        db = Database(temp_session)
        db.add(sample_doc)

        result = db.remove(sample_doc.id)
        assert result is True

    def test_remove_nonexistent(self, temp_session):
        """Test removing nonexistent returns False."""
        db = Database(temp_session)
        result = db.remove('nonexistent_id')
        assert result is False


class TestDatabaseAddOrReplace:
    """Test Database add_or_replace operations."""

    def test_add_or_replace_new(self, temp_session, sample_doc):
        """Test add_or_replace adds new document."""
        db = Database(temp_session)
        result = db.add_or_replace(sample_doc)
        assert result.id == sample_doc.id
        assert db.numdocs() == 1

    def test_add_or_replace_existing(self, temp_session, sample_doc):
        """Test add_or_replace replaces existing document."""
        db = Database(temp_session)
        db.add(sample_doc)

        sample_doc = sample_doc.setproperties(**{'base.name': 'replaced_name'})
        db.add_or_replace(sample_doc)

        reread = db.read(sample_doc.id)
        assert reread.document_properties['base']['name'] == 'replaced_name'
        assert db.numdocs() == 1  # Still just one document


class TestDatabaseSearch:
    """Test Database search operations."""

    def test_search_all(self, temp_session):
        """Test searching for all documents."""
        db = Database(temp_session)

        # Add some documents
        for i in range(3):
            ido = Ido()
            doc = Document({
                'base': {
                    'id': ido.id,
                    'datestamp': timestamp(),
                    'name': f'doc_{i}',
                    'session_id': ''
                },
                'document_class': {'class_name': 'base', 'superclasses': []}
            })
            db.add(doc)

        results = db.search()
        assert len(results) == 3

    def test_search_with_query(self, temp_session):
        """Test searching with a query."""
        db = Database(temp_session)

        # Add documents with different names
        for name in ['alpha', 'beta', 'gamma']:
            ido = Ido()
            doc = Document({
                'base': {
                    'id': ido.id,
                    'datestamp': timestamp(),
                    'name': name,
                    'session_id': ''
                },
                'document_class': {'class_name': 'base', 'superclasses': []}
            })
            db.add(doc)

        # Search for specific name
        query = Query('base.name') == 'beta'
        results = db.search(query)
        assert len(results) == 1
        assert results[0].document_properties['base']['name'] == 'beta'

    def test_search_empty_result(self, temp_session, sample_doc):
        """Test search returns empty list when no matches."""
        db = Database(temp_session)
        db.add(sample_doc)

        query = Query('base.name') == 'nonexistent'
        results = db.search(query)
        assert results == []


class TestDatabaseCounts:
    """Test Database counting operations."""

    def test_numdocs_empty(self, temp_session):
        """Test numdocs on empty database."""
        db = Database(temp_session)
        assert db.numdocs() == 0

    def test_numdocs_with_docs(self, temp_session):
        """Test numdocs with documents."""
        db = Database(temp_session)

        for i in range(5):
            ido = Ido()
            doc = Document({
                'base': {
                    'id': ido.id,
                    'datestamp': timestamp(),
                    'name': f'doc_{i}',
                    'session_id': ''
                },
                'document_class': {'class_name': 'base', 'superclasses': []}
            })
            db.add(doc)

        assert db.numdocs() == 5

    def test_alldocids(self, temp_session):
        """Test getting all document IDs."""
        db = Database(temp_session)
        added_ids = []

        for i in range(3):
            ido = Ido()
            doc = Document({
                'base': {
                    'id': ido.id,
                    'datestamp': timestamp(),
                    'name': f'doc_{i}',
                    'session_id': ''
                },
                'document_class': {'class_name': 'base', 'superclasses': []}
            })
            db.add(doc)
            added_ids.append(ido.id)

        all_ids = db.alldocids()
        assert len(all_ids) == 3
        for id in added_ids:
            assert id in all_ids


class TestDatabaseDependencies:
    """Test Database dependency operations."""

    def test_find_dependencies(self, temp_session):
        """Test finding dependencies of a document."""
        db = Database(temp_session)

        # Create parent document
        parent_ido = Ido()
        parent = Document({
            'base': {
                'id': parent_ido.id,
                'datestamp': timestamp(),
                'name': 'parent',
                'session_id': ''
            },
            'document_class': {'class_name': 'base', 'superclasses': []}
        })
        db.add(parent)

        # Create child document with dependency
        child_ido = Ido()
        child = Document({
            'base': {
                'id': child_ido.id,
                'datestamp': timestamp(),
                'name': 'child',
                'session_id': ''
            },
            'document_class': {'class_name': 'base', 'superclasses': []},
            'depends_on': [
                {'name': 'parent_doc', 'value': parent_ido.id}
            ]
        })
        db.add(child)

        # Find child's dependencies
        deps = db.find_dependencies(child)
        assert len(deps) == 1
        assert deps[0].id == parent_ido.id


class TestDatabasePaths:
    """Test Database path properties."""

    def test_database_path(self, temp_session):
        """Test database_path property points to SQLite file."""
        db = Database(temp_session)
        assert db.database_path.exists()
        assert str(db.database_path).endswith('ndi.db')

    def test_binary_path(self, temp_session):
        """Test binary_path property."""
        db = Database(temp_session)
        assert db.binary_path.exists()

    def test_get_binary_path(self, temp_session, sample_doc):
        """Test get_binary_path method."""
        db = Database(temp_session)
        path = db.get_binary_path(sample_doc, 'data.bin')
        assert str(path).endswith(f'{sample_doc.id}_data.bin')


class TestDatabaseRemoveMany:
    """Test Database remove_many operation."""

    def test_remove_many_by_query(self, temp_session):
        """Test removing multiple documents by query."""
        db = Database(temp_session)

        # Add documents with different types
        for name, doc_type in [('a', 'alpha'), ('b', 'alpha'), ('c', 'beta')]:
            ido = Ido()
            doc = Document({
                'base': {
                    'id': ido.id,
                    'datestamp': timestamp(),
                    'name': name,
                    'session_id': ''
                },
                'document_class': {'class_name': 'base', 'superclasses': []},
                'meta': {'type': doc_type}
            })
            db.add(doc)

        assert db.numdocs() == 3

        # Remove all alpha type
        query = Query('meta.type') == 'alpha'
        count = db.remove_many(query=query)
        assert count == 2
        assert db.numdocs() == 1
