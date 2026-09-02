"""Tests for ndi.gui.app.stimulus_decoder.

MATLAB counterpart: ndi.gui.app.stimulusDecoder

What matters most here is that the window tells the truth about a session's
state, because a user decides what to run next from it and every wrong
answer is silent.

The MARKERS are the first of those: ``*`` means decoded and ``*c`` means the
control stimuli are labeled too, and a session with the first done but not
the second looks finished to anyone checking only for
``stimulus_presentation``. The second is WHICH EPOCHS A SELECTION NAMES --
the selection is read back as row numbers, so a list rebuilt out of order
would decode epochs the user never picked. The third is the REFUSALS: when
every selected epoch is already decoded, pressing Run does nothing, and an
app that says nothing there reads as broken.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.app import SessionApp
from ndi.gui.app.stimulus_decoder import (
    DEFAULT_POSITION,
    NO_EPOCHS,
    NO_STIMULATORS,
    NOT_DECODED_MESSAGE,
    PROBE_TYPE,
    SELECT_EPOCHS_MESSAGE,
    WINDOW_TAG,
    constant_rows,
    epoch_item,
    epoch_marker,
    stimulusDecoder,
    value_to_text,
    varies_lines,
)


class FakeProbe:
    def __init__(self, name="vhvis_spike2", reference=1, epochs=("e1", "e2"), probe_id="p1"):
        self._name = name
        self._reference = reference
        self._epochs = list(epochs)
        self.id = probe_id

    def elementstring(self):
        return f"{self._name} | {self._reference}"

    def epochtable(self):
        return [{"epoch_id": e, "t0_t1": [[0.0, 10.0]]} for e in self._epochs], "hash"


class FakeDocument:
    def __init__(self, doc_id, properties, dependencies=None):
        self.id = doc_id
        self.document_properties = properties
        self._dependencies = dependencies or {}

    def dependency_value(self, name):
        return self._dependencies[name]


def presentation_doc(doc_id, epoch_id, probe_id="p1", stimuli=None):
    return FakeDocument(
        doc_id,
        {
            "epochid": {"epochid": epoch_id},
            "stimulus_presentation": {
                "presentation_order": [1, 2],
                "stimuli": stimuli
                or [
                    {"parameters": {"isblank": 0, "angle": 30}},
                    {"parameters": {"isblank": 1}},
                ],
            },
            "depends_on": [{"name": "stimulus_element_id", "value": probe_id}],
        },
    )


def control_doc(doc_id, presentation_id):
    return FakeDocument(
        doc_id,
        {"control_stimulus_ids": {"control_stimulus_ids": [2, 2]}},
        {"stimulus_presentation_id": presentation_id},
    )


class FakeSession:
    """A session answering the two searches the app makes, by document class."""

    def __init__(self, probes=(), docs=(), reference="2024-01-01", path="/data/s1"):
        self.reference = reference
        self.path = path
        self._probes = list(probes)
        self.docs = list(docs)
        self.probe_type_asked = None

    def getprobes(self, **kwargs):
        self.probe_type_asked = kwargs.get("type")
        return self._probes

    def database_search(self, query):
        wanted = None
        for term in query.search_structure:
            if term["operation"] == "isa":
                wanted = term["param1"]
        return [doc for doc in self.docs if wanted in doc.document_properties]


def _app(session):
    """The app without its window, for the parts that need no display."""
    app = stimulusDecoder(session, build=False)
    app.load_stimulators()
    probe = app.selected_probe()
    if probe is not None:
        app.epoch_ids = app.load_epochs(probe)
        app.decoded_epochs = app.decoded_epoch_ids(probe)
        app.control_labeled_epochs = app.control_labeled_epoch_ids(probe)
    return app


# ----------------------------------------------------------------------
# pure helpers
# ----------------------------------------------------------------------
class TestMarkers:
    def test_an_undecoded_epoch_carries_no_marker(self):
        assert epoch_marker(False, False) == "  "

    def test_a_decoded_epoch_is_starred(self):
        assert epoch_marker(True, False) == "* "

    def test_a_labeled_epoch_adds_the_c(self):
        assert epoch_marker(True, True) == "*c"

    def test_markers_are_all_the_same_width(self):
        """The ids line up under each other; a ragged edge makes a long list
        unreadable, which is why the list is in a fixed-width font."""
        widths = {len(epoch_marker(d, c)) for d in (True, False) for c in (True, False)}
        assert widths == {2}

    def test_a_row_is_its_marker_then_its_epoch_id(self):
        assert epoch_item("t0000_00", True, False) == "*  t0000_00"

    def test_labeling_without_decoding_cannot_be_shown(self):
        """It cannot happen -- a control_stimulus_ids document depends on a
        stimulus_presentation -- and showing "c" alone would suggest it can."""
        assert epoch_marker(False, True) == "  "


class TestValueToText:
    def test_an_integer_valued_float_loses_its_trailing_zero(self):
        assert value_to_text(30.0) == "30"

    def test_a_fractional_value_is_kept(self):
        assert value_to_text(0.25) == "0.25"

    def test_a_string_is_itself(self):
        assert value_to_text("sinusoid") == "sinusoid"

    def test_a_list_of_numbers_reads_as_matlabs_row_vector(self):
        assert value_to_text([0, 90, 180]) == "[0 90 180]"

    def test_a_mixed_list_is_braced(self):
        assert value_to_text([1, "a"]) == "{1, a}"

    def test_a_bool_reads_as_matlab_writes_it(self):
        assert value_to_text(True) == "true"

    def test_an_unrenderable_value_names_its_type_rather_than_raising(self):
        assert value_to_text(object()) == "<object>"


class TestPanels:
    def test_each_varying_parameter_gets_a_line(self):
        lines = varies_lines([{"parameter": "angle", "values": [0, 90]}])
        assert lines == ["angle = [0 90]"]

    def test_nothing_varying_says_so_rather_than_showing_an_empty_panel(self):
        """An empty panel and an undecoded epoch look identical and mean
        opposite things."""
        assert varies_lines([]) == ["(nothing varies across these stimuli)"]

    def test_constants_become_parameter_value_rows(self):
        rows = constant_rows([{"parameter": "sFrequency", "value": 0.5}])
        assert rows == [["sFrequency", "0.5"]]


# ----------------------------------------------------------------------
# the model, without Qt
# ----------------------------------------------------------------------
class TestProbes:
    def test_only_stimulator_probes_are_asked_for(self):
        session = FakeSession([FakeProbe()])
        _app(session)
        assert session.probe_type_asked == PROBE_TYPE

    def test_a_session_that_cannot_answer_lists_nothing(self):
        class Broken(FakeSession):
            def getprobes(self, **kwargs):
                raise RuntimeError("no daq systems")

        assert _app(Broken()).stimulators == []

    def test_the_dropdown_shows_one_element_string_per_stimulator(self):
        app = _app(FakeSession([FakeProbe(reference=1), FakeProbe(reference=2)]))
        assert app.probe_labels() == ["vhvis_spike2 | 1", "vhvis_spike2 | 2"]

    def test_the_session_path_is_read_for_the_subtitle(self):
        assert _app(FakeSession([FakeProbe()])).session_path() == "/data/s1"

    def test_a_session_that_will_not_name_its_path_gives_empty(self):
        """A path is decoration in the subtitle; a session that cannot
        produce one must still open the window."""

        class NoPath(FakeSession):
            def getpath(self):
                raise RuntimeError("no path")

        assert _app(NoPath([FakeProbe()])).session_path() == ""


class TestDecodedEpochs:
    def test_an_undecoded_probe_reports_none(self):
        app = _app(FakeSession([FakeProbe()]))
        assert app.decoded_epochs == []
        assert app.pres_docs == []

    def test_a_presentation_document_marks_its_epoch(self):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _app(session)
        assert app.decoded_epochs == ["e1"]

    def test_the_documents_are_cached_alongside_their_epochs(self):
        """One database read per reload, not one per selection change: the
        panels are refilled on every click."""
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _app(session)
        assert [d.id for d in app.pres_docs] == ["d1"]

    def test_a_document_with_no_readable_epoch_is_skipped(self):
        broken = FakeDocument("d0", {"stimulus_presentation": {}})
        session = FakeSession([FakeProbe()], [broken, presentation_doc("d1", "e1")])
        assert _app(session).decoded_epochs == ["e1"]

    def test_an_unreadable_database_means_nothing_decoded(self):
        class Broken(FakeSession):
            def database_search(self, query):
                raise RuntimeError("database down")

        assert _app(Broken([FakeProbe()])).decoded_epochs == []


class TestControlLabeledEpochs:
    def test_a_control_document_marks_the_epoch_of_its_presentation(self):
        """The link is indirect -- control_stimulus_ids depends on the
        presentation, not the probe -- so this is the mapping that decides
        whether "*c" ever appears."""
        session = FakeSession(
            [FakeProbe()], [presentation_doc("d1", "e1"), control_doc("c1", "d1")]
        )
        assert _app(session).control_labeled_epochs == ["e1"]

    def test_a_control_document_for_another_probe_is_ignored(self):
        session = FakeSession(
            [FakeProbe()], [presentation_doc("d1", "e1"), control_doc("c9", "someone-else")]
        )
        assert _app(session).control_labeled_epochs == []

    def test_nothing_decoded_means_nothing_labeled(self):
        session = FakeSession([FakeProbe()], [control_doc("c1", "d1")])
        assert _app(session).control_labeled_epochs == []


class TestEpochRows:
    def test_each_epoch_gets_a_row_in_epoch_table_order(self):
        app = _app(FakeSession([FakeProbe(epochs=("e1", "e2"))]))
        assert app.epoch_items() == ["   e1", "   e2"]

    def test_a_decoded_epoch_is_starred_in_its_row(self):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e2")])
        assert _app(session).epoch_items() == ["   e1", "*  e2"]

    def test_a_labeled_epoch_shows_both_marks(self):
        session = FakeSession(
            [FakeProbe()], [presentation_doc("d1", "e1"), control_doc("c1", "d1")]
        )
        assert _app(session).epoch_items() == ["*c e1", "   e2"]


class TestButtonRules:
    def test_running_needs_a_selection(self):
        app = _app(FakeSession([FakeProbe()]))
        assert app.can_run_decoder() is False

    def test_labeling_needs_a_decoded_epoch_not_a_selection(self):
        """Labeling has no per-epoch filter, so gating it on a selection
        would misrepresent what the button does."""
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _app(session)
        assert app.can_label_controls() is True

    def test_labeling_is_refused_with_nothing_decoded(self):
        app = _app(FakeSession([FakeProbe()]))
        assert app.can_label_controls() is False


class TestRefusals:
    def test_an_empty_selection_says_what_to_do(self):
        app = _app(FakeSession([FakeProbe()]))
        assert "select one or more epochs" in app.decode_refusal([], False)

    def test_a_fully_decoded_selection_points_at_the_overwrite_box(self):
        """Pressing Run and seeing nothing happen reads as a broken app;
        this is the fix the user can actually act on."""
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _app(session)
        assert "Re-decode selected (overwrite)" in app.decode_refusal(["e1"], False)

    def test_overwrite_clears_that_refusal(self):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _app(session)
        assert app.decode_refusal(["e1"], True) == ""

    def test_a_partly_decoded_selection_is_allowed_through(self):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _app(session)
        assert app.decode_refusal(["e1", "e2"], False) == ""

    def test_labeling_with_no_probe_says_so(self):
        app = _app(FakeSession())
        assert "Choose a stimulator probe" in app.label_refusal(False)

    def test_labeling_with_nothing_decoded_says_to_decode_first(self):
        app = _app(FakeSession([FakeProbe()]))
        assert "Run the decoder first" in app.label_refusal(False)

    def test_labeling_an_already_labeled_probe_points_at_the_overwrite_box(self):
        session = FakeSession(
            [FakeProbe(epochs=("e1",))],
            [presentation_doc("d1", "e1"), control_doc("c1", "d1")],
        )
        app = _app(session)
        assert "already has its control stimuli labeled" in app.label_refusal(False)

    def test_a_partly_labeled_probe_is_allowed_through(self):
        session = FakeSession(
            [FakeProbe(epochs=("e1", "e2"))],
            [
                presentation_doc("d1", "e1"),
                presentation_doc("d2", "e2"),
                control_doc("c1", "d1"),
            ],
        )
        app = _app(session)
        assert app.label_refusal(False) == ""


class TestStimulusInfo:
    def test_no_selection_asks_for_one(self):
        app = _app(FakeSession([FakeProbe()]))
        lines, rows = app.stimulus_info([])
        assert lines == [SELECT_EPOCHS_MESSAGE]
        assert rows == []

    def test_an_undecoded_selection_says_to_run_the_decoder(self):
        app = _app(FakeSession([FakeProbe()]))
        lines, _ = app.stimulus_info(["e1"])
        assert lines == [NOT_DECODED_MESSAGE]

    def test_a_decoded_selection_reports_what_varies(self):
        stimuli = [
            {"parameters": {"isblank": 0, "angle": 0, "sFrequency": 0.5}},
            {"parameters": {"isblank": 0, "angle": 90, "sFrequency": 0.5}},
        ]
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1", stimuli=stimuli)])
        app = _app(session)

        lines, rows = app.stimulus_info(["e1"])

        assert lines == ["angle = [0 90]"]
        assert ["sFrequency", "0.5"] in rows

    def test_blank_stimuli_are_left_out_of_the_comparison(self):
        """A blank differs from every real stimulus in every parameter;
        counting it would report everything as varying."""
        stimuli = [
            {"parameters": {"isblank": 0, "angle": 45}},
            {"parameters": {"isblank": 1}},
        ]
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1", stimuli=stimuli)])
        app = _app(session)

        lines, rows = app.stimulus_info(["e1"])

        assert lines == ["(nothing varies across these stimuli)"]
        assert ["angle", "45"] in rows

    def test_stimuli_that_cannot_be_read_are_reported_in_the_panel(self):
        broken = FakeDocument("d1", {"epochid": {"epochid": "e1"}, "stimulus_presentation": None})
        session = FakeSession([FakeProbe()], [broken])
        app = _app(session)

        lines, _ = app.stimulus_info(["e1"])

        assert lines[0].startswith("(could not read stimuli")


# ----------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_the_app_is_found_by_scanning_ndi_gui_app(self):
        names = [app["Name"] for app in SessionApp.list(["ndi.gui.app"])]
        assert "Stimulus Decoder" in names

    def test_it_reports_the_class_launch_can_resolve(self):
        from ndi.gui.app.session_app import resolve_class

        entry = next(a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "Stimulus Decoder")
        assert resolve_class(entry["Class"]) is stimulusDecoder

    def test_it_groups_under_the_stimulus_submenu(self):
        """Verbatim from MATLAB: the Category is the submenu's title."""
        assert stimulusDecoder.Category == "Stimulus"

    def test_the_menu_label_is_matlabs_verbatim(self):
        assert stimulusDecoder.Name == "Stimulus Decoder"

    def test_its_category_reaches_the_menu_record(self):
        entry = next(a for a in SessionApp.list(["ndi.gui.app"]) if a["Name"] == "Stimulus Decoder")
        assert entry["Category"] == "Stimulus"


