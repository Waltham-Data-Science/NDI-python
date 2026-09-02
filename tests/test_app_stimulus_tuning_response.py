"""Tests for ndi.app.stimulus.tuning_response.

MATLAB counterpart: ndi.app.stimulus.tuning_response

The numbers come first. A synthetic signal whose mean and modulation depth
are known by construction goes in, and the F0 and F1 responses that come out
are checked against those known values -- because every later stage of the
pipeline (tuning curves, fits, the figures in a paper) is a transformation of
these, and a quiet error here would look like data.

Then the document logic: which presentation is a control for which, which
responses are averaged into which point of a curve, and what happens when the
stimuli do not carry what was asked for. Those run against a fake session that
records what was searched, added and removed, so the decisions are visible
without a database.

The complex-response test is a regression on the thing that made this port
necessary: vhlab-toolbox-python's own stimulus_response_scalar preallocates
real arrays and raises the moment an F1 response is stored
(VH-Lab/vhlab-toolbox-python#24).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ndi.app.stimulus.tuning_response import (
    MEAN_RESPONSE_NAMES,
    MODULATED_RESPONSE_NAMES,
    ndi_app_stimulus_tuning__response,
    scalar_responses,
)
from ndi.document import ndi_document

DECODER = "ndi.app.stimulus.decoder.ndi_app_stimulus_decoder"


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------
def _session(search=None):
    """A session that records what it was asked to do."""
    session = MagicMock()
    session.id.return_value = "session-1"
    session.searchquery.return_value = _always_true_query()
    session.database_search = MagicMock(side_effect=search or (lambda q: []))
    session.database_add = MagicMock()
    session.database_rm = MagicMock()
    return session


def _always_true_query():
    from ndi.query import ndi_query

    return ndi_query("base.session_id", "exact_string", "session-1", "")


def _app(session=None):
    return ndi_app_stimulus_tuning__response(session=session if session is not None else _session())


def _matches_parameters(doc, query) -> bool:
    """Does DOC satisfy the parameter fields QUERY asks for?

    The fake session has to honour this filter rather than returning every
    parameter document, or the reuse rule under test -- responses computed
    the same way share one parameter document, responses computed
    differently do not -- would pass for the wrong reason.
    """
    stored = doc.document_properties.get("stimulus_response_scalar_parameters_basic", {})
    prefix = "stimulus_response_scalar_parameters_basic."
    for clause in query.search_structure:
        field = clause.get("field", "")
        if not field.startswith(prefix):
            continue
        if stored.get(field[len(prefix) :]) != clause.get("param1"):
            return False
    return True


def _presentation_doc(stimuli, presentation_order, timing=None):
    doc = ndi_document("stimulus_presentation")
    presentation = {"stimuli": stimuli, "presentation_order": list(presentation_order)}
    if timing is not None:
        presentation["presentation_time"] = timing
    doc.document_properties["stimulus_presentation"] = presentation
    doc.document_properties["epochid"] = {"epochid": "epoch1"}
    return doc


def _timing(onsets, duration=1.0):
    return [
        {"onset": float(o), "offset": float(o) + duration, "clocktype": "dev_local_time"}
        for o in onsets
    ]


def _response_doc(stimid, real, imaginary=None, control=None, response_type="mean"):
    doc = ndi_document("stimulus_response_scalar")
    n = len(stimid)
    doc.document_properties["stimulus_response_scalar"] = {
        "response_type": response_type,
        "responses": {
            "stimid": list(stimid),
            "response_real": list(real),
            "response_imaginary": list(imaginary if imaginary is not None else [0.0] * n),
            "control_response_real": list(control if control is not None else [0.0] * n),
            "control_response_imaginary": [0.0] * n,
        },
    }
    return doc


# ----------------------------------------------------------------------
# the response math
# ----------------------------------------------------------------------
class TestScalarResponses:
    """A signal built so the right answer is known before the code runs."""

    def _signal(self):
        # Three one-second windows at 100 Hz. Window 1 sits at 10 with a 4-unit
        # 2 Hz modulation, window 2 at 20 with 6, window 3 is the blank at 5.
        rate = 100.0
        t = np.arange(0, 3.0, 1 / rate)
        signal = np.empty_like(t)
        first, second, third = (t < 1), (t >= 1) & (t < 2), (t >= 2)
        signal[first] = 10 + 4 * np.cos(2 * np.pi * 2.0 * t[first])
        signal[second] = 20 + 6 * np.cos(2 * np.pi * 2.0 * (t[second] - 1))
        signal[third] = 5.0
        windows = np.array([[0.0, 0.99, 1], [1.0, 1.99, 2], [2.0, 2.99, 3]])
        return signal, t, windows

    def test_f0_is_the_mean_over_each_window(self):
        signal, t, windows = self._signal()
        out = scalar_responses(signal, t, windows, freq_response=0, control_stimid=[3])
        assert np.real(out["response"]) == pytest.approx([10.0, 20.0, 5.0], abs=0.2)

    def test_f1_recovers_the_modulation_depth(self):
        signal, t, windows = self._signal()
        out = scalar_responses(
            signal, t, windows, freq_response=np.array([2.0, 2.0, 0.0]), control_stimid=[3]
        )
        assert abs(out["response"][0]) == pytest.approx(4.0, abs=0.2)
        assert abs(out["response"][1]) == pytest.approx(6.0, abs=0.2)

    def test_a_complex_response_survives_being_stored(self):
        """The toolbox bug this port exists to route around: a real-valued
        output array cannot hold an F1 response."""
        signal, t, windows = self._signal()
        out = scalar_responses(signal, t, windows, freq_response=2.0, control_stimid=[3])
        assert np.iscomplexobj(out["response"])
        assert np.any(np.imag(out["response"]) != 0)

    def test_the_frequency_vector_is_indexed_by_stimulus_id(self):
        """One frequency per stimulus, 1-based as the documents hold them.
        Getting this off by one would measure each stimulus at its
        neighbour's frequency and still return plausible numbers."""
        signal, t, windows = self._signal()
        # Only stimulus 2 is measured at its real 2 Hz; stimulus 1 at 0 Hz
        # must come back as its mean instead.
        out = scalar_responses(
            signal, t, windows, freq_response=np.array([0.0, 2.0, 0.0]), control_stimid=[3]
        )
        assert np.real(out["response"][0]) == pytest.approx(10.0, abs=0.2)
        assert abs(out["response"][1]) == pytest.approx(6.0, abs=0.2)

    def test_an_id_with_no_frequency_entry_warns_and_falls_back(self):
        signal, t, windows = self._signal()
        with pytest.warns(UserWarning, match="likely stimulus glitch"):
            scalar_responses(signal, t, windows, freq_response=np.array([1.0, 2.0]))

    def test_a_window_the_recording_does_not_cover_is_nan(self):
        """NaN, not zero: nothing was measured, which is not the same as
        measuring nothing."""
        signal, t, windows = self._signal()
        windows[1, 1] = 99.0  # runs off the end of the recording
        out = scalar_responses(signal, t, windows, freq_response=0, control_stimid=[3])
        assert np.isnan(out["response"][1])
        assert not np.isnan(out["response"][0])

    def test_the_control_response_comes_from_the_control_window(self):
        signal, t, windows = self._signal()
        out = scalar_responses(signal, t, windows, freq_response=0, control_stimid=[3])
        assert np.real(out["control_response"][0]) == pytest.approx(5.0, abs=1e-6)

    def test_a_spike_process_gives_a_rate(self):
        """F0 for spikes is spikes per second, not the mean of the ones."""
        spikes = np.array([0.1, 0.2, 0.3, 0.4, 1.5, 1.6])
        ones = np.ones_like(spikes)
        windows = np.array([[0.0, 2.0, 1]])
        out = scalar_responses(ones, spikes, windows, freq_response=0, isspike=True)
        assert np.real(out["response"][0]) == pytest.approx(6 / 2.0)

    def test_a_spike_window_that_runs_past_the_recording_is_still_measured(self):
        """The absence of a spike is a measurement, so the out-of-bounds test
        that applies to a sampled signal must not apply here."""
        spikes = np.array([0.1, 0.2])
        windows = np.array([[0.0, 10.0, 1]])
        out = scalar_responses(np.ones_like(spikes), spikes, windows, isspike=True)
        assert not np.isnan(out["response"][0])

    def test_prestimulus_subtraction(self):
        rate = 100.0
        t = np.arange(0, 2.0, 1 / rate)
        signal = np.where(t < 1.0, 3.0, 11.0)  # baseline 3, response 11
        windows = np.array([[1.0, 1.99, 1]])
        out = scalar_responses(
            signal, t, windows, freq_response=0, prestimulus_time=0.5, prestimulus_normalization=1
        )
        assert np.real(out["response"][0]) == pytest.approx(8.0, abs=1e-6)

    def test_prestimulus_fractional_change_and_divide(self):
        rate = 100.0
        t = np.arange(0, 2.0, 1 / rate)
        signal = np.where(t < 1.0, 4.0, 12.0)
        windows = np.array([[1.0, 1.99, 1]])
        fractional = scalar_responses(
            signal, t, windows, prestimulus_time=0.5, prestimulus_normalization="fractional"
        )
        divided = scalar_responses(
            signal, t, windows, prestimulus_time=0.5, prestimulus_normalization=3
        )
        assert np.real(fractional["response"][0]) == pytest.approx(2.0, abs=1e-6)
        assert np.real(divided["response"][0]) == pytest.approx(3.0, abs=1e-6)

    def test_a_zero_baseline_gives_nan_rather_than_raising(self):
        t = np.arange(0, 2.0, 0.01)
        signal = np.where(t < 1.0, 0.0, 5.0)
        windows = np.array([[1.0, 1.99, 1]])
        out = scalar_responses(
            signal, t, windows, prestimulus_time=0.5, prestimulus_normalization=3
        )
        assert np.isnan(out["response"][0])

    def test_the_parameters_are_reported_back(self):
        out = scalar_responses([1.0, 2.0], [0.0, 1.0], [[0.0, 1.0, 1]], isspike=True)
        assert out["parameters"]["isspike"] is True
        assert out["parameters"]["spiketrain_dt"] == 0.001


