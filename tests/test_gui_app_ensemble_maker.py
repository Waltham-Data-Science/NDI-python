"""Tests for ndi.gui.app.ensemble_maker.

MATLAB counterpart: ndi.gui.app.ensembleMaker

The app is the first of MATLAB's eleven session apps to be ported, so two
kinds of thing are checked here. The first is that DISCOVERY finds it: the
navigator's Apps menu was built to fill itself from ndi.gui.app.SessionApp,
and this is the first real app to prove it does, with no change to the pane
or the menu code.

The second is the app's own decisions -- which probes are marked, which are
selected, when Make Ensemble and Plot Ensemble are usable, which epochs are
offered, and what the user is told when something fails. All of that is model
state rather than widget state (see the module docstring), so it is checked
with no display attached. ensemble_map is the exception: it is a database
walk, so it runs against a real session holding a real ensemble, where a mock
would only test the mock.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

import ndi.fun.ensemble as ens_fun
from ndi.element_timeseries import ndi_element_timeseries
from ndi.gui.app.ensemble_maker import (
    CANNOT_PLOT,
    DEFAULT_POSITION,
    EPOCH_PLACEHOLDER,
    LOADING_MESSAGE,
    MARKER,
    NO_EPOCH,
    NO_EPOCHS_ITEM,
    NO_PROBES_ITEM,
    NO_SELECTION,
    NTRODE_TYPE,
    UNMARKED,
    WINDOW_TAG,
    built_message,
    empty_ensemble_message,
    ensemble_map,
    ensembleMaker,
    epoch_choices,
    failures_message,
    if_exists_for,
    number_of_neurons,
    probe_items,
    raster_title,
    session_path,
)
from ndi.gui.app.session_app import SessionApp
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.time.clocktype import ndi_time_clocktype

CLOCK = "dev_local_time"


# ----------------------------------------------------------------------
# fakes
# ----------------------------------------------------------------------
class FakeProbe:
    def __init__(self, name, reference=1, identifier=None):
        self.name = name
        self.reference = reference
        self.id = identifier or f"id_{name}"

    def elementstring(self):
        return f"{self.name} | {self.reference}"


class FakeEnsemble:
    """An ensemble element as the app uses one: an epoch table and an id."""

    def __init__(self, epochs=(), underlying=None, raises=False):
        self.epochs = list(epochs)
        self.underlying_element = underlying
        self.raises = raises
        self.id = "id_ensemble"

    def epochtable(self):
        if self.raises:
            raise RuntimeError("no epoch table")
        # ndi.epoch.epochset.epochtable returns (table, hashvalue).
        return ([{"epoch_id": e} for e in self.epochs], "hash")


class FakeSession:
    reference = "test_session"

    def __init__(self, probes=(), fail_probes=False):
        self.probes = list(probes)
        self.fail_probes = fail_probes
        self.getprobes_calls = []

    def getprobes(self, **kwargs):
        self.getprobes_calls.append(kwargs)
        if self.fail_probes:
            raise RuntimeError("this session cannot list probes")
        return list(self.probes)

    def database_search(self, query):
        return []


def maker(probes=(), ensembles=None, *, session=None, build=False):
    """A built-less app over FAKE probes, with its ensemble lookup stubbed.

    The map from probe to ensemble is a database walk of its own (checked
    against a real session below), so here it is simply DATA: what the rest
    of the app does with it is the point.
    """

    class _Maker(ensembleMaker):
        def build_ensemble_map(self):
            return dict(ensembles or {})

    return _Maker(session or FakeSession(probes), build=build)


# ----------------------------------------------------------------------
# what the window shows
# ----------------------------------------------------------------------
class TestProbeItems:
    def test_one_label_per_probe(self):
        items = probe_items([FakeProbe("a"), FakeProbe("b")])
        assert items == [f"{UNMARKED}a | 1", f"{UNMARKED}b | 1"]

    def test_a_probe_with_an_ensemble_is_marked(self):
        items = probe_items([FakeProbe("a"), FakeProbe("b")], ["id_b"])
        assert items[0].startswith(UNMARKED)
        assert items[1].startswith(MARKER)

    def test_marked_and_unmarked_labels_line_up(self):
        """The mark is a prefix of fixed width, so the names stay in a column."""
        items = probe_items([FakeProbe("a"), FakeProbe("b")], ["id_b"])
        assert len(MARKER) == len(UNMARKED)
        assert [item[len(MARKER) :] for item in items] == ["a | 1", "b | 1"]

    def test_no_probes_is_no_labels(self):
        assert probe_items([]) == []


class TestEpochChoices:
    def test_no_ensemble_offers_the_placeholder_and_is_disabled(self):
        assert epoch_choices(None) == ([EPOCH_PLACEHOLDER], False)

    def test_an_ensemble_with_epochs_offers_them(self):
        assert epoch_choices(FakeEnsemble(["e1", "e2"])) == (["e1", "e2"], True)

    def test_an_ensemble_with_no_epochs_says_so_and_is_disabled(self):
        """A different message from the placeholder: the two states differ."""
        assert epoch_choices(FakeEnsemble([])) == ([NO_EPOCHS_ITEM], False)

    def test_an_unreadable_epoch_table_costs_the_epochs_not_the_window(self):
        assert epoch_choices(FakeEnsemble(raises=True)) == ([NO_EPOCHS_ITEM], False)

    def test_a_bare_epoch_table_is_accepted_too(self):
        """MATLAB's epochtable returns the table alone; a fake may as well."""

        class Bare:
            def epochtable(self):
                return [{"epoch_id": "e1"}]

        assert epoch_choices(Bare()) == (["e1"], True)


