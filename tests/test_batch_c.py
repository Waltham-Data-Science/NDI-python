"""
Tests for Batch C: ndi_app & ndi_calculator subclasses.

Tests ndi_app_markgarbage, ndi_app_spikeextractor, ndi_app_spikesorter, ndi_app_stimulus_decoder,
ndi_app_stimulus_tuning__response, ndi_app_oridirtuning, and ndi_calc_stimulus_tuningcurve.
"""

from types import SimpleNamespace

import pytest

from ndi.app import ndi_app
from ndi.app.appdoc import ndi_app_appdoc

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from ndi.app.markgarbage import ndi_app_markgarbage
from ndi.app.oridirtuning import ndi_app_oridirtuning
from ndi.app.spikeextractor import ndi_app_spikeextractor
from ndi.app.spikesorter import ndi_app_spikesorter
from ndi.app.stimulus import ndi_app_stimulus_decoder, ndi_app_stimulus_tuning__response
from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder as StimulusDecoderDirect
from ndi.app.stimulus.tuning_response import (
    ndi_app_stimulus_tuning__response as TuningResponseDirect,
)
from ndi.calc.stimulus import ndi_calc_stimulus_tuningcurve
from ndi.calc.stimulus.tuningcurve import ndi_calc_stimulus_tuningcurve as TuningCurveCalcDirect
from ndi.calculator import ndi_calculator


class TestImports:
    """Verify all Batch C classes are importable."""

    def test_import_markgarbage(self):
        assert ndi_app_markgarbage is not None

    def test_import_spikeextractor(self):
        assert ndi_app_spikeextractor is not None

    def test_import_spikesorter(self):
        assert ndi_app_spikesorter is not None

    def test_import_stimulus_decoder_from_package(self):
        assert ndi_app_stimulus_decoder is StimulusDecoderDirect

    def test_import_tuning_response_from_package(self):
        assert ndi_app_stimulus_tuning__response is TuningResponseDirect

    def test_import_oridirtuning(self):
        assert ndi_app_oridirtuning is not None

    def test_import_tuningcurvecalc_from_package(self):
        assert ndi_calc_stimulus_tuningcurve is TuningCurveCalcDirect


# ===========================================================================
# ndi_app_markgarbage
# ===========================================================================


class TestMarkGarbage:
    """Tests for the ndi_app_markgarbage app."""

    def test_init_no_session(self):
        app = ndi_app_markgarbage()
        assert app.session is None
        assert app.name == "ndi_app_markgarbage"

    def test_init_with_session(self):
        session = SimpleNamespace(id=lambda: "sess1")
        app = ndi_app_markgarbage(session=session)
        assert app.session is session

    def test_inherits_app(self):
        assert issubclass(ndi_app_markgarbage, ndi_app)

    def test_repr(self):
        app = ndi_app_markgarbage()
        assert "ndi_app_markgarbage" in repr(app)
        assert "False" in repr(app)

    def test_repr_with_session(self):
        session = SimpleNamespace(id=lambda: "s")
        app = ndi_app_markgarbage(session=session)
        assert "True" in repr(app)

    def test_save_no_session_raises(self):
        app = ndi_app_markgarbage()
        with pytest.raises(RuntimeError, match="No session"):
            app.savevalidinterval(None, {"t0": 0, "t1": 1})

    def test_clear_no_session(self):
        app = ndi_app_markgarbage()
        # Should not raise, just returns
        app.clearvalidinterval(SimpleNamespace(id="elem1"))

    def test_load_no_session(self):
        app = ndi_app_markgarbage()
        intervals, docs = app.loadvalidinterval(SimpleNamespace(id="elem1"))
        assert intervals == []
        assert docs == []

    def test_markvalidinterval_calls_save(self):
        """Verify markvalidinterval builds the struct and calls savevalidinterval.

        The time references are stored as the schema's ``timeref_structt0``
        and ``timeref_structt1`` structs, not as the stringified references
        this once wrote -- see the schema and identifyvalidintervals, which
        reads them back. A reference that cannot describe itself (a bare
        string, here) stores the empty struct.
        """
        saved = []

        class MockMarkGarbage(ndi_app_markgarbage):
            def savevalidinterval(self, epochset_obj, interval_struct):
                saved.append(interval_struct)

        app = MockMarkGarbage()
        app.markvalidinterval(
            SimpleNamespace(id="elem"),
            0.5,
            "ref_utc",
            10.0,
            "ref_utc",
        )
        assert len(saved) == 1
        assert saved[0]["t0"] == 0.5
        assert saved[0]["t1"] == 10.0
        assert set(saved[0]) == {"timeref_structt0", "t0", "timeref_structt1", "t1"}
        assert saved[0]["timeref_structt0"]["clocktypestring"] == ""