class TestNaming:
    def test_every_public_method_is_snake_case(self):
        """The house style for new code, and what issue #122 asks of each
        ported app. The CLASS name stays MATLAB's, matching the .m file."""
        import re

        offenders = [
            name
            for name in vars(stimulusDecoder)
            if not name.startswith("_")
            and name not in ("Name", "Category")
            and re.search(r"[a-z][A-Z]", name)
        ]
        assert offenders == []


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


def _window(session):
    _qt_or_skip()
    return stimulusDecoder(session)


class TestWindow:
    def test_the_window_names_the_session_and_is_tagged(self):
        app = _window(FakeSession([FakeProbe()]))
        assert app.figure.windowTitle() == "Stimulus Decoder: 2024-01-01"
        assert app.figure.objectName() == WINDOW_TAG
        app.close()

    def test_it_opens_where_matlab_opens_it(self):
        app = _window(FakeSession([FakeProbe()]))
        assert app.position == DEFAULT_POSITION
        app.close()

    def test_the_dropdown_lists_the_stimulators(self):
        app = _window(FakeSession([FakeProbe(reference=1), FakeProbe(reference=2)]))
        items = [app.probe_dropdown.itemText(i) for i in range(app.probe_dropdown.count())]
        assert items == ["vhvis_spike2 | 1", "vhvis_spike2 | 2"]
        app.close()

    def test_a_session_with_no_stimulators_says_so_in_the_dropdown(self):
        app = _window(FakeSession())
        assert app.probe_dropdown.itemText(0) == NO_STIMULATORS
        assert app.probe_dropdown.isEnabled() is False
        app.close()

    def test_a_probe_with_no_epochs_says_so_in_the_list(self):
        app = _window(FakeSession([FakeProbe(epochs=())]))
        assert app.epoch_list.item(0).text() == NO_EPOCHS
        assert app.selected_epoch_ids() == []
        app.close()

    def test_the_list_shows_one_row_per_epoch(self):
        app = _window(FakeSession([FakeProbe(epochs=("e1", "e2"))]))
        assert [app.epoch_list.item(i).text() for i in range(app.epoch_list.count())] == [
            "   e1",
            "   e2",
        ]
        app.close()

    def test_a_selection_names_the_epochs_it_looks_like_it_names(self):
        app = _window(FakeSession([FakeProbe(epochs=("e1", "e2"))]))
        app.epoch_list.item(1).setSelected(True)
        assert app.selected_epoch_ids() == ["e2"]
        app.close()

    def test_run_is_enabled_only_once_an_epoch_is_selected(self):
        app = _window(FakeSession([FakeProbe()]))
        assert app.run_button.isEnabled() is False

        app.epoch_list.item(0).setSelected(True)

        assert app.run_button.isEnabled() is True
        app.close()

    def test_the_label_button_follows_the_probe_not_the_selection(self):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _window(session)
        assert app.control_button.isEnabled() is True
        app.close()

    def test_a_placeholder_row_selects_no_epochs(self):
        """The "(no stimulus epochs)" row is text, not an epoch; treating it
        as one would ask the decoder for an epoch that does not exist."""
        app = _window(FakeSession([FakeProbe(epochs=())]))
        app.epoch_list.item(0).setSelected(True)
        assert app.selected_epoch_ids() == []
        assert app.run_button.isEnabled() is False
        app.close()

    def test_a_reload_keeps_the_selection_by_epoch_even_as_markers_change(self):
        """The row of the epoch just decoded is exactly the one whose text
        changes, so a selection kept by text would drop it."""
        session = FakeSession([FakeProbe(epochs=("e1", "e2"))])
        app = _window(session)
        app.epoch_list.item(1).setSelected(True)

        session.docs.append(presentation_doc("d1", "e2"))
        rows = app.reload_epochs()

        assert rows == ["   e1", "*  e2"]
        assert app.selected_epoch_ids() == ["e2"]
        app.close()

    def test_the_panels_fill_from_the_selection(self):
        stimuli = [
            {"parameters": {"isblank": 0, "angle": 0}},
            {"parameters": {"isblank": 0, "angle": 90}},
        ]
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1", stimuli=stimuli)])
        app = _window(session)

        app.epoch_list.item(0).setSelected(True)

        assert app.varies_text.toPlainText() == "angle = [0 90]"
        app.close()

    def test_epochs_that_cannot_be_read_are_reported_in_the_list(self):
        class Unreadable(FakeProbe):
            def epochtable(self):
                raise RuntimeError("epoch table is corrupt")

        app = _window(FakeSession([Unreadable()]))
        assert app.epoch_list.item(0).text().startswith("(could not read epochs")
        assert app.run_button.isEnabled() is False
        app.close()