# ----------------------------------------------------------------------
# control stimuli
# ----------------------------------------------------------------------
class TestControlStimulus:
    def _stimuli(self, blank_index=2):
        stimuli = [
            {"parameters": {"angle": 0, "isblank": 0}},
            {"parameters": {"angle": 90, "isblank": 0}},
            {"parameters": {"angle": 0, "isblank": 0}},
        ]
        if blank_index is not None:
            stimuli[blank_index] = {"parameters": {"isblank": 1}}
        return stimuli

    def test_each_repetition_uses_its_own_control(self):
        """The whole point of pseudorandom pairing: a baseline from minutes
        away is a different baseline."""
        doc = _presentation_doc(
            self._stimuli(), [1, 2, 3, 1, 2, 3], timing=_timing([0, 2, 4, 6, 8, 10])
        )
        ids, _ = _app().control_stimulus(doc)
        assert ids == [3.0, 3.0, 3.0, 6.0, 6.0, 6.0]

    def test_an_incomplete_last_repetition_reuses_the_previous_control(self):
        doc = _presentation_doc(self._stimuli(), [1, 2, 3, 1, 2], timing=_timing([0, 2, 4, 6, 8]))
        ids, _ = _app().control_stimulus(doc)
        assert ids[-1] == 3.0

    def test_a_set_with_no_control_gives_nan_throughout(self):
        doc = _presentation_doc(
            self._stimuli(blank_index=None), [1, 2, 3, 1, 2, 3], timing=_timing([0, 2, 4, 6, 8, 10])
        )
        ids, _ = _app().control_stimulus(doc)
        assert all(np.isnan(i) for i in ids)

    def test_two_kinds_of_control_stimulus_are_refused(self):
        stimuli = [{"parameters": {"isblank": 1}}, {"parameters": {"isblank": 1}}]
        doc = _presentation_doc(stimuli, [1, 2])
        with pytest.raises(ValueError, match="more than one control stimulus"):
            _app().control_stimulus(doc)

    def test_an_unknown_method_is_refused(self):
        with pytest.raises(ValueError, match="Unknown control_stim_method"):
            _app().control_stimulus(_presentation_doc([], []), control_stim_method="nonsense")

    def test_hasfield_takes_any_stimulus_carrying_the_parameter(self):
        stimuli = [
            {"parameters": {"angle": 0}},
            {"parameters": {"angle": 90}},
            {"parameters": {"angle": 0, "isblank": 0}},
        ]
        doc = _presentation_doc(stimuli, [1, 2, 3, 1, 2, 3], timing=_timing([0, 2, 4, 6, 8, 10]))
        ids, _ = _app().control_stimulus(doc, control_stim_method="hasfield")
        assert ids == [3.0, 3.0, 3.0, 6.0, 6.0, 6.0]

    def test_an_irregular_order_pairs_by_nearest_onset(self):
        doc = _presentation_doc(self._stimuli(), [1, 1, 2, 3, 2, 3])
        with patch(DECODER) as decoder:
            decoder.return_value.load_presentation_time.return_value = _timing(
                [0.0, 1.0, 2.0, 10.0, 11.0, 20.0]
            )
            ids, _ = _app().control_stimulus(doc)
        assert ids == [4.0, 4.0, 4.0, 4.0, 4.0, 6.0]

    def test_an_irregular_order_without_timing_reports_unknown(self):
        """No time for every trial means no "closest in time" to find. NaN
        per trial says that; guessing a neighbour would not."""
        doc = _presentation_doc(self._stimuli(), [1, 1, 2, 3, 2, 3])
        with patch(DECODER) as decoder:
            decoder.return_value.load_presentation_time.return_value = []
            ids, _ = _app().control_stimulus(doc)
        assert all(np.isnan(i) for i in ids)

    def test_the_document_records_the_method_and_the_presentation(self):
        doc = _presentation_doc(self._stimuli(), [1, 2, 3], timing=_timing([0, 2, 4]))
        session = _session()
        _, control_doc = _app(session).control_stimulus(doc, controlid="isblank")
        method = control_doc.document_properties["control_stimulus_ids"][
            "control_stimulus_id_method"
        ]
        assert method["method"] == "pseudorandom"
        assert method["controlid"] == "isblank"
        assert control_doc.dependency_value("stimulus_presentation_id") == doc.id
        session.database_add.assert_called_once()