# ===========================================================================
# ndi_app_spikeextractor
# ===========================================================================


class TestSpikeExtractor:
    """Tests for the ndi_app_spikeextractor app."""

    def test_init_no_session(self):
        app = ndi_app_spikeextractor()
        assert app.session is None
        assert app.name == "ndi_app_spikeextractor"

    def test_inherits_app_and_appdoc(self):
        assert issubclass(ndi_app_spikeextractor, ndi_app)
        assert issubclass(ndi_app_spikeextractor, ndi_app_appdoc)

    def test_doc_types(self):
        app = ndi_app_spikeextractor()
        assert "extraction_parameters" in app.doc_types
        assert "extraction_parameters_modification" in app.doc_types
        assert "spikewaves" in app.doc_types
        assert len(app.doc_types) == 3

    def test_doc_document_types(self):
        app = ndi_app_spikeextractor()
        assert len(app.doc_document_types) == 3
        assert "apps/spikeextractor/spike_extraction_parameters" in app.doc_document_types
        assert "apps/spikeextractor/spikewaves" in app.doc_document_types

    def test_default_extraction_parameters(self):
        params = ndi_app_spikeextractor.default_extraction_parameters()
        assert "filter" in params
        assert "threshold" in params
        assert "timing" in params
        assert params["filter"]["type"] == "cheby1"
        assert params["threshold"]["method"] == "std"
        assert params["threshold"]["parameter"] == -4.0
        assert params["timing"]["pre_samples"] == 10

    def test_extract_raises(self):
        app = ndi_app_spikeextractor()
        with pytest.raises(NotImplementedError):
            app.extract(SimpleNamespace())

    def test_isvalid_struct_valid(self):
        app = ndi_app_spikeextractor()
        b, errormsg = app.isvalid_appdoc_struct(
            "extraction_parameters",
            {"filter": {}, "threshold": {}},
        )
        assert b is True
        assert errormsg == ""

    def test_isvalid_struct_invalid(self):
        app = ndi_app_spikeextractor()
        b, errormsg = app.isvalid_appdoc_struct(
            "extraction_parameters",
            {"filter": {}},  # missing threshold
        )
        assert b is False
        assert "filter" in errormsg or "threshold" in errormsg

    def test_isvalid_struct_other_type(self):
        app = ndi_app_spikeextractor()
        b, errormsg = app.isvalid_appdoc_struct("spikewaves", {})
        assert b is True

    def test_find_appdoc_no_session(self):
        app = ndi_app_spikeextractor()
        assert app.find_appdoc("extraction_parameters") == []

    def test_struct2doc(self):
        from ndi.document import ndi_document

        app = ndi_app_spikeextractor()
        doc = app.struct2doc("extraction_parameters", {"filter": {}, "threshold": {}})
        assert isinstance(doc, ndi_document)

    def test_repr(self):
        assert "ndi_app_spikeextractor" in repr(ndi_app_spikeextractor())


# ===========================================================================
# ndi_app_spikesorter
# ===========================================================================


