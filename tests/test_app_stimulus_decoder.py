"""Tests for ndi.app.stimulus.decoder.parse_stimuli.

MATLAB counterpart: ndi.app.stimulus.decoder/parse_stimuli

This is the first step of the stimulus pipeline: it turns a stimulator's
per-epoch record into the ``stimulus_presentation`` documents that everything
downstream reads. So the tests care about three things:

  * that what the stimulator reported comes back out of the document
    unchanged -- the presentation order, each stimulus's parameters, and the
    per-presentation timing written to ``presentation_time.bin``;
  * that re-running it does not disturb epochs already done, and that
    ``reset`` disturbs ONLY the epochs it was asked for;
  * that the timing survives the round trip through the binary file, since
    that file is the only place the onsets exist once the document is stored.

The last class runs the output straight into ndi.app.stimulus.tuning_response,
which is the join this port was missing: before it, nothing in Python wrote
the documents that app reads.
"""

from __future__ import annotations

import os
import pathlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from ndi.app.stimulus.decoder import ndi_app_stimulus_decoder
from ndi.database_fun import read_presentation_time_structure
from ndi.document import ndi_document
from ndi.query import ndi_query


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------
def _session(search=None):
    session = MagicMock()
    session.id.return_value = "session-1"
    session.searchquery.return_value = ndi_query("base.session_id", "exact_string", "session-1", "")
    session.database_search = MagicMock(side_effect=search or (lambda q: []))
    session.database_rm = MagicMock()
    session.database_add = MagicMock()
    session.newdocument = MagicMock(side_effect=_newdocument)
    return session


def _newdocument(document_type, **properties):
    doc = ndi_document(document_type, **properties)
    return doc.set_session_id("session-1")


class FakeStimulator:
    """A stimulator that reports a fixed record for each of its epochs."""

    def __init__(self, epochs):
        self.epochs = epochs  # {epoch_id: (data, t)}
        self.reads = []

    def id(self):
        return "stimulator-1"

    def epochtable(self):
        return [{"epoch_id": e, "epoch_number": i + 1} for i, e in enumerate(self.epochs)]

    def readtimeseriesepoch(self, epoch, t0, t1):
        self.reads.append((epoch, t0, t1))
        data, t = self.epochs.get(epoch, (None, None))
        return data, t, SimpleNamespace(clocktype="dev_local_time")


def _record(stimids=(1, 2, 3, 1, 2, 3), onsets=None, events=None):
    """One epoch's worth of what a stimulator reports."""
    onsets = list(onsets if onsets is not None else [i * 2.0 for i in range(len(stimids))])
    data = {
        "stimid": np.asarray(stimids, dtype=int),
        "parameters": [
            {"angle": 0.0, "tFrequency": 2.0},
            {"angle": 90.0, "tFrequency": 2.0},
            {"isblank": 1},
        ],
    }
    t = {
        "stimon": np.asarray(onsets, dtype=float),
        "stimoff": np.asarray([o + 1.5 for o in onsets], dtype=float),
        "stimopenclose": np.asarray([[o - 0.1, o + 1.6] for o in onsets], dtype=float),
        "stimevents": events or [],
    }
    return data, t


def _existing_doc(epoch, element_id="stimulator-1"):
    doc = ndi_document("stimulus_presentation")
    doc.document_properties["epochid"] = {"epochid": epoch}
    return doc.set_dependency_value("stimulus_element_id", element_id, error_if_not_found=False)


def _app(session):
    return ndi_app_stimulus_decoder(session=session)


