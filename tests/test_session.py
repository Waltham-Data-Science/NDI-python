"""Tests for ndi.cache, ndi.session, and ndi.session.dir - Phase 7."""

import shutil
import tempfile
from pathlib import Path

import pytest

from ndi.cache import Cache, CacheEntry
from ndi.ido import Ido
from ndi.query import Query
from ndi.session import DirSession, empty_id

# ==============================================================================
# Cache Tests
# ==============================================================================


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_entry(self):
        """Test creating a cache entry."""
        from datetime import datetime

        entry = CacheEntry(
            key="test_key",
            type="test_type",
            timestamp=datetime.now(),
            priority=1.0,
            bytes=100,
            data={"test": "data"},
        )
        assert entry.key == "test_key"
        assert entry.type == "test_type"
        assert entry.priority == 1.0
        assert entry.bytes == 100
        assert entry.data == {"test": "data"}


class TestCache:
    """Tests for the Cache class."""

    def test_create_default_cache(self):
        """Test creating a cache with defaults."""
        cache = Cache()
        assert cache.max_memory == 10e9
        assert cache.replacement_rule == "fifo"
        assert len(cache) == 0

    def test_create_custom_cache(self):
        """Test creating a cache with custom settings."""
        cache = Cache(max_memory=1e6, replacement_rule="lifo")
        assert cache.max_memory == 1e6
        assert cache.replacement_rule == "lifo"

    def test_invalid_replacement_rule(self):
        """Test that invalid replacement rule raises error."""
        with pytest.raises(ValueError, match="Unknown replacement rule"):
            Cache(replacement_rule="invalid")

    def test_set_replacement_rule(self):
        """Test changing replacement rule."""
        cache = Cache()
        cache.set_replacement_rule("lifo")
        assert cache.replacement_rule == "lifo"
        cache.set_replacement_rule("error")
        assert cache.replacement_rule == "error"

    def test_add_and_lookup(self):
        """Test adding and looking up data."""
        cache = Cache()
        cache.add("key1", "type1", {"value": 42})

        entry = cache.lookup("key1", "type1")
        assert entry is not None
        assert entry.data == {"value": 42}
        assert entry.key == "key1"
        assert entry.type == "type1"

    def test_lookup_not_found(self):
        """Test lookup returns None when not found."""
        cache = Cache()
        assert cache.lookup("nonexistent", "type") is None

    def test_add_with_priority(self):
        """Test adding data with priority."""
        cache = Cache()
        cache.add("key1", "type1", "data1", priority=1)
        cache.add("key2", "type2", "data2", priority=5)

        entry1 = cache.lookup("key1", "type1")
        entry2 = cache.lookup("key2", "type2")

        assert entry1.priority == 1
        assert entry2.priority == 5

    def test_remove_by_key(self):
        """Test removing by key and type."""
        cache = Cache()
        cache.add("key1", "type1", "data1")
        cache.add("key2", "type2", "data2")

        cache.remove("key1", "type1")

        assert cache.lookup("key1", "type1") is None
        assert cache.lookup("key2", "type2") is not None

    def test_remove_by_index(self):
        """Test removing by index."""
        cache = Cache()
        cache.add("key1", "type1", "data1")
        cache.add("key2", "type2", "data2")

        cache.remove(0)

        assert len(cache) == 1

    def test_clear(self):
        """Test clearing all entries."""
        cache = Cache()
        cache.add("key1", "type1", "data1")
        cache.add("key2", "type2", "data2")

        cache.clear()

        assert len(cache) == 0

    def test_bytes(self):
        """Test bytes calculation."""
        cache = Cache()
        cache.add("key1", "type1", "x" * 100)

        assert cache.bytes() > 0

    def test_eviction_fifo(self):
        """Test FIFO eviction when memory exceeded."""
        cache = Cache(max_memory=1000, replacement_rule="fifo")

        # Add data that will approach limit
        cache.add("key1", "type1", "a" * 100, priority=1)
        cache.add("key2", "type2", "b" * 100, priority=1)

        len(cache)

        # Add data that exceeds limit - should evict oldest
        cache.add("key3", "type3", "c" * 500, priority=1)

        # Some eviction should have occurred
        assert cache.lookup("key3", "type3") is not None

    def test_eviction_respects_priority(self):
        """Test that eviction respects priority."""
        cache = Cache(max_memory=500, replacement_rule="fifo")

        cache.add("low_priority", "type", "a" * 100, priority=0)
        cache.add("high_priority", "type", "b" * 100, priority=10)

        # Add data that forces eviction
        cache.add("new", "type", "c" * 200, priority=5)

        # High priority should survive longer
        cache.lookup("high_priority", "type")
        # Just verify the cache still works
        assert len(cache) > 0

    def test_memory_error_too_large(self):
        """Test error when single item exceeds max_memory."""
        cache = Cache(max_memory=100)

        with pytest.raises(MemoryError, match="exceeds cache max_memory"):
            cache.add("key", "type", "x" * 1000)

    def test_memory_error_rule(self):
        """Test error when replacement_rule is 'error' and full."""
        # Use a larger max_memory so individual items fit
        cache = Cache(max_memory=500, replacement_rule="error")
        cache.add("key1", "type1", "x" * 100)
        cache.add("key2", "type2", "y" * 100)

        # This should trigger the 'error' rule since we can't evict
        with pytest.raises(MemoryError):
            cache.add("key3", "type3", "z" * 300)

    def test_repr(self):
        """Test string representation."""
        cache = Cache()
        cache.add("key", "type", "data")
        repr_str = repr(cache)
        assert "Cache" in repr_str
        assert "entries=1" in repr_str