class TestSpikeSorter:
    """Tests for the ndi_app_spikesorter app."""

    def test_init_no_session(self):
        app = ndi_app_spikesorter()
        assert app.session is None
        assert app.name == "ndi_app_spikesorter"

    def test_inherits_app_and_appdoc(self):
        assert issubclass(ndi_app_spikesorter, ndi_app)
        assert issubclass(ndi_app_spikesorter, ndi_app_appdoc)

    def test_doc_types(self):
        app = ndi_app_spikesorter()
        assert "sorting_parameters" in app.doc_types
        assert "spike_clusters" in app.doc_types
        assert len(app.doc_types) == 2

    def test_doc_document_types(self):
        app = ndi_app_spikesorter()
        assert "apps/spikesorter/sorting_parameters" in app.doc_document_types
        assert "apps/spikesorter/spike_clusters" in app.doc_document_types

    def test_default_sorting_parameters(self):
        params = ndi_app_spikesorter.default_sorting_parameters()
        assert params["graphical_mode"] is False
        assert params["num_pca_features"] == 4
        assert params["interpolation"] == 2
        assert params["min_clusters"] == 1
        assert params["max_clusters"] == 5

    def test_spike_sort_raises(self):
        app = ndi_app_spikesorter()
        with pytest.raises(NotImplementedError):
            app.spike_sort(SimpleNamespace())

    def test_clusters2neurons_raises(self):
        app = ndi_app_spikesorter()
        with pytest.raises(NotImplementedError):
            app.clusters2neurons(SimpleNamespace())

    def test_isvalid_struct_valid(self):
        app = ndi_app_spikesorter()
        b, errormsg = app.isvalid_appdoc_struct(
            "sorting_parameters",
            {"num_pca_features": 4},
        )
        assert b is True
        assert errormsg == ""

    def test_isvalid_struct_invalid(self):
        app = ndi_app_spikesorter()
        b, errormsg = app.isvalid_appdoc_struct(
            "sorting_parameters",
            {"interpolation": 2},  # missing num_pca_features
        )
        assert b is False
        assert "num_pca_features" in errormsg

    def test_find_appdoc_no_session(self):
        app = ndi_app_spikesorter()
        assert app.find_appdoc("sorting_parameters") == []

    def test_struct2doc(self):
        from ndi.document import ndi_document

        app = ndi_app_spikesorter()
        doc = app.struct2doc("sorting_parameters", {"num_pca_features": 4})
        assert isinstance(doc, ndi_document)

    def test_repr(self):
        assert "ndi_app_spikesorter" in repr(ndi_app_spikesorter())


# ===========================================================================
# ndi_app_stimulus_decoder
# ===========================================================================


class TestStimulusDecoder:
    """Tests for the ndi_app_stimulus_decoder app."""

    def test_init_no_session(self):
        app = ndi_app_stimulus_decoder()
        assert app.session is None
        assert app.name == "ndi_app_stimulus_decoder"

    def test_inherits_app(self):
        assert issubclass(ndi_app_stimulus_decoder, ndi_app)

    def test_parse_no_session_raises(self):
        app = ndi_app_stimulus_decoder()
        with pytest.raises(RuntimeError, match="No session"):
            app.parse_stimuli(SimpleNamespace())

    def test_parse_an_element_with_no_epochs_writes_nothing(self):
        """This once asserted the stub's unconditional ([], []). It now
        exercises the real path with an element that has no epochs, which is
        the only way the answer is still two empty lists. The port is
        covered in tests/test_app_stimulus_decoder.py."""
        from ndi.query import ndi_query

        session = SimpleNamespace(
            id=lambda: "s1",
            searchquery=lambda: ndi_query("base.session_id", "exact_string", "s1", ""),
            database_search=lambda q: [],
            database_remove=lambda d: None,
        )
        app = ndi_app_stimulus_decoder(session=session)
        element = SimpleNamespace(id=lambda: "stim1", epochtable=lambda: [])
        newdocs, existingdocs = app.parse_stimuli(element)
        assert newdocs == []
        assert existingdocs == []

    def test_load_presentation_time_no_session(self):
        """Empty list, not None: every caller iterates the result.

        This previously asserted None, pinning a stub that returned None
        unconditionally -- including with a session, which is what made the
        method unusable. It now reads the real per-trial timing.
        """
        app = ndi_app_stimulus_decoder()
        assert app.load_presentation_time(SimpleNamespace()) == []

    def test_load_presentation_time_reads_the_deprecated_inline_form(self):
        session = SimpleNamespace(id=lambda: "s")
        app = ndi_app_stimulus_decoder(session=session)
        doc = SimpleNamespace(
            document_properties={
                "stimulus_presentation": {"presentation_time": [{"onset": 1.0, "offset": 2.0}]}
            }
        )
        import pytest as _pytest

        with _pytest.warns(UserWarning, match="deprecated"):
            assert app.load_presentation_time(doc) == [{"onset": 1.0, "offset": 2.0}]

    def test_load_presentation_time_reads_the_binary_form(self, tmp_path):
        """The modern form: the times live in presentation_time.bin."""
        import numpy as np

        from ndi.database_fun import write_presentation_time_structure

        path = tmp_path / "presentation_time.bin"
        write_presentation_time_structure(
            str(path),
            [
                {
                    "clocktype": "dev_local_time",
                    "stimopen": 0.9,
                    "onset": 1.0,
                    "offset": 2.0,
                    "stimclose": 2.1,
                    "stimevents": np.zeros((0, 2)),
                }
            ],
        )
        opened = SimpleNamespace(fullpathfilename=str(path))
        session = SimpleNamespace(
            id=lambda: "s",
            database_openbinarydoc=lambda d, n: opened,
            database_closebinarydoc=lambda f: None,
        )
        app = ndi_app_stimulus_decoder(session=session)
        got = app.load_presentation_time(
            SimpleNamespace(document_properties={"stimulus_presentation": {}})
        )
        assert len(got) == 1 and got[0]["onset"] == 1.0

    def test_clear_presentations_no_session(self):
        app = ndi_app_stimulus_decoder()
        # Should not raise
        app._clear_presentations(SimpleNamespace(id="stim1"))

    def test_clear_presentations_with_session(self):
        removed = []
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [SimpleNamespace(id="doc1")],
            database_remove=lambda d: removed.append(d),
        )
        app = ndi_app_stimulus_decoder(session=session)
        app._clear_presentations(SimpleNamespace(id="stim1"))
        assert len(removed) == 1

    def test_repr(self):
        assert "ndi_app_stimulus_decoder" in repr(ndi_app_stimulus_decoder())


