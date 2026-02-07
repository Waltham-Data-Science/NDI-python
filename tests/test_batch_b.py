"""
Tests for Batch B: DAQ readers, Document methods, MockSession.

Tests format-specific readers, Document.write() and
remove_dependency_value_n(), and MockSession.
"""

import json
import os

# ============================================================================
# Document.write() Tests
# ============================================================================


class TestDocumentWrite:
    """Tests for Document.write() method."""

    def test_write_creates_file(self, tmp_path):
        from ndi.document import Document

        doc = Document("base", **{"base.name": "test_write"})
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath)
        assert os.path.exists(filepath)

    def test_write_valid_json(self, tmp_path):
        from ndi.document import Document

        doc = Document("base", **{"base.name": "test_write"})
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath)
        with open(filepath) as f:
            data = json.load(f)
        assert data["base"]["name"] == "test_write"

    def test_write_creates_parent_dirs(self, tmp_path):
        from ndi.document import Document

        doc = Document("base")
        filepath = str(tmp_path / "sub" / "dir" / "doc.json")
        doc.write(filepath)
        assert os.path.exists(filepath)

    def test_write_roundtrip(self, tmp_path):
        from ndi.document import Document

        doc = Document("base", **{"base.name": "roundtrip"})
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath)

        with open(filepath) as f:
            data = json.load(f)

        doc2 = Document(data)
        assert doc2._document_properties["base"]["name"] == "roundtrip"

    def test_write_with_indent(self, tmp_path):
        from ndi.document import Document

        doc = Document("base")
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath, indent=4)
        with open(filepath) as f:
            content = f.read()
        # 4-space indent should produce wider indentation
        assert "    " in content


# ============================================================================
# Document.remove_dependency_value_n() Tests
# ============================================================================


class TestDocumentRemoveDependencyN:
    """Tests for Document.remove_dependency_value_n()."""

    def test_remove_specific_index(self):
        from ndi.document import Document

        doc = Document("base")
        doc.set_dependency_value("dep_1", "val1", error_if_not_found=False)
        doc.set_dependency_value("dep_2", "val2", error_if_not_found=False)
        doc.set_dependency_value("dep_3", "val3", error_if_not_found=False)

        doc.remove_dependency_value_n("dep", index=2)

        # Check that dep_2 was removed from raw depends_on
        dep_names = [d["name"] for d in doc._document_properties["depends_on"]]
        assert "dep_2" not in dep_names
        assert "dep_1" in dep_names
        assert "dep_3" in dep_names

    def test_remove_all_matching(self):
        from ndi.document import Document

        doc = Document("base")
        doc.set_dependency_value("dep_1", "val1", error_if_not_found=False)
        doc.set_dependency_value("dep_2", "val2", error_if_not_found=False)
        doc.set_dependency_value("other", "keep", error_if_not_found=False)

        doc.remove_dependency_value_n("dep")
        values = doc.dependency_value_n("dep", error_if_not_found=False)
        assert len(values) == 0

        # 'other' should still exist
        assert doc.dependency_value("other") == "keep"

    def test_remove_no_dependencies(self):
        from ndi.document import Document

        doc = Document("base")
        # Should not raise
        doc.remove_dependency_value_n("nonexistent")

    def test_remove_returns_self(self):
        from ndi.document import Document

        doc = Document("base")
        result = doc.remove_dependency_value_n("dep")
        assert result is doc


# ============================================================================
# Format-Specific Reader Tests
# ============================================================================


class TestIntanReader:
    """Tests for IntanReader."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.intan import IntanReader

        assert IntanReader is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.intan import IntanReader

        reader = IntanReader()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.intan"

    def test_inherits_mfdaq_reader(self):
        from ndi.daq.mfdaq import MFDAQReader
        from ndi.daq.reader.mfdaq.intan import IntanReader

        reader = IntanReader()
        assert isinstance(reader, MFDAQReader)

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.intan import IntanReader

        assert ".rhd" in IntanReader.FILE_EXTENSIONS
        assert ".rhs" in IntanReader.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.intan import IntanReader

        reader = IntanReader()
        assert "IntanReader" in repr(reader)


class TestBlackrockReader:
    """Tests for BlackrockReader."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.blackrock import BlackrockReader

        assert BlackrockReader is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.blackrock import BlackrockReader

        reader = BlackrockReader()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.blackrock"

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.blackrock import BlackrockReader

        assert ".ns5" in BlackrockReader.FILE_EXTENSIONS
        assert ".nev" in BlackrockReader.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.blackrock import BlackrockReader

        assert "BlackrockReader" in repr(BlackrockReader())


