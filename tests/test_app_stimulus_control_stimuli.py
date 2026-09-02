"""Tests for control-stimulus labeling in ndi.app.stimulus.tuning_response.

MATLAB counterpart: +ndi/+app/+stimulus/tuning_response.m
(``control_stimulus``, ``label_control_stimuli``)

A tuning measurement is a comparison against the blank trials, so which
blank trial each stimulus trial is compared against decides every number
that comes out of it. Picking the wrong one raises nothing -- it shifts the
whole curve by however much the preparation drifted between the two.

So these tests check the ASSIGNMENT, trial by trial, in both regimes: the
control trial of the same repetition when the presentation order is
regular, and the nearest blank in time when it is not. They also pin the
two answers that are deliberately not errors -- a set with no blank at all,
and a final incomplete repetition -- because turning either into an
exception would refuse to label perfectly ordinary recordings.
"""

from __future__ import annotations

import tempfile

import pytest

from ndi.app.stimulus.tuning_response import (
    _control_stimulus_indexes,
    _match_trials_to_controls,
    ndi_app_stimulus_tuning__response,
)


def stimuli(*flags):
    """Stimuli in presentation-id order; each flag is that stimulus's isblank."""
    return [{"parameters": {"isblank": flag, "angle": 10 * i}} for i, flag in enumerate(flags)]


def onsets(*times):
    return [{"onset": t} for t in times]


class TestControlStimulusIndexes:
    def test_the_blank_stimulus_is_found_by_its_isblank_parameter(self):
        assert _control_stimulus_indexes(stimuli(0, 0, 1), "pseudorandom", "isblank", 1) == [3]

    def test_indexes_are_one_based_to_match_the_presentation_order(self):
        """presentation_order holds 1-based stimulus ids; a 0-based answer
        here would compare every trial against its neighbour."""
        assert _control_stimulus_indexes(stimuli(1, 0), "pseudorandom", "isblank", 1) == [1]

    def test_no_blank_stimulus_is_found_when_none_is_marked(self):
        assert _control_stimulus_indexes(stimuli(0, 0), "pseudorandom", "isblank", 1) == []

    def test_hasfield_matches_on_presence_rather_than_value(self):
        entries = [{"parameters": {"angle": 0}}, {"parameters": {"isblank": 0, "angle": 90}}]
        assert _control_stimulus_indexes(entries, "hasfield", "isblank", 1) == [2]

    def test_a_stimulus_that_cannot_be_searched_is_not_a_control(self):
        entries = [{"parameters": "not a dict"}, {"parameters": {"isblank": 1}}]
        assert _control_stimulus_indexes(entries, "pseudorandom", "isblank", 1) == [2]


class TestMatchTrialsToControls:
    def test_a_regular_order_uses_the_control_of_the_same_repetition(self):
        """The whole point: a drifting preparation makes a distant blank the
        wrong baseline, so each repetition is compared against its own."""
        import numpy as np

        stimids = np.array([1, 2, 1, 2], dtype=float)  # two reps of (grating, blank)
        assert _match_trials_to_controls(stimids, 2, 2, onsets(1, 2, 3, 4)) == [
            2.0,
            2.0,
            4.0,
            4.0,
        ]

    def test_an_incomplete_final_repetition_reuses_the_previous_control(self):
        """A run stopped mid-repetition is ordinary; refusing to label it,
        or labeling it NaN, would throw away the trials that did complete."""
        import numpy as np

        stimids = np.array([1, 2, 1], dtype=float)
        result = _match_trials_to_controls(stimids, 2, 2, onsets(1, 2, 3))
        assert result[:2] == [2.0, 2.0]
        assert result[2] == 2.0

    def test_an_irregular_order_uses_the_blank_closest_in_time(self):
        import numpy as np

        # blanks at trials 2 and 5; trial 4 sits nearer the later one
        stimids = np.array([1, 2, 1, 1, 2], dtype=float)
        result = _match_trials_to_controls(stimids, 2, 2, onsets(0, 1, 2, 9, 10))
        assert result[0] == 2.0
        assert result[3] == 5.0

    def test_a_set_with_no_blank_trial_is_all_nan(self):
        """Not an error: a run with no blank is a legitimate experiment that
        simply cannot be baselined."""
        import math

        import numpy as np

        result = _match_trials_to_controls(np.array([1, 1], dtype=float), 2, 2, onsets(1, 2))
        assert all(math.isnan(v) for v in result)

    def test_missing_onsets_give_nan_rather_than_a_guessed_neighbour(self):
        import math

        import numpy as np

        stimids = np.array([1, 2, 1, 1, 2], dtype=float)
        result = _match_trials_to_controls(stimids, 2, 2, onsets(0, 1))
        assert all(math.isnan(v) for v in result)


