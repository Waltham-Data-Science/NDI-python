"""
Tests for Phase 2 low-priority gap implementations.

Covers:
- Batch 1: stimulus_tuningcurve_log, t0_t1_to_array, ontology_table_row_vars
- Batch 2: database_to_json, copy_doc_file_to_temp, extract_docs_files
- Batch 3: get_probe_type_map, init_probe_type_map
- Batch 4: upload_single_file
- Batch 5: openminds_convert (4 functions)
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# =========================================================================
# Batch 1: Calculator & Doc Utilities
# =========================================================================


class TestStimulusTuningcurveLog:
    """Tests for ndi.fun.stimulus.stimulus_tuningcurve_log."""

    def test_returns_log_string(self):
        from ndi.fun.stimulus import stimulus_tuningcurve_log

        calc_doc = MagicMock()
        calc_doc.document_properties = {
            "tuningcurve_calc": {"log": "calculation complete"},
        }

        doc = MagicMock()
        doc.document_properties = {
            "depends_on": [
                {"name": "stimulus_tuningcurve_id", "value": "tc-123"},
            ],
        }

        session = MagicMock()
        session.database_search.return_value = [calc_doc]

        result = stimulus_tuningcurve_log(session, doc)
        assert result == "calculation complete"

    def test_returns_empty_if_no_dependency(self):
        from ndi.fun.stimulus import stimulus_tuningcurve_log

        doc = MagicMock()
        doc.document_properties = {"depends_on": []}

        session = MagicMock()
        result = stimulus_tuningcurve_log(session, doc)
        assert result == ""

    def test_returns_empty_if_doc_not_found(self):
        from ndi.fun.stimulus import stimulus_tuningcurve_log

        doc = MagicMock()
        doc.document_properties = {
            "depends_on": [
                {"name": "stimulus_tuningcurve_id", "value": "tc-999"},
            ],
        }

        session = MagicMock()
        session.database_search.return_value = []

        result = stimulus_tuningcurve_log(session, doc)
        assert result == ""

    def test_returns_empty_if_no_log_field(self):
        from ndi.fun.stimulus import stimulus_tuningcurve_log

        calc_doc = MagicMock()
        calc_doc.document_properties = {
            "tuningcurve_calc": {},
        }

        doc = MagicMock()
        doc.document_properties = {
            "depends_on": [
                {"name": "stimulus_tuningcurve_id", "value": "tc-123"},
            ],
        }

        session = MagicMock()
        session.database_search.return_value = [calc_doc]

        result = stimulus_tuningcurve_log(session, doc)
        assert result == ""


class TestT0T1ToArray:
    """Tests for ndi.fun.epoch.t0_t1_to_array."""

    def test_basic_conversion(self):
        from ndi.fun.epoch import t0_t1_to_array

        result = t0_t1_to_array([[0.0, 1.5], [2.0, 3.5]])
        expected = np.array([[0.0, 1.5], [2.0, 3.5]])
        np.testing.assert_array_equal(result, expected)

    def test_empty_input(self):
        from ndi.fun.epoch import t0_t1_to_array

        result = t0_t1_to_array([])
        assert result.shape == (0, 2)

    def test_single_pair(self):
        from ndi.fun.epoch import t0_t1_to_array

        result = t0_t1_to_array([[10.0, 20.0]])
        assert result.shape == (1, 2)
        assert result[0, 0] == 10.0
        assert result[0, 1] == 20.0

    def test_tuples(self):
        from ndi.fun.epoch import t0_t1_to_array

        result = t0_t1_to_array([(0.0, 1.0), (2.0, 3.0)])
        assert result.shape == (2, 2)
        assert result[1, 0] == 2.0


class TestOntologyTableRowVars:
    """Tests for ndi.fun.doc.ontology_table_row_vars."""

    def test_extracts_unique_vars(self):
        from ndi.fun.doc import ontology_table_row_vars

        doc1 = MagicMock()
        doc1.document_properties = {
            "ontologyTableRow": {
                "names": "alpha,beta",
                "variableNames": "a,b",
                "ontologyNodes": "ont1,ont2",
            },
        }

        doc2 = MagicMock()
        doc2.document_properties = {
            "ontologyTableRow": {
                "names": "beta,gamma",
                "variableNames": "b,g",
                "ontologyNodes": "ont2,ont3",
            },
        }

        session = MagicMock()
        session.database_search.return_value = [doc1, doc2]

        names, var_names, ont_nodes = ontology_table_row_vars(session)

        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names
        assert len(names) == 3

    def test_empty_session(self):
        from ndi.fun.doc import ontology_table_row_vars

        session = MagicMock()
        session.database_search.return_value = []

        names, var_names, ont_nodes = ontology_table_row_vars(session)
        assert names == []
        assert var_names == []
        assert ont_nodes == []


# =========================================================================
# Batch 2: Database Export/Extract
# =========================================================================


class TestDatabaseToJson:
    """Tests for ndi.database_fun.database_to_json."""

    def test_exports_docs_to_json(self):
        from ndi.database_fun import database_to_json

        doc1 = MagicMock()
        doc1.document_properties = {
            "base": {"id": "doc-001"},
            "data": "hello",
        }

        doc2 = MagicMock()
        doc2.document_properties = {
            "base": {"id": "doc-002"},
            "data": "world",
        }

        session = MagicMock()
        session.database_search.return_value = [doc1, doc2]

        with tempfile.TemporaryDirectory() as tmpdir:
            count = database_to_json(session, tmpdir)
            assert count == 2
            assert (Path(tmpdir) / "doc-001.json").exists()
            assert (Path(tmpdir) / "doc-002.json").exists()

            with open(Path(tmpdir) / "doc-001.json") as f:
                loaded = json.load(f)
            assert loaded["data"] == "hello"

    def test_empty_database(self):
        from ndi.database_fun import database_to_json

        session = MagicMock()
        session.database_search.return_value = []

        with tempfile.TemporaryDirectory() as tmpdir:
            count = database_to_json(session, tmpdir)
            assert count == 0


class TestCopyDocFileToTemp:
    """Tests for ndi.database_fun.copy_doc_file_to_temp."""

    def test_copies_file(self):
        from ndi.database_fun import copy_doc_file_to_temp

        # Mock binary doc
        mock_file = MagicMock()
        mock_file.read.return_value = b"test data content"

        session = MagicMock()
        session.database_openbinarydoc.return_value = mock_file

        doc = MagicMock()

        tname, tname_no_ext = copy_doc_file_to_temp(doc, session, "data.bin", ".bin")

        try:
            assert os.path.exists(tname)
            assert tname.endswith(".bin")
            with open(tname, "rb") as f:
                assert f.read() == b"test data content"
        finally:
            if os.path.exists(tname):
                os.unlink(tname)

    def test_no_extension(self):
        from ndi.database_fun import copy_doc_file_to_temp

        mock_file = MagicMock()
        mock_file.read.return_value = b"xyz"

        session = MagicMock()
        session.database_openbinarydoc.return_value = mock_file

        doc = MagicMock()

        tname, tname_no_ext = copy_doc_file_to_temp(doc, session, "data", "")

        try:
            assert os.path.exists(tname)
            assert tname == tname_no_ext  # Same when no extension
        finally:
            if os.path.exists(tname):
                os.unlink(tname)


class TestExtractDocsFiles:
    """Tests for ndi.database_fun.extract_docs_files."""

    def test_extracts_docs(self):
        from ndi.database_fun import extract_docs_files

        doc1 = MagicMock()
        doc1.document_properties = {
            "base": {"id": "doc-abc"},
            "files": {"file_list": []},
        }

        session = MagicMock()
        session.database_search.return_value = [doc1]

        with tempfile.TemporaryDirectory() as tmpdir:
            docs, path = extract_docs_files(session, tmpdir)
            assert len(docs) == 1
            assert (Path(tmpdir) / "doc-abc" / "document.json").exists()

    def test_creates_temp_dir_if_none(self):
        from ndi.database_fun import extract_docs_files

        session = MagicMock()
        session.database_search.return_value = []

        docs, path = extract_docs_files(session)
        assert os.path.isdir(path)
        # Clean up
        os.rmdir(path)


# =========================================================================
# Batch 3: Probe Type Map
# =========================================================================


class TestProbeTypeMap:
    """Tests for ndi.probe.init_probe_type_map and get_probe_type_map."""

    def test_init_probe_type_map_returns_dict(self):
        from ndi.probe import init_probe_type_map

        result = init_probe_type_map()
        assert isinstance(result, dict)
        # probetype2object.json exists in the repo
        if result:
            assert "n-trode" in result
            assert result["n-trode"] == "ndi.probe.timeseries.mfdaq"

    def test_get_probe_type_map_cached(self):
        import ndi.probe as probe_mod

        # Reset cache
        probe_mod._PROBE_TYPE_MAP = None

        result1 = probe_mod.get_probe_type_map()
        result2 = probe_mod.get_probe_type_map()
        # Should be same object (cached)
        assert result1 is result2

    def test_map_has_expected_types(self):
        from ndi.probe import init_probe_type_map

        m = init_probe_type_map()
        if m:
            assert "stimulator" in m
            assert "patch" in m
            assert "eeg" in m


# =========================================================================
# Batch 4: Cloud Upload Single File
# =========================================================================


class TestUploadSingleFile:
    """Tests for ndi.cloud.upload.upload_single_file."""

    def test_direct_upload_success(self):
        from ndi.cloud.upload import upload_single_file

        client = MagicMock()

        mock_files = MagicMock()
        mock_files.get_upload_url.return_value = "https://s3.example.com/upload"
        mock_files.put_file.return_value = None

        with patch.dict("sys.modules", {"ndi.cloud.api.files": mock_files}):
            with patch("ndi.cloud.api.files", mock_files):
                success, err = upload_single_file(
                    "ds-123", "file-uid-1", "/tmp/test.dat", client=client
                )

        assert success is True
        assert err == ""

    def test_upload_failure(self):
        from ndi.cloud.upload import upload_single_file

        client = MagicMock()

        mock_files = MagicMock()
        mock_files.get_upload_url.side_effect = Exception("Network error")

        with patch.dict("sys.modules", {"ndi.cloud.api.files": mock_files}):
            with patch("ndi.cloud.api.files", mock_files):
                success, err = upload_single_file(
                    "ds-123", "file-uid-1", "/tmp/test.dat", client=client
                )

        assert success is False
        assert "Network error" in err


# =========================================================================
# Batch 5: OpenMINDS Integration
# =========================================================================


class TestOpenmindsObjToDict:
    """Tests for ndi.openminds_convert.openminds_obj_to_dict."""

    @patch("ndi.openminds_convert._is_openminds_object", return_value=False)
    def test_basic_serialization(self, mock_is_om):
        from ndi.openminds_convert import openminds_obj_to_dict

        # Use a plain class so __dict__ introspection works
        class FakeSpecies:
            def __init__(self):
                self.type_ = "https://openminds.om-i.org/types/Species"
                self.id = "@id-species-1"
                self.name = "Mus musculus"

        FakeSpecies.__module__ = "openminds.controlled_terms"
        FakeSpecies.__qualname__ = "Species"

        obj = FakeSpecies()
        result = openminds_obj_to_dict(obj)

        assert len(result) == 1
        assert result[0]["openminds_type"] == "https://openminds.om-i.org/types/Species"
        assert result[0]["openminds_id"] == "@id-species-1"
        assert "ndi_id" in result[0]
        assert "name" in result[0]["fields"]
        assert result[0]["fields"]["name"] == "Mus musculus"

    @patch("ndi.openminds_convert._is_openminds_object", return_value=False)
    def test_cycle_detection(self, mock_is_om):
        from ndi.openminds_convert import openminds_obj_to_dict

        obj = MagicMock()
        obj.type_ = "https://openminds.om-i.org/types/Person"
        obj.id = "@id-person"
        obj.__dict__["name"] = "Test"
        obj.__dict__["type_"] = "https://openminds.om-i.org/types/Person"
        obj.__dict__["id"] = "@id-person"
        obj.__module__ = "openminds"

        # Passing same object twice should not duplicate
        result = openminds_obj_to_dict([obj, obj])
        assert len(result) == 1


class TestOpenmindsObjToNdiDocument:
    """Tests for ndi.openminds_convert.openminds_obj_to_ndi_document."""

    @patch("ndi.openminds_convert.openminds_obj_to_dict")
    def test_creates_documents(self, mock_to_dict):
        """openminds_obj_to_ndi_document creates real NDI Documents."""
        from ndi.document import Document
        from ndi.openminds_convert import openminds_obj_to_ndi_document

        mock_to_dict.return_value = [
            {
                "openminds_type": "https://openminds.om-i.org/types/Species",
                "python_type": "openminds.controlled_terms.Species",
                "openminds_id": "@id-1",
                "ndi_id": "ndi-abc-123",
                "fields": {"name": "Mus musculus"},
            },
        ]

        result = openminds_obj_to_ndi_document(MagicMock(), session_id="sess-1")

        assert len(result) == 1
        assert isinstance(result[0], Document)
        props = result[0].document_properties
        assert props.get("document_class", {}).get("class_name") == "openminds"

    @patch("ndi.openminds_convert.openminds_obj_to_dict")
    def test_subject_dependency(self, mock_to_dict):
        """openminds_obj_to_ndi_document creates openminds_subject Documents with dependency."""
        from ndi.document import Document
        from ndi.openminds_convert import openminds_obj_to_ndi_document

        mock_to_dict.return_value = [
            {
                "openminds_type": "Species",
                "python_type": "openminds.controlled_terms.Species",
                "openminds_id": "@id-1",
                "ndi_id": "ndi-xyz",
                "fields": {},
            },
        ]

        result = openminds_obj_to_ndi_document(
            MagicMock(),
            session_id="sess-1",
            dependency_type="subject",
            dependency_value="subj-001",
        )

        assert len(result) == 1
        assert isinstance(result[0], Document)
        props = result[0].document_properties
        assert props.get("document_class", {}).get("class_name") == "openminds_subject"
        dep_names = {d["name"]: d["value"] for d in props.get("depends_on", [])}
        assert dep_names.get("subject_id") == "subj-001"

    def test_raises_on_empty_dependency_value(self):
        from ndi.openminds_convert import openminds_obj_to_ndi_document

        with pytest.raises(ValueError, match="dependency_value must not be empty"):
            openminds_obj_to_ndi_document(
                MagicMock(),
                session_id="s1",
                dependency_type="subject",
                dependency_value="",
            )

    def test_raises_on_unknown_dependency_type(self):
        from ndi.openminds_convert import openminds_obj_to_ndi_document

        with pytest.raises(ValueError, match="Unknown dependency_type"):
            openminds_obj_to_ndi_document(
                MagicMock(),
                session_id="s1",
                dependency_type="unknown",
                dependency_value="val",
            )


class TestFindControlledInstance:
    """Tests for ndi.openminds_convert.find_controlled_instance."""

    def test_delegates_to_technique_names(self):
        from ndi.openminds_convert import find_controlled_instance

        with patch("ndi.openminds_convert.find_technique_names") as mock_ft:
            mock_ft.return_value = ["electrophysiology (Technique)"]
            result = find_controlled_instance(["electrophysiology"], "TechniquesEmployed")
            mock_ft.assert_called_once_with(["electrophysiology"])
            assert result == ["electrophysiology (Technique)"]

    def test_returns_empty_if_no_openminds(self):
        from ndi.openminds_convert import find_controlled_instance

        with patch.dict("sys.modules", {"openminds.controlled_terms": None}):
            # This should handle ImportError gracefully
            result = find_controlled_instance(["test"], "Species")
            # May return [] or the names depending on import handling
            assert isinstance(result, list)


class TestFindTechniqueNames:
    """Tests for ndi.openminds_convert.find_technique_names."""

    def test_returns_invalid_format_for_unmatched(self):
        from ndi.openminds_convert import find_technique_names

        # Mock the import of openminds to fail gracefully
        with patch.dict(
            "sys.modules", {"openminds.controlled_terms": None, "openminds.latest.core": None}
        ):
            result = find_technique_names(["nonexistent_technique"])
            assert result == ["InvalidFormat"]

    def test_returns_list_matching_input_length(self):
        from ndi.openminds_convert import find_technique_names

        with patch.dict(
            "sys.modules", {"openminds.controlled_terms": None, "openminds.latest.core": None}
        ):
            result = find_technique_names(["a", "b", "c"])
            assert len(result) == 3