class TestLabelControlStimuli:
    def test_without_a_session_it_says_so(self):
        """An empty list would read as "this element has no presentations",
        which is a different thing from "there is nowhere to look"."""
        with pytest.raises(RuntimeError, match="No session configured"):
            ndi_app_stimulus_tuning__response().label_control_stimuli(SimpleNamespace())

    def test_one_document_per_presentation(self):
        doc = _presentation_doc(
            [{"parameters": {"angle": 0}}, {"parameters": {"isblank": 1}}],
            [1, 2, 1, 2],
            timing=_timing([0, 2, 4, 6]),
        )
        session = _session(search=lambda q: [doc])
        stimulator = SimpleNamespace(id="stim-1")
        docs = _app(session).label_control_stimuli(stimulator)
        assert len(docs) == 1
        assert docs[0].doc_class() == "control_stimulus_ids"

    def test_reset_removes_the_existing_labels_first(self):
        doc = _presentation_doc(
            [{"parameters": {"angle": 0}}, {"parameters": {"isblank": 1}}],
            [1, 2],
            timing=_timing([0, 2]),
        )
        old = ndi_document("control_stimulus_ids")
        session = _session(search=lambda q: [doc] if _is_presentation_query(q) else [old])
        _app(session).label_control_stimuli(SimpleNamespace(id="stim-1"), reset=True)
        session.database_rm.assert_called_once()