# ----------------------------------------------------------------------
class TestWhatIsWritten:
    def test_one_document_per_epoch(self):
        stimulator = FakeStimulator({"ep1": _record(), "ep2": _record()})
        session = _session()
        newdocs, existing = _app(session).parse_stimuli(stimulator)
        assert len(newdocs) == 2
        assert existing == []
        assert {d.document_properties["epochid"]["epochid"] for d in newdocs} == {"ep1", "ep2"}

    def test_the_presentation_order_is_what_the_stimulator_reported(self):
        stimulator = FakeStimulator({"ep1": _record(stimids=(2, 1, 3, 3, 1, 2))})
        (doc,), _ = _app(_session()).parse_stimuli(stimulator)
        presentation = doc.document_properties["stimulus_presentation"]
        assert presentation["presentation_order"] == [2, 1, 3, 3, 1, 2]

    def test_each_stimulus_keeps_its_parameters(self):
        stimulator = FakeStimulator({"ep1": _record()})
        (doc,), _ = _app(_session()).parse_stimuli(stimulator)
        stimuli = doc.document_properties["stimulus_presentation"]["stimuli"]
        assert [s["parameters"] for s in stimuli] == [
            {"angle": 0.0, "tFrequency": 2.0},
            {"angle": 90.0, "tFrequency": 2.0},
            {"isblank": 1},
        ]

    def test_the_document_depends_on_the_stimulator(self):
        stimulator = FakeStimulator({"ep1": _record()})
        (doc,), _ = _app(_session()).parse_stimuli(stimulator)
        assert doc.dependency_value("stimulus_element_id") == "stimulator-1"

    def test_the_whole_epoch_is_read(self):
        """-inf to inf: the record is whatever the epoch holds, and a
        narrower window would silently drop stimuli at either end."""
        stimulator = FakeStimulator({"ep1": _record()})
        _app(_session()).parse_stimuli(stimulator)
        assert stimulator.reads == [("ep1", float("-inf"), float("inf"))]

    def test_an_epoch_with_no_stimuli_gets_no_document(self):
        """A stimulator can be running through an epoch it never presented
        in. An empty document would make every later search return
        something with nothing in it."""
        empty = ({"stimid": [], "parameters": []}, {"stimon": [], "stimoff": []})
        stimulator = FakeStimulator({"ep1": empty, "ep2": _record()})
        newdocs, _ = _app(_session()).parse_stimuli(stimulator)
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["ep2"]

    def test_an_element_with_no_epochs_writes_nothing(self):
        session = _session()
        newdocs, existing = _app(session).parse_stimuli(FakeStimulator({}))
        assert (newdocs, existing) == ([], [])
        session.database_add.assert_not_called()

    def test_no_session_is_refused(self):
        with pytest.raises(RuntimeError, match="No session"):
            ndi_app_stimulus_decoder().parse_stimuli(FakeStimulator({}))


class TestTheTimingFile:
    """What parse_stimuli actually wrote to disk, read back off disk.

    The database sees the file at add time and the app cleans it up
    afterwards, so the fake database keeps a COPY of the bytes -- which is
    the only way to check the real file rather than a re-derivation of it.
    """

    def _timing(self, epoch_record, tmp_path):
        stimulator = FakeStimulator({"ep1": epoch_record})
        session = _session()
        captured: dict[str, Any] = {}

        def capture(docs):
            for doc in docs if isinstance(docs, list) else [docs]:
                info = doc.document_properties["files"]["file_info"][0]
                path = info["locations"][0]["location"]
                captured["path"] = path
                copy = tmp_path / "captured.bin"
                copy.write_bytes(pathlib.Path(path).read_bytes())
                captured["copy"] = str(copy)

        session.database_add = MagicMock(side_effect=capture)
        (doc,), _ = _app(session).parse_stimuli(stimulator)
        return captured, doc

    def test_the_times_survive_the_round_trip(self, tmp_path):
        """Once the document is stored, this file is the ONLY place the
        onsets exist -- tuning_response reads them back from it."""
        onsets = [0.0, 2.0, 4.0]
        captured, _ = self._timing(_record(stimids=(1, 2, 3), onsets=onsets), tmp_path)
        _, entries = read_presentation_time_structure(captured["copy"])
        assert [e["onset"] for e in entries] == pytest.approx(onsets)
        assert [e["offset"] for e in entries] == pytest.approx([o + 1.5 for o in onsets])
        assert {e["clocktype"] for e in entries} == {"dev_local_time"}

    def test_the_file_is_named_as_the_schema_declares(self, tmp_path):
        _, doc = self._timing(_record(stimids=(1, 2, 3)), tmp_path)
        assert doc.document_properties["files"]["file_info"][0]["name"] == "presentation_time.bin"

    def test_nothing_is_left_in_the_temp_directory(self, tmp_path):
        """The database ingests the file; whatever it does with the
        original, the app leaves none behind."""
        captured, _ = self._timing(_record(stimids=(1, 2, 3)), tmp_path)
        assert not os.path.exists(captured["path"])


