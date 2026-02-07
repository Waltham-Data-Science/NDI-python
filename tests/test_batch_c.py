"""
Tests for Batch C: App & Calculator subclasses.

Tests MarkGarbage, SpikeExtractor, SpikeSorter, StimulusDecoder,
TuningResponse, OriDirTuning, and TuningCurveCalc.
"""

from types import SimpleNamespace

import pytest

from ndi.app import App
from ndi.app.appdoc import AppDoc

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from ndi.app.markgarbage import MarkGarbage
from ndi.app.oridirtuning import OriDirTuning
from ndi.app.spikeextractor import SpikeExtractor
from ndi.app.spikesorter import SpikeSorter
from ndi.app.stimulus import StimulusDecoder, TuningResponse
from ndi.app.stimulus.decoder import StimulusDecoder as StimulusDecoderDirect
from ndi.app.stimulus.tuning_response import TuningResponse as TuningResponseDirect
from ndi.calc.stimulus import TuningCurveCalc
from ndi.calc.stimulus.tuningcurve import TuningCurveCalc as TuningCurveCalcDirect
from ndi.calculator import Calculator


class TestImports:
    """Verify all Batch C classes are importable."""

    def test_import_markgarbage(self):
        assert MarkGarbage is not None

    def test_import_spikeextractor(self):
        assert SpikeExtractor is not None

    def test_import_spikesorter(self):
        assert SpikeSorter is not None

    def test_import_stimulus_decoder_from_package(self):
        assert StimulusDecoder is StimulusDecoderDirect

    def test_import_tuning_response_from_package(self):
        assert TuningResponse is TuningResponseDirect

    def test_import_oridirtuning(self):
        assert OriDirTuning is not None

    def test_import_tuningcurvecalc_from_package(self):
        assert TuningCurveCalc is TuningCurveCalcDirect


# ===========================================================================
# MarkGarbage
# ===========================================================================


class TestMarkGarbage:
    """Tests for the MarkGarbage app."""

    def test_init_no_session(self):
        app = MarkGarbage()
        assert app.session is None
        assert app.name == "ndi_app_markgarbage"

    def test_init_with_session(self):
        session = SimpleNamespace(id=lambda: "sess1")
        app = MarkGarbage(session=session)
        assert app.session is session

    def test_inherits_app(self):
        assert issubclass(MarkGarbage, App)

    def test_repr(self):
        app = MarkGarbage()
        assert "MarkGarbage" in repr(app)
        assert "False" in repr(app)

    def test_repr_with_session(self):
        session = SimpleNamespace(id=lambda: "s")
        app = MarkGarbage(session=session)
        assert "True" in repr(app)

    def test_save_no_session_raises(self):
        app = MarkGarbage()
        with pytest.raises(RuntimeError, match="No session"):
            app.savevalidinterval(None, {"t0": 0, "t1": 1})

    def test_clear_no_session(self):
        app = MarkGarbage()
        # Should not raise, just returns
        app.clearvalidinterval(SimpleNamespace(id="elem1"))

    def test_load_no_session(self):
        app = MarkGarbage()
        result = app.loadvalidinterval(SimpleNamespace(id="elem1"))
        assert result == []

    def test_markvalidinterval_calls_save(self):
        """Verify markvalidinterval builds struct and calls savevalidinterval."""
        saved = []

        class MockMarkGarbage(MarkGarbage):
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
        assert saved[0]["timeref_t0"] == "ref_utc"
        assert saved[0]["timeref_t1"] == "ref_utc"


# ===========================================================================
# SpikeExtractor
# ===========================================================================


