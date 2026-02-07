"""
Tests for Phase 1 gap-fill implementations.

Covers:
- TuningCurve analysis methods (Batch 1)
- finddocs_element_epoch_type (Batch 2)
- evaluate_fitcurve (Batch 3)
- ndi_document2ndi_object (Batch 4)
- doc_table conversions (Batch 5)
- table utilities (Batch 6)
- copy_session_to_dataset (Batch 7)
- Presentation time read/write (Batch 8)
- Subject/Probe doc helpers (Batch 9)
- pfilemirror (Batch 10)
- readImageStack (Batch 11)
- docComparison (Batch 13)
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# =========================================================================
# Batch 1: TuningCurve analysis methods
# =========================================================================


class TestTuningCurveAnalysis:

    def _make_calc(self):
        from ndi.calc.stimulus.tuningcurve import TuningCurveCalc

        return TuningCurveCalc(session=None)

    def test_best_value_unknown_algorithm(self):
        calc = self._make_calc()
        doc = MagicMock()
        with pytest.raises(ValueError, match="Unknown best_value algorithm"):
            calc.best_value("nonexistent", doc, "angle")

    def test_best_value_routes_to_empirical(self):
        calc = self._make_calc()
        calc.best_value_empirical = MagicMock(return_value=(2, 10.0, 90))
        doc = MagicMock()
        n, v, pv = calc.best_value("empirical_maximum", doc, "angle")
        calc.best_value_empirical.assert_called_once_with(doc, "angle")
        assert n == 2
        assert v == 10.0
        assert pv == 90

    def test_best_value_empirical_basic(self):
        calc = self._make_calc()

        # Create mock session and docs
        session = MagicMock()
        calc._session = session

        # Stim presentation doc
        stim_pres_props = {
            "stimulus_presentation": {
                "stimuli": [
                    {"parameters": {"angle": 0}},
                    {"parameters": {"angle": 90}},
                    {"parameters": {"angle": 180}},
                ],
                "presentation_order": [0, 1, 2, 0, 1, 2],
            },
            "base": {"id": "stim_pres_123"},
        }
        stim_pres_doc = MagicMock()
        stim_pres_doc.document_properties = stim_pres_props

        session.database_search.return_value = [stim_pres_doc]

        # Response doc
        resp_props = {
            "stimulus_response_scalar": {
                "responses": {
                    "response_real": [2.0, 8.0, 3.0, 2.5, 9.0, 3.5],
                    "response_imaginary": [0, 0, 0, 0, 0, 0],
                    "control_response_real": [float("nan")] * 6,
                    "control_response_imaginary": [0] * 6,
                },
            },
            "base": {"id": "resp_123"},
        }
        resp_doc = MagicMock()
        resp_doc.document_properties = resp_props
        resp_doc.dependency_value.return_value = "stim_pres_123"

        n, v, pv = calc.best_value_empirical(resp_doc, "angle")
        # Stimulus 1 (angle=90) has highest mean response
        assert n == 1
        assert pv == 90

    def test_property_value_array(self):
        calc = self._make_calc()
        session = MagicMock()
        calc._session = session

        stim_pres_props = {
            "stimulus_presentation": {
                "stimuli": [
                    {"parameters": {"angle": 0, "contrast": 1}},
                    {"parameters": {"angle": 90, "contrast": 1}},
                    {"parameters": {"angle": 0, "contrast": 0.5}},
                    {"parameters": {"spatial_freq": 2}},
                ],
            },
            "base": {"id": "pres1"},
        }
        stim_pres_doc = MagicMock()
        stim_pres_doc.document_properties = stim_pres_props
        session.database_search.return_value = [stim_pres_doc]

        resp_doc = MagicMock()
        resp_doc.document_properties = {"base": {"id": "r1"}}
        resp_doc.dependency_value.return_value = "pres1"

        pva = calc.property_value_array(resp_doc, "angle")
        assert set(pva) == {0, 90}

        pva2 = calc.property_value_array(resp_doc, "contrast")
        assert set(pva2) == {1, 0.5}

    def test_default_parameters_query(self):
        calc = self._make_calc()
        result = calc.default_parameters_query({})
        assert len(result) == 1
        assert result[0]["name"] == "stimulus_response_scalar_id"

    def test_generate_mock_docs(self):
        calc = self._make_calc()
        docs, out, expected = calc.generate_mock_docs("standard", 4)
        assert len(docs) == 4
        assert docs[0] is not None
        assert docs[0]["independent_variables"] == ["contrast"]
        assert docs[1]["independent_variables"] == ["angle", "contrast"]

    def test_generate_mock_docs_lowsnr(self):
        calc = self._make_calc()
        docs, _, _ = calc.generate_mock_docs("lowSNR", 1)
        assert docs[0]["noise"] == 0.2

    def test_generate_mock_docs_specific_inds(self):
        calc = self._make_calc()
        docs, _, _ = calc.generate_mock_docs("standard", 4, specific_test_inds=[0, 2])
        assert docs[0] is not None
        assert docs[1] is None  # Not in specific_test_inds
        assert docs[2] is not None
        assert docs[3] is None


# =========================================================================
# Batch 2: finddocs_element_epoch_type
# =========================================================================


class TestFinddocsElementEpochType:

    def test_basic_search(self):
        from ndi.database_fun import finddocs_element_epoch_type

        session = MagicMock()
        doc = MagicMock()
        session.database_search.return_value = [doc]

        result = finddocs_element_epoch_type(session, "elem_123", "epoch_001", "spectrogram")
        assert result == [doc]
        session.database_search.assert_called_once()

    def test_no_results(self):
        from ndi.database_fun import finddocs_element_epoch_type

        session = MagicMock()
        session.database_search.return_value = []

        result = finddocs_element_epoch_type(session, "elem_123", "epoch_001", "spectrogram")
        assert result == []

    def test_exception_fallback(self):
        from ndi.database_fun import finddocs_element_epoch_type

        session = MagicMock()
        session.database_search.side_effect = Exception("DB error")
        session.session = MagicMock()
        session.session.database_search.return_value = ["doc1"]

        result = finddocs_element_epoch_type(session, "elem_123", "epoch_001", "spectrogram")
        assert result == ["doc1"]


# =========================================================================
# Batch 3: evaluate_fitcurve
# =========================================================================


class TestEvaluateFitcurve:

    def test_basic_evaluation(self):
        from ndi.fun.data import evaluate_fitcurve

        doc = MagicMock()
        doc.document_properties = {
            "fitcurve": {
                "fit_equation": "a * x + b",
                "fit_parameter_names": ["a", "b"],
                "fit_parameter_values": [2.0, 1.0],
                "fit_variable_names": ["x", "y"],
            }
        }

        x = np.array([0, 1, 2, 3])
        result = evaluate_fitcurve(doc, x)
        np.testing.assert_array_almost_equal(result, [1.0, 3.0, 5.0, 7.0])

    def test_power_equation(self):
        from ndi.fun.data import evaluate_fitcurve

        doc = MagicMock()
        doc.document_properties = {
            "fitcurve": {
                "fit_equation": "a * x^n + b",
                "fit_parameter_names": ["a", "n", "b"],
                "fit_parameter_values": [1.0, 2.0, 0.0],
                "fit_variable_names": ["x", "y"],
            }
        }

        x = np.array([0, 1, 2, 3])
        result = evaluate_fitcurve(doc, x)
        np.testing.assert_array_almost_equal(result, [0, 1, 4, 9])

    def test_trig_equation(self):
        from ndi.fun.data import evaluate_fitcurve

        doc = MagicMock()
        doc.document_properties = {
            "fitcurve": {
                "fit_equation": "a * sin(x)",
                "fit_parameter_names": ["a"],
                "fit_parameter_values": [2.0],
                "fit_variable_names": ["x", "y"],
            }
        }

        x = np.array([0, np.pi / 2, np.pi])
        result = evaluate_fitcurve(doc, x)
        np.testing.assert_array_almost_equal(result, [0, 2.0, 0], decimal=10)

    def test_wrong_var_count(self):
        from ndi.fun.data import evaluate_fitcurve

        doc = MagicMock()
        doc.document_properties = {
            "fitcurve": {
                "fit_equation": "x + z",
                "fit_parameter_names": [],
                "fit_parameter_values": [],
                "fit_variable_names": ["x", "z", "y"],  # 2 independent
            }
        }

        with pytest.raises(ValueError, match="Expected 2 independent"):
            evaluate_fitcurve(doc, np.array([1, 2]))

    def test_missing_equation(self):
        from ndi.fun.data import evaluate_fitcurve

        doc = MagicMock()
        doc.document_properties = {"fitcurve": {}}

        with pytest.raises(ValueError, match="missing equation"):
            evaluate_fitcurve(doc, np.array([1]))


# =========================================================================
# Batch 4: ndi_document2ndi_object
# =========================================================================


class TestNdiDocument2NdiObject:

    def test_string_id_lookup(self):
        from ndi.database_fun import ndi_document2ndi_object

        session = MagicMock()
        doc = MagicMock()
        doc.document_properties = {
            "document_class": {"class_name": "unknown_type"},
            "base": {"id": "abc"},
        }
        session.database_search.return_value = [doc]

        result = ndi_document2ndi_object("abc", session)
        # Unknown type returns None
        assert result is None

    def test_not_found(self):
        from ndi.database_fun import ndi_document2ndi_object

        session = MagicMock()
        session.database_search.return_value = []

        result = ndi_document2ndi_object("nonexistent", session)
        assert result is None

    def test_non_dict_props(self):
        from ndi.database_fun import ndi_document2ndi_object

        session = MagicMock()
        doc = MagicMock()
        doc.document_properties = "not a dict"

        result = ndi_document2ndi_object(doc, session)
        assert result is None


# =========================================================================
# Batch 5: Document-to-Table conversions
# =========================================================================


class TestDocTable:

    def test_doc_cell_array_to_table(self):
        from ndi.fun.doc_table import doc_cell_array_to_table

        doc1 = MagicMock()
        doc1.document_properties = {
            "base": {"id": "abc", "session_id": "s1"},
            "element": {"name": "e1"},
        }
        doc2 = MagicMock()
        doc2.document_properties = {
            "base": {"id": "def", "session_id": "s1"},
            "element": {"name": "e2"},
        }

        df = doc_cell_array_to_table([doc1, doc2])
        assert len(df) == 2
        assert "base.id" in df.columns
        assert df["element.name"].tolist() == ["e1", "e2"]

    def test_empty_list(self):
        from ndi.fun.doc_table import doc_cell_array_to_table

        df = doc_cell_array_to_table([])
        assert len(df) == 0


# =========================================================================
# Batch 6: Table utilities
# =========================================================================


class TestTableUtils:

    def test_identify_matching_rows_identical(self):
        import pandas as pd

        from ndi.fun.table import identify_matching_rows

        df = pd.DataFrame({"name": ["a", "b", "c", "a"]})
        mask = identify_matching_rows(df, "name", "a")
        assert mask.tolist() == [True, False, False, True]

    def test_identify_matching_rows_contains(self):
        import pandas as pd

        from ndi.fun.table import identify_matching_rows

        df = pd.DataFrame({"name": ["alpha", "beta", "gamma"]})
        mask = identify_matching_rows(df, "name", "al", "contains")
        assert mask.tolist() == [True, False, False]

    def test_identify_matching_rows_numeric(self):
        import pandas as pd

        from ndi.fun.table import identify_matching_rows

        df = pd.DataFrame({"val": [1, 2, 3, 4]})
        mask = identify_matching_rows(df, "val", 2, "gt")
        assert mask.tolist() == [False, False, True, True]

    def test_identify_valid_rows(self):
        import pandas as pd

        from ndi.fun.table import identify_valid_rows

        df = pd.DataFrame(
            {
                "a": [1, float("nan"), 3],
                "b": [4, 5, float("nan")],
            }
        )
        mask = identify_valid_rows(df)
        assert mask.tolist() == [True, False, False]

    def test_identify_valid_rows_specific_cols(self):
        import pandas as pd

        from ndi.fun.table import identify_valid_rows

        df = pd.DataFrame(
            {
                "a": [1, float("nan"), 3],
                "b": [4, 5, float("nan")],
            }
        )
        mask = identify_valid_rows(df, columns=["a"])
        assert mask.tolist() == [True, False, True]

    def test_vstack(self):
        import pandas as pd

        from ndi.fun.table import vstack

        t1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        t2 = pd.DataFrame({"a": [5], "c": [6]})

        result = vstack([t1, t2])
        assert len(result) == 3
        assert "a" in result.columns
        assert "b" in result.columns
        assert "c" in result.columns

    def test_move_columns_left(self):
        import pandas as pd

        from ndi.fun.table import move_columns_left

        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        result = move_columns_left(df, ["c", "b"])
        assert list(result.columns) == ["c", "b", "a"]

    def test_join_tables(self):
        import pandas as pd

        from ndi.fun.table import join_tables

        t1 = pd.DataFrame({"id": ["a", "b"], "val1": [1, 2]})
        t2 = pd.DataFrame({"id": ["a", "c"], "val2": [3, 4]})

        result = join_tables([t1, t2], key_columns=["id"])
        assert len(result) == 3  # outer join

    def test_vstack_empty(self):
        from ndi.fun.table import vstack

        result = vstack([])
        assert len(result) == 0


# =========================================================================
# Batch 7: copy_session_to_dataset
# =========================================================================


class TestCopySessionToDataset:

    def test_already_copied(self):
        from ndi.database_fun import copy_session_to_dataset

        session = MagicMock()
        session.id.return_value = "session_123"
        dataset = MagicMock()
        dataset.session_list.return_value = (["ref1"], ["session_123"])

        success, msg = copy_session_to_dataset(session, dataset)
        assert not success
        assert "already part of" in msg

    def test_successful_copy(self):
        from ndi.database_fun import copy_session_to_dataset

        session = MagicMock()
        session.id.return_value = "session_456"
        doc = MagicMock()
        doc.document_properties = {"base": {"session_id": "session_456"}}
        session.database_search.return_value = [doc]

        dataset = MagicMock()
        dataset.session_list.return_value = ([], [])

        success, msg = copy_session_to_dataset(session, dataset)
        assert success
        assert msg == ""
        dataset.database_add.assert_called_once()


# =========================================================================
# Batch 8: Presentation time read/write
# =========================================================================


class TestPresentationTime:

    def test_roundtrip(self):
        from ndi.database_fun import (
            read_presentation_time_structure,
            write_presentation_time_structure,
        )

        entries = [
            {
                "clocktype": "utc",
                "stimopen": 1.0,
                "onset": 2.0,
                "offset": 3.0,
                "stimclose": 4.0,
                "stimevents": np.array([[0.5, 1.0], [1.5, 2.0]]),
            },
            {
                "clocktype": "dev_local_time",
                "stimopen": 10.0,
                "onset": 11.0,
                "offset": 12.0,
                "stimclose": 13.0,
                "stimevents": np.array([[5.0, 6.0]]),
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            fname = f.name

        try:
            write_presentation_time_structure(fname, entries)
            header, result = read_presentation_time_structure(fname)

            assert header == "presentation_time structure"
            assert len(result) == 2

            assert result[0]["clocktype"] == "utc"
            assert result[0]["stimopen"] == 1.0
            assert result[0]["onset"] == 2.0
            assert result[0]["offset"] == 3.0
            assert result[0]["stimclose"] == 4.0
            np.testing.assert_array_almost_equal(
                result[0]["stimevents"],
                [[0.5, 1.0], [1.5, 2.0]],
            )

            assert result[1]["clocktype"] == "dev_local_time"
            np.testing.assert_array_almost_equal(
                result[1]["stimevents"],
                [[5.0, 6.0]],
            )
        finally:
            os.unlink(fname)

    def test_roundtrip_empty_events(self):
        from ndi.database_fun import (
            read_presentation_time_structure,
            write_presentation_time_structure,
        )

        entries = [
            {
                "clocktype": "utc",
                "stimopen": 0.0,
                "onset": 1.0,
                "offset": 2.0,
                "stimclose": 3.0,
                "stimevents": np.empty((0, 2)),
            },
        ]

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            fname = f.name

        try:
            write_presentation_time_structure(fname, entries)
            header, result = read_presentation_time_structure(fname)
            assert len(result) == 1
            assert result[0]["stimevents"].shape == (0, 2)
        finally:
            os.unlink(fname)

    def test_read_subset(self):
        from ndi.database_fun import (
            read_presentation_time_structure,
            write_presentation_time_structure,
        )

        entries = [
            {
                "clocktype": f"clock_{i}",
                "stimopen": float(i),
                "onset": float(i),
                "offset": float(i),
                "stimclose": float(i),
                "stimevents": np.empty((0, 2)),
            }
            for i in range(5)
        ]

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            fname = f.name

        try:
            write_presentation_time_structure(fname, entries)
            # Read entries 2-3 (0-based)
            header, result = read_presentation_time_structure(fname, 2, 3)
            assert len(result) == 2
            assert result[0]["clocktype"] == "clock_2"
            assert result[1]["clocktype"] == "clock_3"
        finally:
            os.unlink(fname)


# =========================================================================
# Batch 9: Subject/Probe doc helpers
# =========================================================================


class TestDocHelpers:

    def test_make_species_strain_sex(self):
        """make_species_strain_sex creates real openMINDS NDI Documents."""
        pytest.importorskip("openminds", reason="openminds package not installed")
        from ndi.document import Document
        from ndi.fun.doc import make_species_strain_sex

        session = MagicMock()
        session.id.return_value = "sess_1"

        subj_doc = MagicMock()
        subj_doc.document_properties = {"base": {"id": "subj_123"}}

        docs = make_species_strain_sex(
            session,
            subj_doc,
            species="Mus musculus",
            strain="C57BL/6",
            sex="male",
        )
        # Species + Strain + BiologicalSex = 3 documents
        assert len(docs) == 3
        for doc in docs:
            assert isinstance(doc, Document)
            props = doc.document_properties
            # All should be openminds_subject docs linked to subject
            assert props.get("document_class", {}).get("class_name") == "openminds_subject"
            dep_names = {d["name"]: d["value"] for d in props.get("depends_on", [])}
            assert dep_names.get("subject_id") == "subj_123"

    def test_make_species_only(self):
        """make_species_strain_sex with species only creates 1 document."""
        pytest.importorskip("openminds", reason="openminds package not installed")
        from ndi.document import Document
        from ndi.fun.doc import make_species_strain_sex

        session = MagicMock()
        session.id.return_value = "sess_1"
        subj_doc = MagicMock()
        subj_doc.document_properties = {"base": {"id": "subj_123"}}

        docs = make_species_strain_sex(session, subj_doc, species="Rattus")
        assert len(docs) == 1
        assert isinstance(docs[0], Document)
        om = docs[0].document_properties.get("openminds", {})
        assert "Species" in om.get("openminds_type", "")

    def test_probe_locations_for_probes(self):
        """probe_locations_for_probes creates real probe_location Documents."""
        from ndi.document import Document
        from ndi.fun.doc import probe_locations_for_probes

        session = MagicMock()
        session.id.return_value = "sess_1"

        probe1 = MagicMock()
        probe1.document_properties = {"base": {"id": "probe_1"}}
        probe2 = MagicMock()
        probe2.document_properties = {"base": {"id": "probe_2"}}

        locations = [
            {"name": "V1", "ontology": "ncbi:123"},
            {"name": "LGN"},
        ]

        docs = probe_locations_for_probes(
            session,
            [probe1, probe2],
            locations,
        )
        assert len(docs) == 2
        for doc in docs:
            assert isinstance(doc, Document)
            props = doc.document_properties
            assert props.get("document_class", {}).get("class_name") == "probe_location"


# =========================================================================
# Batch 10: pfilemirror
# =========================================================================


class TestPfilemirror:

    def test_mirror_basic(self):
        from ndi.file.pfilemirror import pfilemirror

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            # Create test files
            (Path(src) / "test.py").write_text('print("hello")')
            (Path(src) / "data.txt").write_text("data")
            (Path(src) / "sub").mkdir()
            (Path(src) / "sub" / "nested.py").write_text("x = 1")

            result = pfilemirror(src, dest, verbose=False)
            assert result is True
            assert (Path(dest) / "test.py").exists()
            assert not (Path(dest) / "data.txt").exists()  # Non-py not copied
            assert (Path(dest) / "sub" / "nested.py").exists()

    def test_mirror_with_non_py(self):
        from ndi.file.pfilemirror import pfilemirror

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            (Path(src) / "test.py").write_text("x = 1")
            (Path(src) / "data.txt").write_text("data")

            result = pfilemirror(src, dest, copy_non_py_files=True, verbose=False)
            assert result is True
            assert (Path(dest) / "test.py").exists()
            assert (Path(dest) / "data.txt").exists()

    def test_dry_run(self):
        from ndi.file.pfilemirror import pfilemirror

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            (Path(src) / "test.py").write_text("x = 1")

            result = pfilemirror(src, dest, dry_run=True, verbose=False)
            assert result is True
            # In dry run, files should NOT be copied
            assert not (Path(dest) / "test.py").exists()

    def test_skip_hidden(self):
        from ndi.file.pfilemirror import pfilemirror

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            (Path(src) / ".hidden.py").write_text("x = 1")
            (Path(src) / "visible.py").write_text("y = 2")

            result = pfilemirror(src, dest, verbose=False)
            assert result is True
            assert not (Path(dest) / ".hidden.py").exists()
            assert (Path(dest) / "visible.py").exists()

    def test_invalid_source(self):
        from ndi.file.pfilemirror import pfilemirror

        result = pfilemirror("/nonexistent/path", "/tmp/dest", verbose=False)
        assert result is False


# =========================================================================
# Batch 13: docComparison
# =========================================================================


class TestDocComparison:

    def test_basic_comparison(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("base.id", "character_exact")
        dc.add_comparison_parameter("response.mean", "abs_difference", tolerance=0.01)
        dc.add_comparison_parameter("meta.label", "none")

        doc1 = MagicMock()
        doc1.document_properties = {
            "base": {"id": "abc"},
            "response": {"mean": 10.0},
            "meta": {"label": "x"},
        }
        doc2 = MagicMock()
        doc2.document_properties = {
            "base": {"id": "abc"},
            "response": {"mean": 10.005},
            "meta": {"label": "y"},
        }

        result = dc.compare(doc1, doc2)
        assert result["equal"] is True

    def test_comparison_fails(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("value", "abs_difference", tolerance=0.01)

        doc1 = MagicMock()
        doc1.document_properties = {"value": 10.0}
        doc2 = MagicMock()
        doc2.document_properties = {"value": 20.0}

        result = dc.compare(doc1, doc2)
        assert result["equal"] is False

    def test_percent_difference(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("val", "abs_percent_difference", tolerance=5.0)

        doc1 = MagicMock()
        doc1.document_properties = {"val": 100}
        doc2 = MagicMock()
        doc2.document_properties = {"val": 103}

        result = dc.compare(doc1, doc2)
        assert result["equal"] is True  # 3% < 5%

    def test_json_roundtrip(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("a", "none")
        dc.add_comparison_parameter("b", "character_exact", scope="test")
        dc.add_comparison_parameter("c", "abs_difference", tolerance=0.5)

        json_str = dc.to_json()
        dc2 = DocComparison.from_json(json_str)

        assert len(dc2._parameters) == 3
        assert dc2._parameters[1]["scope"] == "test"
        assert dc2._parameters[2]["tolerance"] == 0.5

    def test_invalid_method(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        with pytest.raises(ValueError, match="Unknown comparison method"):
            dc.add_comparison_parameter("x", "bogus_method")

    def test_matches_scope(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("a", "none", scope="")
        dc.add_comparison_parameter("b", "none", scope="test")
        dc.add_comparison_parameter("c", "none", scope="test")

        assert len(dc.matches_scope("test")) == 2
        # Empty scope returns all parameters (no filter)
        assert len(dc.matches_scope("")) == 3

    def test_p_value_consistent(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("pval", "p_value_consistent", tolerance=0.05)

        doc1 = MagicMock()
        doc1.document_properties = {"pval": 0.8}
        doc2 = MagicMock()
        doc2.document_properties = {"pval": 0.01}

        result = dc.compare(doc1, doc2)
        assert result["equal"] is True  # p=0.8 >= 0.05

    def test_repr(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("a", "none")
        assert "parameters=1" in repr(dc)