class TestTimingContent:
    """The timing entries, read back from a file written the same way."""

    def _entries(self, record, tmp_path):
        app = ndi_app_stimulus_decoder(session=_session())
        data, t = record
        entries = app._presentation_time(t, SimpleNamespace(clocktype="dev_local_time"))
        from ndi.database_fun import write_presentation_time_structure

        path = str(tmp_path / "presentation_time.bin")
        write_presentation_time_structure(path, entries)
        _, read_back = read_presentation_time_structure(path)
        return entries, read_back

    def test_one_entry_per_presentation(self, tmp_path):
        entries, read_back = self._entries(_record(stimids=(1, 2, 3, 1)), tmp_path)
        assert len(entries) == 4
        assert len(read_back) == 4

    def test_the_onsets_and_offsets_round_trip(self, tmp_path):
        onsets = [0.0, 2.0, 4.0]
        _, read_back = self._entries(_record(stimids=(1, 2, 3), onsets=onsets), tmp_path)
        assert [e["onset"] for e in read_back] == pytest.approx(onsets)
        assert [e["offset"] for e in read_back] == pytest.approx([o + 1.5 for o in onsets])

    def test_open_and_close_bracket_the_stimulus(self, tmp_path):
        """They differ from onset/offset when the display was opened before
        the stimulus began; both are kept because a prestimulus baseline is
        measured against one and a response against the other."""
        entries, _ = self._entries(_record(stimids=(1,), onsets=[10.0]), tmp_path)
        assert entries[0]["stimopen"] == pytest.approx(9.9)
        assert entries[0]["stimclose"] == pytest.approx(11.6)

    def test_the_clock_is_recorded(self, tmp_path):
        entries, read_back = self._entries(_record(stimids=(1,)), tmp_path)
        assert entries[0]["clocktype"] == "dev_local_time"
        assert read_back[0]["clocktype"] == "dev_local_time"

    def test_events_are_matched_to_the_trial_they_fall_in(self, tmp_path):
        record = _record(stimids=(1, 2), onsets=[0.0, 10.0], events=[[0.5, 10.5], [0.7]])
        entries, _ = self._entries(record, tmp_path)
        first = np.asarray(entries[0]["stimevents"])
        second = np.asarray(entries[1]["stimevents"])
        assert first[:, 0].tolist() == [0.5, 0.7]
        assert second[:, 0].tolist() == [10.5]

    def test_event_channels_are_one_based(self, tmp_path):
        """They name a marker channel to a person reading the document, not
        a Python index."""
        record = _record(stimids=(1,), onsets=[0.0], events=[[0.5], [0.6]])
        entries, _ = self._entries(record, tmp_path)
        assert np.asarray(entries[0]["stimevents"])[:, 1].tolist() == [1.0, 2.0]

    def test_events_are_sorted_by_time_across_channels(self, tmp_path):
        record = _record(stimids=(1,), onsets=[0.0], events=[[0.9], [0.2]])
        entries, _ = self._entries(record, tmp_path)
        assert np.asarray(entries[0]["stimevents"])[:, 0].tolist() == [0.2, 0.9]

    def test_an_event_just_outside_the_stimulus_but_inside_the_trial_is_kept(self, tmp_path):
        """The window is the widest of the trial's bounds: the rig can mark
        something before the stimulus is drawn, and losing it would lose the
        record of something that happened."""
        record = _record(stimids=(1,), onsets=[10.0], events=[[9.95]])
        entries, _ = self._entries(record, tmp_path)
        assert np.asarray(entries[0]["stimevents"])[:, 0].tolist() == [9.95]

    def test_an_epoch_with_no_events_has_an_empty_matrix(self, tmp_path):
        entries, _ = self._entries(_record(stimids=(1,)), tmp_path)
        assert np.asarray(entries[0]["stimevents"]).shape == (0, 2)