def _is_presentation_query(query) -> bool:
    return "stimulus_presentation" in repr(query.search_structure)


# ----------------------------------------------------------------------
# tuning curves
# ----------------------------------------------------------------------
class TestTuningCurve:
    def _pair(self, real=(10.0, 20.0, 12.0, 22.0), imaginary=None):
        stimuli = [{"parameters": {"angle": 0.0}}, {"parameters": {"angle": 90.0}}]
        presentation = _presentation_doc(stimuli, [1, 2, 1, 2])
        response = _response_doc(
            [1, 2, 1, 2], real, imaginary=imaginary, control=[1.0, 1.0, 1.0, 1.0]
        )
        response = response.set_dependency_value(
            "stimulus_presentation_id", presentation.id, error_if_not_found=False
        )
        response = response.set_dependency_value(
            "element_id", "element-1", error_if_not_found=False
        )
        return response, presentation

    def _app_for(self, presentation):
        return _app(_session(search=lambda q: [presentation]))

    def test_a_parameter_is_required(self):
        response, presentation = self._pair()
        with pytest.raises(ValueError, match="independent_parameter is empty"):
            self._app_for(presentation).tuning_curve(response)

    def test_labels_must_match_parameters_one_for_one(self):
        response, presentation = self._pair()
        with pytest.raises(ValueError, match="Mismatch between dimensions"):
            self._app_for(presentation).tuning_curve(
                response, independent_parameter=["angle"], independent_label=["a", "b"]
            )

    def test_one_point_per_unique_parameter_value(self):
        response, presentation = self._pair()
        doc = self._app_for(presentation).tuning_curve(response, independent_parameter=["angle"])
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["independent_variable_value"] == [[0.0], [90.0]]
        assert curve["response_mean"] == pytest.approx([11.0, 21.0])

    def test_the_individual_responses_are_kept(self):
        """A later fit needs them; a mean alone cannot be weighted or
        resampled."""
        response, presentation = self._pair()
        doc = self._app_for(presentation).tuning_curve(response, independent_parameter=["angle"])
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["individual_responses_real"] == [[10.0, 12.0], [20.0, 22.0]]
        assert curve["control_individual_responses_real"] == [[1.0, 1.0], [1.0, 1.0]]

    def test_presentation_numbers_are_one_based(self):
        response, presentation = self._pair()
        doc = self._app_for(presentation).tuning_curve(response, independent_parameter=["angle"])
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["stimulus_presentation_number"] == [[1, 3], [2, 4]]
        assert curve["stimid"] == [1.0, 2.0]

    def test_the_spread_is_reported_three_ways(self):
        response, presentation = self._pair()
        doc = self._app_for(presentation).tuning_curve(response, independent_parameter=["angle"])
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["response_stddev"] == pytest.approx([np.sqrt(2.0), np.sqrt(2.0)])
        assert curve["response_stderr"] == pytest.approx([1.0, 1.0])

    def test_a_complex_mean_is_reported_as_its_magnitude(self):
        """The phase of an F1 response depends on when the stimulus started,
        so it is not comparable across stimuli; the magnitude is."""
        response, presentation = self._pair(
            real=(3.0, 0.0, 3.0, 0.0), imaginary=(4.0, 0.0, 4.0, 0.0)
        )
        doc = self._app_for(presentation).tuning_curve(response, independent_parameter=["angle"])
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["response_mean"][0] == pytest.approx(5.0)

    def test_a_constraint_narrows_which_stimuli_count(self):
        stimuli = [
            {"parameters": {"angle": 0.0, "sFrequency": 1.0}},
            {"parameters": {"angle": 90.0, "sFrequency": 2.0}},
        ]
        presentation = _presentation_doc(stimuli, [1, 2])
        response = _response_doc([1, 2], [10.0, 20.0])
        response = response.set_dependency_value(
            "stimulus_presentation_id", presentation.id, error_if_not_found=False
        )
        doc = self._app_for(presentation).tuning_curve(
            response,
            independent_parameter=["angle"],
            constraint=[
                {"field": "sFrequency", "operation": "exact_number", "param1": 1.0, "param2": ""}
            ],
        )
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["independent_variable_value"] == [[0.0]]

    def test_nothing_matching_gives_no_curve_and_says_so(self):
        response, presentation = self._pair()
        with pytest.warns(UserWarning, match="empty tuning curve"):
            doc = self._app_for(presentation).tuning_curve(
                response, independent_parameter=["nosuchparameter"]
            )
        assert doc is None

    def test_two_parameters_make_a_multivariate_curve(self):
        stimuli = [
            {"parameters": {"angle": 0.0, "sFrequency": 1.0}},
            {"parameters": {"angle": 90.0, "sFrequency": 1.0}},
            {"parameters": {"angle": 0.0, "sFrequency": 2.0}},
        ]
        presentation = _presentation_doc(stimuli, [1, 2, 3])
        response = _response_doc([1, 2, 3], [10.0, 20.0, 30.0])
        response = response.set_dependency_value(
            "stimulus_presentation_id", presentation.id, error_if_not_found=False
        )
        doc = self._app_for(presentation).tuning_curve(
            response,
            independent_parameter=["angle", "sFrequency"],
            independent_label=["angle", "sf"],
        )
        curve = doc.document_properties["stimulus_tuningcurve"]
        assert curve["independent_variable_label"] == ["angle,sf"]
        assert len(curve["independent_variable_value"]) == 3

    def test_the_curve_depends_on_the_response_it_came_from(self):
        response, presentation = self._pair()
        session = _session(search=lambda q: [presentation])
        doc = _app(session).tuning_curve(response, independent_parameter=["angle"])
        assert doc.dependency_value("stimulus_response_scalar_id") == response.id
        assert doc.dependency_value("element_id") == "element-1"
        session.database_add.assert_called_once()

    def test_do_add_false_leaves_the_database_alone(self):
        response, presentation = self._pair()
        session = _session(search=lambda q: [presentation])
        _app(session).tuning_curve(response, independent_parameter=["angle"], do_add=False)
        session.database_add.assert_not_called()

    def test_a_missing_presentation_document_is_named_in_the_error(self):
        response, _ = self._pair()
        with pytest.raises(RuntimeError, match="Could not load the stimulus presentation"):
            _app(_session()).tuning_curve(response, independent_parameter=["angle"])


