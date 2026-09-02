"""Tests for ndi.app.stimulus.decoder.parse_stimuli.

MATLAB counterpart: +ndi/+app/+stimulus/decoder.m

The stimulus_presentation document is the record of what was shown and
when, and everything downstream of a stimulus experiment reads it. Two
things about it fail silently and are therefore pinned hardest here.

The first is WHICH EPOCH a document belongs to: a document keyed to the
wrong epoch lines a recording up against the wrong stimuli, and nothing
raises -- the tuning curves simply come out flat.

The second is THE PRESENTATION TIMES SURVIVING THE WRITE. They go to a temp
file that the database copies in during ``database_add``; delete that file
first and the document is stored with a ``presentation_time.bin`` that
cannot be opened, which nothing notices until something tries to read the
times back. The round-trip test through a real session database is what
catches that, so it is not mocked.
"""

from __future__ import annotations

import tempfile

import numpy as np
import pytest

from ndi.app.stimulus.decoder import (
    _presentation_time,
    _stimevents_in_window,
    ndi_app_stimulus_decoder,
)


class FakeStimulator:
    """A stimulus element answering the decoder's API.

    Two epochs, four trials each: stimulus 1 (a grating) and stimulus 2
    (blank) alternating, so a document keyed to the wrong epoch or a
    presentation order read the wrong way round is visible in the numbers.
    """

    def __init__(self, element_id="stim1", epochs=("e1", "e2")):
        self.id = element_id
        self.epochs = list(epochs)
        self.read_epochs: list[str] = []

    def elementstring(self):
        return "vhvis_spike2 | 1"

    def epochtable(self):
        return [{"epoch_id": e, "t0_t1": [[0.0, 10.0]]} for e in self.epochs], "hash"

    def readtimeseriesepoch(self, epoch, t0, t1):  # noqa: ARG002
        self.read_epochs.append(epoch)
        data = {
            "stimid": np.array([1, 2, 1, 2]),
            "parameters": [{"isblank": 0, "angle": 30}, {"isblank": 1}],
        }
        t = {
            "stimon": np.array([1.0, 2.0, 3.0, 4.0]),
            "stimoff": np.array([1.5, 2.5, 3.5, 4.5]),
            "stimopenclose": np.array([[0.9, 1.6], [1.9, 2.6], [2.9, 3.6], [3.9, 4.6]]),
            "stimevents": [np.array([1.1, 2.2, 9.9])],
        }
        return data, t, _FakeTimeRef()


class _FakeTimeRef:
    class clocktype:  # noqa: N801 - stands in for the enum
        def __str__(self):
            return "dev_local_time"

    clocktype = clocktype()


def real_session():
    """A real ndi.session.dir with a subject and a stimulator element document.

    The element has to exist in the database because the document written
    depends on it, and the database validates that.
    """
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
    return session, element.id


class TestStimeventsWindow:
    def test_events_inside_the_trial_are_kept_with_their_channel(self):
        events = _stimevents_in_window([np.array([1.1, 9.9])], 1.0, 1.5, 0.9, 1.6)
        assert events.tolist() == [[1.1, 1.0]]

    def test_channels_are_numbered_from_one(self):
        """As MATLAB numbers them, and as the reader of the file expects."""
        events = _stimevents_in_window([np.array([]), np.array([1.2])], 1.0, 1.5, 0.9, 1.6)
        assert events.tolist() == [[1.2, 2.0]]

    def test_the_window_is_the_widest_bracket_the_trial_offers(self):
        """An event between stimopen and onset is still this trial's; taking
        only onset..offset would drop it from the record."""
        events = _stimevents_in_window([np.array([0.95])], 1.0, 1.5, 0.9, 1.6)
        assert events.tolist() == [[0.95, 1.0]]

    def test_rows_come_back_sorted_by_time_across_channels(self):
        events = _stimevents_in_window([np.array([1.4]), np.array([1.1])], 1.0, 1.5, 0.9, 1.6)
        assert events[:, 0].tolist() == [1.1, 1.4]
        assert events[:, 1].tolist() == [2.0, 1.0]

    def test_no_events_is_an_empty_two_column_array(self):
        """Shape matters: the writer packs an Nx2 matrix."""
        assert _stimevents_in_window(None, 1.0, 1.5, 0.9, 1.6).shape == (0, 2)

    def test_a_trial_with_no_finite_bracket_keeps_nothing(self):
        nan = float("nan")
        assert _stimevents_in_window([np.array([1.0])], nan, nan, nan, nan).shape == (0, 2)


