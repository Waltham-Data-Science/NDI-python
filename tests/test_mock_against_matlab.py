"""ndi.mock against MATLAB's +ndi/+mock/.

The mock helpers exist so that a calculator's self-test can build a session,
run, and check its own answer. Every defect covered here breaks that: a
reference collision fuses two elements into one, a subject that is never
added to the database cannot be found again, and a clear() that swallows its
own errors leaves the session full.
"""

from __future__ import annotations

import math
import tempfile
from unittest.mock import MagicMock

import pytest

from ndi.mock import (
    MOCK_SPIKES_NAME,
    MOCK_STIMULATOR_NAME,
    _pick_free_reference,
    clear_mock_docs,
    ndi_mock_ctest,
    stimulus_presentation,
    subject_stimulator_neuron,
)
from ndi.query import ndi_query


@pytest.fixture
def session():
    from ndi.session.dir import ndi_session_dir

    return ndi_session_dir("testref", tempfile.mkdtemp())


class TestSubjectStimulatorNeuronTouchesTheDatabase:
    """MATLAB adds the subject document and builds real element objects."""

    def test_the_subject_document_is_added_to_the_session(self, session):
        result = subject_stimulator_neuron(session)
        found = session.database_search(
            ndi_query("subject.local_identifier", "exact_string", result["subject_name"])
        )
        assert len(found) == 1

    def test_the_elements_are_element_objects_not_loose_documents(self, session):
        from ndi.element_timeseries import ndi_element_timeseries

        result = subject_stimulator_neuron(session)
        assert isinstance(result["stimulator"], ndi_element_timeseries)
        assert isinstance(result["spikes"], ndi_element_timeseries)

    def test_the_elements_carry_the_reference_and_type(self, session):
        result = subject_stimulator_neuron(session)
        for key, name, kind in (
            ("stimulator", MOCK_STIMULATOR_NAME, "stimulator"),
            ("spikes", MOCK_SPIKES_NAME, "spikes"),
        ):
            element = result[key]
            assert element.name == name
            assert element.reference == result["ref_num"]
            assert element.type == kind

    def test_both_elements_depend_on_the_mock_subject(self, session):
        result = subject_stimulator_neuron(session)
        subject_id = result["subject"].id
        assert result["stimulator"].subject_id == subject_id
        assert result["spikes"].subject_id == subject_id


class TestReferenceCollisions:
    """The defect MATLAB's pickFreeReference was written to fix."""

    def test_the_span_is_matlabs_not_the_old_thousand(self, session):
        for _ in range(5):
            ref = _pick_free_reference(session)
            assert 20001 <= ref <= 80000

    def test_repeated_calls_on_one_session_never_reuse_a_reference(self, session):
        refs = {subject_stimulator_neuron(session)["ref_num"] for _ in range(8)}
        assert len(refs) == 8

    def test_a_reference_already_in_the_session_is_rejected(self, session):
        taken = subject_stimulator_neuron(session)["ref_num"]
        assert _pick_free_reference(session) != taken

    def test_a_full_session_raises_and_names_the_remedy(self, session, monkeypatch):
        monkeypatch.setattr("ndi.mock._mock_reference_in_use", lambda s, n: True)
        with pytest.raises(RuntimeError, match="clear_mock_docs"):
            _pick_free_reference(session)


class TestClearDoesNotSwallowErrors:
    """MATLAB's clear is two lines and lets failures through."""

    def test_a_failing_removal_reaches_the_caller(self):
        session = MagicMock()
        session.database_search.return_value = [MagicMock()]
        session.database_rm.side_effect = RuntimeError("database is read-only")
        with pytest.raises(RuntimeError, match="read-only"):
            clear_mock_docs(session)

    def test_a_failing_search_reaches_the_caller(self):
        session = MagicMock()
        session.database_search.side_effect = RuntimeError("no database")
        with pytest.raises(RuntimeError, match="no database"):
            clear_mock_docs(session)

    def test_it_removes_what_the_search_found(self, session):
        subject_stimulator_neuron(session)
        clear_mock_docs(session)
        remaining = session.database_search(
            ndi_query("subject.local_identifier", "contains_string", "mock")
        )
        assert remaining == []