class TestSpikeExtractor:
    """Tests for the SpikeExtractor app."""

    def test_init_no_session(self):
        app = SpikeExtractor()
        assert app.session is None
        assert app.name == "ndi_app_spikeextractor"

    def test_inherits_app_and_appdoc(self):
        assert issubclass(SpikeExtractor, App)
        assert issubclass(SpikeExtractor, AppDoc)

    def test_doc_types(self):
        app = SpikeExtractor()
        assert "extraction_parameters" in app.doc_types
        assert "extraction_parameters_modification" in app.doc_types
        assert "spikewaves" in app.doc_types
        assert len(app.doc_types) == 3

    def test_doc_document_types(self):
        app = SpikeExtractor()
        assert len(app.doc_document_types) == 3
        assert "apps/spikeextractor/spike_extraction_parameters" in app.doc_document_types
        assert "apps/spikeextractor/spikewaves" in app.doc_document_types

    def test_default_extraction_parameters(self):
        params = SpikeExtractor.default_extraction_parameters()
        assert "filter" in params
        assert "threshold" in params
        assert "timing" in params
        assert params["filter"]["type"] == "cheby1"
        assert params["threshold"]["method"] == "std"
        assert params["threshold"]["parameter"] == -4.0
        assert params["timing"]["pre_samples"] == 10

    def test_extract_raises(self):
        app = SpikeExtractor()
        with pytest.raises(NotImplementedError):
            app.extract(SimpleNamespace())

    def test_isvalid_struct_valid(self):
        app = SpikeExtractor()
        result = app.isvalid_appdoc_struct(
            "extraction_parameters",
            {"filter": {}, "threshold": {}},
        )
        assert result is True

    def test_isvalid_struct_invalid(self):
        app = SpikeExtractor()
        result = app.isvalid_appdoc_struct(
            "extraction_parameters",
            {"filter": {}},  # missing threshold
        )
        assert result is False

    def test_isvalid_struct_other_type(self):
        app = SpikeExtractor()
        result = app.isvalid_appdoc_struct("spikewaves", {})
        assert result is True

    def test_find_appdoc_no_session(self):
        app = SpikeExtractor()
        assert app.find_appdoc("extraction_parameters") == []

    def test_struct2doc(self):
        from ndi.document import Document

        app = SpikeExtractor()
        doc = app.struct2doc("extraction_parameters", {"filter": {}, "threshold": {}})
        assert isinstance(doc, Document)

    def test_repr(self):
        assert "SpikeExtractor" in repr(SpikeExtractor())


# ===========================================================================
# SpikeSorter
# ===========================================================================


class TestSpikeSorter:
    """Tests for the SpikeSorter app."""

    def test_init_no_session(self):
        app = SpikeSorter()
        assert app.session is None
        assert app.name == "ndi_app_spikesorter"

    def test_inherits_app_and_appdoc(self):
        assert issubclass(SpikeSorter, App)
        assert issubclass(SpikeSorter, AppDoc)

    def test_doc_types(self):
        app = SpikeSorter()
        assert "sorting_parameters" in app.doc_types
        assert "spike_clusters" in app.doc_types
        assert len(app.doc_types) == 2

    def test_doc_document_types(self):
        app = SpikeSorter()
        assert "apps/spikesorter/sorting_parameters" in app.doc_document_types
        assert "apps/spikesorter/spike_clusters" in app.doc_document_types

    def test_default_sorting_parameters(self):
        params = SpikeSorter.default_sorting_parameters()
        assert params["graphical_mode"] is False
        assert params["num_pca_features"] == 4
        assert params["interpolation"] == 2
        assert params["min_clusters"] == 1
        assert params["max_clusters"] == 5

    def test_spike_sort_raises(self):
        app = SpikeSorter()
        with pytest.raises(NotImplementedError):
            app.spike_sort(SimpleNamespace())

    def test_clusters2neurons_raises(self):
        app = SpikeSorter()
        with pytest.raises(NotImplementedError):
            app.clusters2neurons(SimpleNamespace())

    def test_isvalid_struct_valid(self):
        app = SpikeSorter()
        result = app.isvalid_appdoc_struct(
            "sorting_parameters",
            {"num_pca_features": 4},
        )
        assert result is True

    def test_isvalid_struct_invalid(self):
        app = SpikeSorter()
        result = app.isvalid_appdoc_struct(
            "sorting_parameters",
            {"interpolation": 2},  # missing num_pca_features
        )
        assert result is False

    def test_find_appdoc_no_session(self):
        app = SpikeSorter()
        assert app.find_appdoc("sorting_parameters") == []

    def test_struct2doc(self):
        from ndi.document import Document

        app = SpikeSorter()
        doc = app.struct2doc("sorting_parameters", {"num_pca_features": 4})
        assert isinstance(doc, Document)

    def test_repr(self):
        assert "SpikeSorter" in repr(SpikeSorter())