class TestPresentationTime:
    def test_one_entry_per_trial_in_presentation_order(self):
        _data, t, timeref = FakeStimulator().readtimeseriesepoch("e1", 0, 1)
        entries = _presentation_time(t, timeref)
        assert len(entries) == 4
        assert [e["onset"] for e in entries] == [1.0, 2.0, 3.0, 4.0]

    def test_each_entry_carries_the_full_bracket_and_the_clock(self):
        _data, t, timeref = FakeStimulator().readtimeseriesepoch("e1", 0, 1)
        first = _presentation_time(t, timeref)[0]
        assert (first["stimopen"], first["onset"], first["offset"], first["stimclose"]) == (
            0.9,
            1.0,
            1.5,
            1.6,
        )
        assert first["clocktype"] == "dev_local_time"

    def test_a_time_reference_that_cannot_name_its_clock_gives_empty(self):
        """Not a made-up clock name: the reader treats "" as unknown, and a
        wrong clock silently misplaces every time in the file."""
        _data, t, _ = FakeStimulator().readtimeseriesepoch("e1", 0, 1)
        assert _presentation_time(t, object())[0]["clocktype"] == ""


class TestParseStimuli:
    def test_no_session_is_refused(self):
        with pytest.raises(RuntimeError, match="No session"):
            ndi_app_stimulus_decoder().parse_stimuli(FakeStimulator())

    def test_every_epoch_gets_a_document_keyed_to_it(self):
        session, element_id = real_session()
        stim = FakeStimulator(element_id)

        newdocs, existingdocs = ndi_app_stimulus_decoder(session).parse_stimuli(stim)

        assert existingdocs == []
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["e1", "e2"]

    def test_the_document_records_the_order_and_the_stimuli(self):
        session, element_id = real_session()
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(FakeStimulator(element_id))
        presentation = newdocs[0].document_properties["stimulus_presentation"]
        assert presentation["presentation_order"] == [1, 2, 1, 2]
        assert presentation["stimuli"][0]["parameters"] == {"isblank": 0, "angle": 30}

    def test_it_depends_on_the_element_it_decoded(self):
        session, element_id = real_session()
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(FakeStimulator(element_id))
        assert newdocs[0].dependency_value("stimulus_element_id") == element_id

    def test_the_presentation_times_survive_the_write(self):
        """The round trip that a deleted temp file breaks. Storing a
        document whose presentation_time.bin cannot be opened raises
        nothing at write time -- only here, when something reads it."""
        session, element_id = real_session()
        decoder = ndi_app_stimulus_decoder(session)
        newdocs, _ = decoder.parse_stimuli(FakeStimulator(element_id))

        times = decoder.load_presentation_time(newdocs[0])

        assert len(times) == 4
        assert times[0]["onset"] == 1.0
        assert times[0]["clocktype"] == "dev_local_time"

    def test_a_second_run_decodes_nothing_and_reports_what_is_there(self):
        """Re-running over a decoded probe has to be free: each epoch costs
        minutes, and the GUI's Run button is one click away."""
        session, element_id = real_session()
        stim = FakeStimulator(element_id)
        decoder = ndi_app_stimulus_decoder(session)
        decoder.parse_stimuli(stim)

        newdocs, existingdocs = decoder.parse_stimuli(stim)

        assert newdocs == []
        assert len(existingdocs) == 2

    def test_only_the_requested_epochs_are_decoded(self):
        session, element_id = real_session()
        stim = FakeStimulator(element_id)

        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(stim, epochids=["e2"])

        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["e2"]
        assert stim.read_epochs == ["e2"]

    def test_a_single_epoch_id_may_be_given_as_a_string(self):
        session, element_id = real_session()
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(
            FakeStimulator(element_id), epochids="e1"
        )
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["e1"]

    def test_reset_rebuilds_only_the_epochs_it_was_asked_about(self):
        """The whole point of the per-epoch reset: re-decoding one epoch
        must not destroy the others, each of which cost minutes."""
        session, element_id = real_session()
        stim = FakeStimulator(element_id)
        decoder = ndi_app_stimulus_decoder(session)
        first, _ = decoder.parse_stimuli(stim)
        kept_id = next(d.id for d in first if d.document_properties["epochid"]["epochid"] == "e2")

        newdocs, existingdocs = decoder.parse_stimuli(stim, True, ["e1"])

        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["e1"]
        assert [d.id for d in existingdocs] == [kept_id]

    def test_reset_writes_a_new_document_rather_than_reusing_the_old_one(self):
        session, element_id = real_session()
        stim = FakeStimulator(element_id)
        decoder = ndi_app_stimulus_decoder(session)
        first, _ = decoder.parse_stimuli(stim, epochids=["e1"])

        second, _ = decoder.parse_stimuli(stim, True, ["e1"])

        assert second[0].id != first[0].id

    def test_an_element_with_no_epochs_writes_nothing(self):
        session, element_id = real_session()
        newdocs, existingdocs = ndi_app_stimulus_decoder(session).parse_stimuli(
            FakeStimulator(element_id, epochs=())
        )
        assert (newdocs, existingdocs) == ([], [])

    def test_an_unknown_epoch_id_decodes_nothing(self):
        session, element_id = real_session()
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(
            FakeStimulator(element_id), epochids=["not-an-epoch"]
        )
        assert newdocs == []