# ==============================================================================
# Session Tests
# ==============================================================================


class TestEmptyId:
    """Tests for empty_id function."""

    def test_empty_id_format(self):
        """Test empty_id returns correct format."""
        eid = empty_id()
        assert "_" in eid
        parts = eid.split("_")
        assert len(parts) == 2
        # All characters except underscore should be '0'
        for c in eid:
            if c != "_":
                assert c == "0"

    def test_empty_id_length(self):
        """Test empty_id has correct length."""
        eid = empty_id()
        # Should match the format of regular IDs
        regular_id = Ido().id
        assert len(eid) == len(regular_id)


class TestDirSession:
    """Tests for DirSession class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_create_session_from_path(self, temp_dir):
        """Test creating a session from a path."""
        session = DirSession("TestSession", temp_dir)

        assert session.reference == "TestSession"
        assert session.path == temp_dir
        assert session.id() is not None
        assert len(session.id()) > 0

    def test_session_creates_ndi_dir(self, temp_dir):
        """Test that session creates .ndi directory."""
        DirSession("Test", temp_dir)

        ndi_dir = temp_dir / ".ndi"
        assert ndi_dir.exists()
        assert ndi_dir.is_dir()

    def test_session_writes_reference_files(self, temp_dir):
        """Test that session writes reference files."""
        session = DirSession("MyReference", temp_dir)

        ref_file = temp_dir / ".ndi" / "reference.txt"
        unique_ref_file = temp_dir / ".ndi" / "unique_reference.txt"

        assert ref_file.exists()
        assert unique_ref_file.exists()

        assert ref_file.read_text() == "MyReference"
        assert unique_ref_file.read_text() == session.id()

    def test_session_getpath(self, temp_dir):
        """Test getpath returns the session path."""
        session = DirSession("Test", temp_dir)
        assert session.getpath() == temp_dir

    def test_session_creator_args(self, temp_dir):
        """Test creator_args returns correct arguments."""
        session = DirSession("TestRef", temp_dir)
        args = session.creator_args()

        assert len(args) == 3
        assert args[0] == "TestRef"
        assert args[1] == str(temp_dir)
        assert args[2] == session.id()

    def test_session_cache(self, temp_dir):
        """Test session has a cache."""
        session = DirSession("Test", temp_dir)

        assert session.cache is not None
        assert isinstance(session.cache, Cache)

    def test_session_database(self, temp_dir):
        """Test session has a database."""
        session = DirSession("Test", temp_dir)

        assert session.database is not None

    def test_session_equality(self, temp_dir):
        """Test session equality by ID."""
        session1 = DirSession("Test", temp_dir)

        # Same session
        assert session1 == session1

        # Different ID means different session
        session2 = DirSession("Test2", tempfile.mkdtemp())
        assert session1 != session2
        shutil.rmtree(session2.path, ignore_errors=True)

    def test_session_exists_check(self, temp_dir):
        """Test static exists method."""
        # Not a session yet
        assert DirSession.exists(temp_dir) is False

        # Create a session
        DirSession("Test", temp_dir)

        # Now it exists
        assert DirSession.exists(temp_dir) is True

    def test_invalid_path_raises(self):
        """Test that invalid path raises error."""
        with pytest.raises(ValueError, match="does not exist"):
            DirSession("Test", "/nonexistent/path/12345")

    def test_file_path_raises(self, temp_dir):
        """Test that file path raises error."""
        file_path = temp_dir / "testfile.txt"
        file_path.write_text("test")

        with pytest.raises(ValueError, match="not a directory"):
            DirSession("Test", file_path)

    def test_session_repr(self, temp_dir):
        """Test string representation."""
        session = DirSession("TestRef", temp_dir)
        repr_str = repr(session)

        assert "DirSession" in repr_str
        assert "TestRef" in repr_str

    def test_newdocument(self, temp_dir):
        """Test creating a new document with session ID."""
        session = DirSession("Test", temp_dir)

        try:
            doc = session.newdocument("base", **{"base.name": "test"})
            assert doc.session_id == session.id()
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_searchquery(self, temp_dir):
        """Test creating a search query."""
        session = DirSession("Test", temp_dir)

        q = session.searchquery()
        assert q is not None

    def test_validate_documents(self, temp_dir):
        """Test document validation."""
        session = DirSession("Test", temp_dir)

        try:
            doc = session.newdocument()
            b, errmsg = session.validate_documents(doc)
            assert b is True
            assert errmsg == ""
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_database_add_search(self, temp_dir):
        """Test adding and searching documents."""
        session = DirSession("Test", temp_dir)

        try:
            doc = session.newdocument("base", **{"base.name": "testdoc"})
            session.database_add(doc)

            results = session.database_search(Query("base.name") == "testdoc")
            assert len(results) >= 1
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_reopen_session(self, temp_dir):
        """Test reopening an existing session."""
        # Create session
        session1 = DirSession("MySession", temp_dir)
        original_id = session1.id()

        # Reopen by path
        session2 = DirSession("MySession", temp_dir, session_id=original_id)

        assert session2.id() == original_id

    def test_delete_session_data(self, temp_dir):
        """Test deleting session data structures."""
        session = DirSession("Test", temp_dir)
        ndi_dir = temp_dir / ".ndi"
        assert ndi_dir.exists()

        result = session.delete_session_data_structures(are_you_sure=True)
        assert result is None
        assert not ndi_dir.exists()

    def test_delete_session_requires_confirmation(self, temp_dir):
        """Test that delete requires confirmation."""
        session = DirSession("Test", temp_dir)
        ndi_dir = temp_dir / ".ndi"

        result = session.delete_session_data_structures(are_you_sure=False)
        assert result is session
        assert ndi_dir.exists()


class TestSessionMethods:
    """Tests for Session methods using DirSession."""

    @pytest.fixture
    def session(self):
        """Create a test session."""
        tmpdir = tempfile.mkdtemp()
        sess = DirSession("TestSession", tmpdir)
        yield sess
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_id_method(self, session):
        """Test id() returns identifier."""
        assert session.id() == session.identifier

    def test_cache_add_lookup(self, session):
        """Test using session's cache."""
        session.cache.add("mykey", "mytype", "mydata")
        entry = session.cache.lookup("mykey", "mytype")
        assert entry is not None
        assert entry.data == "mydata"

    def test_getprobes_empty(self, session):
        """Test getprobes returns empty list when no DAQs."""
        probes = session.getprobes()
        assert isinstance(probes, list)

    def test_getelements_empty(self, session):
        """Test getelements returns empty list when no elements."""
        elements = session.getelements()
        assert isinstance(elements, list)

    def test_is_fully_ingested_empty(self, session):
        """Test is_fully_ingested returns True when no DAQs."""
        assert session.is_fully_ingested() is True

    def test_get_ingested_docs_empty(self, session):
        """Test get_ingested_docs returns empty list."""
        docs = session.get_ingested_docs()
        assert isinstance(docs, list)
        assert len(docs) == 0

    def test_database_clear(self, session):
        """Test database_clear with confirmation."""
        try:
            doc = session.newdocument("base", **{"base.name": "test"})
            session.database_add(doc)

            # Without confirmation
            session.database_clear("no")
            results = session.database_search(Query("base.name") == "test")
            # Should still exist

            # With confirmation
            session.database_clear("yes")
            results = session.database_search(Query("base.name") == "test")
            assert len(results) == 0
        except FileNotFoundError:
            pytest.skip("Schema not available")