class TestMake1dTuning:
    def test_one_curve_per_value_of_the_fixed_parameter(self):
        stimuli = [
            {"parameters": {"angle": 0.0, "sFrequency": 1.0}},
            {"parameters": {"angle": 90.0, "sFrequency": 1.0}},
            {"parameters": {"angle": 0.0, "sFrequency": 2.0}},
            {"parameters": {"angle": 90.0, "sFrequency": 2.0}},
            {"parameters": {"isblank": 1}},
        ]
        presentation = _presentation_doc(stimuli, [1, 2, 3, 4, 5])
        response = _response_doc([1, 2, 3, 4, 5], [10.0, 20.0, 30.0, 40.0, 1.0])
        response = response.set_dependency_value(
            "stimulus_presentation_id", presentation.id, error_if_not_found=False
        )
        app = _app(_session(search=lambda q: [presentation]))
        docs = app.make_1d_tuning(response, "angle", "direction", "sFrequency")
        assert len(docs) == 2
        first = docs[0].document_properties["stimulus_tuningcurve"]
        assert first["independent_variable_value"] == [[0.0], [90.0]]

    def test_a_missing_presentation_document_is_an_error(self):
        response = _response_doc([1], [1.0])
        with pytest.raises(RuntimeError, match="Could not find the stimulus presentation"):
            _app(_session()).make_1d_tuning(response, "angle", "direction", "sFrequency")