class TestBlankStimuli:
    """MATLAB reads a NaN in X as a control (blank) stimulus."""

    def test_a_nan_becomes_isblank(self):
        result = stimulus_presentation(
            independent_variables=["contrast"],
            param_values=[[math.nan]],
            response_rates=[0.0],
            reps=1,
            stim_duration=1.0,
        )
        assert result["presentations"][0]["parameters"] == {"isblank": 1}

    def test_a_real_value_is_untouched(self):
        result = stimulus_presentation(
            independent_variables=["contrast"],
            param_values=[[0.5]],
            response_rates=[0.0],
            reps=1,
            stim_duration=1.0,
        )
        assert result["presentations"][0]["parameters"] == {"contrast": 0.5}

    def test_a_blank_and_a_stimulus_in_one_list(self):
        result = stimulus_presentation(
            independent_variables=["contrast"],
            param_values=[[math.nan], [1.0]],
            response_rates=[0.0, 5.0],
            reps=1,
            stim_duration=1.0,
        )
        params = [p["parameters"] for p in result["presentations"]]
        assert params == [{"isblank": 1}, {"contrast": 1.0}]


class TestCtestPaths:
    """MATLAB's mock_path is calc_path()/mock/<classname>/ and the filename
    methods return full paths."""

    def test_calc_path_is_the_class_module_directory(self):
        from pathlib import Path

        import ndi.mock

        assert ndi_mock_ctest().calc_path() == Path(ndi.mock.__file__).resolve().parent

    def test_a_subclass_gets_its_own_directory(self):
        class Sub(ndi_mock_ctest):
            pass

        assert Sub().mock_path().name == "Sub"

    def test_mock_path_ends_in_the_class_name(self):
        ct = ndi_mock_ctest()
        assert ct.mock_path() == ct.calc_path() / "mock" / "ndi_mock_ctest"

    def test_the_filename_methods_return_full_paths(self):
        ct = ndi_mock_ctest()
        assert ct.mock_expected_filename(2).parent == ct.mock_path()
        assert ct.mock_comparison_filename(2).parent == ct.mock_path()


class TestCtestNewMethods:
    """Three methods MATLAB has that had no Python counterpart."""

    def test_load_mock_comparison_returns_none_when_absent(self, tmp_path):
        ct = ndi_mock_ctest()
        ct.mock_path = lambda: tmp_path
        assert ct.load_mock_comparison(1) is None

    def test_load_mock_comparison_reads_the_stored_rules(self, tmp_path):
        from ndi.doc_comparison import DocComparison

        rules = DocComparison()
        rules.add_comparison_parameter("response.mean", "abs_difference", tolerance=0.25)

        ct = ndi_mock_ctest()
        ct.mock_path = lambda: tmp_path
        ct.mock_comparison_filename(1).write_text(rules.to_json())

        loaded = ct.load_mock_comparison(1)
        assert isinstance(loaded, DocComparison)
        assert loaded.matches_scope("")

    def test_clean_mock_docs_is_a_no_op_that_exists(self):
        assert ndi_mock_ctest().clean_mock_docs() is None

    def test_report_summary_of_nothing_is_empty(self):
        assert ndi_mock_ctest.reportSummary(None) == ""
        assert ndi_mock_ctest.reportSummary("") == ""
        assert ndi_mock_ctest.reportSummary([]) == ""

    def test_report_summary_of_text_keeps_the_leading_space(self):
        assert ndi_mock_ctest.reportSummary("it exploded") == " it exploded"

    def test_report_summary_names_the_out_of_tolerance_fields(self):
        report = [{"name": "response.mean"}, {"name": "response.stderr"}]
        assert (
            ndi_mock_ctest.reportSummary(report)
            == " Out of tolerance: response.mean, response.stderr."
        )


