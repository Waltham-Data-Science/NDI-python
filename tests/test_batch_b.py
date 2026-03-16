"""
Tests for Batch B: DAQ readers, ndi_document methods, ndi_session_mock.

Tests format-specific readers, ndi_document.write() and
remove_dependency_value_n(), and ndi_session_mock.
"""

import json
import os

# ============================================================================
# ndi_document.write() Tests
# ============================================================================


class TestDocumentWrite:
    """Tests for ndi_document.write() method."""

    def test_write_creates_file(self, tmp_path):
        from ndi.document import ndi_document

        doc = ndi_document("base", **{"base.name": "test_write"})
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath)
        assert os.path.exists(filepath)

    def test_write_valid_json(self, tmp_path):
        from ndi.document import ndi_document

        doc = ndi_document("base", **{"base.name": "test_write"})
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath)
        with open(filepath) as f:
            data = json.load(f)
        assert data["base"]["name"] == "test_write"

    def test_write_creates_parent_dirs(self, tmp_path):
        from ndi.document import ndi_document

        doc = ndi_document("base")
        filepath = str(tmp_path / "sub" / "dir" / "doc.json")
        doc.write(filepath)
        assert os.path.exists(filepath)

    def test_write_roundtrip(self, tmp_path):
        from ndi.document import ndi_document

        doc = ndi_document("base", **{"base.name": "roundtrip"})
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath)

        with open(filepath) as f:
            data = json.load(f)

        doc2 = ndi_document(data)
        assert doc2._document_properties["base"]["name"] == "roundtrip"

    def test_write_with_indent(self, tmp_path):
        from ndi.document import ndi_document

        doc = ndi_document("base")
        filepath = str(tmp_path / "doc.json")
        doc.write(filepath, indent=4)
        with open(filepath) as f:
            content = f.read()
        # 4-space indent should produce wider indentation
        assert "    " in content


# ============================================================================
# ndi_document.remove_dependency_value_n() Tests
# ============================================================================


class TestDocumentRemoveDependencyN:
    """Tests for ndi_document.remove_dependency_value_n()."""

    def test_remove_specific_index(self):
        from ndi.document import ndi_document

        doc = ndi_document("base")
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
        from ndi.document import ndi_document

        doc = ndi_document("base")
        doc.set_dependency_value("dep_1", "val1", error_if_not_found=False)
        doc.set_dependency_value("dep_2", "val2", error_if_not_found=False)
        doc.set_dependency_value("other", "keep", error_if_not_found=False)

        doc.remove_dependency_value_n("dep")
        values = doc.dependency_value_n("dep", error_if_not_found=False)
        assert len(values) == 0

        # 'other' should still exist
        assert doc.dependency_value("other") == "keep"

    def test_remove_no_dependencies(self):
        from ndi.document import ndi_document

        doc = ndi_document("base")
        # Should not raise
        doc.remove_dependency_value_n("nonexistent")

    def test_remove_returns_self(self):
        from ndi.document import ndi_document

        doc = ndi_document("base")
        result = doc.remove_dependency_value_n("dep")
        assert result is doc


# ============================================================================
# Format-Specific Reader Tests
# ============================================================================