# ===========================================================================
# StimulusDecoder
# ===========================================================================


class TestStimulusDecoder:
    """Tests for the StimulusDecoder app."""

    def test_init_no_session(self):
        app = StimulusDecoder()
        assert app.session is None
        assert app.name == "ndi_app_stimulus_decoder"

    def test_inherits_app(self):
        assert issubclass(StimulusDecoder, App)

    def test_parse_no_session_raises(self):
        app = StimulusDecoder()
        with pytest.raises(RuntimeError, match="No session"):
            app.parse_stimuli(SimpleNamespace())

    def test_parse_returns_empty_list(self):
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [],
            database_remove=lambda d: None,
        )
        app = StimulusDecoder(session=session)
        result = app.parse_stimuli(SimpleNamespace(id="stim1"))
        assert result == []

    def test_load_presentation_time_no_session(self):
        app = StimulusDecoder()
        result = app.load_presentation_time(SimpleNamespace())
        assert result is None

    def test_load_presentation_time_with_session(self):
        session = SimpleNamespace(id=lambda: "s")
        app = StimulusDecoder(session=session)
        result = app.load_presentation_time(SimpleNamespace())
        assert result is None

    def test_clear_presentations_no_session(self):
        app = StimulusDecoder()
        # Should not raise
        app._clear_presentations(SimpleNamespace(id="stim1"))

    def test_clear_presentations_with_session(self):
        removed = []
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [SimpleNamespace(id="doc1")],
            database_remove=lambda d: removed.append(d),
        )
        app = StimulusDecoder(session=session)
        app._clear_presentations(SimpleNamespace(id="stim1"))
        assert len(removed) == 1

    def test_repr(self):
        assert "StimulusDecoder" in repr(StimulusDecoder())


# ===========================================================================
# TuningResponse
# ===========================================================================


class TestTuningResponse:
    """Tests for the TuningResponse app."""

    def test_init_no_session(self):
        app = TuningResponse()
        assert app.session is None
        assert app.name == "ndi_app_tuning_response"

    def test_inherits_app(self):
        assert issubclass(TuningResponse, App)

    def test_stimulus_responses_raises(self):
        app = TuningResponse()
        with pytest.raises(NotImplementedError):
            app.stimulus_responses(SimpleNamespace(), SimpleNamespace())

    def test_tuning_curve_raises(self):
        app = TuningResponse()
        with pytest.raises(NotImplementedError):
            app.tuning_curve(SimpleNamespace())

    def test_label_control_stimuli(self):
        app = TuningResponse()
        result = app.label_control_stimuli(SimpleNamespace())
        assert result == []

    def test_find_tuningcurve_no_session(self):
        app = TuningResponse()
        result = app.find_tuningcurve_document(
            SimpleNamespace(id="elem1"),
            "epoch1",
        )
        assert result == []

    def test_find_tuningcurve_with_session(self):
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [],
        )
        app = TuningResponse(session=session)
        result = app.find_tuningcurve_document(
            SimpleNamespace(id="elem1"),
            "epoch1",
        )
        assert result == []

    def test_repr(self):
        assert "TuningResponse" in repr(TuningResponse())


# ===========================================================================
# OriDirTuning
# ===========================================================================