# ===========================================================================
# ndi_app_stimulus_tuning__response
# ===========================================================================


class TestTuningResponse:
    """Tests for the ndi_app_stimulus_tuning__response app."""

    def test_init_no_session(self):
        app = ndi_app_stimulus_tuning__response()
        assert app.session is None
        assert app.name == "ndi_app_tuning_response"

    def test_inherits_app(self):
        assert issubclass(ndi_app_stimulus_tuning__response, ndi_app)

    def test_stimulus_responses_without_a_session_finds_nothing(self):
        """These raised NotImplementedError until the compute methods were
        ported; the behaviour without a session is now an empty result, as in
        the rest of the app layer. The port itself is covered in
        tests/test_app_stimulus_tuning_response.py."""
        app = ndi_app_stimulus_tuning__response()
        assert app.stimulus_responses(SimpleNamespace(), SimpleNamespace()) == []

    def test_tuning_curve_without_a_session_says_so(self):
        app = ndi_app_stimulus_tuning__response()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.tuning_curve(SimpleNamespace(), independent_parameter=["angle"])

    def test_label_control_stimuli(self):
        app = ndi_app_stimulus_tuning__response()
        result = app.label_control_stimuli(SimpleNamespace())
        assert result == []

    def test_find_tuningcurve_no_session(self):
        app = ndi_app_stimulus_tuning__response()
        tc_docs, srs_docs = app.find_tuningcurve_document(
            SimpleNamespace(id="elem1"),
            "epoch1",
        )
        assert tc_docs == []
        assert srs_docs == []

    def test_find_tuningcurve_with_session(self):
        from ndi.query import ndi_query

        session = SimpleNamespace(
            id=lambda: "s1",
            searchquery=lambda: ndi_query("base.session_id", "exact_string", "s1", ""),
            database_search=lambda q: [],
        )
        app = ndi_app_stimulus_tuning__response(session=session)
        tc_docs, srs_docs = app.find_tuningcurve_document(
            SimpleNamespace(id=lambda: "elem1"),
            "epoch1",
        )
        assert tc_docs == []
        assert srs_docs == []

    def test_repr(self):
        assert "ndi_app_stimulus_tuning__response" in repr(ndi_app_stimulus_tuning__response())


# ===========================================================================
# ndi_app_oridirtuning
# ===========================================================================