class TestSessionPath:
    def test_getpath_is_preferred(self):
        class S:
            path = "/wrong"

            def getpath(self):
                return "/right"

        assert session_path(S()) == "/right"

    def test_the_path_property_is_the_fallback(self):
        class S:
            path = "/only"

        assert session_path(S()) == "/only"

    def test_a_session_with_neither_reports_nothing(self):
        assert session_path(object()) == ""

    def test_a_getpath_that_raises_falls_through(self):
        class S:
            path = "/still/here"

            def getpath(self):
                raise RuntimeError("no path")

        assert session_path(S()) == "/still/here"


class TestMessages:
    def test_rebuild_maps_to_replace_and_off_to_skip(self):
        assert if_exists_for(True) == "replace"
        assert if_exists_for(False) == "skip"

    def test_built_message_counts_the_probes(self):
        assert built_message(3) == "Built ensembles for 3 probe(s)."

    def test_failures_are_one_line_each(self):
        assert failures_message(["a: boom", "b: bang"]) == "a: boom\nb: bang"

    def test_empty_ensemble_names_the_probe_and_epoch(self):
        message = empty_ensemble_message("ntrode1 | 1", "e1")
        assert "ntrode1 | 1" in message and "e1" in message

    def test_raster_title_carries_the_neuron_count(self):
        assert raster_title("p | 1", "e1", 2) == "p | 1  -  epoch e1  (2 neuron(s))"


class TestNumberOfNeurons:
    def test_from_a_dense_matrix(self):
        assert number_of_neurons({"activity": np.zeros((3, 5))}) == 3

    def test_from_a_sparse_matrix(self):
        sparse = pytest.importorskip("scipy.sparse")
        assert number_of_neurons({"activity": sparse.csr_matrix((2, 4))}) == 2

    def test_from_a_list_of_rows(self):
        assert number_of_neurons({"activity": [[0.5], [0.25]]}) == 2

    def test_no_activity_is_no_neurons(self):
        assert number_of_neurons({}) == 0


