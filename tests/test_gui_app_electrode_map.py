"""Tests for ndi.gui.app.electrode_map.

MATLAB counterpart: ndi.gui.app.ElectrodeMap

Two halves, as elsewhere in ndi.gui: what the window SAYS -- the two lists,
which geometry a probe already has, whether the buttons are live -- is plain
Python and tested without a display; the widgets are tested under
QT_QPA_PLATFORM=offscreen and skip where Qt cannot start.

The session and its documents are real, for the reason the geometry tests give:
a probe_geometry declares a probe_id dependency that DID validates.
"""

from __future__ import annotations

import os

import pytest

from ndi.element import ndi_element
from ndi.fun.probe import geometry
from ndi.gui.app import ElectrodeMap
from ndi.gui.app.electrode_map import DEFAULT_POSITION, TITLE_TEXT, WINDOW_TAG
from ndi.gui.app.session_app import SessionApp
from ndi.session.dir import ndi_session_dir
from ndi.subject import ndi_subject


@pytest.fixture
def session(tmp_path):
    directory = tmp_path / "sess"
    directory.mkdir(parents=True, exist_ok=True)
    s = ndi_session_dir("emap_test", str(directory))
    subject_doc = ndi_subject("mouse@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(s.id())
    s.database_add(subject_doc)
    s._subject_doc = subject_doc
    return s


def make_probe(session, name="ntrodeA"):
    probe = ndi_element(
        session=session,
        name=name,
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=session._subject_doc.id,
    )
    session.database_add(probe.newdocument())
    return probe


def app_with(session, *probes, build=False):
    """An app whose probe list is PROBES.

    Assigned directly because a bare session has no DAQ system, so getprobes
    finds nothing -- the probes here stand in for what it would return.
    """
    app = ElectrodeMap(session, build=build)
    app.probes = list(probes)
    if build:
        app.refresh_probe_list()
    return app


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestItIsASessionApp:
    def test_it_adopts_the_interface(self):
        assert issubclass(ElectrodeMap, SessionApp)

    def test_it_carries_matlabs_menu_label(self):
        assert ElectrodeMap.Name == "Electrode Map"

    def test_it_stays_at_the_top_level_of_the_apps_menu(self):
        """MATLAB gives it no Category, so it is not grouped into a submenu."""
        assert ElectrodeMap.Category == ""

    def test_discovery_finds_it(self):
        """The end of the wire from NDI-python#113: NDI now ships an app, so
        the navigator's Apps menu has something in it."""
        found = {app["Name"]: app["Class"] for app in SessionApp.list()}
        assert found["Electrode Map"] == "ndi.gui.app.electrode_map.ElectrodeMap"


class TestGeometryList:
    def test_every_library_layout_is_offered(self, session):
        app = ElectrodeMap(session, build=False)
        assert "generic/tetrode" in app.geometry_names

    def test_a_label_carries_the_site_count(self, session):
        app = ElectrodeMap(session, build=False)
        index = app.geometry_names.index("generic/tetrode")
        assert app.geometry_labels[index] == "generic/tetrode (4)"

    def test_the_models_are_parallel_to_the_names(self, session):
        app = ElectrodeMap(session, build=False)
        index = app.geometry_names.index("generic/tetrode")
        assert app.geometry_models[index] == "tetrode"

    def test_an_unreadable_layout_keeps_its_name(self, session, tmp_path, monkeypatch):
        """One bad file in the library must not empty the list."""
        group = tmp_path / "labA"
        group.mkdir(parents=True)
        (group / "broken.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(geometry, "library_root", lambda: tmp_path)
        app = ElectrodeMap(session, build=False)
        assert app.geometry_labels == ["labA/broken"]
        assert app.geometry_models == [""]

    def test_no_library_leaves_an_empty_list(self, session, tmp_path, monkeypatch):
        monkeypatch.setattr(geometry, "library_root", lambda: tmp_path / "absent")
        app = ElectrodeMap(session, build=False)
        assert app.geometry_names == []


class TestProbeList:
    def test_an_unassigned_probe_shows_no_stars(self, session):
        app = app_with(session, make_probe(session))
        assert app.probe_rows() == ["ntrodeA | 1"]

    def test_an_assigned_probe_shows_its_model_in_stars(self, session):
        probe = make_probe(session)
        geometry.from_library(session, probe, "generic/tetrode", verbose=0)
        assert app_with(session, probe).probe_rows() == ["ntrodeA | 1 *tetrode*"]

    def test_the_channel_count_is_shown_when_known(self, session):
        probe = make_probe(session)
        probe.epochtable = lambda: ([{"epoch_id": "e1"}], None)
        probe.getchanneldevinfo = lambda epoch: ("dev", 1, "ai", [1, 2, 3, 4])
        assert app_with(session, probe).probe_rows() == ["ntrodeA | 1 (4)"]

    def test_a_geometry_without_a_model_still_reads_as_assigned(self, session):
        """Otherwise the window would invite the user to assign it again."""
        probe = make_probe(session)
        geometry.from_struct(
            session,
            probe,
            {"site_locations_leftright": [0, 1], "site_locations_depth": [0, 10]},
            verbose=0,
        )
        assert app_with(session, probe).probe_rows() == ["ntrodeA | 1 *assigned*"]

    def test_a_session_that_cannot_list_probes_has_none(self, session):
        def boom(*args, **kwargs):
            raise RuntimeError("no daq systems")

        session.getprobes = boom
        assert ElectrodeMap(session, build=False).probes == []


class TestSelectionMatching:
    def test_a_model_finds_its_library_layout(self, session):
        app = ElectrodeMap(session, build=False)
        index = app.geometry_index_for_model("tetrode")
        assert app.geometry_names[index] == "generic/tetrode"

    def test_an_unknown_model_matches_nothing(self, session):
        assert ElectrodeMap(session, build=False).geometry_index_for_model("nope") is None

    def test_an_unassigned_probe_matches_nothing(self, session):
        assert ElectrodeMap(session, build=False).geometry_index_for_model("") is None


class TestAssign:
    def test_it_saves_the_geometry(self, session):
        probe = make_probe(session)
        app = app_with(session, probe)
        app.assign("generic/tetrode", 0)
        assert geometry.get(session, probe).pg["probe_model"] == "tetrode"

    def test_reassigning_replaces_rather_than_stacks(self, session):
        """MATLAB passes replace: a probe has one geometry, not a pile of them."""
        from ndi.query import ndi_query

        probe = make_probe(session)
        app = app_with(session, probe)
        app.assign("generic/tetrode", 0)
        app.assign("generic/linear16_25um", 0)
        assert len(session.database_search(ndi_query("").isa("probe_geometry"))) == 1
        assert geometry.get(session, probe).pg["probe_model"] == "linear16_25um"

    def test_it_reports_a_channel_mismatch(self, session):
        probe = make_probe(session)
        probe.epochtable = lambda: ([{"epoch_id": "e1"}], None)
        probe.getchanneldevinfo = lambda epoch: ("dev", 1, "ai", list(range(9)))
        app = app_with(session, probe)
        with pytest.warns(UserWarning):
            info = app.assign("generic/tetrode", 0)
        assert info["channel_mismatch"] is True

    def test_the_window_title_names_the_session(self, session):
        assert ElectrodeMap(session, build=False).window_title() == "Electrode Map: emap_test"


class TestWindow:
    def test_it_is_titled_and_tagged(self, session):
        _qt_or_skip()
        app = app_with(session, make_probe(session), build=True)
        assert app.figure.objectName() == WINDOW_TAG
        assert app.figure.windowTitle() == "Electrode Map: emap_test"

    def test_the_heading_says_what_the_window_is_for(self, session):
        _qt_or_skip()
        app = app_with(session, build=True)
        assert app.title_label.text() == TITLE_TEXT == "Assign Electrode Geometries to Probes"

    def test_the_geometry_is_matlabs(self, session):
        _qt_or_skip()
        app = app_with(session, build=True)
        assert DEFAULT_POSITION == (100, 100, 680, 480)
        assert app.figure.width() == 680
        assert app.figure.height() == 480

    def test_both_lists_are_filled(self, session):
        _qt_or_skip()
        app = app_with(session, make_probe(session), build=True)
        assert app.geometry_list.count() == len(app.geometry_names)
        assert app.probe_list.count() == 1
        assert app.probe_list.item(0).text() == "ntrodeA | 1"

    def test_the_buttons_start_dead(self, session):
        _qt_or_skip()
        app = app_with(session, make_probe(session), build=True)
        assert not app.assign_button.isEnabled()
        assert not app.plot_button.isEnabled()

    def test_plot_needs_only_a_geometry(self, session):
        _qt_or_skip()
        app = app_with(session, make_probe(session), build=True)
        app.geometry_list.setCurrentRow(0)
        assert app.plot_button.isEnabled()
        assert not app.assign_button.isEnabled()

    def test_assign_needs_both(self, session):
        _qt_or_skip()
        app = app_with(session, make_probe(session), build=True)
        app.geometry_list.setCurrentRow(0)
        app.probe_list.setCurrentRow(0)
        assert app.assign_button.isEnabled()

    def test_the_arrow_assigns_and_the_row_updates(self, session):
        _qt_or_skip()
        probe = make_probe(session)
        app = app_with(session, probe, build=True)
        app.geometry_list.setCurrentRow(app.geometry_names.index("generic/tetrode"))
        app.probe_list.setCurrentRow(0)
        app.assign_selected()
        assert app.probe_list.item(0).text() == "ntrodeA | 1 *tetrode*"
        assert geometry.get(session, probe).found is True

    def test_selecting_an_assigned_probe_highlights_its_geometry(self, session):
        _qt_or_skip()
        probe = make_probe(session)
        geometry.from_library(session, probe, "generic/tetrode", verbose=0)
        app = app_with(session, probe, build=True)
        app.geometry_list.setCurrentRow(0)
        app.probe_list.setCurrentRow(0)
        app.on_probe_selected()
        assert app.geometry_names[app.geometry_list.currentRow()] == "generic/tetrode"

    def test_a_failed_assignment_is_reported_not_raised(self, session):
        _qt_or_skip()
        said = []
        app = app_with(session, make_probe(session), build=True)
        app.alert = lambda message, title: said.append((message, title))
        app.assign = _raise("the database is read-only")
        app.geometry_list.setCurrentRow(0)
        app.probe_list.setCurrentRow(0)
        assert app.assign_selected() is None
        assert said == [("the database is read-only", "Assignment failed")]

    def test_a_mismatch_is_shown_after_the_assignment_succeeds(self, session):
        _qt_or_skip()
        said = []
        probe = make_probe(session)
        probe.epochtable = lambda: ([{"epoch_id": "e1"}], None)
        probe.getchanneldevinfo = lambda epoch: ("dev", 1, "ai", list(range(9)))
        app = app_with(session, probe, build=True)
        app.alert = lambda message, title: said.append(title)
        app.geometry_list.setCurrentRow(app.geometry_names.index("generic/tetrode"))
        app.probe_list.setCurrentRow(0)
        with pytest.warns(UserWarning):
            app.assign_selected()
        assert said == ["Channel count mismatch"]
        assert geometry.get(session, probe).found is True

    def test_plotting_reaches_the_library(self, session):
        _qt_or_skip()
        import matplotlib

        matplotlib.use("Agg")
        app = app_with(session, build=True)
        app.show_plot = lambda: None
        app.geometry_list.setCurrentRow(app.geometry_names.index("generic/tetrode"))
        handles = app.plot_selected_geometry()
        assert len(handles["labels"]) == 4

    def test_a_failed_plot_is_reported_not_raised(self, session):
        _qt_or_skip()
        said = []
        app = app_with(session, build=True)
        app.alert = lambda message, title: said.append(title)
        app.geometry_names[0] = "nosuchgroup/nosuchlayout"
        app.geometry_list.setCurrentRow(0)
        assert app.plot_selected_geometry() is None
        assert said == ["Plot failed"]

    def test_refresh_keeps_the_selected_row(self, session):
        _qt_or_skip()
        app = app_with(session, make_probe(session, "a"), make_probe(session, "b"), build=True)
        app.probe_list.setCurrentRow(1)
        app.refresh_probe_list()
        assert app.probe_list.currentRow() == 1


def _raise(message):
    def boom(*args, **kwargs):
        raise RuntimeError(message)

    return boom


if __name__ == "__main__":
    pytest.main([__file__])