class TestIntanReader:
    """Tests for ndi_daq_reader_mfdaq_intan."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

        assert ndi_daq_reader_mfdaq_intan is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

        reader = ndi_daq_reader_mfdaq_intan()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.intan"

    def test_inherits_mfdaq_reader(self):
        from ndi.daq.mfdaq import ndi_daq_reader_mfdaq
        from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

        reader = ndi_daq_reader_mfdaq_intan()
        assert isinstance(reader, ndi_daq_reader_mfdaq)

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

        assert ".rhd" in ndi_daq_reader_mfdaq_intan.FILE_EXTENSIONS
        assert ".rhs" in ndi_daq_reader_mfdaq_intan.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan

        reader = ndi_daq_reader_mfdaq_intan()
        assert "ndi_daq_reader_mfdaq_intan" in repr(reader)


class TestBlackrockReader:
    """Tests for ndi_daq_reader_mfdaq_blackrock."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.blackrock import ndi_daq_reader_mfdaq_blackrock

        assert ndi_daq_reader_mfdaq_blackrock is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.blackrock import ndi_daq_reader_mfdaq_blackrock

        reader = ndi_daq_reader_mfdaq_blackrock()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.blackrock"

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.blackrock import ndi_daq_reader_mfdaq_blackrock

        assert ".ns5" in ndi_daq_reader_mfdaq_blackrock.FILE_EXTENSIONS
        assert ".nev" in ndi_daq_reader_mfdaq_blackrock.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.blackrock import ndi_daq_reader_mfdaq_blackrock

        assert "ndi_daq_reader_mfdaq_blackrock" in repr(ndi_daq_reader_mfdaq_blackrock())


