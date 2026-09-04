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
from ndi.query import ndi_query


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
        # Fields mirror apps/spikeextractor/spike_extraction_parameters.json,
        # which is what the doc actually validates against.
        params = ndi_app_spikeextractor.default_extraction_parameters()
        assert params["filter_type"] == "cheby1high"
        assert params["threshold_method"] == "standard_deviation"
        assert params["threshold_parameter"] == -4
        assert params["threshold_sign"] == -1
        assert params["filter_order"] == 4

    def test_extract_needs_extraction_parameters_document(self):
        # No session -> no way to find the required extraction_parameters doc.
        app = ndi_app_spikeextractor()
        with pytest.raises(ValueError, match="spike_extraction_parameters"):
            app.extract(SimpleNamespace())

    def test_isvalid_struct_valid(self):
        app = ndi_app_spikeextractor()
        b, errormsg = app.isvalid_appdoc_struct(
            "extraction_parameters",
            ndi_app_spikeextractor.default_extraction_parameters(),
        )
        assert b is True
        assert errormsg == ""

    def test_isvalid_struct_invalid(self):
        app = ndi_app_spikeextractor()
        b, errormsg = app.isvalid_appdoc_struct(
            "extraction_parameters",
            {"filter_type": "cheby1high"},  # missing most required fields
        )
        assert b is False
        assert "missing fields" in errormsg

    def test_isvalid_struct_other_type(self):
        app = ndi_app_spikeextractor()
        b, errormsg = app.isvalid_appdoc_struct("spikewaves", {})
        assert b is True

    def test_find_appdoc_no_session(self):
        app = ndi_app_spikeextractor()
        # find_appdoc requires a name arg for extraction_parameters.
        assert app.find_appdoc("extraction_parameters", "default") == []

    def test_struct2doc(self):
        from ndi.document import ndi_document

        app = ndi_app_spikeextractor()
        doc = app.struct2doc(
            "extraction_parameters",
            ndi_app_spikeextractor.default_extraction_parameters(),
            "default",
        )
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
        # MATLAB parity: graphical_mode default is 1 (interactive), the
        # non-graphical path is opt-in.
        params = ndi_app_spikesorter.default_sorting_parameters()
        assert params["graphical_mode"] == 1
        assert params["num_pca_features"] == 10
        assert params["interpolation"] == 3
        assert params["min_clusters"] == 3
        assert params["max_clusters"] == 10

    def test_spike_sort_without_session_raises(self):
        app = ndi_app_spikesorter()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.spike_sort(SimpleNamespace())

    def test_clusters2neurons_without_session_raises(self):
        app = ndi_app_spikesorter()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.clusters2neurons(SimpleNamespace())

    def test_isvalid_struct_valid(self):
        app = ndi_app_spikesorter()
        b, errormsg = app.isvalid_appdoc_struct(
            "sorting_parameters",
            ndi_app_spikesorter.default_sorting_parameters(),
        )
        assert b is True
        assert errormsg == ""

    def test_isvalid_struct_invalid(self):
        app = ndi_app_spikesorter()
        # Missing every field; the vlt-style error names the first one absent.
        b, errormsg = app.isvalid_appdoc_struct("sorting_parameters", {})
        assert b is False
        assert "'graphical_mode' not present." in errormsg

    def test_find_appdoc_no_session(self):
        app = ndi_app_spikesorter()
        # find_appdoc requires a name arg for sorting_parameters.
        assert app.find_appdoc("sorting_parameters", "default") == []

    def test_struct2doc(self):
        from ndi.document import ndi_document

        app = ndi_app_spikesorter()
        doc = app.struct2doc(
            "sorting_parameters",
            ndi_app_spikesorter.default_sorting_parameters(),
            "default",
        )
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

    def test_an_element_with_no_epochs_decodes_nothing(self):
        """Empty because there is nothing to decode, not because the method
        is a stub. This previously pinned ``return [], []``, which is what
        made the decoder unusable: it reported success having written no
        documents at all. See tests/test_app_stimulus_decoder.py for what
        it writes when there ARE epochs.
        """
        session = SimpleNamespace(
            id=lambda: "s1",
            searchquery=lambda: ndi_query("base.session_id") == "s1",
            database_search=lambda q: [],
            database_rm=lambda d: None,
        )
        app = ndi_app_stimulus_decoder(session=session)
        element = SimpleNamespace(id="stim1", epochtable=lambda: ([], "hash"))

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
        """Removal goes through database_rm, which sessions actually have.

        The double here previously supplied ``database_remove``, a method no
        session defines, so this passed while the real call raised
        AttributeError against every real session.
        """
        removed = []
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [SimpleNamespace(id="doc1")],
            database_rm=lambda d: removed.append(d),
        )
        app = ndi_app_stimulus_decoder(session=session)
        app._clear_presentations(SimpleNamespace(id="stim1"))
        assert removed == [[SimpleNamespace(id="doc1")]]

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

    def test_label_control_stimuli_needs_a_session(self):
        """It writes documents, so a session is not optional. This
        previously asserted [] from a stub that returned [] with or without
        one -- indistinguishable from "this element has no presentations".
        """
        app = ndi_app_stimulus_tuning__response()
        with pytest.raises(RuntimeError, match="No session"):
            app.label_control_stimuli(SimpleNamespace())

    def test_label_control_stimuli_with_no_presentations_writes_nothing(self):
        session = SimpleNamespace(id=lambda: "s1", database_search=lambda q: [])
        app = ndi_app_stimulus_tuning__response(session=session)
        assert app.label_control_stimuli(SimpleNamespace(id="stim1")) == []

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
        assert "stimulus_tuningcurve" in app.doc_types
        assert len(app.doc_types) == 2

    def test_doc_document_types_name_documents_that_exist(self):
        """Was: asserted the strings "apps/oridirtuning/...".

        Those paths name no document in ndi_common -- ndi_document() raises
        FileNotFoundError on both -- so struct2doc, add_appdoc and
        calculate_all_tuning_curves could not have produced anything. The old
        test passed because it compared strings and never built a document.
        This one builds them.
        """
        app = ndi_app_oridirtuning()
        for appdoc_type in app.doc_types:
            doc = app.struct2doc(appdoc_type, {})
            assert doc.document_properties["document_class"]["class_name"] == appdoc_type

    def test_calculate_all_tuning_curves_requires_a_session(self):
        """Was: asserted NotImplementedError. The method is implemented now;
        without a session it raises RuntimeError instead."""
        app = ndi_app_oridirtuning()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.calculate_all_tuning_curves(SimpleNamespace())

    def test_calculate_all_oridir_indexes_requires_a_session(self):
        """Was: asserted NotImplementedError. Both index methods are
        implemented now that VH-Lab/vhlab-toolbox-python#24 and
        VH-Lab/vhlab-library-python#8 landed, so the no-session case is what
        distinguishes a missing session from an untuned cell."""
        app = ndi_app_oridirtuning()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.calculate_all_oridir_indexes(SimpleNamespace())

    def test_is_oridir_stimulus_response_needs_a_session(self):
        """Replaces five tests that asserted a label lookup on the response
        document: each built a SimpleNamespace carrying
        ``document_properties.stimulus_tuningcurve.independent_variable_label``
        and checked that label against a list of words.

        No ``stimulus_response_scalar`` document has a
        ``stimulus_tuningcurve`` field -- it is a different document type --
        so against a real document the lookup raised and the answer was
        always False. SimpleNamespace accepts any attribute, which is what
        let five tests agree with each other and with nothing else.

        MATLAB follows the response to its stimulus presentation and asks
        what varies across the stimuli, which needs the session. The real
        behaviour is covered against realistic documents in
        tests/test_app_oridirtuning.py.
        """
        app = ndi_app_oridirtuning()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.is_oridir_stimulus_response(SimpleNamespace())

    def test_matlabs_other_tuning_curve_spelling_still_resolves(self):
        """MATLAB's constructor says "tuning_curve" while its struct2doc and
        add_appdoc say "stimulus_tuningcurve". Both reach the document."""
        app = ndi_app_oridirtuning()
        doc = app.struct2doc("tuning_curve", {})
        assert doc.document_properties["document_class"]["class_name"] == "stimulus_tuningcurve"

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