class TestOriDirTuning:
    """Tests for the OriDirTuning app."""

    def test_init_no_session(self):
        app = OriDirTuning()
        assert app.session is None
        assert app.name == "ndi_app_oridirtuning"

    def test_inherits_app_and_appdoc(self):
        assert issubclass(OriDirTuning, App)
        assert issubclass(OriDirTuning, AppDoc)

    def test_doc_types(self):
        app = OriDirTuning()
        assert "orientation_direction_tuning" in app.doc_types
        assert "tuning_curve" in app.doc_types
        assert len(app.doc_types) == 2

    def test_doc_document_types(self):
        app = OriDirTuning()
        assert "apps/oridirtuning/orientation_direction_tuning" in app.doc_document_types
        assert "apps/oridirtuning/tuning_curve" in app.doc_document_types

    def test_calculate_tuning_curves_raises(self):
        app = OriDirTuning()
        with pytest.raises(NotImplementedError):
            app.calculate_all_tuning_curves(SimpleNamespace())

    def test_calculate_oridir_indexes_raises(self):
        app = OriDirTuning()
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
        assert OriDirTuning.is_oridir_stimulus_response(doc) is True

    def test_is_oridir_stimulus_direction(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="Direction",
                ),
            ),
        )
        assert OriDirTuning.is_oridir_stimulus_response(doc) is True

    def test_is_oridir_stimulus_orientation(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="ORIENTATION",
                ),
            ),
        )
        assert OriDirTuning.is_oridir_stimulus_response(doc) is True

    def test_is_oridir_stimulus_false(self):
        doc = SimpleNamespace(
            document_properties=SimpleNamespace(
                stimulus_tuningcurve=SimpleNamespace(
                    independent_variable_label="spatial_frequency",
                ),
            ),
        )
        assert OriDirTuning.is_oridir_stimulus_response(doc) is False

    def test_is_oridir_stimulus_no_attr(self):
        doc = SimpleNamespace(document_properties=SimpleNamespace())
        assert OriDirTuning.is_oridir_stimulus_response(doc) is False

    def test_struct2doc_maps_type_correctly(self):
        """struct2doc maps appdoc_type to correct schema path."""
        app = OriDirTuning()
        idx = app.doc_types.index("tuning_curve")
        assert app.doc_document_types[idx] == "apps/oridirtuning/tuning_curve"
        idx2 = app.doc_types.index("orientation_direction_tuning")
        assert app.doc_document_types[idx2] == "apps/oridirtuning/orientation_direction_tuning"

    def test_find_appdoc_no_session(self):
        app = OriDirTuning()
        assert app.find_appdoc("tuning_curve") == []

    def test_isvalid(self):
        app = OriDirTuning()
        assert app.isvalid_appdoc_struct("tuning_curve", {}) is True

    def test_repr(self):
        assert "OriDirTuning" in repr(OriDirTuning())


# ===========================================================================
# TuningCurveCalc
# ===========================================================================


class TestTuningCurveCalc:
    """Tests for the TuningCurveCalc calculator."""

    def test_init_no_session(self):
        calc = TuningCurveCalc()
        assert calc.session is None

    def test_inherits_calculator(self):
        assert issubclass(TuningCurveCalc, Calculator)

    def test_doc_types(self):
        calc = TuningCurveCalc()
        assert "tuningcurve_calc" in calc.doc_types

    def test_doc_document_types(self):
        calc = TuningCurveCalc()
        assert "apps/calculators/tuningcurve_calc" in calc.doc_document_types

    def test_calculate_returns_document(self):
        from ndi.document import Document

        calc = TuningCurveCalc()
        params = {
            "input_parameters": {
                "independent_label": "angle",
                "independent_parameter": "angle",
            },
            "depends_on": [],
        }
        docs = calc.calculate(params)
        assert len(docs) == 1
        assert isinstance(docs[0], Document)

    def test_calculate_with_dependencies(self):
        calc = TuningCurveCalc()
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
        calc = TuningCurveCalc(session=session)
        params = {"input_parameters": {}, "depends_on": []}
        docs = calc.calculate(params)
        assert len(docs) == 1
        assert docs[0].session_id == "sess1"

    def test_default_search_parameters(self):
        calc = TuningCurveCalc()
        params = calc.default_search_for_input_parameters()
        assert "input_parameters" in params
        assert "depends_on" in params
        assert "query" in params
        assert params["input_parameters"]["independent_label"] == "angle"
        assert params["input_parameters"]["best_algorithm"] == "empirical"
        assert len(params["query"]) == 1
        assert params["query"][0]["name"] == "document_id"

    def test_repr(self):
        assert "TuningCurveCalc" in repr(TuningCurveCalc())