class TestCEDSpike2Reader:
    """Tests for ndi_daq_reader_mfdaq_cedspike2."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2

        assert ndi_daq_reader_mfdaq_cedspike2 is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2

        reader = ndi_daq_reader_mfdaq_cedspike2()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.cedspike2"

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2

        assert ".smr" in ndi_daq_reader_mfdaq_cedspike2.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2

        assert "ndi_daq_reader_mfdaq_cedspike2" in repr(ndi_daq_reader_mfdaq_cedspike2())


class TestSpikeGadgetsReader:
    """Tests for ndi_daq_reader_mfdaq_spikegadgets."""

    def test_import(self):
        from ndi.daq.reader.mfdaq.spikegadgets import ndi_daq_reader_mfdaq_spikegadgets

        assert ndi_daq_reader_mfdaq_spikegadgets is not None

    def test_construction(self):
        from ndi.daq.reader.mfdaq.spikegadgets import ndi_daq_reader_mfdaq_spikegadgets

        reader = ndi_daq_reader_mfdaq_spikegadgets()
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.spikegadgets"

    def test_file_extensions(self):
        from ndi.daq.reader.mfdaq.spikegadgets import ndi_daq_reader_mfdaq_spikegadgets

        assert ".rec" in ndi_daq_reader_mfdaq_spikegadgets.FILE_EXTENSIONS

    def test_repr(self):
        from ndi.daq.reader.mfdaq.spikegadgets import ndi_daq_reader_mfdaq_spikegadgets

        assert "ndi_daq_reader_mfdaq_spikegadgets" in repr(ndi_daq_reader_mfdaq_spikegadgets())


class TestReaderPackageImports:
    """Test that format-specific readers are importable from expected paths."""

    def test_from_reader_mfdaq(self):
        from ndi.daq.reader.mfdaq import (
            ndi_daq_reader_mfdaq_blackrock,
            ndi_daq_reader_mfdaq_cedspike2,
            ndi_daq_reader_mfdaq_intan,
            ndi_daq_reader_mfdaq_spikegadgets,
        )

        assert all(
            [
                ndi_daq_reader_mfdaq_intan,
                ndi_daq_reader_mfdaq_blackrock,
                ndi_daq_reader_mfdaq_cedspike2,
                ndi_daq_reader_mfdaq_spikegadgets,
            ]
        )

    def test_from_reader(self):
        from ndi.daq.reader import (
            ndi_daq_reader_mfdaq_blackrock,
            ndi_daq_reader_mfdaq_cedspike2,
            ndi_daq_reader_mfdaq_intan,
            ndi_daq_reader_mfdaq_spikegadgets,
        )

        assert all(
            [
                ndi_daq_reader_mfdaq_intan,
                ndi_daq_reader_mfdaq_blackrock,
                ndi_daq_reader_mfdaq_cedspike2,
                ndi_daq_reader_mfdaq_spikegadgets,
            ]
        )

    def test_all_inherit_from_mfdaq_reader(self):
        from ndi.daq.mfdaq import ndi_daq_reader_mfdaq
        from ndi.daq.reader.mfdaq import (
            ndi_daq_reader_mfdaq_blackrock,
            ndi_daq_reader_mfdaq_cedspike2,
            ndi_daq_reader_mfdaq_intan,
            ndi_daq_reader_mfdaq_spikegadgets,
        )

        for cls in [
            ndi_daq_reader_mfdaq_intan,
            ndi_daq_reader_mfdaq_blackrock,
            ndi_daq_reader_mfdaq_cedspike2,
            ndi_daq_reader_mfdaq_spikegadgets,
        ]:
            reader = cls()
            assert isinstance(reader, ndi_daq_reader_mfdaq)

    def test_each_has_unique_daqreader_class(self):
        from ndi.daq.reader.mfdaq import (
            ndi_daq_reader_mfdaq_blackrock,
            ndi_daq_reader_mfdaq_cedspike2,
            ndi_daq_reader_mfdaq_intan,
            ndi_daq_reader_mfdaq_spikegadgets,
        )

        classes = set()
        for cls in [
            ndi_daq_reader_mfdaq_intan,
            ndi_daq_reader_mfdaq_blackrock,
            ndi_daq_reader_mfdaq_cedspike2,
            ndi_daq_reader_mfdaq_spikegadgets,
        ]:
            reader = cls()
            classes.add(reader._ndi_daqreader_class)
        assert len(classes) == 4


# ============================================================================
# ndi_session_mock Tests
# ============================================================================


class TestMockSession:
    """Tests for ndi_session_mock."""

    def test_import(self):
        from ndi.session.mock import ndi_session_mock

        assert ndi_session_mock is not None

    def test_construction(self):
        from ndi.session.mock import ndi_session_mock

        session = ndi_session_mock("test")
        assert session is not None
        assert os.path.isdir(session._tmpdir)
        session.close()

    def test_inherits_dirsession(self):
        from ndi.session import ndi_session_dir
        from ndi.session.mock import ndi_session_mock

        session = ndi_session_mock("test")
        assert isinstance(session, ndi_session_dir)
        session.close()

    def test_context_manager(self):
        from ndi.session.mock import ndi_session_mock

        with ndi_session_mock("test") as session:
            tmpdir = session._tmpdir
            assert os.path.isdir(tmpdir)
        assert not os.path.exists(tmpdir)

    def test_database_operations(self):
        from ndi.document import ndi_document
        from ndi.query import ndi_query
        from ndi.session.mock import ndi_session_mock

        with ndi_session_mock("test") as session:
            doc = ndi_document("base", **{"base.name": "mock_test"})
            session.database_add(doc)
            results = session.database_search(ndi_query("").isa("base"))
            assert len(results) >= 1

    def test_cleanup_on_close(self):
        from ndi.session.mock import ndi_session_mock

        session = ndi_session_mock("test")
        tmpdir = session._tmpdir
        assert os.path.isdir(tmpdir)
        session.close()
        assert not os.path.exists(tmpdir)

    def test_no_cleanup_option(self):
        from ndi.session.mock import ndi_session_mock

        session = ndi_session_mock("test", cleanup=False)
        tmpdir = session._tmpdir
        session.close()
        assert os.path.isdir(tmpdir)  # Should still exist
        # Clean up manually
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_id_is_method(self):
        from ndi.session.mock import ndi_session_mock

        with ndi_session_mock("test") as session:
            sid = session.id()
            assert isinstance(sid, str)
            assert len(sid) > 0

    def test_repr(self):
        from ndi.session.mock import ndi_session_mock

        with ndi_session_mock("test") as session:
            assert "ndi_session_mock" in repr(session)

    def test_from_session_module(self):
        from ndi.session import ndi_session_mock

        assert ndi_session_mock is not None