class TestRunning:
    def test_running_the_decoder_reports_what_it_wrote(self, monkeypatch):
        session = FakeSession([FakeProbe()])
        app = _window(session)
        app.epoch_list.item(0).setSelected(True)

        calls = {}

        class FakeDecoder:
            def __init__(self, s):
                calls["session"] = s

            def parse_stimuli(self, probe, overwrite, epochs):
                calls["args"] = (probe, overwrite, list(epochs))
                return [presentation_doc("d1", "e1")], []

        monkeypatch.setattr("ndi.app.stimulus.decoder.ndi_app_stimulus_decoder", FakeDecoder)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        newdocs = app.run_decoder()

        assert len(newdocs) == 1
        assert calls["args"][1] is False
        assert calls["args"][2] == ["e1"]
        app.close()

    def test_the_overwrite_box_reaches_the_decoder(self, monkeypatch):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _window(session)
        app.epoch_list.item(0).setSelected(True)
        app.overwrite_checkbox.setChecked(True)

        seen = {}

        class FakeDecoder:
            def __init__(self, s):
                pass

            def parse_stimuli(self, probe, overwrite, epochs):
                seen["overwrite"] = overwrite
                return [], []

        monkeypatch.setattr("ndi.app.stimulus.decoder.ndi_app_stimulus_decoder", FakeDecoder)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.run_decoder()

        assert seen["overwrite"] is True
        app.close()

    def test_a_fully_decoded_selection_is_refused_without_calling_the_decoder(self, monkeypatch):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _window(session)
        app.epoch_list.item(0).setSelected(True)

        def boom(*a, **k):
            raise AssertionError("the decoder must not run")

        monkeypatch.setattr("ndi.app.stimulus.decoder.ndi_app_stimulus_decoder", boom)
        seen = {}
        monkeypatch.setattr(app, "alert", lambda m, t, **k: seen.update(message=m, title=t))

        assert app.run_decoder() == []
        assert seen["title"] == "Already decoded"
        app.close()

    def test_a_decoder_that_raises_is_reported_and_the_buttons_come_back(self, monkeypatch):
        session = FakeSession([FakeProbe()])
        app = _window(session)
        app.epoch_list.item(0).setSelected(True)

        class FakeDecoder:
            def __init__(self, s):
                pass

            def parse_stimuli(self, *a):
                raise RuntimeError("stimulus file is missing")

        monkeypatch.setattr("ndi.app.stimulus.decoder.ndi_app_stimulus_decoder", FakeDecoder)
        seen = {}
        monkeypatch.setattr(app, "alert", lambda m, t, **k: seen.update(message=m, title=t))

        assert app.run_decoder() == []
        assert seen["title"] == "Decoding failed"
        assert "stimulus file is missing" in seen["message"]
        assert app.run_button.isEnabled() is True
        app.close()

    def test_labeling_control_stimuli_reports_what_it_wrote(self, monkeypatch):
        session = FakeSession([FakeProbe()], [presentation_doc("d1", "e1")])
        app = _window(session)

        class FakeTuning:
            def __init__(self, s):
                pass

            def label_control_stimuli(self, probe, overwrite):
                return [control_doc("c1", "d1")]

        monkeypatch.setattr(
            "ndi.app.stimulus.tuning_response.ndi_app_stimulus_tuning__response", FakeTuning
        )
        seen = {}
        monkeypatch.setattr(app, "alert", lambda m, t, **k: seen.update(message=m))

        cs_docs = app.run_control_labels()

        assert len(cs_docs) == 1
        assert "1 control_stimulus_ids document(s)" in seen["message"]
        app.close()

    def test_labeling_is_refused_with_nothing_decoded(self, monkeypatch):
        app = _window(FakeSession([FakeProbe()]))

        def boom(*a, **k):
            raise AssertionError("labeling must not run")

        monkeypatch.setattr(
            "ndi.app.stimulus.tuning_response.ndi_app_stimulus_tuning__response", boom
        )
        seen = {}
        monkeypatch.setattr(app, "alert", lambda m, t, **k: seen.update(title=t))

        assert app.run_control_labels() == []
        assert seen["title"] == "Nothing to label"
        app.close()

    def test_the_markers_refresh_after_a_run(self, monkeypatch):
        session = FakeSession([FakeProbe(epochs=("e1",))])
        app = _window(session)
        app.epoch_list.item(0).setSelected(True)

        class FakeDecoder:
            def __init__(self, s):
                pass

            def parse_stimuli(self, probe, overwrite, epochs):
                session.docs.append(presentation_doc("d1", "e1"))
                return [session.docs[-1]], []

        monkeypatch.setattr("ndi.app.stimulus.decoder.ndi_app_stimulus_decoder", FakeDecoder)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.run_decoder()

        assert app.epoch_list.item(0).text() == "*  e1"
        app.close()


class TestLaunching:
    def test_launch_constructs_it_with_the_session(self):
        _qt_or_skip()
        session = FakeSession([FakeProbe()])
        app = SessionApp.launch("ndi.gui.app.stimulus_decoder.stimulusDecoder", session)
        assert isinstance(app, stimulusDecoder)
        assert app.session is session
        app.close()