class TestFindTuningcurveDocument:
    def _docs(self):
        response = _response_doc([1], [1.0], response_type="F1")
        response.document_properties["stimulus_response"] = {"element_epochid": "epoch1"}
        other = _response_doc([1], [1.0], response_type="mean")
        other.document_properties["stimulus_response"] = {"element_epochid": "epoch1"}
        curve = ndi_document("stimulus_tuningcurve")
        curve = curve.set_dependency_value(
            "stimulus_response_scalar_id", response.id, error_if_not_found=False
        )
        return curve, response, other

    def _session_for(self, curve, response):
        def search(query):
            text = repr(query.search_structure)
            if "stimulus_tuningcurve" in text:
                return [curve]
            return [response]

        return _session(search=search)

    def test_the_response_type_is_filtered_on(self):
        """An element usually has both a mean and an F1 curve per epoch, so
        returning all of them would leave the caller to guess."""
        curve, response, _ = self._docs()
        app = _app(self._session_for(curve, response))
        element = SimpleNamespace(id="element-1")
        assert app.find_tuningcurve_document(element, "epoch1", "F1") == ([curve], [response])
        assert app.find_tuningcurve_document(element, "epoch1", "mean") == ([], [])

    def test_the_epoch_is_filtered_on(self):
        curve, response, _ = self._docs()
        app = _app(self._session_for(curve, response))
        element = SimpleNamespace(id="element-1")
        assert app.find_tuningcurve_document(element, "other-epoch", "F1") == ([], [])

    def test_without_a_session_there_is_nothing_to_find(self):
        found = ndi_app_stimulus_tuning__response().find_tuningcurve_document(
            SimpleNamespace(), "epoch1"
        )
        assert found == ([], [])


# ----------------------------------------------------------------------
# statics
# ----------------------------------------------------------------------
class TestModulatedOrMean:
    def _docs(self, mean_values, modulated_values):
        mean = _response_doc([1, 2], mean_values, response_type="mean")
        modulated = _response_doc([1, 2], modulated_values, response_type="F1")
        return [mean, modulated]

    def test_modulated_wins(self):
        docs = self._docs([1.0, 2.0], [5.0, 6.0])
        b, ratio, mean, modulated, mean_index, modulated_index = (
            ndi_app_stimulus_tuning__response.modulated_or_mean(docs)
        )
        assert b == 1
        assert modulated == pytest.approx(6.0)
        assert mean == pytest.approx(2.0)
        assert ratio == pytest.approx(3.0)
        assert (mean_index, modulated_index) == (0, 1)

    def test_mean_wins(self):
        docs = self._docs([10.0, 20.0], [1.0, 2.0])
        b, ratio, mean, modulated, _, _ = ndi_app_stimulus_tuning__response.modulated_or_mean(docs)
        assert b == 0
        assert mean == pytest.approx(20.0)
        assert modulated == pytest.approx(2.0)
        assert ratio == pytest.approx(0.1)

    def test_only_one_kind_is_no_basis_to_compare(self):
        docs = [_response_doc([1], [1.0], response_type="mean")]
        assert ndi_app_stimulus_tuning__response.modulated_or_mean(docs)[0] == -1

    def test_two_of_a_kind_is_refused(self):
        docs = self._docs([1.0, 2.0], [3.0, 4.0])
        docs.append(_response_doc([1, 2], [5.0, 6.0], response_type="F1"))
        with pytest.raises(ValueError, match="More than one modulated response"):
            ndi_app_stimulus_tuning__response.modulated_or_mean(docs)

    def test_a_document_that_is_not_a_response_is_refused(self):
        with pytest.raises(ValueError, match="stimulus_response_scalar"):
            ndi_app_stimulus_tuning__response.modulated_or_mean([ndi_document("base")])

    def test_a_bare_document_rather_than_a_list_is_refused(self):
        with pytest.raises(TypeError, match="should be a list"):
            ndi_app_stimulus_tuning__response.modulated_or_mean(_response_doc([1], [1.0]))

    def test_the_response_type_names_are_the_matlab_ones(self):
        assert MEAN_RESPONSE_NAMES == ("F0", "mean")
        assert MODULATED_RESPONSE_NAMES == ("F1", "modulated")


class TestVhlabRespStruct:
    def _curve_doc(self):
        doc = ndi_document("stimulus_tuningcurve")
        doc.document_properties["stimulus_tuningcurve"] = {
            "independent_variable_value": [[0.0], [90.0]],
            "individual_responses_real": [[10.0, 12.0], [20.0, 22.0]],
            "individual_responses_imaginary": [[0.0, 0.0], [0.0, 0.0]],
            "control_individual_responses_real": [[1.0, 1.0], [1.0, 1.0]],
            "control_individual_responses_imaginary": [[0.0, 0.0], [0.0, 0.0]],
            "response_mean": [11.0, 21.0],
        }
        return doc

    def test_the_curve_is_four_rows_with_the_control_subtracted(self):
        resp = ndi_app_stimulus_tuning__response.tuningcurvedoc2vhlabrespstruct(self._curve_doc())
        assert resp["curve"].shape == (4, 2)
        assert resp["curve"][0].tolist() == [0.0, 90.0]
        assert resp["curve"][1] == pytest.approx([10.0, 20.0])

    def test_the_blank_response_is_reported_three_ways(self):
        resp = ndi_app_stimulus_tuning__response.tuningcurvedoc2vhlabrespstruct(self._curve_doc())
        assert resp["blankresp"][0] == pytest.approx(1.0)
        assert resp["spont"] == resp["blankresp"]
        assert np.asarray(resp["spontind"]).tolist() == [1.0, 1.0]

    def test_a_multivariate_curve_is_plotted_against_point_number(self):
        doc = self._curve_doc()
        doc.document_properties["stimulus_tuningcurve"]["independent_variable_value"] = [
            [0.0, 1.0],
            [90.0, 1.0],
        ]
        resp = ndi_app_stimulus_tuning__response.tuningcurvedoc2vhlabrespstruct(doc)
        assert resp["curve"][0].tolist() == [1.0, 2.0]


