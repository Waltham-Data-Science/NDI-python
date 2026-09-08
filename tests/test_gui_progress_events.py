"""``ndi.gui.component`` progress events against ``+ndi/+gui/+component/``.

WHY THIS FILE EXISTS. All eight entries in this group were recorded as a
plain ``ported`` with no ``decision_log`` at all -- an unqualified claim that
this Python matches that MATLAB. Two parts of the event machinery did not.

* ``ProgressUpdatedEventData`` carried ONE field where MATLAB carries three.
  MATLAB's ``ProgressTracker`` raises it from two places and passes
  ``ProgressPercentage``, ``CurrentStep`` and ``TotalSteps`` at both; the port
  passed only the percentage, under a different name.
* ``ProgressTracker.updateMessage`` was not ported at all. It is the ONLY
  place MATLAB notifies MessageUpdated, so its absence left the whole message
  channel dead on this side: ``ProgressMonitor`` registers a listener on
  ``on_message_updated``, ``MessageUpdatedEventData`` exists, and
  ``_fire_message_updated`` had no caller anywhere in the tree.

Neither had a test, which is how a wired-up channel with no producer went
unnoticed.
"""

from __future__ import annotations

import json

import pytest

from ndi.gui.component.internal.AsynchProgressTracker import (
    ndi_gui_component_internal_AsynchProgressTracker,
)
from ndi.gui.component.internal.event import (
    ndi_gui_component_internal_event_MessageUpdatedEventData,
    ndi_gui_component_internal_event_ProgressUpdatedEventData,
)
from ndi.gui.component.internal.ProgressTracker import (
    ndi_gui_component_internal_ProgressTracker,
)

Tracker = ndi_gui_component_internal_ProgressTracker
AsynchTracker = ndi_gui_component_internal_AsynchProgressTracker
ProgressEvent = ndi_gui_component_internal_event_ProgressUpdatedEventData
MessageEvent = ndi_gui_component_internal_event_MessageUpdatedEventData


class TestProgressUpdatedEventData:
    """MATLAB counterpart:
    ``+ndi/+gui/+component/+internal/+event/ProgressUpdatedEventData.m``."""

    def test_it_carries_matlabs_three_properties(self):
        evt = ProgressEvent(37.5, 3, 8)
        assert evt.ProgressPercentage == 37.5
        assert evt.CurrentStep == 3
        assert evt.TotalSteps == 8

    def test_the_old_single_field_name_still_reads(self):
        """``PercentageComplete`` was this port's name for MATLAB's
        ``ProgressPercentage``; kept so existing callers keep working."""
        assert ProgressEvent(37.5, 3, 8).PercentageComplete == 37.5


class TestTheProgressEventCarriesTheStepCounts:
    """The regression. A listener written against the MATLAB API asks the
    event for CurrentStep and TotalSteps; it used to have neither."""

    def test_progress_updates_report_the_step_counts(self):
        seen = []
        tracker = Tracker(4)
        tracker.on_progress_updated.append(
            lambda _src, evt: seen.append((evt.ProgressPercentage, evt.CurrentStep, evt.TotalSteps))
        )
        for _ in range(3):
            tracker.updateProgress()
        assert seen == [(25.0, 1, 4), (50.0, 2, 4), (75.0, 3, 4)]

    def test_completion_reports_the_final_counts(self):
        """MATLAB raises TaskCompleted with the SAME event data, so a
        completion listener sees the counts rather than having to go back to
        the tracker."""
        seen = []
        tracker = Tracker(2)
        tracker.on_task_completed.append(
            lambda _src, evt: seen.append((evt.ProgressPercentage, evt.CurrentStep, evt.TotalSteps))
        )
        tracker.updateProgress()
        tracker.updateProgress()
        assert seen == [(100.0, 2, 2)]


class TestUpdateMessage:
    """MATLAB counterpart: ``ProgressTracker.updateMessage``."""

    def test_it_exists(self):
        """It did not. Everything downstream of it was already in place."""
        assert hasattr(Tracker(1), "updateMessage")

    def test_it_raises_message_updated_with_the_given_text(self):
        seen = []
        tracker = Tracker(3)
        tracker.on_message_updated.append(lambda _src, evt: seen.append(evt.Message))
        tracker.updateMessage("Loading epoch 2 of 3")
        assert seen == ["Loading epoch 2 of 3"]

    def test_the_snake_case_alias_is_the_same_method(self):
        assert Tracker.update_message is Tracker.updateMessage

    def test_it_notifies_without_storing(self):
        """MATLAB's updateMessage only notifies; the tracker's own Message
        stays the rendered TemplateMessage."""
        tracker = Tracker(4)
        tracker.TemplateMessage = "Step {{CurrentStep}} of {{TotalSteps}}"
        tracker.updateMessage("something else")
        assert tracker.Message == "Step 0 of 4"

    def test_the_event_type_is_the_ported_one(self):
        seen = []
        tracker = Tracker(1)
        tracker.on_message_updated.append(lambda _src, evt: seen.append(evt))
        tracker.updateMessage("x")
        assert isinstance(seen[0], MessageEvent)


class TestProgressMonitorStillListens:
    """The listener side was already wired; these check the two changes did
    not break it."""

    def test_a_completion_listener_taking_the_event_is_called(self):
        calls = []
        tracker = Tracker(1)
        tracker.on_task_completed.append(lambda src, evt: calls.append((src, evt)))
        tracker.updateProgress()
        assert len(calls) == 1
        assert calls[0][1].TotalSteps == 1

    def test_a_message_listener_receives_the_event_object(self):
        calls = []
        tracker = Tracker(1)
        tracker.on_message_updated.append(lambda src, evt: calls.append(evt.Message))
        tracker.updateMessage("hello")
        assert calls == ["hello"]


class TestAsynchProgressTrackerStillDumps:
    """AsynchProgressTracker overrides updateProgress and fires the same
    events; the payload change has to reach it too."""

    def test_the_dump_file_carries_the_three_recorded_properties(self, tmp_path):
        target = tmp_path / "progress.json"
        tracker = AsynchTracker(2)
        tracker.DumpFilePath = str(target)
        tracker.TemplateMessage = "working"
        tracker.updateProgress()
        tracker.updateProgress()
        payload = json.loads(target.read_text())
        assert payload == {"CurrentStep": 2, "TotalSteps": 2, "TemplateMessage": "working"}

    def test_its_progress_events_carry_the_step_counts_too(self, tmp_path):
        seen = []
        tracker = AsynchTracker(2)
        tracker.DumpFilePath = str(tmp_path / "p.json")
        tracker.on_task_completed.append(
            lambda _src, evt: seen.append((evt.CurrentStep, evt.TotalSteps))
        )
        tracker.updateProgress()
        tracker.updateProgress()
        assert seen == [(2, 2)]


class TestMessageUpdatedEventData:
    """MATLAB counterpart:
    ``+ndi/+gui/+component/+internal/+event/MessageUpdatedEventData.m``.
    One property, one constructor argument -- this one always matched."""

    def test_it_carries_the_message(self):
        assert MessageEvent("hello").Message == "hello"

    def test_the_message_is_required(self):
        with pytest.raises(TypeError):
            MessageEvent()