class TestOriDirTuning:
    """Tests for the ndi_app_oridirtuning app."""

    def test_init_no_session(self):
        app = ndi_app_oridirtuning()
        assert app.session is None
        assert app.name == "ndi_app_oridirtuning"

    def test_inherits_app_and_appdoc(self):
        assert issubclass(ndi_app_oridirtuning, ndi_app)
        assert issubclass(ndi_app_oridirtuning, ndi_app_appdoc)

    def test_doc_types(self):
        app = ndi_app_oridirtuning()
        assert "orientation_direction_tuning" in app.doc_types
        assert "tuning_curve" in app.doc_types
        assert len(app.doc_types) == 2

    def test_doc_document_types(self):
        app = ndi_app_oridirtuning()
        assert "apps/oridirtuning/orientation_direction_tuning" in app.doc_document_types
        assert "apps/oridirtuning/tuning_curve" in app.doc_document_types

    def test_calculate_tuning_curves_raises(self):
        app = ndi_app_oridirtuning()
        with pytest.raises(NotImplementedError):
            app.calculate_all_tuning_curves(SimpleNamespace())

    def test_calculate_oridir_indexes_raises(self):
        app = ndi_app_oridirtuning()
        with pytest.raises(NotImplementedError):
            app.calculate_all_oridir_indexes(SimpleNamespace())

    def test_is_oridir_stimulus_angle(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="angle",
                ),
            ),
        )
        assert ndi_app_oridirtuning.is_oridir_stimulus_response(doc) is True

    def test_is_oridir_stimulus_direction(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="Direction",
                ),
            ),
        )
        assert ndi_app_oridirtuning.is_oridir_stimulus_response(doc) is True

    def test_is_oridir_stimulus_orientation(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="ORIENTATION",
                ),
            ),
        )
        assert ndi_app_oridirtuning.is_oridir_stimulus_response(doc) is True

    def test_is_oridir_stimulus_false(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="spatial_frequency",
                ),
            ),
        )
        assert ndi_app_oridirtuning.is_oridir_stimulus_response(doc) is False

    def test_is_oridir_stimulus_no_attr(self):
        doc = SimpleNamespace(document_properties=SimpleNamespace())
        assert ndi_app_oridirtuning.is_oridir_stimulus_response(doc) is False

    def test_struct2doc_maps_type_correctly(self):
        """struct2doc maps appdoc_type to correct schema path."""
        app = ndi_app_oridirtuning()
        idx = app.doc_types.index("tuning_curve")
        assert app.doc_document_types[idx] == "apps/oridirtuning/tuning_curve"
        idx2 = app.doc_types.index("orientation_direction_tuning")
        assert app.doc_document_types[idx2] == "apps/oridirtuning/orientation_direction_tuning"

    def test_find_appdoc_no_session(self):
        app = ndi_app_oridirtuning()
        assert app.find_appdoc("tuning_curve") == []

    def test_isvalid(self):
        app = ndi_app_oridirtuning()
        b, errormsg = app.isvalid_appdoc_struct("tuning_curve", {})
        assert b is True
        assert errormsg == ""

    def test_repr(self):
        assert "ndi_app_oridirtuning" in repr(ndi_app_oridirtuning())


# ===========================================================================
# ndi_calc_stimulus_tuningcurve
# ===========================================================================


class TestTuningCurveCalc:
    """Tests for the ndi_calc_stimulus_tuningcurve calculator."""

    def test_init_no_session(self):
        calc = ndi_calc_stimulus_tuningcurve()
        assert calc.session is None

    def test_inherits_calculator(self):
        assert issubclass(ndi_calc_stimulus_tuningcurve, ndi_calculator)

    def test_doc_types(self):
        calc = ndi_calc_stimulus_tuningcurve()
        assert "tuningcurve_calc" in calc.doc_types

    def test_doc_document_types(self):
        calc = ndi_calc_stimulus_tuningcurve()
        assert "apps/calculators/tuningcurve_calc" in calc.doc_document_types

    def test_calculate_returns_document(self):
        from ndi.document import ndi_document

        calc = ndi_calc_stimulus_tuningcurve()
        params = {
            "input_parameters": {
                "independent_label": "angle",
                "independent_parameter": "angle",
            },
            "depends_on": [],
        }
        docs = calc.calculate(params)
        assert len(docs) == 1
        assert isinstance(docs[0], ndi_document)

    def test_calculate_with_dependencies(self):
        calc = ndi_calc_stimulus_tuningcurve()
        params = {
            "input_parameters": {"label": "angle"},
            "depends_on": [{"name": "stimulus_response_scalar_id", "value": "abc123"}],
        }
        docs = calc.calculate(params)
        assert len(docs) == 1
        # Check the dependency was set (schema defines stimulus_response_scalar_id)
        dep = docs[0].dependency_value("stimulus_response_scalar_id")
        assert dep == "abc123"

    def test_calculate_with_session(self):
        session = SimpleNamespace(id=lambda: "sess1")
        calc = ndi_calc_stimulus_tuningcurve(session=session)
        params = {"input_parameters": {}, "depends_on": []}
        docs = calc.calculate(params)
        assert len(docs) == 1
        assert docs[0].session_id == "sess1"

    def test_default_search_parameters(self):
        calc = ndi_calc_stimulus_tuningcurve()
        params = calc.default_search_for_input_parameters()
        assert "input_parameters" in params
        assert "depends_on" in params
        assert "query" in params
        assert params["input_parameters"]["independent_label"] == "angle"
        assert params["input_parameters"]["best_algorithm"] == "empirical"
        assert len(params["query"]) == 1
        assert params["query"][0]["name"] == "document_id"

    def test_repr(self):
        assert "ndi_calc_stimulus_tuningcurve" in repr(ndi_calc_stimulus_tuningcurve())