# ----------------------------------------------------------------------
# the model
# ----------------------------------------------------------------------
class TestLoading:
    def test_the_constructor_lists_the_n_trode_probes(self):
        session = FakeSession([FakeProbe("a"), FakeProbe("b")])
        app = maker(session=session)
        assert session.getprobes_calls == [{"type": NTRODE_TYPE}]
        assert app.items == [f"{UNMARKED}a | 1", f"{UNMARKED}b | 1"]

    def test_probes_with_ensembles_are_marked(self):
        app = maker([FakeProbe("a"), FakeProbe("b")], {"id_b": FakeEnsemble(["e1"])})
        assert app.have_ensemble == ["id_b"]
        assert app.items[1].startswith(MARKER)

    def test_a_session_that_cannot_list_probes_shows_the_placeholder(self):
        """MATLAB's try/catch: an empty list, not a window that will not open."""
        app = maker(session=FakeSession(fail_probes=True))
        assert app.probes == []
        assert app.items == [NO_PROBES_ITEM]
        assert app.selected_probes() == []

    def test_reload_keeps_a_selection_that_still_exists(self):
        session = FakeSession([FakeProbe("a"), FakeProbe("b")])
        app = maker(session=session)
        app.set_selection([1])
        app.reload_probes()
        assert app.selection == [1]

    def test_reload_drops_a_selection_that_no_longer_exists(self):
        session = FakeSession([FakeProbe("a"), FakeProbe("b")])
        app = maker(session=session)
        app.set_selection([0, 1])
        session.probes = [FakeProbe("a")]
        app.reload_probes()
        assert app.selection == [0]
        assert [p.name for p in app.selected_probes()] == ["a"]

    def test_reload_refreshes_the_markers(self):
        session = FakeSession([FakeProbe("a")])
        built = {}

        class _Maker(ensembleMaker):
            def build_ensemble_map(self):
                return dict(built)

        app = _Maker(session, build=False)
        assert app.items == [f"{UNMARKED}a | 1"]
        built["id_a"] = FakeEnsemble(["e1"])
        app.reload_probes()
        assert app.items == [f"{MARKER}a | 1"]


class TestSelection:
    def test_make_is_disabled_until_something_is_selected(self):
        app = maker([FakeProbe("a")])
        assert app.make_enabled is False
        app.set_selection([0])
        assert app.make_enabled is True

    def test_out_of_range_rows_are_dropped(self):
        app = maker([FakeProbe("a")])
        assert app.set_selection([0, 5, -1]) == [0]

    def test_plotting_needs_exactly_one_probe_with_an_ensemble(self):
        app = maker(
            [FakeProbe("a"), FakeProbe("b")],
            {"id_b": FakeEnsemble(["e1"])},
        )
        assert app.single_plottable_probe() == (None, None)  # nothing selected

        app.set_selection([0])  # a probe with no ensemble
        assert app.single_plottable_probe() == (None, None)
        assert app.plot_enabled is False
        assert app.epoch_items == [EPOCH_PLACEHOLDER]

        app.set_selection([0, 1])  # two probes
        assert app.single_plottable_probe() == (None, None)

        app.set_selection([1])
        probe, ensemble = app.single_plottable_probe()
        assert probe.name == "b"
        assert isinstance(ensemble, FakeEnsemble)
        assert app.plot_enabled is True
        assert app.epoch_items == ["e1"]
        assert app.epoch == "e1"

    def test_the_chosen_epoch_survives_a_reload(self):
        """A reload refreshes the markers; it must not move the plot."""
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1", "e2"])})
        app.set_selection([0])
        app.set_epoch("e2")
        app.reload_probes()
        assert app.epoch == "e2"

    def test_leaving_the_probe_forgets_the_epoch(self):
        """MATLAB's behaviour too: deselecting puts the PLACEHOLDER in the
        dropdown, so the epoch remembered on the way back is not an epoch and
        the first one is chosen instead."""
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1", "e2"])})
        app.set_selection([0])
        app.set_epoch("e2")
        app.set_selection([])
        assert app.epoch == ""
        app.set_selection([0])
        assert app.epoch == "e1"

    def test_an_epoch_that_is_no_longer_offered_is_not_kept(self):
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1", "e2"])})
        app.set_selection([0])
        app.set_epoch("e2")
        app.ensemble_map = {"id_a": FakeEnsemble(["e1"])}
        app.on_selection_changed()
        assert app.epoch == "e1"

    def test_setting_an_epoch_that_is_not_offered_changes_nothing(self):
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1"])})
        app.set_selection([0])
        assert app.set_epoch("nope") == "e1"


