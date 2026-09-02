"""Tests for ndi.gui.app.katz_exporter.

MATLAB counterpart: ndi.gui.app.katzExporter

The quality filter carries the weight. Its rule is
ndi.fun.ensemble.read's -- quality is a hard filter, and an unrated neuron
fails any active one unless "Keep unrated" overrides -- and the window's whole
purpose is to show the effect of that rule BEFORE an export rather than after.
So the preview, the summary and the export button's enablement are checked
against it directly, with no display attached; the widgets are tested under
QT_QPA_PLATFORM=offscreen and skip where Qt cannot start.

The neurons here are fakes: what ndi.fun.ensemble.neuron_quality reads out of
a database has its own tests, and what this app does with the answer is the
part that lives here.
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from ndi.gui.app import katzExporter
from ndi.gui.app.katz_exporter import (
    DEFAULT_POSITION,
    DEFAULT_POST_STIM,
    DEFAULT_PRE_STIM,
    NO_ENSEMBLES_ITEM,
    NO_EPOCHS_ITEM,
    NO_NEURONS_ITEM,
    TITLE_TEXT,
    UNRATED_LABEL,
    WINDOW_TAG,
    ensemble_items,
    epoch_ids,
    neuron_row,
    passes_filter,
    session_path,
    suggest_file_name,
    summary_message,
)
from ndi.gui.app.session_app import SessionApp

NAN = float("nan")


# ----------------------------------------------------------------------
# fakes
# ----------------------------------------------------------------------
class FakeStimulator:
    def __init__(self, name="stim", reference=1):
        self.name = name
        self.reference = reference
        self.id = f"id_{name}"

    def elementstring(self):
        return f"{self.name} | {self.reference}"


class FakeEnsemble:
    """An ensemble as the app uses one: epochs, neurons, an underlying probe."""

    def __init__(self, epochs=("e1",), neurons=(), underlying="probe", raises=False, name="ens"):
        self.epochs = list(epochs)
        self.neurons = list(neurons)  # (id, name) pairs
        self.underlying_element = underlying
        self.raises = raises
        self.name = name
        self.reference = 1
        self.id = "id_ensemble"

    def elementstring(self):
        return f"{self.name} | {self.reference}"

    def epochtable(self):
        return ([{"epoch_id": e} for e in self.epochs], "hash")

    def neuron_ids(self, epoch):
        if self.raises:
            raise RuntimeError("this ensemble cannot be read")
        return [nid for nid, _ in self.neurons]

    def neuron_names(self, epoch):
        return [name for _, name in self.neurons]


class FakeSession:
    reference = "test_session"
    path = "/data/test_session"

    def __init__(self, ensembles=(), stimulators=(), fail_elements=False, fail_probes=False):
        self.ensembles = list(ensembles)
        self.stimulators = list(stimulators)
        self.fail_elements = fail_elements
        self.fail_probes = fail_probes
        self.getelements_calls = []
        self.getprobes_calls = []

    def getelements(self, **kwargs):
        self.getelements_calls.append(kwargs)
        if self.fail_elements:
            raise RuntimeError("this session cannot list elements")
        return list(self.ensembles)

    def getprobes(self, **kwargs):
        self.getprobes_calls.append(kwargs)
        if self.fail_probes:
            raise RuntimeError("this session cannot list probes")
        return list(self.stimulators)

    def database_search(self, query):
        return []


def exporter(session=None, quality=None, *, build=False, **session_kwargs):
    """An app over a fake session, with the quality lookup stubbed.

    QUALITY is (quality_numbers, quality_labels) as
    ndi.fun.ensemble.neuron_quality returns them.
    """
    numbers, labels = quality if quality is not None else (np.zeros(0), [])

    class _Exporter(katzExporter):
        def refresh_neurons(self):
            # Only the neuron_quality call is stubbed; the caching, filtering
            # and redraw around it are the real ones.
            import ndi.fun.ensemble as ensemble_module

            original = ensemble_module.neuron_quality
            ensemble_module.neuron_quality = lambda s, ids: (numbers, list(labels))
            try:
                return super().refresh_neurons()
            finally:
                ensemble_module.neuron_quality = original

    return _Exporter(session or FakeSession(**session_kwargs), build=build)


# ----------------------------------------------------------------------
# the rule
# ----------------------------------------------------------------------
class TestPassesFilter:
    def test_no_filter_passes_everything(self):
        assert passes_filter(1, "poor", None, [], False)
        assert passes_filter(NAN, "", None, [], False)

    def test_a_quality_below_the_minimum_fails(self):
        assert not passes_filter(1, "fair", 2, [], False)
        assert passes_filter(2, "fair", 2, [], False)

    def test_a_label_outside_the_set_fails(self):
        assert passes_filter(3, "good", None, ["good", "great"], False)
        assert not passes_filter(3, "fair", None, ["good", "great"], False)

    def test_an_unrated_neuron_fails_an_active_filter(self):
        assert not passes_filter(NAN, "", 2, [], False)
        assert not passes_filter(NAN, "", None, ["good"], False)

    def test_keep_unrated_rescues_only_the_unrated(self):
        """It overrides for a neuron with no quality document, and for no
        other -- a rated neuron below the minimum still fails."""
        assert passes_filter(NAN, "", 2, [], True)
        assert not passes_filter(1, "fair", 2, [], True)

    def test_keep_unrated_does_nothing_without_a_filter(self):
        assert passes_filter(NAN, "", None, [], False)
        assert passes_filter(NAN, "", None, [], True)

    def test_both_filters_must_pass(self):
        assert not passes_filter(3, "fair", 2, ["good"], False)
        assert passes_filter(3, "good", 2, ["good"], False)

    def test_none_is_unrated_too(self):
        assert not passes_filter(None, "", 2, [], False)
        assert passes_filter(None, "", 2, [], True)


class TestRows:
    def test_a_row_shows_quality_and_label(self):
        assert neuron_row("cell_1", 3, "good", True) == "  cell_1             | q=  3 | good"

    def test_an_excluded_row_is_marked(self):
        assert neuron_row("cell_1", 1, "poor", False).startswith("x ")

    def test_an_unrated_row_says_so(self):
        row = neuron_row("cell_1", NAN, "", True)
        assert "q=  -" in row
        assert row.endswith(UNRATED_LABEL)

    def test_the_summary_counts_both_ways(self):
        assert summary_message(2, 5) == "2 of 5 neurons pass the quality filter (x = excluded)"

    def test_no_neurons_means_no_summary(self):
        assert summary_message(0, 0) == ""


class TestFileName:
    def test_it_names_session_ensemble_and_epoch(self):
        assert suggest_file_name("sess", "ens", "e1") == "sess_ens_e1_blech.h5"

    def test_whitespace_is_squashed(self):
        assert suggest_file_name("my sess", "the ens", "ep 1") == "my_sess_the_ens_ep_1_blech.h5"

    def test_missing_parts_still_yield_a_name(self):
        assert suggest_file_name("", "", "") == "___blech.h5"


class TestSessionPath:
    def test_it_reads_the_path_attribute(self):
        assert session_path(FakeSession()) == "/data/test_session"

    def test_it_prefers_getpath_where_there_is_one(self):
        class WithGetPath(FakeSession):
            def getpath(self):
                return "/from/getpath"

        assert session_path(WithGetPath()) == "/from/getpath"

    def test_a_session_that_will_not_say_has_no_path(self):
        class Silent:
            pass

        assert session_path(Silent()) == ""


class TestItemsAndEpochs:
    def test_one_label_per_element(self):
        assert ensemble_items([FakeEnsemble(name="a"), FakeEnsemble(name="b")]) == [
            "a | 1",
            "b | 1",
        ]

    def test_an_element_that_cannot_name_itself_still_gets_a_row(self):
        class Nameless:
            def elementstring(self):
                raise RuntimeError("no")

        assert ensemble_items([Nameless()]) == ["Nameless"]

    def test_epochs_come_off_the_epoch_table(self):
        assert epoch_ids(FakeEnsemble(epochs=("e1", "e2"))) == ["e1", "e2"]

    def test_an_unreadable_ensemble_offers_no_epochs(self):
        class Broken:
            def epochtable(self):
                raise RuntimeError("no epoch table")

        assert epoch_ids(Broken()) == []


# ----------------------------------------------------------------------
# the model
# ----------------------------------------------------------------------
class TestLoading:
    def test_it_asks_for_ensembles_and_stimulators(self):
        session = FakeSession(ensembles=[FakeEnsemble()], stimulators=[FakeStimulator()])
        app = exporter(session)
        assert session.getelements_calls == [{"element.type": "ensemble"}]
        assert session.getprobes_calls == [{"type": "stimulator"}]
        assert app.selected_ensemble() is session.ensembles[0]
        assert app.selected_stimulator() is session.stimulators[0]

    def test_a_session_that_cannot_list_has_neither(self):
        app = exporter(FakeSession(fail_elements=True, fail_probes=True))
        assert app.ensembles == []
        assert app.stimulators == []
        assert app.selected_ensemble() is None
        assert app.selected_stimulator() is None

    def test_the_first_epoch_is_chosen(self):
        app = exporter(FakeSession(ensembles=[FakeEnsemble(epochs=("e1", "e2"))]))
        assert app.epoch == "e1"
        assert app.epoch_choices() == ["e1", "e2"]

    def test_no_ensemble_means_no_epoch(self):
        assert exporter(FakeSession()).epoch == ""


class TestNeurons:
    def _app(self, numbers, labels, names=("a", "b", "c")):
        neurons = [(f"id_{n}", n) for n in names]
        session = FakeSession(
            ensembles=[FakeEnsemble(neurons=neurons)], stimulators=[FakeStimulator()]
        )
        return exporter(session, quality=(np.array(numbers, dtype=float), list(labels)))

    def test_the_cache_carries_name_quality_and_label(self):
        app = self._app([3, 1, NAN], ["good", "poor", ""])
        assert [info["name"] for info in app.neuron_info] == ["a", "b", "c"]
        assert app.neuron_info[0]["quality_label"] == "good"
        assert math.isnan(app.neuron_info[2]["quality_number"])

    def test_the_label_choices_are_those_present(self):
        app = self._app([3, 1, NAN], ["good", "poor", ""])
        assert app.quality_labels_present() == ["good", "poor"]

    def test_everything_passes_with_no_filter(self):
        app = self._app([3, 1, NAN], ["good", "poor", ""])
        assert app.apply_filter() == 3
        assert app.summary_text().startswith("3 of 3")

    def test_a_minimum_excludes_the_low_and_the_unrated(self):
        app = self._app([3, 1, NAN], ["good", "poor", ""])
        app.min_quality_enabled = True
        app.min_quality = 2
        assert app.apply_filter() == 1
        assert [info["passes"] for info in app.neuron_info] == [True, False, False]

    def test_keep_unrated_brings_back_only_the_unrated(self):
        app = self._app([3, 1, NAN], ["good", "poor", ""])
        app.min_quality_enabled = True
        app.min_quality = 2
        app.keep_unrated = True
        assert app.apply_filter() == 2
        assert [info["passes"] for info in app.neuron_info] == [True, False, True]

    def test_a_label_selection_filters(self):
        app = self._app([3, 1, NAN], ["good", "poor", ""])
        app.quality_labels = ["poor"]
        assert app.apply_filter() == 1
        assert [info["passes"] for info in app.neuron_info] == [False, True, False]

    def test_the_rows_mark_the_excluded(self):
        app = self._app([3, 1], ["good", "poor"], names=("a", "b"))
        app.min_quality_enabled = True
        app.min_quality = 2
        rows = app.neuron_rows()
        assert rows[0].startswith("  a")
        assert rows[1].startswith("x b")

    def test_no_neurons_says_so(self):
        app = exporter(FakeSession(ensembles=[FakeEnsemble(neurons=())]))
        assert app.neuron_rows() == [NO_NEURONS_ITEM]
        assert app.summary_text() == ""

    def test_a_failed_read_is_reported_in_the_list(self):
        """'could not read' and 'no neurons' are different answers."""
        session = FakeSession(ensembles=[FakeEnsemble(raises=True)])
        app = exporter(session)
        assert app.read_error == "this ensemble cannot be read"
        assert app.neuron_rows() == ["(could not read neurons: this ensemble cannot be read)"]
        assert app.summary_text() == ""

    def test_a_label_that_vanished_is_dropped_from_the_selection(self):
        app = self._app([3, 1], ["good", "poor"], names=("a", "b"))
        app.quality_labels = ["good", "gone"]
        app.refresh_neurons()
        assert app.quality_labels == ["good"]


class TestExportGating:
    def _ready(self):
        session = FakeSession(
            ensembles=[FakeEnsemble(neurons=[("id_a", "a")])],
            stimulators=[FakeStimulator()],
        )
        return exporter(session, quality=(np.array([3.0]), ["good"]))

    def test_a_complete_selection_can_export(self):
        assert self._ready().can_export()

    def test_no_stimulator_cannot(self):
        app = exporter(
            FakeSession(ensembles=[FakeEnsemble(neurons=[("id_a", "a")])]),
            quality=(np.array([3.0]), ["good"]),
        )
        assert not app.can_export()

    def test_no_ensemble_cannot(self):
        assert not exporter(FakeSession(stimulators=[FakeStimulator()])).can_export()

    def test_a_filter_that_excludes_everything_cannot(self):
        app = self._ready()
        app.min_quality_enabled = True
        app.min_quality = 5
        assert not app.can_export()

    def test_the_default_name_uses_the_selection(self):
        assert self._ready().default_file_name() == "test_session_ens_e1_blech.h5"


class TestExport:
    def _app(self, monkeypatch, **kwargs):
        session = FakeSession(
            ensembles=[FakeEnsemble(neurons=[("id_a", "a")], **kwargs)],
            stimulators=[FakeStimulator()],
        )
        app = exporter(session, quality=(np.array([3.0]), ["good"]))
        calls = []
        monkeypatch.setattr(
            "ndi.fun.export.blech_clust",
            lambda *args, **kw: calls.append((args, kw)),
        )
        return app, calls

    def test_it_passes_the_selection_and_the_filter_through(self, monkeypatch):
        app, calls = self._app(monkeypatch)
        app.min_quality_enabled = True
        app.min_quality = 2
        app.quality_labels = ["good"]
        app.keep_unrated = True
        app.pre_stim = 1500
        app.post_stim = 4000
        app.export("/tmp/out.h5")

        (stimulator, probe, epoch, outputfile), kwargs = calls[0]
        assert stimulator is app.stimulators[0]
        assert probe == "probe"
        assert epoch == "e1"
        assert outputfile == "/tmp/out.h5"
        assert kwargs["ensemble"] is app.ensembles[0]
        assert kwargs["min_quality"] == 2
        assert kwargs["quality_label"] == ["good"]
        assert kwargs["keep_unrated"] is True
        assert kwargs["pre_stim"] == 1500
        assert kwargs["post_stim"] == 4000

    def test_an_inactive_minimum_is_not_sent(self, monkeypatch):
        app, calls = self._app(monkeypatch)
        app.export("/tmp/out.h5")
        assert calls[0][1]["min_quality"] is None

    def test_an_ensemble_with_no_probe_says_so(self, monkeypatch):
        app, _ = self._app(monkeypatch, underlying=None)
        with pytest.raises(ValueError, match="no underlying probe"):
            app.export("/tmp/out.h5")

    def test_an_incomplete_selection_says_so(self, monkeypatch):
        app, _ = self._app(monkeypatch)
        app.epoch = ""
        with pytest.raises(ValueError, match="Select an ensemble"):
            app.export("/tmp/out.h5")


class TestDefaults:
    def test_the_stimulus_window_is_blech_clusts(self):
        assert (DEFAULT_PRE_STIM, DEFAULT_POST_STIM) == (2000, 5000)

    def test_it_is_a_session_app_in_the_exporters_submenu(self):
        assert issubclass(katzExporter, SessionApp)
        assert katzExporter.Name == "Katz Lab Exporter"
        assert katzExporter.Category == "Exporters"

    def test_discovery_finds_it(self):
        found = {app["Name"]: app["Class"] for app in SessionApp.list()}
        assert found["Katz Lab Exporter"] == "ndi.gui.app.katz_exporter.katzExporter"


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


def built(quality=None, **session_kwargs):
    return exporter(FakeSession(**session_kwargs), quality=quality, build=True)


class TestWindow:
    def _ready(self):
        return exporter(
            FakeSession(
                ensembles=[FakeEnsemble(neurons=[("id_a", "a"), ("id_b", "b")])],
                stimulators=[FakeStimulator()],
            ),
            quality=(np.array([3.0, 1.0]), ["good", "poor"]),
            build=True,
        )

    def test_it_is_titled_and_tagged(self):
        _qt_or_skip()
        app = built()
        assert app.figure.objectName() == WINDOW_TAG
        assert app.figure.windowTitle() == "Katz Lab Exporter: test_session"
        assert app.title_label.text() == TITLE_TEXT

    def test_the_geometry_is_matlabs(self):
        _qt_or_skip()
        assert DEFAULT_POSITION == (100, 100, 680, 620)
        assert built().figure.width() == 680

    def test_the_subtitle_names_the_session_and_path(self):
        _qt_or_skip()
        assert "Session: test_session" in built().subtitle_label.text()
        assert "/data/test_session" in built().subtitle_label.text()

    def test_the_dropdowns_show_placeholders_when_empty(self):
        _qt_or_skip()
        app = built()
        assert app.ensemble_dropdown.itemText(0) == NO_ENSEMBLES_ITEM
        assert app.epoch_dropdown.itemText(0) == NO_EPOCHS_ITEM

    def test_the_dropdowns_fill_from_the_session(self):
        _qt_or_skip()
        app = self._ready()
        assert app.ensemble_dropdown.itemText(0) == "ens | 1"
        assert app.stimulator_dropdown.itemText(0) == "stim | 1"
        assert app.epoch_dropdown.itemText(0) == "e1"

    def test_the_preview_lists_the_neurons(self):
        _qt_or_skip()
        app = self._ready()
        assert app.neuron_list.count() == 2
        assert app.summary_label.text().startswith("2 of 2")

    def test_export_starts_live_and_dies_with_the_filter(self):
        _qt_or_skip()
        app = self._ready()
        assert app.export_button.isEnabled()
        app.min_quality_checkbox.setChecked(True)
        app.min_quality_spinner.setValue(5)
        assert not app.export_button.isEnabled()
        assert app.summary_label.text().startswith("0 of 2")

    def test_the_minimum_spinner_follows_its_checkbox(self):
        _qt_or_skip()
        app = self._ready()
        assert not app.min_quality_spinner.isEnabled()
        app.min_quality_checkbox.setChecked(True)
        assert app.min_quality_spinner.isEnabled()

    def test_selecting_a_label_filters_the_preview(self):
        _qt_or_skip()
        app = self._ready()
        assert [
            app.quality_label_list.item(i).text() for i in range(app.quality_label_list.count())
        ] == ["good", "poor"]
        app.quality_label_list.item(0).setSelected(True)
        assert app.quality_labels == ["good"]
        assert app.summary_label.text().startswith("1 of 2")

    def test_the_stimulus_window_spinners_reach_the_model(self):
        _qt_or_skip()
        app = self._ready()
        app.pre_stim_spinner.setValue(1000)
        app.post_stim_spinner.setValue(3000)
        assert (app.pre_stim, app.post_stim) == (1000, 3000)

    def test_a_cancelled_save_dialog_exports_nothing(self, monkeypatch):
        _qt_or_skip()
        app = self._ready()
        monkeypatch.setattr(type(app), "ask_for_file", lambda self, default: "")
        called = []
        monkeypatch.setattr("ndi.fun.export.blech_clust", lambda *a, **k: called.append(1))
        assert app.do_export() is None
        assert called == []

    def test_a_successful_export_says_where_it_went(self, monkeypatch):
        _qt_or_skip()
        app = self._ready()
        monkeypatch.setattr(type(app), "ask_for_file", lambda self, default: "/tmp/out.h5")
        monkeypatch.setattr("ndi.fun.export.blech_clust", lambda *a, **k: None)
        assert app.do_export() == "/tmp/out.h5"
        title, message = app.last_alert
        assert title == "Export complete"
        assert "/tmp/out.h5" in message

    def test_a_failed_export_is_reported_not_raised(self, monkeypatch):
        _qt_or_skip()
        app = self._ready()
        monkeypatch.setattr(type(app), "ask_for_file", lambda self, default: "/tmp/out.h5")

        def boom(*args, **kwargs):
            raise RuntimeError("the disk is full")

        monkeypatch.setattr("ndi.fun.export.blech_clust", boom)
        assert app.do_export() is None
        assert app.last_alert == ("Export failed", "the disk is full")
        assert app.export_button.isEnabled()  # restored, not left dead

    def test_reload_re_reads_the_session(self):
        _qt_or_skip()
        app = self._ready()
        before = len(app.session.getelements_calls)
        app.with_wait("Loading ensembles...", app.reload_all)
        assert len(app.session.getelements_calls) == before + 1


class TestWithWait:
    def test_it_returns_what_the_work_returned(self):
        app = exporter(FakeSession())
        assert app.with_wait("working", lambda: 42) == 42

    def test_it_is_nestable(self):
        app = exporter(FakeSession())
        assert app.with_wait("outer", lambda: app.with_wait("inner", lambda: "done")) == "done"
        assert app.wait_dialog is None


if __name__ == "__main__":
    pytest.main([__file__])