def real_session_with_presentation(order, stim_flags):
    """A real session holding one stimulus_presentation with ORDER and STIM_FLAGS."""
    import numpy as np

    from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder
    from ndi.session.dir import ndi_session_dir

    session = ndi_session_dir("testref", tempfile.mkdtemp())
    subject = session.newdocument(
        "subject",
        **{"subject.local_identifier": "mock@nosuchlab.org", "subject.description": ""},
    )
    session.database_add(subject)
    element = session.newdocument(
        "element",
        **{
            "element.ndi_element_class": "ndi.element",
            "element.name": "vhvis_spike2",
            "element.reference": 1,
            "element.type": "stimulator",
            "element.direct": 1,
        },
    )
    element = element.set_dependency_value("subject_id", subject.id)
    session.database_add(element)

    class Stim:
        def __init__(self, element_id):
            self.id = element_id

        def elementstring(self):
            return "vhvis_spike2 | 1"

        def epochtable(self):
            return [{"epoch_id": "e1", "t0_t1": [[0.0, 10.0]]}], "hash"

        def readtimeseriesepoch(self, epoch, t0, t1):  # noqa: ARG002
            n = len(order)
            data = {
                "stimid": np.array(order),
                "parameters": [
                    {"isblank": flag, "angle": 10 * i} for i, flag in enumerate(stim_flags)
                ],
            }
            t = {
                "stimon": np.arange(1.0, n + 1.0),
                "stimoff": np.arange(1.5, n + 1.5),
                "stimopenclose": np.column_stack(
                    (np.arange(0.9, n + 0.9), np.arange(1.6, n + 1.6))
                ),
                "stimevents": [],
            }
            return data, t, _TimeRef()

    stim = Stim(element.id)
    ndi_app_stimulus_decoder(session).parse_stimuli(stim)
    return session, stim


class _TimeRef:
    class clocktype:  # noqa: N801 - stands in for the enum
        def __str__(self):
            return "dev_local_time"

    clocktype = clocktype()


class TestLabelControlStimuli:
    def test_no_session_is_refused(self):
        with pytest.raises(RuntimeError, match="No session"):
            ndi_app_stimulus_tuning__response().label_control_stimuli(object())

    def test_one_document_per_presentation_is_written(self):
        session, stim = real_session_with_presentation([1, 2, 1, 2], [0, 1])

        cs_docs = ndi_app_stimulus_tuning__response(session).label_control_stimuli(stim)

        assert len(cs_docs) == 1

    def test_the_document_holds_one_control_trial_per_trial(self):
        session, stim = real_session_with_presentation([1, 2, 1, 2], [0, 1])

        cs_docs = ndi_app_stimulus_tuning__response(session).label_control_stimuli(stim)

        ids = cs_docs[0].document_properties["control_stimulus_ids"]["control_stimulus_ids"]
        assert ids == [2.0, 2.0, 4.0, 4.0]

    def test_it_records_how_the_control_was_chosen(self):
        """The method is part of the result: a later reader cannot tell a
        pseudorandom assignment from a nearest-in-time one otherwise."""
        session, stim = real_session_with_presentation([1, 2], [0, 1])

        cs_docs = ndi_app_stimulus_tuning__response(session).label_control_stimuli(stim)

        method = cs_docs[0].document_properties["control_stimulus_ids"][
            "control_stimulus_id_method"
        ]
        assert method["method"] == "pseudorandom"
        assert method["controlid"] == "isblank"

    def test_it_depends_on_the_presentation_it_labeled(self):
        session, stim = real_session_with_presentation([1, 2], [0, 1])
        app = ndi_app_stimulus_tuning__response(session)

        cs_docs = app.label_control_stimuli(stim)

        from ndi.query import ndi_query

        pres = session.database_search(ndi_query("").isa("stimulus_presentation"))
        assert cs_docs[0].dependency_value("stimulus_presentation_id") == pres[0].id

    def test_the_documents_are_findable_in_the_database_afterwards(self):
        """The GUI reads them back to draw its "*c" markers, so writing them
        without adding them would look like the labeling never happened."""
        from ndi.query import ndi_query

        session, stim = real_session_with_presentation([1, 2], [0, 1])
        ndi_app_stimulus_tuning__response(session).label_control_stimuli(stim)

        found = session.database_search(ndi_query("").isa("control_stimulus_ids"))
        assert len(found) == 1

    def test_an_element_with_no_presentations_labels_nothing(self):
        from ndi.session.dir import ndi_session_dir

        session = ndi_session_dir("testref", tempfile.mkdtemp())
        app = ndi_app_stimulus_tuning__response(session)

        assert app.label_control_stimuli(_ElementWithId("nothing")) == []

    def test_reset_replaces_the_documents_rather_than_adding_more(self):
        from ndi.query import ndi_query

        session, stim = real_session_with_presentation([1, 2], [0, 1])
        app = ndi_app_stimulus_tuning__response(session)
        app.label_control_stimuli(stim)

        app.label_control_stimuli(stim, True)

        found = session.database_search(ndi_query("").isa("control_stimulus_ids"))
        assert len(found) == 1

    def test_an_unknown_method_is_refused_by_name(self):
        session, stim = real_session_with_presentation([1, 2], [0, 1])
        app = ndi_app_stimulus_tuning__response(session)

        with pytest.raises(ValueError, match="Unknown control_stim_method"):
            app.label_control_stimuli(stim, control_stim_method="telepathy")

    def test_two_control_stimuli_are_refused_rather_than_guessed(self):
        """Which of them a trial belongs to is genuinely undecidable, so
        MATLAB errors and so does this."""
        session, stim = real_session_with_presentation([1, 2, 3], [0, 1, 1])
        app = ndi_app_stimulus_tuning__response(session)

        with pytest.raises(ValueError, match="more than one control stimulus"):
            app.label_control_stimuli(stim)


class _ElementWithId:
    def __init__(self, element_id):
        self.id = element_id