class TestFixCellArrays:
    def test_rows_of_scalars_become_rows_of_one(self):
        """The one case JSON leaves genuinely ambiguous: one repetition per
        point may have been written as bare numbers."""
        doc = ndi_document("stimulus_tuningcurve")
        doc.document_properties["stimulus_tuningcurve"] = {
            "individual_responses_real": [10.0, 20.0],
            "stimulus_presentation_number": [[1], [2]],
        }
        fixed = ndi_app_stimulus_tuning__response.tuningdoc_fixcellarrays_static(doc)
        curve = fixed.document_properties["stimulus_tuningcurve"]
        assert curve["individual_responses_real"] == [[10.0], [20.0]]
        assert curve["stimulus_presentation_number"] == [[1], [2]]


# ----------------------------------------------------------------------
# orchestration
# ----------------------------------------------------------------------
class TestStimulusResponses:
    def test_without_a_session_there_is_nothing_to_compute(self):
        app = ndi_app_stimulus_tuning__response()
        assert app.stimulus_responses(SimpleNamespace(), SimpleNamespace()) == []

    def test_a_presentation_with_no_timing_is_skipped(self):
        doc = _presentation_doc([{"parameters": {}}], [1])
        session = _session(search=lambda q: [doc])
        with patch(DECODER) as decoder:
            decoder.return_value.load_presentation_time.return_value = []
            found = _app(session).stimulus_responses(
                SimpleNamespace(id="stim"), SimpleNamespace(id="element")
            )
        assert found == []

    def test_an_epoch_the_element_cannot_reach_is_skipped_not_raised(self):
        """A stimulator and an electrode that never ran together simply have
        no responses; that is not an error."""
        doc = _presentation_doc([{"parameters": {}}], [1])
        session = _session(search=lambda q: [doc])
        session.syncgraph.time_convert.return_value = (None, None, "no path")
        stimulator = SimpleNamespace(id="stim", session=session)
        with patch(DECODER) as decoder:
            decoder.return_value.load_presentation_time.return_value = _timing([0.0])
            found = _app(session).stimulus_responses(stimulator, SimpleNamespace(id="element"))
        assert found == []
        session.database_add.assert_not_called()

    def test_reset_removes_the_existing_responses_and_their_parameters(self):
        response = _response_doc([1], [1.0])
        response = response.set_dependency_value(
            "stimulus_response_scalar_parameters_id", "param-1", error_if_not_found=False
        )
        parameters = ndi_document("stimulus_response_scalar_parameters_basic")

        def search(query):
            text = repr(query.search_structure)
            if "stimulus_presentation" in text:
                return []
            if "param-1" in text:
                return [parameters]
            return [response]

        session = _session(search=search)
        _app(session).stimulus_responses(
            SimpleNamespace(id="stim"),
            SimpleNamespace(id="element"),
            reset=True,
        )
        removed = [call.args[0] for call in session.database_rm.call_args_list]
        assert [response] in removed
        assert [parameters] in removed


