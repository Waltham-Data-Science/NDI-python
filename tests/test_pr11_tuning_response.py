"""
PR11 part 2, item 2: tests for the ported compute methods of
``ndi.app.stimulus.tuning_response``.

The numerical helpers (F0 mean / F1 Fourier amplitude, control-stimulus
indexing, repetition labeling) are exercised against SYNTHETIC data with
hand-computed expected values. The higher-level methods are exercised with a
mocked session that produces REAL ``ndi_document`` objects, mirroring
tests/matlab_tests/test_app.py.

Methods that depend on the unported
``ndi.app.stimulus.decoder.load_presentation_time`` stub (which returns
``None``) are verified to raise ``NotImplementedError`` with the documented
BLOCKER message.

Run single-process (memory-safety):
    PYTHONPATH=src:../NDR-python/src python3 -m pytest \
        -p no:xdist -p no:cacheprovider tests/test_pr11_tuning_response.py
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ndi.app.stimulus.tuning_response import (
    _fieldsearch,
    _findcontrolstimulus,
    _fouriercoeffs_tf2,
    _mean_mag,
    _stimids2reps,
    _stimulus_response_scalar,
    _unique_rows,
    ndi_app_stimulus_tuning__response,
)
from ndi.document import ndi_document

# ===========================================================================
# F0 / F1 Fourier math (vlt.math.fouriercoeffs_tf2 port)
# ===========================================================================


class TestFourierCoeffs:
    """fouriercoeffs_tf2: F0 == mean, F1 == (2/N)*sum(resp*exp(-i 2pi f k/fs))."""

    def test_f0_is_mean(self):
        sig = np.array([1.0, 2.0, 3.0, 4.0])
        assert _fouriercoeffs_tf2(sig, 0, 4.0) == pytest.approx(2.5)

    def test_f0_constant_offset(self):
        fs = 100.0
        t = np.arange(0, 1.0, 1 / fs)
        sig = 7.0 + 3.0 * np.cos(2 * np.pi * 5.0 * t)
        # mean over an integer number of cycles -> the DC offset
        assert _fouriercoeffs_tf2(sig, 0, fs) == pytest.approx(7.0, abs=1e-9)

    def test_f1_amplitude_of_cosine(self):
        # A pure cosine of amplitude A at frequency f over an integer number
        # of cycles has |F1| == A under the (2/N)*sum convention.
        fs = 100.0
        t = np.arange(0, 1.0, 1 / fs)  # 100 samples, 1 s
        A, f = 3.0, 5.0
        sig = A * np.cos(2 * np.pi * f * t)
        f1 = _fouriercoeffs_tf2(sig, f, fs)
        assert abs(f1) == pytest.approx(A, abs=1e-9)

    def test_f1_empty_window_is_zero(self):
        assert _fouriercoeffs_tf2(np.array([]), 5.0, 100.0) == 0.0 + 0.0j

    def test_f0_empty_window_is_nan(self):
        assert np.isnan(_fouriercoeffs_tf2(np.array([]), 0, 100.0))

    def test_index_convention_is_one_based(self):
        # Mirror MATLAB exactly: expvec uses k = 1..N (not 0..N-1).
        fs = 8.0
        f = 1.0
        resp = np.array([1.0, 0.0, -1.0, 0.0, 1.0, 0.0, -1.0, 0.0])
        n = resp.size
        k = np.arange(1, n + 1)
        expected = (2.0 / n) * np.dot(np.exp(-k * 2j * np.pi * f / fs), resp)
        assert _fouriercoeffs_tf2(resp, f, fs) == pytest.approx(expected)


# ===========================================================================
# stimids2reps / findcontrolstimulus (vlt.neuro.stimulus ports)
# ===========================================================================


class TestStimidsReps:
    def test_regular_sequence(self):
        reps, isreg = _stimids2reps(np.array([1, 2, 3, 1, 2, 3]), 3)
        assert reps.tolist() == [1, 1, 1, 2, 2, 2]
        assert isreg is True

    def test_regular_shuffled(self):
        reps, isreg = _stimids2reps(np.array([2, 1, 3, 3, 1, 2]), 3)
        assert reps.tolist() == [1, 1, 1, 2, 2, 2]
        assert isreg is True

    def test_irregular_first_block(self):
        _, isreg = _stimids2reps(np.array([1, 1, 2, 3, 2, 3]), 3)
        assert isreg is False

    def test_incomplete_last_rep_still_regular(self):
        _, isreg = _stimids2reps(np.array([1, 2, 3, 1, 2]), 3)
        assert isreg is True


class TestFindControlStimulus:
    def test_regular_matches_matlab_docstring(self):
        # The exact example from findcontrolstimulus.m.
        stimid = np.array([1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3])
        cs = _findcontrolstimulus(stimid, 3)
        assert cs.tolist() == [3, 3, 3, 6, 6, 6, 9, 9, 9, 12, 12, 12, 15, 15, 15]

    def test_empty_control_returns_empty(self):
        cs = _findcontrolstimulus(np.array([1, 2, 3]), [])
        assert cs.size == 0

    def test_irregular_closest(self):
        # Control id 2 is irregular; the closest control index (1-based) wins.
        stimid = np.array([2, 1, 1, 2, 1])
        cs = _findcontrolstimulus(stimid, 2)
        # control positions (1-based): 1 and 4.
        # nearest control for each position 1..5:
        #   pos1->1, pos2->1, pos3->4 (dist 1 < dist 2), pos4->4, pos5->4
        assert cs.tolist() == [1, 1, 4, 4, 4]


# ===========================================================================
# _stimulus_response_scalar — the full F0/F1 + control-subtraction pipeline
# ===========================================================================


class TestStimulusResponseScalar:
    """Synthetic deterministic signal with known mean + sinusoidal modulation."""

    def _build(self):
        # Two stimulus windows + 1 control window, sampled at 100 Hz.
        fs = 100.0
        # window 0: t in [0,1), DC=10 + 2 Hz cosine amplitude 4 -> stim 1
        # window 1: t in [1,2), DC=20 + 2 Hz cosine amplitude 6 -> stim 2
        # window 2: t in [2,3), DC=5  (blank control)          -> stim 3
        t = np.arange(0, 3.0, 1 / fs)
        sig = np.empty_like(t)
        w0 = (t >= 0) & (t < 1)
        w1 = (t >= 1) & (t < 2)
        w2 = (t >= 2) & (t < 3)
        sig[w0] = 10 + 4 * np.cos(2 * np.pi * 2.0 * (t[w0] - 0))
        sig[w1] = 20 + 6 * np.cos(2 * np.pi * 2.0 * (t[w1] - 1))
        sig[w2] = 5.0
        # onsets/offsets in the same time base as timestamps.
        soi = np.array(
            [
                [0.0, 0.99, 1],
                [1.0, 1.99, 2],
                [2.0, 2.99, 3],
            ]
        )
        return sig, t, soi

    def test_f0_mean_with_control_subtraction_inputs(self):
        sig, t, soi = self._build()
        out = _stimulus_response_scalar(sig, t, soi, control_stimid=[3], freq_response=0)
        # F0 of each window is ~ its DC offset (mean over ~full cycles).
        resp = np.real(out["response"])
        assert resp[0] == pytest.approx(10.0, abs=0.2)
        assert resp[1] == pytest.approx(20.0, abs=0.2)
        assert resp[2] == pytest.approx(5.0, abs=1e-9)
        # control response equals the blank window mean for all stimuli.
        ctl = np.real(out["control_response"])
        assert ctl[0] == pytest.approx(5.0, abs=1e-9)
        assert ctl[1] == pytest.approx(5.0, abs=1e-9)

    def test_f1_amplitude_at_temporal_frequency(self):
        sig, t, soi = self._build()
        # freq_response per stimulus: window 0 & 1 are 2 Hz; window 2 is blank.
        freq_vec = np.array([2.0, 2.0, 0.0])
        out = _stimulus_response_scalar(sig, t, soi, control_stimid=[3], freq_response=freq_vec)
        amp0 = abs(out["response"][0])
        amp1 = abs(out["response"][1])
        # |F1| recovers the cosine amplitude of each window.
        assert amp0 == pytest.approx(4.0, abs=0.2)
        assert amp1 == pytest.approx(6.0, abs=0.2)

    def test_controlstimnumber_regular(self):
        sig, t, soi = self._build()
        out = _stimulus_response_scalar(sig, t, soi, control_stimid=[3], freq_response=0)
        # only one repetition, control is stim 3 at index 3 (1-based) for all.
        assert out["controlstimnumber"].tolist() == [3, 3, 3]


# ===========================================================================
# fieldsearch / unique_rows / mean_mag helpers
# ===========================================================================


class TestSmallHelpers:
    def test_fieldsearch_hasfield(self):
        assert _fieldsearch({"angle": 30}, [{"field": "angle", "operation": "hasfield"}])
        assert not _fieldsearch({"contrast": 1}, [{"field": "angle", "operation": "hasfield"}])

    def test_fieldsearch_exact_number(self):
        cons = [{"field": "isblank", "operation": "exact_number", "param1": 1}]
        assert _fieldsearch({"isblank": 1}, cons)
        assert not _fieldsearch({"isblank": 0}, cons)
        assert not _fieldsearch({"contrast": 1}, cons)

    def test_fieldsearch_unsupported_raises(self):
        with pytest.raises(ValueError):
            _fieldsearch({"a": 1}, [{"field": "a", "operation": "regexp"}])

    def test_unique_rows_sorted(self):
        vals = np.array([[30.0], [0.0], [30.0], [90.0]])
        ur = _unique_rows(vals)
        assert ur.ravel().tolist() == [0.0, 30.0, 90.0]

    def test_mean_mag_real(self):
        assert _mean_mag(np.array([2.0, 4.0])) == pytest.approx(3.0)

    def test_mean_mag_complex(self):
        # complex mean -> magnitude
        v = np.array([3 + 4j, 3 + 4j])
        assert _mean_mag(v) == pytest.approx(5.0)


# ===========================================================================
# control_stimulus / label_control_stimuli (regular path is fully grounded)
# ===========================================================================


def _make_session():
    session = MagicMock()
    session.id.return_value = "sess-1"
    session.database_add = MagicMock()
    session.database_search = MagicMock(return_value=[])
    session.database_rm = MagicMock()
    return session


def _make_stim_presentation_doc(stimuli, presentation_order):
    doc = ndi_document("stimulus/stimulus_presentation")
    doc.document_properties["stimulus_presentation"]["stimuli"] = stimuli
    doc.document_properties["stimulus_presentation"]["presentation_order"] = presentation_order
    return doc


class TestControlStimulus:
    def test_pseudorandom_regular(self):
        # 3 stimuli, stim 3 is blank (isblank=1), 2 regular repetitions.
        stimuli = [
            {"parameters": {"angle": 0, "isblank": 0}},
            {"parameters": {"angle": 90, "isblank": 0}},
            {"parameters": {"isblank": 1}},
        ]
        order = [1, 2, 3, 1, 2, 3]
        stim_doc = _make_stim_presentation_doc(stimuli, order)
        session = _make_session()
        app = ndi_app_stimulus_tuning__response(session=session)

        cs_ids, cs_doc = app.control_stimulus(stim_doc)
        # both reps map to their own blank (index 3 then 6, 1-based).
        assert cs_ids == [3.0, 3.0, 3.0, 6.0, 6.0, 6.0]
        assert isinstance(cs_doc, ndi_document)
        assert cs_doc.doc_class() == "control_stimulus_ids"
        # dependency + database add happened
        assert cs_doc.dependency_value("stimulus_presentation_id") == stim_doc.id
        session.database_add.assert_called_once()

    def test_no_control_gives_nan(self):
        stimuli = [
            {"parameters": {"angle": 0, "isblank": 0}},
            {"parameters": {"angle": 90, "isblank": 0}},
        ]
        order = [1, 2, 1, 2]
        stim_doc = _make_stim_presentation_doc(stimuli, order)
        app = ndi_app_stimulus_tuning__response(session=_make_session())
        cs_ids, _ = app.control_stimulus(stim_doc)
        assert all(np.isnan(x) for x in cs_ids)

    def test_more_than_one_control_raises(self):
        stimuli = [
            {"parameters": {"isblank": 1}},
            {"parameters": {"isblank": 1}},
        ]
        order = [1, 2]
        stim_doc = _make_stim_presentation_doc(stimuli, order)
        app = ndi_app_stimulus_tuning__response(session=_make_session())
        with pytest.raises(ValueError, match="more than one control"):
            app.control_stimulus(stim_doc)

    def test_unknown_method_raises(self):
        stim_doc = _make_stim_presentation_doc([], [])
        app = ndi_app_stimulus_tuning__response(session=_make_session())
        with pytest.raises(ValueError, match="Unknown control stimulus method"):
            app.control_stimulus(stim_doc, control_stim_method="bogus")

    def test_hasfield_method(self):
        stimuli = [
            {"parameters": {"angle": 0}},
            {"parameters": {"angle": 90}},
            {"parameters": {"angle": 0, "isblank": 1}},
        ]
        order = [1, 2, 3, 1, 2, 3]
        stim_doc = _make_stim_presentation_doc(stimuli, order)
        app = ndi_app_stimulus_tuning__response(session=_make_session())
        cs_ids, _ = app.control_stimulus(stim_doc, control_stim_method="hasfield")
        assert cs_ids == [3.0, 3.0, 3.0, 6.0, 6.0, 6.0]


class TestLabelControlStimuli:
    def test_no_session_returns_empty(self):
        app = ndi_app_stimulus_tuning__response()
        assert app.label_control_stimuli(SimpleNamespace(id="elem1")) == []

    def test_labels_each_presentation(self):
        stimuli = [
            {"parameters": {"angle": 0, "isblank": 0}},
            {"parameters": {"isblank": 1}},
        ]
        order = [1, 2, 1, 2]
        stim_doc = _make_stim_presentation_doc(stimuli, order)
        session = _make_session()
        session.database_search = MagicMock(return_value=[stim_doc])
        app = ndi_app_stimulus_tuning__response(session=session)

        cs_docs = app.label_control_stimuli(SimpleNamespace(id="stim-elem"))
        assert len(cs_docs) == 1
        assert cs_docs[0].doc_class() == "control_stimulus_ids"


# ===========================================================================
# tuning_curve — aggregation of a real stimulus_response_scalar doc
# ===========================================================================


class TestTuningCurve:
    def _make_response_doc_and_presentation(self):
        # 2 stimuli (angle 0, angle 90), 2 reps each -> presentation_order
        # [1,2,1,2]. responses keyed by stimid.
        stimuli = [
            {"parameters": {"angle": 0.0}},
            {"parameters": {"angle": 90.0}},
        ]
        stim_pres = _make_stim_presentation_doc(stimuli, [1, 2, 1, 2])

        resp_doc = ndi_document("stimulus/stimulus_response_scalar")
        resp_doc.document_properties["stimulus_response_scalar"]["response_type"] = "mean"
        resp_doc.document_properties["stimulus_response_scalar"]["responses"] = {
            "stimid": [1, 2, 1, 2],
            "response_real": [10.0, 20.0, 12.0, 22.0],
            "response_imaginary": [0.0, 0.0, 0.0, 0.0],
            "control_response_real": [1.0, 1.0, 1.0, 1.0],
            "control_response_imaginary": [0.0, 0.0, 0.0, 0.0],
        }
        resp_doc = resp_doc.set_dependency_value(
            "stimulus_presentation_id", stim_pres.id, error_if_not_found=False
        )
        resp_doc = resp_doc.set_dependency_value("element_id", "elem-xyz", error_if_not_found=False)
        return resp_doc, stim_pres

    def test_requires_independent_parameter(self):
        app = ndi_app_stimulus_tuning__response(session=_make_session())
        resp_doc, _ = self._make_response_doc_and_presentation()
        with pytest.raises(ValueError, match="independent_parameter is empty"):
            app.tuning_curve(resp_doc, independent_parameter=[])

    def test_label_param_dimension_mismatch(self):
        app = ndi_app_stimulus_tuning__response(session=_make_session())
        resp_doc, _ = self._make_response_doc_and_presentation()
        with pytest.raises(ValueError, match="Mismatch"):
            app.tuning_curve(
                resp_doc,
                independent_parameter=["angle"],
                independent_label=["a", "b"],
            )

    def test_builds_tuning_curve(self):
        resp_doc, stim_pres = self._make_response_doc_and_presentation()
        session = _make_session()
        session.database_search = MagicMock(return_value=[stim_pres])
        app = ndi_app_stimulus_tuning__response(session=session)

        tc_doc = app.tuning_curve(
            resp_doc,
            independent_parameter=["angle"],
            independent_label=["angle"],
        )
        assert isinstance(tc_doc, ndi_document)
        assert tc_doc.doc_class() == "stimulus_tuningcurve"
        tc = tc_doc.document_properties["stimulus_tuningcurve"]

        # two unique angles, sorted: 0, 90
        assert tc["independent_variable_value"] == [[0.0], [90.0]]
        # angle 0 -> responses 10, 12 -> mean 11; angle 90 -> 20, 22 -> mean 21
        assert tc["response_mean"][0] == pytest.approx(11.0)
        assert tc["response_mean"][1] == pytest.approx(21.0)
        # control mean is 1.0 for both
        assert tc["control_response_mean"][0] == pytest.approx(1.0)
        # individual responses recorded
        assert sorted(tc["individual_responses_real"][0]) == [10.0, 12.0]
        # stderr of [10,12] = std([10,12],ddof=1)/sqrt(2) = sqrt(2)/sqrt(2)=1
        assert tc["response_stderr"][0] == pytest.approx(1.0)
        # dependencies + add
        assert tc_doc.dependency_value("stimulus_response_scalar_id") == resp_doc.id
        assert tc_doc.dependency_value("element_id") == "elem-xyz"
        session.database_add.assert_called_once()

    def test_non_matching_parameter_gives_zero_point_curve(self):
        # No stimulus carries the requested parameter, but the presentation is
        # non-empty -> MATLAB (tuning_response.m:432) only short-circuits when
        # there are zero stimuli. Here it builds a zero-point tuning doc.
        stimuli = [{"parameters": {"contrast": 1.0}}]
        stim_pres = _make_stim_presentation_doc(stimuli, [1])
        resp_doc = ndi_document("stimulus/stimulus_response_scalar")
        resp_doc.document_properties["stimulus_response_scalar"]["responses"] = {
            "stimid": [1],
            "response_real": [5.0],
            "response_imaginary": [0.0],
            "control_response_real": [0.0],
            "control_response_imaginary": [0.0],
        }
        resp_doc = resp_doc.set_dependency_value(
            "stimulus_presentation_id", stim_pres.id, error_if_not_found=False
        )
        session = _make_session()
        session.database_search = MagicMock(return_value=[stim_pres])
        app = ndi_app_stimulus_tuning__response(session=session)
        result = app.tuning_curve(
            resp_doc, independent_parameter=["angle"], independent_label=["angle"]
        )
        assert isinstance(result, ndi_document)
        tc = result.document_properties["stimulus_tuningcurve"]
        assert tc["independent_variable_value"] == []
        assert tc["response_mean"] == []

    def test_zero_stimuli_warns_and_returns_none(self):
        # Truly empty presentation (zero stimuli) -> MATLAB isempty(isincluded)
        # branch: warn + return None.
        stim_pres = _make_stim_presentation_doc([], [])
        resp_doc = ndi_document("stimulus/stimulus_response_scalar")
        resp_doc.document_properties["stimulus_response_scalar"]["responses"] = {
            "stimid": [],
            "response_real": [],
            "response_imaginary": [],
            "control_response_real": [],
            "control_response_imaginary": [],
        }
        resp_doc = resp_doc.set_dependency_value(
            "stimulus_presentation_id", stim_pres.id, error_if_not_found=False
        )
        session = _make_session()
        session.database_search = MagicMock(return_value=[stim_pres])
        app = ndi_app_stimulus_tuning__response(session=session)
        with pytest.warns(UserWarning, match="empty tuning curve"):
            result = app.tuning_curve(
                resp_doc, independent_parameter=["angle"], independent_label=["angle"]
            )
        assert result is None


# ===========================================================================
# BLOCKER paths: compute_stimulus_response_scalar / stimulus_responses
# ===========================================================================


class TestComputeBlocker:
    """When no timing is available (no inline presentation_time and no readable
    presentation_time.bin), compute raises a clear ValueError."""

    def test_compute_raises_blocker_on_missing_timing(self):
        stimuli = [{"parameters": {"angle": 0}}]
        stim_doc = _make_stim_presentation_doc(stimuli, [1])
        # no inline timing and the mock session has no readable binary -> None
        stim_doc.document_properties["stimulus_presentation"]["presentation_time"] = []
        session = _make_session()
        app = ndi_app_stimulus_tuning__response(session=session)

        stim_obj = SimpleNamespace(id="stim-elem")
        ts_obj = SimpleNamespace(id="ts-elem")

        with pytest.raises(ValueError, match="presentation_time"):
            app.compute_stimulus_response_scalar(stim_obj, ts_obj, stim_doc, None, freq_response=0)

    def test_compute_no_session_returns_empty(self):
        app = ndi_app_stimulus_tuning__response()
        stim_doc = _make_stim_presentation_doc([{"parameters": {}}], [1])
        result = app.compute_stimulus_response_scalar(
            SimpleNamespace(id="s"), SimpleNamespace(id="t"), stim_doc, None
        )
        assert result == []

    def test_stimulus_responses_no_session_returns_empty(self):
        app = ndi_app_stimulus_tuning__response()
        result = app.stimulus_responses(SimpleNamespace(id="stim"), SimpleNamespace(id="ts"))
        assert result == []

    def test_stimulus_responses_propagates_blocker(self):
        # With a session that returns a stim doc + control doc, the
        # orchestration reaches compute and hits the timing BLOCKER.
        stimuli = [{"parameters": {"angle": 0}}]
        stim_doc = _make_stim_presentation_doc(stimuli, [1])
        # binary-only document: no inline timing -> compute hits the BLOCKER
        stim_doc.document_properties["stimulus_presentation"]["presentation_time"] = []
        control_doc = ndi_document("stimulus/control_stimulus_ids")

        session = _make_session()

        def search(_q):
            # First two calls (stim/resp lookups) and the control lookup:
            # return the stim doc when an isa(stimulus_presentation) is in play,
            # the control doc otherwise. Simplest: return both lists by call.
            return search.queue.pop(0) if search.queue else []

        search.queue = [
            [stim_doc],  # doc_stim
            [],  # doc_resp
            [control_doc],  # control_stim_docs for stim_doc
        ]
        session.database_search = MagicMock(side_effect=search)
        app = ndi_app_stimulus_tuning__response(session=session)

        with pytest.raises(ValueError, match="presentation_time"):
            app.stimulus_responses(SimpleNamespace(id="stim"), SimpleNamespace(id="ts"))


# ===========================================================================
# basic API parity
# ===========================================================================


class TestApiParity:
    def test_repr(self):
        assert "ndi_app_stimulus_tuning__response" in repr(ndi_app_stimulus_tuning__response())

    def test_find_tuningcurve_no_session(self):
        app = ndi_app_stimulus_tuning__response()
        tc, srs = app.find_tuningcurve_document(SimpleNamespace(id="e"), "epoch1")
        assert tc == []
        assert srs == []

    def test_make_1d_tuning_requires_session(self):
        app = ndi_app_stimulus_tuning__response()
        with pytest.raises(RuntimeError, match="requires a session"):
            app.make_1d_tuning(
                ndi_document("stimulus/stimulus_response_scalar"),
                "angle",
                "angle",
                "spatial_frequency",
            )


# ===========================================================================
# decoder.load_presentation_time — inline form now supported (PR11 pt2)
# ===========================================================================


class TestLoadPresentationTimeInline:
    """Both presentation_time forms are supported: the deprecated/inline field
    and the current binary 'presentation_time.bin' (read via database_openbinarydoc
    + read_presentation_time_structure)."""

    def test_inline_presentation_time_is_returned(self):
        from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder

        pt = [
            {"onset": 1.0, "offset": 2.0, "clocktype": "dev_local_time"},
            {"onset": 3.0, "offset": 4.0, "clocktype": "dev_local_time"},
        ]
        doc = SimpleNamespace(
            document_properties={"stimulus_presentation": {"presentation_time": pt}}
        )
        dec = ndi_app_stimulus_decoder(MagicMock())
        out = dec.load_presentation_time(doc)
        assert out == pt
        # a copy of each entry, not the same dict objects
        assert out is not pt

    def test_binary_presentation_time_is_read(self, tmp_path):
        # no inline 'presentation_time' -> timing is read from presentation_time.bin
        # via database_openbinarydoc (here a mock session opens a real temp file).
        import numpy as np

        from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder
        from ndi.database_fun import write_presentation_time_structure

        fn = tmp_path / "presentation_time.bin"
        entries = [
            {
                "clocktype": "dev_local_time",
                "stimopen": 0.0,
                "onset": 1.0,
                "offset": 2.0,
                "stimclose": 3.0,
                "stimevents": np.array([[1.1, 1.0], [1.5, 2.0]]),
            }
        ]
        write_presentation_time_structure(str(fn), entries)

        doc = SimpleNamespace(document_properties={"stimulus_presentation": {}})
        sess = MagicMock()
        sess.database_openbinarydoc.return_value = open(str(fn), "rb")  # noqa: SIM115
        dec = ndi_app_stimulus_decoder(sess)

        out = dec.load_presentation_time(doc)
        assert out is not None and len(out) == 1
        assert out[0]["onset"] == 1.0 and out[0]["clocktype"] == "dev_local_time"
        np.testing.assert_array_almost_equal(out[0]["stimevents"], [[1.1, 1.0], [1.5, 2.0]])

    def test_binary_unavailable_returns_none(self):
        from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder

        # no inline form and no readable binary file -> None (blocker)
        doc = SimpleNamespace(
            document_properties={"stimulus_presentation": {"presentation_order": [1, 2]}}
        )
        sess = MagicMock()
        sess.database_openbinarydoc.side_effect = FileNotFoundError("no presentation_time.bin")
        dec = ndi_app_stimulus_decoder(sess)
        assert dec.load_presentation_time(doc) is None