class TestCompareMockDocsUsesTolerances:
    """`compare_mock_docs` must honor the tolerance object MATLAB uses.

    Exact comparison marks a calculator wrong if its answer differs from
    the stored expectation by so much as a floating-point rounding step.
    The whole point of the comparison file is that MATLAB compares within
    a stated tolerance; Python must too.
    """

    @staticmethod
    def _docs(expected_mean: float, actual_mean: float):
        expected = MagicMock()
        expected.document_properties = {"response": {"mean": expected_mean}}
        actual = MagicMock()
        actual.document_properties = {"response": {"mean": actual_mean}}
        return expected, actual

    def test_close_answer_passes_within_tolerance(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("response.mean", "abs_difference", tolerance=0.1)

        ct = ndi_mock_ctest()
        expected, actual = self._docs(1.0, 1.05)
        match, report = ct.compare_mock_docs(expected, actual, "highSNR", dc)
        assert match is True
        assert report == []

    def test_far_answer_fails_and_report_names_the_field(self):
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("response.mean", "abs_difference", tolerance=0.1)

        ct = ndi_mock_ctest()
        expected, actual = self._docs(1.0, 1.5)
        match, report = ct.compare_mock_docs(expected, actual, "highSNR", dc)
        assert match is False
        assert isinstance(report, list)
        assert any(item.get("name") == "response.mean" for item in report)
        # And reportSummary can render it as a leading-space sentence.
        assert "response.mean" in ndi_mock_ctest.reportSummary(report)

    def test_lowsnr_falls_through_to_exact_comparison(self):
        """MATLAB only consults docCompare when scope is highSNR."""
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter("response.mean", "abs_difference", tolerance=0.1)

        ct = ndi_mock_ctest()
        expected, actual = self._docs(1.0, 1.05)
        match, _ = ct.compare_mock_docs(expected, actual, "lowSNR", dc)
        # Exact comparison rejects 1.0 vs 1.05.
        assert match is False

    def test_no_docCompare_stays_exact(self):
        ct = ndi_mock_ctest()
        expected, actual = self._docs(1.0, 1.0)
        match, _ = ct.compare_mock_docs(expected, actual)
        assert match is True

    def test_two_argument_call_still_works(self):
        """The legacy two-arg signature is preserved for callers that
        never passed scope or a comparison object."""
        ct = ndi_mock_ctest()
        expected, actual = self._docs(1.0, 2.0)
        match, _ = ct.compare_mock_docs(expected, actual)
        assert match is False


class TestCtestTestReturnsControlAndUsesTolerances:
    """test() must load mock.N.compare.json for each test and pass it to
    compare_mock_docs, and must also return the expected-vs-expected
    control matrix that MATLAB returns."""

    def _ctest_with_tolerance(self, tmp_path, tolerance):
        from ndi.doc_comparison import DocComparison

        def make_doc(mean_value):
            d = MagicMock()
            d.document_properties = {"response": {"mean": mean_value}}
            return d

        class FakeCalculator:
            def __init__(self, produced_mean):
                self._mean = produced_mean

            def run(self, input_docs):
                return make_doc(self._mean)

        class Sub(ndi_mock_ctest):
            def generate_mock_docs(self, scope="highSNR", number=1):
                return {"input_docs": [], "expected_output": make_doc(1.0)}

        ct = Sub(calculator=FakeCalculator(produced_mean=1.05))
        ct.mock_path = lambda: tmp_path

        rules = DocComparison()
        rules.add_comparison_parameter("response.mean", "abs_difference", tolerance=tolerance)
        ct.mock_comparison_filename(1).write_text(rules.to_json())

        return ct

    def test_calculator_within_tolerance_now_passes(self, tmp_path):
        ct = self._ctest_with_tolerance(tmp_path, tolerance=0.1)
        result = ct.test("highSNR", 1)
        assert result["passed"] is True
        assert result["b_actual"] == [[True]]

    def test_calculator_out_of_tolerance_still_fails(self, tmp_path):
        ct = self._ctest_with_tolerance(tmp_path, tolerance=0.01)
        result = ct.test("highSNR", 1)
        assert result["passed"] is False
        assert result["b_actual"] == [[False]]

    def test_result_has_b_expected_control_matrix(self, tmp_path):
        ct = self._ctest_with_tolerance(tmp_path, tolerance=0.1)
        result = ct.test("highSNR", 1)
        assert "b_expected" in result
        assert result["b_expected"] == [[True]]
        assert "doc_output" in result
        assert "doc_expected_output" in result