# ----------------------------------------------------------------------
# building
# ----------------------------------------------------------------------
class TestMakeEnsembles:
    def test_nothing_selected_says_so_and_builds_nothing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ens_fun, "all_element", lambda *a, **k: calls.append(a))
        app = maker([FakeProbe("a")])
        assert app.make_ensembles() == []
        assert calls == []
        assert app.last_alert == ("Nothing selected", NO_SELECTION)

    def test_each_selected_probe_is_built_and_skipped_by_default(self, monkeypatch):
        calls = []

        def fake_all_element(session, element, *, if_exists="skip", verbose=False, **kw):
            calls.append((element.name, if_exists, verbose))

        monkeypatch.setattr(ens_fun, "all_element", fake_all_element)
        app = maker([FakeProbe("a"), FakeProbe("b")])
        app.set_selection([0, 1])
        assert app.make_ensembles() == []
        assert calls == [("a", "skip", False), ("b", "skip", False)]
        assert app.last_alert == ("Done", built_message(2))

    def test_the_rebuild_checkbox_replaces(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            ens_fun,
            "all_element",
            lambda session, element, *, if_exists="skip", **kw: seen.append(if_exists),
        )
        app = maker([FakeProbe("a")])
        app.set_selection([0])
        app.set_rebuild(True)
        app.make_ensembles()
        assert seen == ["replace"]

    def test_one_failure_does_not_cost_the_other_probes(self, monkeypatch):
        built = []

        def fake_all_element(session, element, **kw):
            if element.name == "a":
                raise RuntimeError("boom")
            built.append(element.name)

        monkeypatch.setattr(ens_fun, "all_element", fake_all_element)
        app = maker([FakeProbe("a"), FakeProbe("b")])
        app.set_selection([0, 1])
        errors = app.make_ensembles()
        assert built == ["b"]
        assert errors == ["a | 1: boom"]
        title, message = app.last_alert
        assert title == "Some ensembles failed"
        assert "a | 1: boom" in message

    def test_building_refreshes_the_markers(self, monkeypatch):
        session = FakeSession([FakeProbe("a")])
        built = {}

        def fake_all_element(session_, element, **kw):
            built[element.id] = FakeEnsemble(["e1"])

        monkeypatch.setattr(ens_fun, "all_element", fake_all_element)

        class _Maker(ensembleMaker):
            def build_ensemble_map(self):
                return dict(built)

        app = _Maker(session, build=False)
        app.set_selection([0])
        app.make_ensembles()
        assert app.items == [f"{MARKER}a | 1"]
        assert app.make_enabled is True  # the button comes back