class TestCEDSpike2Reader:
    """Tests for CEDSpike2Reader."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.cedspike2 import CEDSpike2Reader

        assert CEDSpike2Reader is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.cedspike2 import CEDSpike2Reader

        reader = CEDSpike2Reader()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.cedspike2"

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.cedspike2 import CEDSpike2Reader

        assert ".smr" in CEDSpike2Reader.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.cedspike2 import CEDSpike2Reader

        assert "CEDSpike2Reader" in repr(CEDSpike2Reader())


class TestSpikeGadgetsReader:
    """Tests for SpikeGadgetsReader."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.spikegadgets import SpikeGadgetsReader

        assert SpikeGadgetsReader is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.spikegadgets import SpikeGadgetsReader

        reader = SpikeGadgetsReader()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.spikegadgets"

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.spikegadgets import SpikeGadgetsReader

        assert ".rec" in SpikeGadgetsReader.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.spikegadgets import SpikeGadgetsReader

        assert "SpikeGadgetsReader" in repr(SpikeGadgetsReader())


class TestReaderPackageImports:
    """Test that format-specific readers are importable from expected paths."""

    def test_from_reader_mfdaq(self):
        from ndi.daq.reader.mfdaq import (
            BlackrockReader,
            CEDSpike2Reader,
            IntanReader,
            SpikeGadgetsReader,
        )

        assert all([IntanReader, BlackrockReader, CEDSpike2Reader, SpikeGadgetsReader])

    def test_from_reader(self):
        from ndi.daq.reader import BlackrockReader, CEDSpike2Reader, IntanReader, SpikeGadgetsReader

        assert all([IntanReader, BlackrockReader, CEDSpike2Reader, SpikeGadgetsReader])

    def test_all_inherit_from_mfdaq_reader(self):
        from ndi.daq.mfdaq import MFDAQReader
        from ndi.daq.reader.mfdaq import (
            BlackrockReader,
            CEDSpike2Reader,
            IntanReader,
            SpikeGadgetsReader,
        )

        for cls in [IntanReader, BlackrockReader, CEDSpike2Reader, SpikeGadgetsReader]:
            reader = cls()
            assert isinstance(reader, MFDAQReader)

    def test_each_has_unique_daqreader_class(self):
        from ndi.daq.reader.mfdaq import (
            BlackrockReader,
            CEDSpike2Reader,
            IntanReader,
            SpikeGadgetsReader,
        )

        classes = set()
        for cls in [IntanReader, BlackrockReader, CEDSpike2Reader, SpikeGadgetsReader]:
            reader = cls()
            classes.add(reader._ndi_daqreader_class)
        assert len(classes) == 4


# ============================================================================
# MockSession Tests
# ============================================================================


class TestMockSession:
    """Tests for MockSession."""

    def test_import(self):
        from ndi.session.mock import MockSession

        assert MockSession is not None

    def test_construction(self):
        from ndi.session.mock import MockSession

        session = MockSession("test")
        assert session is not None
        assert os.path.isdir(session._tmpdir)
        session.close()

    def test_inherits_dirsession(self):
        from ndi.session import DirSession
        from ndi.session.mock import MockSession

        session = MockSession("test")
        assert isinstance(session, DirSession)
        session.close()

    def test_context_manager(self):
        from ndi.session.mock import MockSession

        with MockSession("test") as session:
            tmpdir = session._tmpdir
            assert os.path.isdir(tmpdir)
        assert not os.path.exists(tmpdir)

    def test_database_operations(self):
        from ndi.document import Document
        from ndi.query import Query
        from ndi.session.mock import MockSession

        with MockSession("test") as session:
            doc = Document("base", **{"base.name": "mock_test"})
            session.database_add(doc)
            results = session.database_search(Query("").isa("base"))
            assert len(results) >= 1

    def test_cleanup_on_close(self):
        from ndi.session.mock import MockSession

        session = MockSession("test")
        tmpdir = session._tmpdir
        assert os.path.isdir(tmpdir)
        session.close()
        assert not os.path.exists(tmpdir)

    def test_no_cleanup_option(self):
        from ndi.session.mock import MockSession

        session = MockSession("test", cleanup=False)
        tmpdir = session._tmpdir
        session.close()
        assert os.path.isdir(tmpdir)  # Should still exist
        # Clean up manually
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_id_is_method(self):
        from ndi.session.mock import MockSession

        with MockSession("test") as session:
            sid = session.id()
            assert isinstance(sid, str)
            assert len(sid) > 0

    def test_repr(self):
        from ndi.session.mock import MockSession

        with MockSession("test") as session:
            assert "MockSession" in repr(session)

    def test_from_session_module(self):
        from ndi.session import MockSession

        assert MockSession is not None
