"""Tests for ndi.gui.app.stimulus_response.

MATLAB counterpart: ndi.gui.app.stimulusResponse

What is worth pinning here is not the window -- it is the two decisions the
app makes on a user's data:

  * which elements get computed (everything, or only those without a
    response), and
  * which documents get DELETED when "Replace existing responses" is ticked.

Both are exercised against a fake session, with no display: the app mirrors
its widget state on the object precisely so they can be. The Qt tests at the
end check that the window builds and that the widgets write into that state,
and skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.app.session_app import SessionApp
from ndi.gui.app.stimulus_response import (
    DEFAULT_POSITION,
    ELEMENT_TYPES,
    NO_ELEMENTS,
    NO_STIMULATORS,
    NOTHING_SELECTED,
    NOTHING_TO_DO,
    UNPORTED_NOTE,
    WINDOW_TAG,
    close_progress_bar,
    elements_to_compute,
    make_progress_bar,
    probe_labels,
    response_query,
    stimulusResponse,
    summary_message,
    update_progress_bar,
)

TUNING_RESPONSE = "ndi.app.stimulus.tuning_response.ndi_app_stimulus_tuning__response"


class FakeElement:
    """A stand-in element.

    ``id`` is a PROPERTY, not a method, because that is what a real
    ndi.element and ndi.probe inherit from ndi.ido -- and a fake that made it
    callable is exactly what let ``element.id()`` through code review and
    into a TypeError against real data. See ndi.fun.utils.identifier.
    """

    def __init__(self, element_id, name="e", element_type="spikes"):
        self._id = element_id
        self.name = name
        self.type = element_type

    @property
    def id(self):
        return self._id

    def elementstring(self):
        return f"{self.name} | 1"


class FakeDoc:
    """A stimulus_response document, with just the dependencies read off it."""

    def __init__(self, doc_id="d", element_id=None, parameters_id=None):
        self.doc_id = doc_id
        self._deps = {
            "element_id": element_id,
            "stimulus_response_scalar_parameters_id": parameters_id,
        }

    def dependency_value(self, name, error_if_not_found=True):
        value = self._deps.get(name)
        if value is None and error_if_not_found:
            raise KeyError(name)
        return value


class FakeSession:
    """Enough of ndi.session for the app: probes, elements, and a database.

    ``search_results`` is consulted in order, one list per search, so a test
    can say what the first search returns and what the second does -- which
    is how the two-search structure of a run is checked.
    """

    def __init__(self, probes=(), elements=(), search_results=()):
        self.reference = "ref-1"
        self._probes = list(probes)
        self._elements = list(elements)
        self._search_results = [list(r) for r in search_results]
        self.searches = []
        self.removed = []

    def getpath(self):
        return "/data/ref-1"

    def getprobes(self, **kwargs):
        if kwargs.get("type") == "stimulator":
            return list(self._probes)
        return []

    def getelements(self, **kwargs):
        wanted = kwargs.get("element.type")
        return [e for e in self._elements if e.type == wanted]

    def database_search(self, query):
        self.searches.append(query)
        if self._search_results:
            return self._search_results.pop(0)
        return []

    def database_rm(self, docs):
        self.removed.append(list(docs))


class Recorder:
    """Stands in for ndi.app.stimulus.tuning_response."""

    def __init__(self, session=None, fail=None):
        self.session = session
        self.calls = []
        self.fail = fail

    def stimulus_responses(self, stimulator, element, reset=False, do_mean_only=False):
        self.calls.append((stimulator, element, reset))
        if self.fail is not None:
            raise self.fail
        return []


def _responder(monkeypatch, recorder):
    monkeypatch.setattr(TUNING_RESPONSE, lambda session: recorder)


def _app(**kwargs):
    session = kwargs.pop("session", None) or FakeSession()
    return stimulusResponse(session, build=False, **kwargs)


def _qt_or_skip():
    """Skip unless the toolkit can actually build widgets.

    ``PySide6`` importing is not enough: a wheel installed without the
    system GL libraries imports and then fails on QtWidgets, which is a skip
    and not a failure -- the app is what is under test, not the box.
    """
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestTheAppIsDiscoverable:
    def test_it_is_offered_in_the_apps_menu(self):
        """The point of the whole exercise: no registration anywhere, the app
        is found because it subclasses SessionApp and lives here."""
        found = {app["Name"]: app for app in SessionApp.list(["ndi.gui.app"])}
        assert found["Stimulus Response"]["Category"] == "Stimulus"
        assert found["Stimulus Response"]["Class"].endswith("stimulusResponse")

    def test_the_menu_labels_are_matlabs_verbatim(self):
        assert stimulusResponse.Name == "Stimulus Response"
        assert stimulusResponse.Category == "Stimulus"

    def test_launch_constructs_it_with_the_session(self):
        _qt_or_skip()  # launch() opens the window, as the menu does
        session = FakeSession()
        app = SessionApp.launch("ndi.gui.app.stimulus_response.stimulusResponse", session)
        try:
            assert isinstance(app, stimulusResponse)
            assert app.session is session
        finally:
            app.close()

    def test_every_method_is_snake_case(self):
        """The house style, and the reason nothing goes in
        tests/test_matlab_name_aliases.py: there is no camelCase spelling to
        keep in step."""
        camel = [
            name
            for name in vars(stimulusResponse)
            if not name.startswith("_") and any(c.isupper() for c in name)
        ]
        assert camel == ["Name", "Category"]


class TestProbeLabels:
    def test_one_label_per_probe(self):
        assert probe_labels([FakeElement("p1", "stim"), FakeElement("p2", "other")]) == [
            "stim | 1",
            "other | 1",
        ]

    def test_a_probe_that_will_not_name_itself_still_gets_a_row(self):
        class Mute:
            def elementstring(self):
                raise RuntimeError("no")

        (label,) = probe_labels([Mute()])
        assert label and "Mute" in label


class TestResponseQuery:
    def _ops(self, query):
        return [(s["operation"], s["param1"], s["param2"]) for s in query.search_structure]

    def test_it_asks_for_this_stimulators_responses(self):
        ops = self._ops(response_query("P1", []))
        assert ("isa", "stimulus_response", "") in ops
        assert ("depends_on", "stimulator_id", "P1") in ops

    def test_the_elements_are_one_or_not_one_query_each(self):
        """The reason the app searches once and not once per element."""
        structure = response_query("P1", ["e1", "e2", "e3"]).search_structure
        ors = [s for s in structure if s["operation"] == "or"]
        assert len(ors) == 1
        flat = repr(structure)
        assert "e1" in flat and "e2" in flat and "e3" in flat

    def test_no_elements_leaves_the_stimulator_query_alone(self):
        assert all(s["operation"] != "or" for s in response_query("P1", []).search_structure)


class TestElementsToCompute:
    def test_an_element_with_a_response_is_skipped(self):
        elements = [FakeElement("e1"), FakeElement("e2")]
        assert elements_to_compute(elements, ["e1"]) == [False, True]

    def test_nothing_existing_means_everything_is_computed(self):
        assert elements_to_compute([FakeElement("e1")], []) == [True]

    def test_an_element_that_will_not_identify_itself_is_computed(self):
        """A visible duplicate beats a silent gap -- see the docstring."""

        class Mute:
            def id(self):
                raise RuntimeError("no")

        assert elements_to_compute([Mute()], ["e1"]) == [True]


class TestSummaryMessage:
    def test_it_reports_computed_and_skipped(self):
        assert summary_message(3, 2, 0) == (
            "Computed responses for 3 element(s); skipped 2 already done."
        )

    def test_failures_point_at_the_command_window(self):
        assert "1 element(s) failed" in summary_message(1, 0, 1)

    def test_the_unported_computation_is_named_rather_than_implied(self):
        message = summary_message(0, 0, 2, unported=True)
        assert UNPORTED_NOTE in message
        assert "0 element(s)" in message

    def test_a_clean_run_says_nothing_about_failures(self):
        assert "failed" not in summary_message(2, 0, 0)


class TestSelection:
    def test_run_is_disabled_until_a_probe_and_a_type_are_chosen(self):
        app = _app()
        assert app.update_button_state() is False

        app = _app(session=FakeSession(probes=[FakeElement("p1", "stim")]))
        assert app.update_button_state() is True

        app.element_types = []
        assert app.update_button_state() is False

    def test_reload_finds_the_stimulator_probes_and_selects_the_first(self):
        probes = [FakeElement("p1", "a"), FakeElement("p2", "b")]
        app = _app(session=FakeSession(probes=probes))
        assert app.stimulators == probes
        assert app.selected_probe() is probes[0]

    def test_a_session_that_cannot_be_read_costs_probes_and_not_the_window(self):
        class Broken(FakeSession):
            def getprobes(self, **kwargs):
                raise RuntimeError("no daq systems")

        app = _app(session=Broken())
        assert app.stimulators == []
        assert app.selected_probe() is None

    def test_every_element_type_starts_selected(self):
        assert _app().selected_types() == list(ELEMENT_TYPES)

    def test_the_session_path_is_shown_and_survives_a_session_without_one(self):
        assert _app().session_path() == "/data/ref-1"

        class NoPath(FakeSession):
            def getpath(self):
                raise RuntimeError("no path")

        assert _app(session=NoPath()).session_path() == ""


class TestElementsOfTypes:
    def test_each_element_is_paired_with_the_type_it_was_found_under(self):
        elements = [FakeElement("e1"), FakeElement("e2")]
        app = _app(session=FakeSession(elements=elements))
        found, types = app.elements_of_types(["spikes"])
        assert found == elements
        assert types == ["spikes", "spikes"]

    def test_a_type_nothing_can_be_found_for_is_not_an_error(self):
        class Broken(FakeSession):
            def getelements(self, **kwargs):
                raise RuntimeError("no such field")

        assert _app(session=Broken()).elements_of_types(["spikes"]) == ([], [])


class TestExistingResponses:
    def test_the_element_ids_are_read_off_one_search(self):
        session = FakeSession(search_results=[[FakeDoc(element_id="e1"), FakeDoc(element_id="e2")]])
        app = _app(session=session)
        assert app.existing_response_element_ids(FakeElement("p1")) == ["e1", "e2"]
        assert len(session.searches) == 1

    def test_an_id_seen_twice_is_listed_once(self):
        session = FakeSession(search_results=[[FakeDoc(element_id="e1"), FakeDoc(element_id="e1")]])
        assert _app(session=session).existing_response_element_ids(FakeElement("p1")) == ["e1"]

    def test_a_response_with_no_element_is_skipped_not_raised(self):
        session = FakeSession(search_results=[[FakeDoc(element_id=None)]])
        assert _app(session=session).existing_response_element_ids(FakeElement("p1")) == []


class TestRemoveExistingResponses:
    def test_the_parameter_documents_go_with_the_responses(self):
        """Nothing else points at a parameter document, so leaving it behind
        would orphan it on every rebuild."""
        response = FakeDoc("r1", element_id="e1", parameters_id="p-doc")
        parameters = FakeDoc("p-doc")
        session = FakeSession(search_results=[[response], [parameters]])
        app = _app(session=session)

        assert app.remove_existing_responses(FakeElement("p1"), [FakeElement("e1")]) == 1
        assert session.removed == [[response], [parameters]]

    def test_a_response_without_parameters_removes_only_itself(self):
        response = FakeDoc("r1", element_id="e1")
        session = FakeSession(search_results=[[response]])
        app = _app(session=session)

        app.remove_existing_responses(FakeElement("p1"), [FakeElement("e1")])
        assert session.removed == [[response]]

    def test_nothing_found_removes_nothing(self):
        session = FakeSession(search_results=[[]])
        app = _app(session=session)
        assert app.remove_existing_responses(FakeElement("p1"), [FakeElement("e1")]) == 0
        assert session.removed == []


class TestRunResponses:
    def _session(self, elements, search_results=()):
        return FakeSession(
            probes=[FakeElement("p1", "stim")],
            elements=elements,
            search_results=search_results,
        )

    def test_nothing_selected_is_refused_with_a_message(self):
        app = _app()  # no probes in the session
        result = app.run_responses()
        assert result.message == NOTHING_SELECTED
        assert app.last_alert == (NOTHING_SELECTED, "Nothing selected")

    def test_a_session_with_no_elements_says_so(self):
        app = _app(session=self._session([]))
        assert app.run_responses().message == NO_ELEMENTS

    def test_every_element_without_a_response_is_computed(self, monkeypatch):
        elements = [FakeElement("e1"), FakeElement("e2")]
        app = _app(session=self._session(elements, search_results=[[]]))
        recorder = Recorder()
        _responder(monkeypatch, recorder)

        result = app.run_responses()
        assert result.computed == 2
        assert result.skipped == 0
        assert [call[1] for call in recorder.calls] == elements

    def test_an_element_that_already_has_a_response_is_left_alone(self, monkeypatch):
        elements = [FakeElement("e1"), FakeElement("e2")]
        session = self._session(elements, search_results=[[FakeDoc(element_id="e1")]])
        app = _app(session=session)
        recorder = Recorder()
        _responder(monkeypatch, recorder)

        result = app.run_responses()
        assert (result.computed, result.skipped) == (1, 1)
        assert [call[1] for call in recorder.calls] == [elements[1]]

    def test_all_done_already_asks_the_user_to_tick_replace(self, monkeypatch):
        elements = [FakeElement("e1")]
        session = self._session(elements, search_results=[[FakeDoc(element_id="e1")]])
        app = _app(session=session)
        recorder = Recorder()
        _responder(monkeypatch, recorder)

        result = app.run_responses()
        assert result.message == NOTHING_TO_DO
        assert result.skipped == 1
        assert recorder.calls == []

    def test_replace_removes_first_and_then_computes_everything(self, monkeypatch):
        elements = [FakeElement("e1"), FakeElement("e2")]
        response = FakeDoc("r1", element_id="e1")
        session = self._session(elements, search_results=[[response]])
        app = _app(session=session)
        app.replace = True
        recorder = Recorder()
        _responder(monkeypatch, recorder)

        result = app.run_responses()
        assert session.removed == [[response]]
        assert result.computed == 2
        assert result.skipped == 0

    def test_the_search_happens_once_and_not_once_per_element(self, monkeypatch):
        """The structural claim of the port: one search decides the whole run."""
        elements = [FakeElement(f"e{i}") for i in range(5)]
        session = self._session(elements, search_results=[[]])
        app = _app(session=session)
        _responder(monkeypatch, Recorder())

        app.run_responses()
        assert len(session.searches) == 1

    def test_responses_are_never_recomputed_with_reset(self, monkeypatch):
        """reset would re-do the deletion the replace path just did, and on
        the skip path would discard responses the user asked to keep."""
        app = _app(session=self._session([FakeElement("e1")], search_results=[[]]))
        recorder = Recorder()
        _responder(monkeypatch, recorder)

        app.run_responses()
        assert [call[2] for call in recorder.calls] == [False]

    def test_the_stimulator_is_the_one_that_was_chosen(self, monkeypatch):
        app = _app(session=self._session([FakeElement("e1")], search_results=[[]]))
        recorder = Recorder()
        _responder(monkeypatch, recorder)

        app.run_responses()
        assert recorder.calls[0][0] is app.selected_probe()

    def test_one_failing_element_does_not_stop_the_others(self, monkeypatch):
        elements = [FakeElement("e1"), FakeElement("e2")]
        app = _app(session=self._session(elements, search_results=[[]]))

        calls = []

        class Flaky(Recorder):
            def stimulus_responses(self, stimulator, element, reset=False, do_mean_only=False):
                calls.append(element)
                if element is elements[0]:
                    raise RuntimeError("bad epoch")

        _responder(monkeypatch, Flaky())

        with pytest.warns(UserWarning, match="bad epoch"):
            result = app.run_responses()
        assert (result.computed, result.failed) == (1, 1)
        assert calls == elements

    def test_the_unported_computation_is_reported_as_such(self, monkeypatch):
        """Today's real behaviour: tuning_response.stimulus_responses raises
        NotImplementedError, and the user is told that rather than left with
        "0 computed"."""
        app = _app(session=self._session([FakeElement("e1")], search_results=[[]]))
        _responder(monkeypatch, Recorder(fail=NotImplementedError("not ported")))

        with pytest.warns(UserWarning):
            result = app.run_responses()
        assert result.failed == 1
        assert UNPORTED_NOTE in result.message
        assert app.last_alert[1] == "Done with errors"


class TestProgressBarHelpers:
    def test_a_bar_that_cannot_be_made_is_none_and_not_an_error(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "ndi.gui.component.ProgressBarWindow", None)
        assert make_progress_bar("t", "l", "tag") is None

    def test_the_helpers_tolerate_no_bar(self):
        update_progress_bar(None, "tag", 0.5)
        close_progress_bar(None, "tag")

    def test_the_fraction_is_clamped(self):
        seen = []

        class Bar:
            def updateBar(self, tag, fraction):  # noqa: N802 - the component's name
                seen.append(fraction)

        update_progress_bar(Bar(), "tag", 2.0)
        update_progress_bar(Bar(), "tag", -1.0)
        assert seen == [1.0, 0.0]


class TestTheWindow:
    def test_it_builds_with_matlabs_tag_and_geometry(self):
        _qt_or_skip()
        app = stimulusResponse(FakeSession(probes=[FakeElement("p1", "stim")]))
        try:
            assert app.figure.objectName() == WINDOW_TAG
            assert app.figure.width() == DEFAULT_POSITION[2]
            assert "ref-1" in app.figure.windowTitle()
        finally:
            app.close()

    def test_the_dropdown_holds_the_sessions_stimulators(self):
        _qt_or_skip()
        probes = [FakeElement("p1", "a"), FakeElement("p2", "b")]
        app = stimulusResponse(FakeSession(probes=probes))
        try:
            items = [app.probe_dropdown.itemText(i) for i in range(app.probe_dropdown.count())]
            assert items == ["a | 1", "b | 1"]
            assert app.run_button.isEnabled()
        finally:
            app.close()

    def test_a_session_with_no_stimulators_says_so_and_leaves_run_disabled(self):
        _qt_or_skip()
        app = stimulusResponse(FakeSession())
        try:
            assert app.probe_dropdown.itemText(0) == NO_STIMULATORS
            assert not app.run_button.isEnabled()
        finally:
            app.close()

    def test_the_listbox_opens_with_every_type_selected(self):
        _qt_or_skip()
        app = stimulusResponse(FakeSession(probes=[FakeElement("p1", "stim")]))
        try:
            selected = [item.text() for item in app.type_list.selectedItems()]
            assert selected == list(ELEMENT_TYPES)
            assert app.element_types == list(ELEMENT_TYPES)
        finally:
            app.close()

    def test_the_widgets_write_into_the_state_the_run_reads(self):
        _qt_or_skip()
        probes = [FakeElement("p1", "a"), FakeElement("p2", "b")]
        app = stimulusResponse(FakeSession(probes=probes))
        try:
            app.probe_dropdown.setCurrentIndex(1)
            assert app.selected_probe() is probes[1]

            app.replace_checkbox.setChecked(True)
            assert app.replace is True

            app.type_list.clearSelection()
            assert app.element_types == []
            assert not app.run_button.isEnabled()
        finally:
            app.close()

    def test_a_reload_does_not_reset_the_users_choice_to_a_click(self):
        """Refilling the dropdown emits an index change; letting it through
        would make a reload look like a user's selection."""
        _qt_or_skip()
        app = stimulusResponse(FakeSession(probes=[FakeElement("p1", "a")]))
        try:
            app.probe_index = None
            app._refill_probe_dropdown()
            assert app.probe_index is None
        finally:
            app.close()