class TestItFeedsTheNextStep:
    """What parse_stimuli writes is what tuning_response reads.

    The join between the two halves of the stimulus pipeline, and the reason
    both had to be ported before either could be checked end to end. These
    are here rather than in the tuning_response tests because the input is a
    real decoder output, not a document hand-built to look like one.
    """

    def test_control_stimulus_finds_the_blank_in_the_document_just_written(self):
        """FakeStimulator alternates a grating with a blank, so trial 2 and
        trial 4 are the controls -- 1-based trial numbers, as stored."""
        from ndi.app.stimulus.tuning_response import ndi_app_stimulus_tuning__response

        session, element_id = real_session()
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(FakeStimulator(element_id))

        responder = ndi_app_stimulus_tuning__response(session)
        cs_ids, cs_doc = responder.control_stimulus(newdocs[0])

        assert cs_ids == [2.0, 2.0, 4.0, 4.0]
        assert cs_doc.dependency_value("stimulus_presentation_id") == newdocs[0].id

    def test_label_control_stimuli_labels_every_presentation_written(self):
        from ndi.app.stimulus.tuning_response import ndi_app_stimulus_tuning__response

        session, element_id = real_session()
        stimulator = FakeStimulator(element_id)
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(stimulator)
        assert len(newdocs) == 2  # one per epoch

        cs_docs = ndi_app_stimulus_tuning__response(session).label_control_stimuli(stimulator)
        assert len(cs_docs) == len(newdocs)

    def test_the_stored_parameters_carry_what_decides_an_f1_response(self):
        """ndi.fun.stimulustemporalfrequency reads the stimulus parameters
        out of this document to decide whether F1 and F2 exist at all. The
        grating here declares no temporal frequency, so it has none -- which
        is the answer, not a failure to look."""
        from ndi.fun.stimulus import stimulustemporalfrequency

        session, element_id = real_session()
        newdocs, _ = ndi_app_stimulus_decoder(session).parse_stimuli(FakeStimulator(element_id))
        stimuli = newdocs[0].document_properties["stimulus_presentation"]["stimuli"]

        assert stimuli[0]["parameters"] == {"isblank": 0, "angle": 30}
        assert stimulustemporalfrequency(stimuli[0]["parameters"]) == (None, "")
        assert stimulustemporalfrequency({**stimuli[0]["parameters"], "tFrequency": 4.0}) == (
            4.0,
            "tFrequency",
        )
