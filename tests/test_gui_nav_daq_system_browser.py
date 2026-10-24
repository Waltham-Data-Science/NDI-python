"""ndi.gui.nav.daq_system_browser against MATLAB's daqSystemBrowser.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/daqSystemBrowser.m`` (tests:
``tests/+ndi/+unittest/+gui/+nav/daqSystemBrowser_test.m`` and
``TestDaqSystemBrowserWindow.m``)

The description and epoch-table logic is plain Python and runs everywhere;
the window tests build it under the offscreen platform and skip without
PySide6, as elsewhere in this package. The window tests use a real session
with one DAQ system, 'intan1', whose epochs are '#.rhd' + '#.epochprobemap.ndi'
file pairs and whose epoch probe map is the '(.*)epochprobemap.ndi' file --
the session MATLAB's buildSession makes.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from ndi.gui.nav.daq_system_browser import DaqSystemBrowser

B = DaqSystemBrowser


def fake_daq():
    nav = SimpleNamespace(
        fileparameters={"filematch": ["#.rhd", "#.epochprobemap.txt"]},
        epochprobemap_class="ndi.epoch.epochprobemap_daqsystem",
        epochprobemap_fileparameters={"filematch": ["#.epochprobemap.txt"]},
    )
    return SimpleNamespace(name="intan1", filenavigator=nav, daqreader=None, daqmetadatareaders=[])


class TestDescribe:
    def test_filematch_list_forms(self):
        assert B.filematch_list(None) == []
        assert B.filematch_list(".*\\.rhd\\>") == [".*\\.rhd\\>"]
        assert B.filematch_list(["#.rhd", "#.epochprobemap.txt"]) == [
            "#.rhd",
            "#.epochprobemap.txt",
        ]
        assert B.filematch_list({"filematch": ["a.ext", "b.ext"]}) == ["a.ext", "b.ext"]
        assert B.filematch_list({"filematch": []}) == []
        assert B.filematch_list({"other": 1}) == []

    def test_describe_reads_navigator_parameters(self):
        s = B.describe(fake_daq())
        assert s["name"] == "intan1"
        assert s["file_parameters"] == ["#.rhd", "#.epochprobemap.txt"]
        assert s["epoch_probe_map_class"] == "ndi.epoch.epochprobemap_daqsystem"
        assert s["epoch_probe_map_file_parameters"] == ["#.epochprobemap.txt"]

    def test_describe_tolerates_missing_parts(self):
        s = B.describe(SimpleNamespace(name="bare"))
        assert s["name"] == "bare"
        assert s["file_parameters"] == []
        assert s["navigator_class"] == ""
        assert s["metadata_readers"] == []

    def test_describe_none_is_the_template(self):
        assert B.describe(None)["name"] == ""

    def test_short_class_name(self):
        assert B.short_class_name("ndi.daq.reader.mfdaq.intan") == "intan"
        assert B.short_class_name("struct") == "struct"
        assert B.short_class_name("") == ""

    def test_epoch_labels(self):
        assert B.epoch_labels([1, 2], ["t00001", ""]) == ["Epoch 1  (t00001)", "Epoch 2"]

    def test_detail_items_one_pattern_per_line(self):
        items = B.detail_items(B.describe(fake_daq()))
        patterns = [v for kind, _, v, _ in items if kind == "pattern"]
        assert "#.rhd" in patterns
        assert "#.epochprobemap.txt" in patterns
        # the default text when no probe map patterns are set
        d = fake_daq()
        d.filenavigator.epochprobemap_fileparameters = {"filematch": []}
        notes = [v for kind, _, v, _ in B.detail_items(B.describe(d)) if kind == "note"]
        assert any("default" in n for n in notes)


class TestEpochFileRows:
    def test_marks_the_probe_map_and_matches_patterns(self, tmp_path):
        d = tmp_path / "t00001"
        files = [str(d / "reference.txt"), str(d / "data.rhd"), str(d / "grouping.txt")]
        patterns = ["reference.txt", ".*\\.rhd\\>", "grouping.txt"]
        rows = B.epoch_file_rows(files, patterns, files[2])
        assert [r[0] for r in rows] == ["reference.txt", "data.rhd", "grouping.txt"]
        assert rows[0][1] == "reference.txt"
        assert rows[1][1] == ".*\\.rhd\\>"
        assert rows[2][2] == "epoch probe map"
        assert rows[0][2] == ""

    def test_hash_is_a_wildcard(self):
        assert B.matching_pattern(["#.rhd"], "rec1.rhd") == "#.rhd"

    def test_default_probe_map_gets_its_own_row(self, tmp_path):
        d = tmp_path / "no_such_epoch_dir"
        files = [str(d / "data.rhd")]
        pm = str(d / ".data.rhd.epochprobemap.ndi")
        rows = B.epoch_file_rows(files, [], pm)
        assert len(rows) == 2
        assert rows[1][0] == ".data.rhd.epochprobemap.ndi"
        assert "default location" in rows[1][2]
        assert "not found" in rows[1][2]

    def test_empty(self):
        assert "no files" in B.epoch_file_rows([], [], "")[0][0]

    def test_no_match(self):
        assert B.matching_pattern(["a.txt"], "b.dat") == ""
        assert B.matching_pattern([], "b.dat") == ""


# ----------------------------------------------------------------------
# a real session
# ----------------------------------------------------------------------
@pytest.fixture
def intan_session(tmp_path):
    from ndi.daq.reader.mfdaq import ndi_daq_reader_mfdaq_intan
    from ndi.daq.system_mfdaq import ndi_daq_system_mfdaq
    from ndi.file.navigator import ndi_file_navigator
    from ndi.session import ndi_session_dir

    (tmp_path / "rec1.rhd").write_text("x")
    (tmp_path / "rec1.epochprobemap.ndi").write_text(
        "name\treference\ttype\tdevicestring\tsubjectstring\n"
    )
    session = ndi_session_dir("exp1", str(tmp_path))
    nav = ndi_file_navigator(
        session,
        ["#.rhd", "#.epochprobemap.ndi"],
        "ndi.epoch.epochprobemap_daqsystem",
        ["(.*)epochprobemap.ndi"],
    )
    session.daqsystem_add(ndi_daq_system_mfdaq("intan1", nav, ndi_daq_reader_mfdaq_intan()))
    return session


class TestOnARealSession:
    """No widgets: what the browser reads and would show."""

    def test_lists_and_describes_the_daq_system(self, intan_session):
        b = DaqSystemBrowser(intan_session, build=False)
        assert [s["name"] for s in b.info] == ["intan1"]
        s = b.info[0]
        assert s["daq_class"] == "ndi.daq.system.mfdaq"
        assert s["reader_class"] == "ndi.daq.reader.mfdaq.intan"
        assert s["navigator_class"] == "ndi.file.navigator"
        assert s["file_parameters"] == ["#.rhd", "#.epochprobemap.ndi"]
        assert s["epoch_probe_map_file_parameters"] == ["(.*)epochprobemap.ndi"]

    def test_epochs_are_not_read_until_asked(self, intan_session):
        b = DaqSystemBrowser(intan_session, build=False)
        assert b.epochs == [None]

    def test_load_epochs_shows_the_files(self, intan_session):
        b = DaqSystemBrowser(intan_session, build=False)
        epochs = b.load_epochs(0)
        assert [e["number"] for e in epochs] == [1]
        rows = b.epoch_rows
        by_name = {r[0]: r for r in rows}
        assert by_name["rec1.rhd"][1] == "#.rhd"
        assert by_name["rec1.epochprobemap.ndi"][2] == "epoch probe map"

    def test_choose_epoch(self, intan_session):
        b = DaqSystemBrowser(intan_session, build=False)
        assert b.choose_epoch(1) is None  # not loaded yet
        b.load_epochs(0)
        assert b.choose_epoch(1) == b.epoch_rows
        before = list(b.epoch_rows)
        assert b.choose_epoch(99) is None
        assert b.epoch_rows == before

    def test_a_session_with_no_daq_systems(self, tmp_path):
        from ndi.session import ndi_session_dir

        b = DaqSystemBrowser(ndi_session_dir("empty", str(tmp_path)), build=False)
        assert b.info == []


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestWindow:
    def test_the_window_lists_and_describes(self, intan_session):
        _qt_or_skip()
        b = DaqSystemBrowser(intan_session)
        assert b.list.count() == 1
        assert b.list.item(0).text() == "intan1"
        assert b.list.currentRow() == 0
        texts = b.detail_texts
        assert texts[0] == "intan1"
        assert "Files in each epoch" in texts
        assert "#.rhd" in texts
        assert "(.*)epochprobemap.ndi" in texts
        # short class name shown, full name on hover
        from PySide6 import QtWidgets

        labels = b.detail_panel.findChildren(QtWidgets.QLabel)
        intan = [w for w in labels if w.text() == "intan"]
        assert len(intan) == 1
        assert intan[0].toolTip() == "ndi.daq.reader.mfdaq.intan"
        assert not b.epoch_dropdown.isEnabled()

    def test_load_epochs_fills_the_chooser_and_table(self, intan_session):
        _qt_or_skip()
        b = DaqSystemBrowser(intan_session)
        b.epoch_button.click()
        assert b.epoch_dropdown.isEnabled()
        assert b.epoch_dropdown.count() == 1
        assert b.epoch_dropdown.currentText().startswith("Epoch 1")
        assert not b.epoch_button.isEnabled()
        names = [b.epoch_table.item(r, 0).text() for r in range(b.epoch_table.rowCount())]
        assert sorted(names) == ["rec1.epochprobemap.ndi", "rec1.rhd"]

    def test_reselecting_keeps_loaded_epochs(self, intan_session):
        _qt_or_skip()
        b = DaqSystemBrowser(intan_session)
        b.load_epochs()
        before = list(b.epoch_rows)
        b.select(0)
        assert b.epoch_dropdown.isEnabled()
        assert b.epoch_rows == before

    def test_no_daq_systems(self, tmp_path):
        _qt_or_skip()
        from ndi.session import ndi_session_dir

        b = DaqSystemBrowser(ndi_session_dir("empty", str(tmp_path)))
        assert not b.list.isEnabled()
        assert b.detail_texts == ["This session has no DAQ systems."]


if __name__ == "__main__":
    pytest.main([__file__])