class TestRerunningIt:
    def test_an_epoch_that_is_done_is_left_alone(self):
        """Parsing is idempotent, so it can be run again after new epochs
        arrive without disturbing the responses already computed from the
        old ones."""
        stimulator = FakeStimulator({"ep1": _record(), "ep2": _record()})
        done = _existing_doc("ep1")
        session = _session(search=lambda q: [done])
        newdocs, existing = _app(session).parse_stimuli(stimulator)
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["ep2"]
        assert existing == [done]
        session.database_rm.assert_not_called()

    def test_reset_rebuilds_the_epochs_it_covers(self):
        stimulator = FakeStimulator({"ep1": _record()})
        done = _existing_doc("ep1")
        session = _session(search=lambda q: [done])
        newdocs, existing = _app(session).parse_stimuli(stimulator, reset=True)
        session.database_rm.assert_called_once_with([done])
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["ep1"]
        assert existing == []

    def test_reset_of_one_epoch_leaves_another_epochs_work_alone(self):
        """The reason reset takes the epoch list into account at all."""
        stimulator = FakeStimulator({"ep1": _record(), "ep2": _record()})
        done1, done2 = _existing_doc("ep1"), _existing_doc("ep2")
        session = _session(search=lambda q: [done1, done2])
        newdocs, existing = _app(session).parse_stimuli(stimulator, reset=True, epochids="ep1")
        session.database_rm.assert_called_once_with([done1])
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["ep1"]
        assert existing == [done2]

    def test_epochids_limits_which_epochs_are_parsed(self):
        stimulator = FakeStimulator({"ep1": _record(), "ep2": _record(), "ep3": _record()})
        newdocs, _ = _app(_session()).parse_stimuli(stimulator, epochids=["ep1", "ep3"])
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["ep1", "ep3"]

    def test_an_epochid_that_names_nothing_is_not_an_error(self):
        """Asking to parse an epoch that is not there has already been
        answered; the epochs that ARE there should still be parsed."""
        stimulator = FakeStimulator({"ep1": _record()})
        newdocs, _ = _app(_session()).parse_stimuli(stimulator, epochids=["ep1", "nosuchepoch"])
        assert [d.document_properties["epochid"]["epochid"] for d in newdocs] == ["ep1"]


class TestItFeedsTheNextStep:
    """The join this port was missing: what parse_stimuli writes is what
    ndi.app.stimulus.tuning_response reads."""

    def test_the_document_is_one_tuning_response_can_work_from(self):
        from ndi.app.stimulus.tuning_response import ndi_app_stimulus_tuning__response

        stimulator = FakeStimulator({"ep1": _record(stimids=(1, 2, 3, 1, 2, 3))})
        session = _session()
        (presentation,), _ = _app(session).parse_stimuli(stimulator)

        # control_stimulus reads the same document, and finds the blank
        # (stimulus 3, the one carrying isblank) in each repetition.
        responder = ndi_app_stimulus_tuning__response(session=session)
        control_ids, control_doc = responder.control_stimulus(presentation)
        assert control_ids == [3.0, 3.0, 3.0, 6.0, 6.0, 6.0]
        assert control_doc.dependency_value("stimulus_presentation_id") == presentation.id

    def test_the_stimuli_carry_the_frequency_that_earns_an_f1_response(self):
        """tFrequency is what ndi.fun.stimulustemporalfrequency reads to
        decide there is an F1 and F2 to compute at all."""
        from ndi.fun.stimulus import stimulustemporalfrequency

        stimulator = FakeStimulator({"ep1": _record()})
        (presentation,), _ = _app(_session()).parse_stimuli(stimulator)
        stimuli = presentation.document_properties["stimulus_presentation"]["stimuli"]
        assert stimulustemporalfrequency(stimuli[0]["parameters"]) == (2.0, "tFrequency")
