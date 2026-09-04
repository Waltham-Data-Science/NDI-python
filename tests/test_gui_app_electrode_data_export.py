"""Tests for ndi.gui.app.electrode_data_export.

MATLAB counterpart: ndi.gui.app.ElectrodeDataExport

Two things here are worth more than the rest.

The first is DISCOVERY: this is the first app to adopt the SessionApp
interface in Python, so the test that ``SessionApp.list()`` finds it -- with
no edit to the pane, the menu, or any registry -- is what proves the
mechanism NDI-python#117 landed actually works from the app's side.

The second is WHICH PROBE GOT EXPORTED. Every list row is a name, and the
selection is read back as row numbers; a row labelled with the wrong probe,
or a selection that shifts when the list is rebuilt, does not raise. It just
spends twenty minutes writing the wrong recording into the sorter's folder.
So the label, the selection, and the mapping from selection to probe are
each pinned separately.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from ndi.gui.app import SessionApp
from ndi.gui.app.electrode_data_export import (
    DEFAULT_POSITION,
    EXPORTERS,
    PROBE_TYPE,
    WINDOW_TAG,
    ElectrodeDataExport,
    missing_geometry_message,
    probe_label,
)


class FakeProbe:
    def __init__(self, name="ctx", reference=1, channels=2, rate=1000.0, duration=0.002):
        self._name = name
        self._reference = reference
        self._channels = channels
        self._rate = rate
        self._duration = duration

    def elementstring(self):
        return f"{self._name} | {self._reference}"

    def id(self):
        return f"{self._name}_{self._reference}"

    def epochtable(self):
        return [{"epoch_id": "e1", "t0_t1": [[0.0, self._duration]]}], "hash"

    def samplerate(self, epoch_id):  # noqa: ARG002
        return self._rate

    def times2samples(self, epoch_id, times):  # noqa: ARG002
        return np.round(np.asarray(times) * self._rate).astype(int)

    def readtimeseries(self, timeref_or_epoch=None, t0=0.0, t1=0.0, timeref=None):  # noqa: ARG002
        n = max(int(round(t1 * self._rate)) - int(round(t0 * self._rate)) + 1, 0)
        return np.zeros((n, self._channels)), np.zeros(n), None

    def getchanneldevinfo(self, epoch):  # noqa: ARG002
        return (None, None, "ai", list(range(1, self._channels + 1)))


class FakeSession:
    def __init__(self, path, probes=(), reference="2024-01-01"):
        self.path = str(path)
        self.reference = reference
        self._probes = list(probes)
        self.probe_type_asked = None

    def getprobes(self, **kwargs):
        self.probe_type_asked = kwargs.get("type")
        return self._probes

    def database_search(self, query):  # noqa: ARG002 - no geometry documents
        return []


def _app(session):
    """The app without its window, for the parts that do not need Qt."""
    app = ElectrodeDataExport(session, build=False)
    app.load_probes()
    return app


# ----------------------------------------------------------------------
# pure helpers
# ----------------------------------------------------------------------
class TestProbeLabel:
    def test_a_probe_exported_for_nothing_is_just_its_name(self):
        assert probe_label("ctx | 1") == "ctx | 1"

    def test_the_sorters_it_is_exported_for_follow_in_parentheses(self):
        assert probe_label("ctx | 1", ["KIASORT"]) == "ctx | 1 (KIASORT)"

    def test_several_sorters_are_comma_separated(self):
        assert probe_label("ctx | 1", ["KIASORT", "Kilosort"]) == "ctx | 1 (KIASORT, Kilosort)"


class TestMissingGeometryMessage:
    def test_it_names_the_probes_and_counts_them(self):
        message = missing_geometry_message(["ctx | 1", "ctx | 2"])
        assert "2 of the selected probe(s)" in message
        assert "ctx | 1, ctx | 2" in message

    def test_it_points_at_the_app_that_fixes_the_problem(self):
        assert "Electrode Map" in missing_geometry_message(["ctx | 1"])

    def test_it_ends_by_asking_rather_than_telling(self):
        assert missing_geometry_message(["ctx | 1"]).endswith("Export anyway?")


class TestExporters:
    def test_each_sorter_has_its_own_folder_and_file(self):
        """Sharing either would make exporting for one sorter silently
        overwrite the other's binary."""
        assert len({e.dir for e in EXPORTERS}) == len(EXPORTERS)
        assert len({e.name for e in EXPORTERS}) == len(EXPORTERS)

    def test_the_supported_sorters_are_kiasort_and_kilosort(self):
        assert [e.name for e in EXPORTERS] == ["KIASORT", "Kilosort"]