# ----------------------------------------------------------------------
# plotting
# ----------------------------------------------------------------------
class TestPlotEnsemble:
    def test_refuses_without_a_single_ensemble_bearing_probe(self):
        app = maker([FakeProbe("a")])
        app.set_selection([0])
        assert app.plot_ensemble() is None
        assert app.last_alert == ("Cannot plot", CANNOT_PLOT)

    def test_refuses_with_no_epoch_chosen(self):
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1"])})
        app.set_selection([0])
        app.epoch = ""  # as an ensemble whose epochs vanished under it would be
        assert app.plot_ensemble() is None
        assert app.last_alert == ("No epoch", NO_EPOCH)

    def test_reads_the_chosen_epoch_and_draws_it(self, monkeypatch):
        drawn = []
        monkeypatch.setattr(
            ens_fun,
            "read",
            lambda session, ens, epoch: {"activity": np.zeros((2, 3)), "epoch": epoch},
        )
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1", "e2"])})
        monkeypatch.setattr(
            type(app),
            "draw_raster",
            lambda self, E, label, epoch, count: drawn.append((label, epoch, count)),
        )
        app.set_selection([0])
        app.set_epoch("e2")
        app.plot_ensemble()
        assert drawn == [("a | 1", "e2", 2)]

    def test_an_unreadable_ensemble_is_reported_not_raised(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("cannot read that")

        monkeypatch.setattr(ens_fun, "read", boom)
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1"])})
        app.set_selection([0])
        assert app.plot_ensemble() is None
        assert app.last_alert == ("Could not read ensemble", "cannot read that")

    def test_an_ensemble_with_no_neurons_says_so_rather_than_drawing_nothing(self, monkeypatch):
        monkeypatch.setattr(
            ens_fun, "read", lambda *a, **k: {"activity": np.zeros((0, 0)), "epoch": "e1"}
        )
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1"])})
        app.set_selection([0])
        assert app.plot_ensemble() is None
        assert app.last_alert == ("Empty ensemble", empty_ensemble_message("a | 1", "e1"))

    def test_the_raster_is_drawn_with_the_ensemble_plot_function(self, monkeypatch):
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")
        passed = {}

        def fake_plot(E, *, ax=None, color=None, **kw):
            passed["ax"] = ax
            passed["color"] = color
            return ax

        monkeypatch.setattr(ens_fun, "plot", fake_plot)
        app = maker([FakeProbe("a")], {"id_a": FakeEnsemble(["e1"])})
        figure = app.draw_raster({"activity": np.zeros((2, 2))}, "a | 1", "e1", 2)
        assert passed["ax"] is not None
        assert passed["ax"].get_title() == raster_title("a | 1", "e1", 2)
        assert figure in app.rasters
        app.close()


# ----------------------------------------------------------------------
# the wait indicator
# ----------------------------------------------------------------------
class TestWithWait:
    def test_the_work_runs_and_its_result_comes_back(self):
        app = maker([FakeProbe("a")])
        assert app.with_wait(LOADING_MESSAGE, lambda: "done") == "done"

    def test_a_nested_wait_does_not_stack_a_second_dialog(self):
        app = maker([FakeProbe("a")])
        app.wait_dialog = object()  # as an outer wait would have left it
        assert app.with_wait("inner", lambda: "done") == "done"
        assert app.wait_dialog is not None  # the outer one still owns it


# ----------------------------------------------------------------------
# ensemble_map, against a real session
# ----------------------------------------------------------------------
@pytest.fixture
def session_with_ensemble(tmp_path):
    """A session with an n-trode element, two spiking neurons, and an ensemble."""
    directory = tmp_path / "sess"
    directory.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("ensemble_maker_test", str(directory))

    subject_doc = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(session.id())
    session.database_add(subject_doc)

    probe = ndi_element_timeseries(
        session=session,
        name="ntrode1",
        reference=1,
        type=NTRODE_TYPE,
        direct=False,
        subject_id=subject_doc.id,
    )
    session.database_add(probe.newdocument())
    clock = [ndi_time_clocktype(CLOCK)]
    probe.addepoch("epoch_1", clock, [(0.0, 3.0)])

    for name, times in {"n1": [0.25, 0.75], "n2": [0.5]}.items():
        neuron = ndi_element_timeseries(
            session=session,
            name=name,
            reference=1,
            type="spikes",
            underlying_element=probe,
            direct=False,
            subject_id=subject_doc.id,
        )
        doc = neuron.newdocument()
        doc.set_dependency_value("underlying_element_id", probe.id)
        session.database_add(doc)
        t = np.asarray(times, dtype=float)
        neuron.addepoch("epoch_1", clock, [(0.0, 3.0)], t, np.ones_like(t))

    return session, probe


class TestEnsembleMap:
    def test_nothing_built_is_an_empty_map(self, session_with_ensemble):
        session, _ = session_with_ensemble
        assert ensemble_map(session) == {}

    def test_a_built_ensemble_is_found_under_its_probe_id(self, session_with_ensemble):
        session, probe = session_with_ensemble
        ens_fun.all_element(session, probe)

        found = ensemble_map(session)
        assert list(found) == [probe.id]
        # The walk back to the probe is the point: the ensemble that comes
        # out must be the one whose underlying element IS this probe, with
        # its stored id intact and its epochs readable.
        ensemble = found[probe.id]
        assert ensemble.underlying_element.id == probe.id
        table, _ = ensemble.epochtable()
        assert [entry["epoch_id"] for entry in table] == ["epoch_1"]

    def test_the_epochs_reach_the_dropdown(self, session_with_ensemble):
        session, probe = session_with_ensemble
        ens_fun.all_element(session, probe)
        assert epoch_choices(ensemble_map(session)[probe.id]) == (["epoch_1"], True)

    def test_an_unsearchable_database_costs_the_markers_not_the_window(self):
        class Broken:
            def database_search(self, query):
                raise RuntimeError("no database")

        assert ensemble_map(Broken()) == {}


# ----------------------------------------------------------------------
# discovery: the app reaches the menu by existing
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_it_adopts_the_session_app_interface(self):
        assert issubclass(ensembleMaker, SessionApp)
        assert SessionApp.is_session_app(ensembleMaker)
        assert not SessionApp.is_abstract(ensembleMaker)

    def test_the_menu_text_is_matlab_s_verbatim(self):
        """Name and Category are user-visible, so they do not get Pythonized."""
        assert ensembleMaker.Name == "Ensemble Maker"
        assert ensembleMaker.Category == "Ensembles"

    def test_scanning_ndi_gui_app_finds_it(self):
        found = SessionApp.list(["ndi.gui.app"])
        assert {
            "Name": "Ensemble Maker",
            "Class": "ndi.gui.app.ensemble_maker.ensembleMaker",
            "Category": "Ensembles",
        } in found

    def test_the_navigator_offers_it_without_naming_it(self):
        """The check that the mechanism was right: no edit to the pane."""
        from ndi.gui.nav.datasets_pane import session_apps
        from ndi.gui.nav.datasets_text import order_app_menu

        entries = order_app_menu(session_apps())
        ensembles = [e for e in entries if e["label"] == "Ensembles"]
        assert len(ensembles) == 1
        assert ensembles[0]["kind"] == "category"
        assert "Ensemble Maker" in [app["Label"] for app in ensembles[0]["apps"]]

    def test_launch_constructs_it_with_the_session(self, monkeypatch):
        session = FakeSession([FakeProbe("a")])
        monkeypatch.setattr(ensembleMaker, "build", lambda self: None)
        app = SessionApp.launch("ndi.gui.app.ensemble_maker.ensembleMaker", session)
        assert isinstance(app, ensembleMaker)
        assert app.session is session

    def test_methods_are_snake_case(self):
        """The house style: no camelCase method reaches this class.

        The class NAME is MATLAB's, and so are Name and Category, but the
        methods are snake_case -- which is also why this class needs no entry
        in tests/test_matlab_name_aliases.py.
        """
        import re

        camel = [
            name
            for name in vars(ensembleMaker)
            if not name.startswith("_") and re.search(r"[a-z][A-Z]", name)
        ]
        assert camel == []


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


class TestWindow:
    def test_the_window_carries_matlab_s_tag_and_geometry(self):
        _qt_or_skip()
        app = maker([FakeProbe("a")], build=True)
        assert app.figure.objectName() == WINDOW_TAG
        assert app.figure.windowTitle() == "Ensemble Maker: test_session"
        geometry = app.figure.geometry()
        assert (geometry.width(), geometry.height()) == DEFAULT_POSITION[2:]
        app.close()

    def test_the_list_shows_the_probes_and_the_selection_reaches_the_model(self):
        _qt_or_skip()
        app = maker([FakeProbe("a"), FakeProbe("b")], {"id_b": FakeEnsemble(["e1"])}, build=True)
        assert [app.probe_list.item(i).text() for i in range(app.probe_list.count())] == [
            f"{UNMARKED}a | 1",
            f"{MARKER}b | 1",
        ]
        assert app.make_button.isEnabled() is False

        app.probe_list.item(1).setSelected(True)
        assert app.selection == [1]
        assert app.make_button.isEnabled() is True
        assert app.plot_button.isEnabled() is True
        assert [app.epoch_dropdown.itemText(i) for i in range(app.epoch_dropdown.count())] == ["e1"]
        app.close()

    def test_the_epoch_dropdown_is_disabled_without_a_plottable_probe(self):
        _qt_or_skip()
        app = maker([FakeProbe("a")], build=True)
        assert app.epoch_dropdown.isEnabled() is False
        assert app.plot_button.isEnabled() is False
        assert app.epoch_dropdown.currentText() == EPOCH_PLACEHOLDER
        app.close()

    def test_the_rebuild_checkbox_reaches_the_model(self):
        _qt_or_skip()
        app = maker([FakeProbe("a")], build=True)
        app.rebuild_checkbox.setChecked(True)
        assert app.rebuild is True
        assert if_exists_for(app.rebuild) == "replace"
        app.close()