# ----------------------------------------------------------------------
# end to end
# ----------------------------------------------------------------------
class TestTheWholePipeline:
    """A synthetic experiment, from stimulus documents to a tuning curve.

    Three gratings modulated at 2 Hz plus a blank, three repetitions, and a
    spike train generated at a known rate with a known modulation depth. The
    unit tests above check each step; this checks that the steps compose --
    that the control document the first step writes is the one the second
    step pairs by, that the stimulus ids line up with the presentation order,
    and that the numbers surviving all of it are still the ones put in.
    """

    RATES = {1: 20.0, 2: 40.0, 3: 10.0, 4: 2.0}
    DEPTH = {1: 0.9, 2: 0.9, 3: 0.9, 4: 0.0}

    def _experiment(self):
        stimuli = [
            {"parameters": {"angle": 0.0, "tFrequency": 2.0, "isblank": 0}},
            {"parameters": {"angle": 90.0, "tFrequency": 2.0, "isblank": 0}},
            {"parameters": {"angle": 180.0, "tFrequency": 2.0, "isblank": 0}},
            {"parameters": {"isblank": 1}},
        ]
        order = [1, 2, 3, 4] * 3
        onsets = [i * 2.0 for i in range(len(order))]
        presentation = _presentation_doc(stimuli, order, timing=_timing(onsets, duration=1.5))

        rng = np.random.default_rng(0)
        step = 0.0005
        spikes: list[float] = []
        for stimulus, onset in zip(order, onsets, strict=True):
            t = np.arange(0, 1.5, step)
            rate = self.RATES[stimulus] * (1 + self.DEPTH[stimulus] * np.cos(2 * np.pi * 2.0 * t))
            spikes.extend(onset + t[rng.random(t.size) < rate * step])
        return presentation, np.asarray(sorted(spikes))

    def _session_for(self, presentation, store):
        def search(query):
            text = repr(query.search_structure)
            if presentation.id in text:
                return [presentation]
            if "stimulus_response_scalar_parameters_basic" in text:
                return [
                    d
                    for d in store
                    if d.doc_class() == "stimulus_response_scalar_parameters_basic"
                    and _matches_parameters(d, query)
                ]
            return []

        session = _session(search=search)
        session.database_add = MagicMock(side_effect=store.append)
        session.syncgraph.time_convert = MagicMock(
            side_effect=lambda ref, t, out, clock: (t, SimpleNamespace(epoch="epoch1"), "")
        )
        return session

    def _run(self):
        presentation, spikes = self._experiment()
        store: list = []
        session = self._session_for(presentation, store)
        element = SimpleNamespace(
            id="neuron-1",
            type="spikes",
            session=session,
            readtimeseries=lambda epoch, t0, t1: (
                np.ones_like(spikes),
                spikes,
                SimpleNamespace(epoch="epoch1"),
            ),
        )
        stimulator = SimpleNamespace(id="stim-1", session=session)

        app = _app(session)
        _, control_doc = app.control_stimulus(presentation)
        with pytest.warns(UserWarning, match="deprecated form"):
            responses = app.compute_stimulus_response_scalar(
                stimulator, element, presentation, control_doc
            )
        return app, responses, store

    def test_a_stimulus_with_a_temporal_frequency_gets_all_three_responses(self):
        """mean, F1 and F2 -- which needs ndi.fun.stimulustemporalfrequency to
        actually find the frequency. When it silently found none, this
        produced only the mean."""
        _, responses, _ = self._run()
        types = [
            d.document_properties["stimulus_response_scalar"]["response_type"] for d in responses
        ]
        assert types == ["mean", "F1", "F2"]

    def test_the_f0_responses_are_the_rates_that_went_in(self):
        _, responses, _ = self._run()
        curve = self._curve(responses[0])
        assert curve["response_mean"] == pytest.approx([20.0, 40.0, 10.0], rel=0.25)

    def test_the_control_response_is_the_blank_rate(self):
        _, responses, _ = self._run()
        curve = self._curve(responses[0])
        assert curve["control_response_mean"] == pytest.approx([2.0, 2.0, 2.0], abs=1.5)

    def test_the_f1_responses_recover_the_modulation_depth(self):
        """|F1| of a rate R modulated to depth d is about d*R."""
        _, responses, _ = self._run()
        curve = self._curve(responses[1])
        assert curve["response_mean"] == pytest.approx([18.0, 36.0, 9.0], rel=0.35)

    def test_the_three_responses_share_one_parameter_document_per_frequency(self):
        """Responses computed the same way must point at the SAME parameters,
        not at equal copies, or nothing downstream can tell them apart."""
        _, responses, store = self._run()
        parameter_ids = {
            d.dependency_value("stimulus_response_scalar_parameters_id") for d in responses
        }
        assert len(parameter_ids) == 3  # one per frequency, and no duplicates
        stored = [d for d in store if d.doc_class() == "stimulus_response_scalar_parameters_basic"]
        assert len(stored) == 3

    def test_the_vhlab_structure_carries_the_control_subtracted_curve(self):
        app, responses, _ = self._run()
        curve_doc = app.tuning_curve(responses[0], independent_parameter=["angle"])
        resp = ndi_app_stimulus_tuning__response.tuningcurvedoc2vhlabrespstruct(curve_doc)
        assert resp["curve"][0].tolist() == [0.0, 90.0, 180.0]
        assert resp["curve"][1] == pytest.approx([18.0, 38.0, 8.0], rel=0.3)

    def _curve(self, response_doc):
        """The tuning curve of RESPONSE_DOC, aggregated over angle."""
        presentation, _ = self._experiment()
        store: list = []
        session = self._session_for(presentation, store)
        response_doc = response_doc.set_dependency_value(
            "stimulus_presentation_id", presentation.id, error_if_not_found=False
        )
        doc = _app(session).tuning_curve(response_doc, independent_parameter=["angle"])
        return doc.document_properties["stimulus_tuningcurve"]