# ----------------------------------------------------------------------
# the model, without Qt
# ----------------------------------------------------------------------
class TestLoadProbes:
    def test_only_n_trode_probes_are_asked_for(self, tmp_path):
        session = FakeSession(tmp_path, [FakeProbe()])
        _app(session)
        assert session.probe_type_asked == PROBE_TYPE

    def test_a_session_that_cannot_answer_lists_nothing(self, tmp_path):
        class Broken(FakeSession):
            def getprobes(self, **kwargs):
                raise RuntimeError("no daq systems")

        assert _app(Broken(tmp_path)).probes == []


class TestExportedSorters:
    def test_a_probe_with_no_exports_reports_none(self, tmp_path):
        app = _app(FakeSession(tmp_path, [FakeProbe()]))
        assert app.exported_sorters(app.probes[0]) == []

    def test_an_existing_binary_is_reported_under_its_sorters_name(self, tmp_path):
        probe_dir = tmp_path / "kiasort" / "ctx_-_1"
        probe_dir.mkdir(parents=True)
        (probe_dir / "kiasort.bin").write_bytes(b"")

        app = _app(FakeSession(tmp_path, [FakeProbe()]))
        assert app.exported_sorters(app.probes[0]) == ["KIASORT"]

    def test_a_legacy_folders_export_still_counts(self, tmp_path):
        """Data written by an older NDI lives under 'ctx_|_1'. Missing it
        would offer to re-export what is already there."""
        probe_dir = tmp_path / "kilosort" / "ctx_|_1"
        probe_dir.mkdir(parents=True)
        (probe_dir / "kilosort.bin").write_bytes(b"")

        app = _app(FakeSession(tmp_path, [FakeProbe()]))
        assert app.exported_sorters(app.probes[0]) == ["Kilosort"]

    def test_an_empty_probe_folder_is_not_an_export(self, tmp_path):
        (tmp_path / "kiasort" / "ctx_-_1").mkdir(parents=True)
        app = _app(FakeSession(tmp_path, [FakeProbe()]))
        assert app.exported_sorters(app.probes[0]) == []

    def test_rows_carry_the_exports_in_the_label(self, tmp_path):
        probe_dir = tmp_path / "kiasort" / "ctx_-_1"
        probe_dir.mkdir(parents=True)
        (probe_dir / "kiasort.bin").write_bytes(b"")

        app = _app(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        assert app.probe_items() == ["ctx | 1 (KIASORT)", "ctx | 2"]


class TestExporterLookup:
    def test_a_sorter_is_found_by_the_name_the_dropdown_shows(self, tmp_path):
        app = _app(FakeSession(tmp_path))
        assert app.exporter_by_name("Kilosort").dir == "kilosort"

    def test_an_unknown_name_resolves_to_nothing(self, tmp_path):
        assert _app(FakeSession(tmp_path)).exporter_by_name("Mountainsort") is None


class TestGeometryCheck:
    def test_probes_with_no_geometry_document_are_all_reported(self, tmp_path):
        app = _app(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        assert app.probes_without_geometry([0, 1]) == ["ctx | 1", "ctx | 2"]

    def test_a_probe_with_geometry_is_not_reported(self, tmp_path, monkeypatch):
        from ndi.fun.probe.geometry import ProbeGeometry

        app = _app(FakeSession(tmp_path, [FakeProbe()]))
        monkeypatch.setattr(
            "ndi.fun.probe.geometry.get",
            lambda session, probe, **kwargs: ProbeGeometry(found=True),
        )
        assert app.probes_without_geometry([0]) == []

    def test_a_database_that_raises_counts_as_no_geometry(self, tmp_path):
        """An unreadable database and an absent document are the same thing
        to the user: neither can produce a real channel map, and warning is
        the safe answer to both."""

        class Broken(FakeSession):
            def database_search(self, query):
                raise RuntimeError("database down")

        app = _app(Broken(tmp_path, [FakeProbe()]))
        assert app.probes_without_geometry([0]) == ["ctx | 1"]


# ----------------------------------------------------------------------
# discovery: the whole point of the SessionApp interface
# ----------------------------------------------------------------------
class TestDiscovery:
    def test_the_app_is_found_by_scanning_ndi_gui_app(self):
        found = {app["Name"]: app for app in SessionApp.list(["ndi.gui.app"])}
        assert "Electrode Data Export" in found

    def test_it_reports_the_class_launch_can_resolve(self):
        entry = next(
            app
            for app in SessionApp.list(["ndi.gui.app"])
            if app["Name"] == "Electrode Data Export"
        )
        from ndi.gui.app.session_app import resolve_class

        assert resolve_class(entry["Class"]) is ElectrodeDataExport

    def test_it_declares_no_category_so_it_stays_at_the_top_level(self):
        assert ElectrodeDataExport.Category == ""

    def test_the_menu_label_is_matlabs_verbatim(self):
        """The label is user-visible text; a Pythonised one is a divergence
        a user would see."""
        assert ElectrodeDataExport.Name == "Electrode Data Export"

    def test_it_is_not_treated_as_abstract(self):
        assert SessionApp.is_abstract(ElectrodeDataExport) is False

    def test_ndi_gui_app_is_scanned_by_default(self):
        assert "ndi.gui.app" in SessionApp.default_packages()


class TestNaming:
    def test_every_public_method_is_snake_case(self):
        """The house style for new code, and what issue #122 asks of each
        ported app."""
        import re

        offenders = [
            name
            for name in vars(ElectrodeDataExport)
            if not name.startswith("_") and re.search(r"[a-z][A-Z]", name)
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
    return ElectrodeDataExport(session)


class TestWindow:
    def test_the_window_names_the_session_and_is_tagged(self, tmp_path):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        assert app.figure.windowTitle() == "Electrode Data Export: 2024-01-01"
        assert app.figure.objectName() == WINDOW_TAG
        app.close()

    def test_it_opens_where_matlab_opens_it(self, tmp_path):
        app = _window(FakeSession(tmp_path))
        assert app.position == DEFAULT_POSITION
        app.close()

    def test_the_list_shows_one_row_per_probe(self, tmp_path):
        app = _window(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        assert app.probe_list.count() == 2
        assert app.probe_list.item(1).text() == "ctx | 2"
        app.close()

    def test_the_dropdown_offers_every_sorter(self, tmp_path):
        app = _window(FakeSession(tmp_path))
        items = [app.export_dropdown.itemText(i) for i in range(app.export_dropdown.count())]
        assert items == [e.name for e in EXPORTERS]
        app.close()

    def test_export_is_disabled_until_a_probe_is_chosen(self, tmp_path):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        assert app.export_button.isEnabled() is False

        app.probe_list.item(0).setSelected(True)
        assert app.update_button_state() is True
        assert app.export_button.isEnabled() is True
        app.close()

    def test_the_selection_names_the_probes_it_looks_like_it_names(self, tmp_path):
        app = _window(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        app.probe_list.item(1).setSelected(True)
        assert app.selected_indices() == [1]
        assert app.probes[app.selected_indices()[0]].elementstring() == "ctx | 2"
        app.close()

    def test_several_probes_can_be_selected_at_once(self, tmp_path):
        app = _window(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        app.probe_list.item(0).setSelected(True)
        app.probe_list.item(1).setSelected(True)
        assert app.selected_indices() == [0, 1]
        app.close()

    def test_a_refresh_keeps_the_selection_even_as_labels_change(self, tmp_path):
        """The label of the probe just exported is exactly the one that
        changes, so a selection kept by text would drop it."""
        app = _window(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        app.probe_list.item(1).setSelected(True)

        probe_dir = tmp_path / "kiasort" / "ctx_-_2"
        probe_dir.mkdir(parents=True)
        (probe_dir / "kiasort.bin").write_bytes(b"")

        rows = app.refresh_probe_list()
        assert rows[1] == "ctx | 2 (KIASORT)"
        assert app.selected_indices() == [1]
        app.close()

    def test_a_session_with_no_probes_opens_empty_rather_than_failing(self, tmp_path):
        app = _window(FakeSession(tmp_path))
        assert app.probe_list.count() == 0
        assert app.export_button.isEnabled() is False
        app.close()


class TestExporting:
    def test_exporting_writes_the_binary_and_the_channel_map(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        app.probe_list.item(0).setSelected(True)
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        errors = app.do_export()

        assert errors == []
        assert (tmp_path / "kiasort" / "ctx_-_1" / "kiasort.bin").is_file()
        assert (tmp_path / "kiasort" / "ctx_-_1" / "channel_map.mat").is_file()
        app.close()

    def test_the_row_says_so_afterwards(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        app.probe_list.item(0).setSelected(True)
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.do_export()

        assert app.probe_list.item(0).text() == "ctx | 1 (KIASORT)"
        app.close()

    def test_only_the_selected_probes_are_exported(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe(), FakeProbe(reference=2)]))
        app.probe_list.item(1).setSelected(True)
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.do_export()

        assert (tmp_path / "kiasort" / "ctx_-_2" / "kiasort.bin").is_file()
        assert not (tmp_path / "kiasort" / "ctx_-_1").exists()
        app.close()

    def test_the_chosen_sorter_decides_the_folder(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        app.probe_list.item(0).setSelected(True)
        app.export_dropdown.setCurrentText("Kilosort")
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.do_export()

        assert (tmp_path / "kilosort" / "ctx_-_1" / "kilosort.bin").is_file()
        app.close()

    def test_declining_the_geometry_warning_exports_nothing(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        app.probe_list.item(0).setSelected(True)
        monkeypatch.setattr(app, "confirm", lambda *a, **k: False)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        assert app.do_export() == []
        assert not (tmp_path / "kiasort").exists()
        app.close()

    def test_the_warning_names_the_probes_that_would_get_a_default_map(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        app.probe_list.item(0).setSelected(True)
        seen = {}
        monkeypatch.setattr(
            app, "confirm", lambda message, title, **k: seen.update(message=message) or False
        )
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.do_export()

        assert "ctx | 1" in seen["message"]
        app.close()

    def test_pressing_export_with_nothing_selected_does_nothing(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        assert app.do_export() == []
        assert not (tmp_path / "kiasort").exists()
        app.close()

    def test_one_failing_probe_does_not_stop_the_others(self, tmp_path, monkeypatch):
        """A selection is minutes of work per probe; abandoning the rest
        because the first had an unreadable epoch throws that away."""
        good = FakeProbe(reference=2)

        class Unreadable(FakeProbe):
            def readtimeseries(self, *args, **kwargs):
                raise RuntimeError("epoch is missing")

        app = _window(FakeSession(tmp_path, [Unreadable(), good]))
        app.probe_list.item(0).setSelected(True)
        app.probe_list.item(1).setSelected(True)
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        errors = app.do_export()

        assert len(errors) == 1
        assert errors[0].startswith("ctx | 1: ")
        assert (tmp_path / "kiasort" / "ctx_-_2" / "kiasort.bin").is_file()
        app.close()

    def test_the_export_button_is_usable_again_afterwards(self, tmp_path, monkeypatch):
        app = _window(FakeSession(tmp_path, [FakeProbe()]))
        app.probe_list.item(0).setSelected(True)
        monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(app, "alert", lambda *a, **k: None)

        app.do_export()

        assert app.export_button.isEnabled() is True
        app.close()

    def test_progress_runs_forward_across_the_whole_selection(self, tmp_path):
        """Each probe gets its own slice of one bar; per-probe bars would
        run 0..1 twice and read as the job restarting."""
        app = _app(
            FakeSession(
                tmp_path,
                [
                    FakeProbe(duration=250.0, rate=100.0),
                    FakeProbe(reference=2, duration=250.0, rate=100.0),
                ],
            )
        )
        seen: list[float] = []

        class Bar:
            def updateBar(self, tag, fraction):  # noqa: N802, ARG002
                seen.append(fraction)

        app.export_probes([0, 1], EXPORTERS[0], bar=Bar(), tag="t")

        assert seen == sorted(seen)
        assert max(seen) == pytest.approx(1.0)
        assert any(f < 0.5 for f in seen) and any(0.5 <= f < 1.0 for f in seen)

    def test_a_missing_progress_bar_does_not_stop_the_export(self, tmp_path):
        app = _app(FakeSession(tmp_path, [FakeProbe()]))
        assert app.export_probes([0], EXPORTERS[0], bar=None, tag="t") == []
        assert (tmp_path / "kiasort" / "ctx_-_1" / "kiasort.bin").is_file()


class TestLaunching:
    def test_launch_constructs_it_with_the_session(self, tmp_path):
        _qt_or_skip()
        session = FakeSession(tmp_path, [FakeProbe()])
        app = SessionApp.launch("ndi.gui.app.electrode_data_export.ElectrodeDataExport", session)
        assert isinstance(app, ElectrodeDataExport)
        assert app.session is session
        app.close()
