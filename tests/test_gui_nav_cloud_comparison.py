"""ndi.gui.nav.cloud_comparison against MATLAB's cloudComparison.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudComparison.m`` (tests:
``tests/+ndi/+unittest/+gui/+nav/cloudComparison_test.m``)

What the window says is decided by static methods, tested everywhere. The
sync buttons are checked through ``run_action`` with the widgets absent, so
the rule that matters -- a mirror never runs without a confirmation -- is
tested without a display. The window itself is built under the offscreen
platform and skips without PySide6.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.nav import datasets_cloud
from ndi.gui.nav.cloud_comparison import ACTION_SPECS, CloudComparison

C = CloudComparison


class FakeDataset:
    reference = "myds"

    def id(self):
        return "local-id"

    def getpath(self):
        return "/data/copy1"


class TestWhatItSays:
    def test_summary_counts_and_in_sync(self):
        report = {"remote_only_ids": ["a", "b"], "local_only_ids": ["c"], "common_ids": ["d"]}
        msg = C.summary_text(report)
        assert "Only in cloud: 2" in msg
        assert "Only local: 1" in msg
        assert "In both: 1" in msg
        assert "in sync" not in msg
        assert "Content differs" not in msg
        assert "in sync" in C.summary_text({"common_ids": ["d"]})

    def test_summary_reports_content_differences(self):
        msg = C.summary_text({"common_ids": ["d", "e"], "mismatched_ids": ["e"]})
        assert "Content differs: 1" in msg
        assert "in sync" not in msg

    def test_rows_order_and_labels(self):
        report = {
            "remote_only_ids": ["r1"],
            "local_only_ids": ["l1"],
            "common_ids": ["c1", "c2"],
            "mismatched_ids": ["c2"],
        }
        assert C.comparison_rows(report) == [
            ("r1", "Only in cloud"),
            ("l1", "Only local"),
            ("c2", "In both - content differs"),
            ("c1", "In both"),
        ]
        assert C.comparison_rows({}) == []
        assert C.comparison_rows(None) == []

    def test_action_specs_cover_every_sync_mode(self):
        from ndi.cloud.sync import SyncMode

        assert len(ACTION_SPECS) == len(list(SyncMode))
        assert {s["mode"] for s in ACTION_SPECS if s["destructive"]} == {
            "mirrorFromRemote",
            "mirrorToRemote",
        }
        # every key is one datasets_cloud can run
        for spec in ACTION_SPECS:
            table = (
                datasets_cloud.MIRROR_MODES if spec["destructive"] else datasets_cloud.SYNC_MODES
            )
            assert table[spec["key"]][0] == spec["mode"]

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            C.action_spec("nope")

    def test_mirror_warning_names_counts_and_places(self):
        report = {"remote_only_ids": ["a", "b", "c"], "local_only_ids": ["x"]}
        msg = C.mirror_warning("mirrorFromRemote", report, "/data/copy1", "CLOUD1")
        assert "1 document will be permanently DELETED from this local copy" in msg
        assert "/data/copy1" in msg and "CLOUD1" in msg
        msg = C.mirror_warning("mirrorToRemote", report, "/data/copy1", "CLOUD1")
        assert "3 documents will be permanently DELETED from the cloud dataset" in msg

    def test_mirror_warning_without_report_and_bad_mode(self):
        assert "permanently DELETED" in C.mirror_warning("mirrorToRemote", None, "", "")
        with pytest.raises(ValueError):
            C.mirror_warning("uploadNew", None, "", "")


class TestRunAction:
    """No widgets: the options boxes are absent, so both options are off."""

    def _window(self):
        return CloudComparison(FakeDataset(), cloud_dataset_id="CLOUD1", build=False)

    def test_header_values(self):
        w = self._window()
        assert w.dataset_name == "myds"
        assert w.local_path == "/data/copy1"
        assert w.cloud_dataset_id == "CLOUD1"

    def test_a_declined_mirror_never_runs(self, monkeypatch):
        calls = []
        monkeypatch.setattr(datasets_cloud, "mirror_dataset", lambda *a, **k: calls.append(a))
        w = self._window()
        asked = []
        assert w.run_action("mirrorToRemote", confirm=lambda t, p: asked.append(p) or False) is None
        assert calls == []
        assert asked and "DELETED from the cloud dataset" in asked[0]

    def test_a_mirror_without_a_confirm_is_refused(self, monkeypatch):
        calls = []
        monkeypatch.setattr(datasets_cloud, "mirror_dataset", lambda *a, **k: calls.append(a))
        assert self._window().run_action("mirrorFromRemote") is None
        assert calls == []

    def test_an_accepted_mirror_runs_and_refreshes(self, monkeypatch):
        calls = []

        def mirror(ds, key, **kwargs):
            calls.append((key, kwargs))
            return datasets_cloud.CloudActionResult(True, "Mirror to Cloud", "Done.", "success")

        monkeypatch.setattr(datasets_cloud, "mirror_dataset", mirror)
        w = self._window()
        refreshed = []
        monkeypatch.setattr(w, "refresh", lambda: refreshed.append(True))
        result = w.run_action("mirrorToRemote", confirm=lambda t, p: True)
        assert result.ok
        assert calls == [("to_remote", {"sync_files": False, "dry_run": False})]
        assert refreshed == [True]

    def test_additive_modes_need_no_confirmation(self, monkeypatch):
        calls = []

        def sync(ds, key, **kwargs):
            calls.append(key)
            return datasets_cloud.CloudActionResult(True, "x", "Done.", "success")

        monkeypatch.setattr(datasets_cloud, "sync_dataset", sync)
        w = self._window()
        monkeypatch.setattr(w, "refresh", lambda: None)
        for mode in ("downloadNew", "uploadNew", "twoWaySync"):
            w.run_action(mode)
        assert calls == ["download_new", "upload_new", "two_way_sync"]

    def test_compare_uses_document_difference(self, monkeypatch):
        from ndi.cloud.sync import operations

        monkeypatch.setattr(
            operations,
            "documentDifference",
            lambda ds, cid: {"remote_only_ids": ["a"], "local_only_ids": [], "common_ids": []},
        )
        w = self._window()
        report = w.refresh()
        assert report["remote_only_ids"] == ["a"]
        assert w.report is report

    def test_unlinked_dataset_does_not_compare(self, monkeypatch):
        monkeypatch.setattr(
            datasets_cloud,
            "resolve_cloud_target",
            lambda ds: (_ for _ in ()).throw(ValueError("not linked")),
        )
        w = CloudComparison(FakeDataset(), build=False)
        assert w.cloud_dataset_id == ""
        assert w.refresh() is None


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestWindow:
    def test_builds_with_header_and_buttons(self):
        _qt_or_skip()
        w = CloudComparison(FakeDataset(), cloud_dataset_id="CLOUD1", compute=False)
        from PySide6 import QtWidgets

        path = w.figure.findChild(QtWidgets.QLineEdit, "ndiComparePath")
        cloud = w.figure.findChild(QtWidgets.QLineEdit, "ndiCompareCloudId")
        assert path.text() == "/data/copy1"
        assert cloud.text() == "CLOUD1"
        assert [b.text() for b in w.action_buttons] == [s["label"] for s in ACTION_SPECS]

    def test_report_fills_the_table(self, monkeypatch):
        _qt_or_skip()
        from ndi.cloud.sync import operations

        monkeypatch.setattr(
            operations,
            "documentDifference",
            lambda ds, cid: {"remote_only_ids": ["a"], "local_only_ids": ["b"], "common_ids": []},
        )
        w = CloudComparison(FakeDataset(), cloud_dataset_id="CLOUD1")
        assert w.table.rowCount() == 2
        assert "Only in cloud: 1" in w.summary_label.text()
        assert all(b.isEnabled() for b in w.action_buttons)

    def test_dry_run_box_reaches_the_sync(self, monkeypatch):
        _qt_or_skip()
        calls = []

        def mirror(ds, key, **kwargs):
            calls.append(kwargs)
            return datasets_cloud.CloudActionResult(True, "x", "Done.", "success")

        monkeypatch.setattr(datasets_cloud, "mirror_dataset", mirror)
        w = CloudComparison(FakeDataset(), cloud_dataset_id="CLOUD1", compute=False)
        w.dry_run_box.setChecked(True)
        # a dry run deletes nothing, so it is not asked about
        w.run_action("mirrorToRemote")
        assert calls == [{"sync_files": False, "dry_run": True}]


if __name__ == "__main__":
    pytest.main([__file__])