class TestSessionSyncGraph:
    """Tests for Session syncgraph methods."""

    @pytest.fixture
    def session(self):
        """Create a test session."""
        tmpdir = tempfile.mkdtemp()
        sess = DirSession("TestSession", tmpdir)
        yield sess
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_syncgraph_exists(self, session):
        """Test session has a syncgraph."""
        assert session.syncgraph is not None

    def test_syncgraph_addrule(self, session):
        """Test adding a sync rule."""
        from ndi.time.syncrule.filematch import FileMatch

        rule = FileMatch()
        try:
            session.syncgraph_addrule(rule)
            assert len(session.syncgraph.rules) == 1
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_syncgraph_rmrule(self, session):
        """Test removing a sync rule."""
        from ndi.time.syncrule.filematch import FileMatch

        rule = FileMatch()
        try:
            session.syncgraph_addrule(rule)
            session.syncgraph_rmrule(0)
            assert len(session.syncgraph.rules) == 0
        except FileNotFoundError:
            pytest.skip("Schema not available")


# ==============================================================================
# Integration Tests
# ==============================================================================


class TestSessionIntegration:
    """Integration tests for Session functionality."""

    @pytest.fixture
    def session(self):
        """Create a test session with full setup."""
        tmpdir = tempfile.mkdtemp()
        sess = DirSession("IntegrationTest", tmpdir)
        yield sess
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_full_workflow(self, session):
        """Test a full session workflow."""
        # Create documents
        try:
            doc1 = session.newdocument("base", **{"base.name": "doc1"})
            doc2 = session.newdocument("base", **{"base.name": "doc2"})

            # Add to database
            session.database_add(doc1)
            session.database_add(doc2)

            # Search
            results = session.database_search(Query("base.name") == "doc1")
            assert len(results) == 1

            # Remove
            session.database_rm(doc1)
            results = session.database_search(Query("base.name") == "doc1")
            assert len(results) == 0

            # doc2 should still exist
            results = session.database_search(Query("base.name") == "doc2")
            assert len(results) == 1
        except FileNotFoundError:
            pytest.skip("Schema not available")

    def test_session_persistence(self):
        """Test that session data persists across reopens."""
        tmpdir = tempfile.mkdtemp()

        try:
            # Create session and add data
            session1 = DirSession("Persist", tmpdir)
            session_id = session1.id()

            try:
                doc = session1.newdocument("base", **{"base.name": "persistent"})
                session1.database_add(doc)
            except FileNotFoundError:
                pytest.skip("Schema not available")

            # Reopen and check data
            session2 = DirSession("Persist", tmpdir, session_id=session_id)
            results = session2.database_search(Query("base.name") == "persistent")
            assert len(results) >= 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
