"""ndi.gui.nav.cloud_dataset_browser against MATLAB's cloudDatasetBrowser.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudDatasetBrowser.m`` (tests:
``tests/+ndi/+unittest/+gui/+nav/cloudDatasetBrowser_test.m``)

The decisions (record parsing, sorting, the delete checks, the group test)
are static and tested without a display. Deleting is tested with the
confirmation stubbed, so the rule that matters -- nothing is deleted unless
the confirmation says yes -- is checked headlessly.
"""

from __future__ import annotations

import math
import os

import pytest

from ndi.gui.nav.cloud_dataset_browser import COLUMN_NAMES, CloudDatasetBrowser

B = CloudDatasetBrowser


class TestRecords:
    def test_entries_from_list(self):
        answer = {
            "datasets": [
                {
                    "id": "d1",
                    "name": "Alpha",
                    "organizationId": "o1",
                    "organizationName": "Lab",
                    "documentCount": 12,
                    "fileCount": 3,
                    "createdAt": "2024-05-01T12:34:56.789Z",
                    "updatedAt": "2025-01-02T03:04:05Z",
                },
                {"_id": "d2", "name": "beta"},
                {"name": "no id"},
            ]
        }
        e = B.entries_from_list(answer)
        assert [x["id"] for x in e] == ["d1", "d2"]
        assert e[0]["documentCount"] == 12 and e[0]["detailed"]
        assert math.isnan(e[1]["documentCount"]) and not e[1]["detailed"]

    def test_merge_fills_only_missing(self):
        e = B.entry_from_record({"id": "d2", "name": "beta"})
        full = B.entry_from_record(
            {"id": "d2", "name": "renamed", "documentCount": 5, "fileCount": 0, "createdAt": "x"}
        )
        m = B.merge_entry(e, full)
        assert m["name"] == "beta"
        assert m["documentCount"] == 5 and m["fileCount"] == 0
        assert m["createdAt"] == "x"


class TestSort:
    def _entries(self):
        return B.entries_from_list(
            [
                {"id": "1", "name": "b", "documentCount": 5, "createdAt": "2024-02-01T00:00:00Z"},
                {"id": "2", "name": "A", "documentCount": 9, "createdAt": "2023-01-01T00:00:00Z"},
                {"id": "3", "name": "c"},
            ]
        )

    def test_each_direction_and_unknowns_last(self):
        e = self._entries()

        def ids(col, desc):
            return [x["id"] for x in B.sort_entries(e, col, desc)]

        assert ids("Name", False) == ["2", "1", "3"]
        assert ids("Name", True) == ["3", "1", "2"]
        assert ids("Documents", False) == ["1", "2", "3"]
        assert ids("Documents", True) == ["2", "1", "3"]
        assert ids("Created", False) == ["2", "1", "3"]

    def test_every_column_sorts_and_bad_column_raises(self):
        e = self._entries()
        for col in COLUMN_NAMES:
            assert len(B.sort_entries(e, col)) == 3
        with pytest.raises(ValueError):
            B.sort_entries(e, "Nope")

    def test_ties_keep_their_order_both_ways(self):
        e = B.entries_from_list(
            [{"id": "1", "name": "same"}, {"id": "2", "name": "same"}, {"id": "3", "name": "a"}]
        )
        assert [x["id"] for x in B.sort_entries(e, "Name", False)] == ["3", "1", "2"]
        assert [x["id"] for x in B.sort_entries(e, "Name", True)] == ["1", "2", "3"]


class TestDeleteChecks:
    def test_delete_allowed(self):
        f = B.delete_allowed
        assert f("My Data", "My Data", True, False, False)
        assert f("My Data", "  My Data ", True, False, False)
        assert not f("My Data", "my data", True, False, False)
        assert not f("My Data", "My Data", False, False, False)
        assert not f("My Data", "My Data", True, True, False)
        assert f("My Data", "My Data", True, True, True)
        assert not f("", "", True, False, False)

    def test_is_group_organization(self):
        f = B.is_group_organization
        assert f({"id": "o", "name": "Lab"})
        assert not f({"id": "o", "isPersonal": True})
        assert f({"id": "o", "isPersonal": False})
        assert not f({"id": "o", "type": "personal"})
        assert not f({"id": "o", "memberCount": 1})
        assert f({"id": "o", "memberCount": 4})
        assert f(None)

    def test_details_and_formatting(self):
        e = B.entry_from_record(
            {
                "id": "d1",
                "name": "Alpha",
                "organizationName": "Lab",
                "documentCount": 12,
                "createdAt": "2024-05-01T12:34:56.789Z",
            }
        )
        text = "\n".join(B.details_text(e, True))
        assert "d1" in text
        assert "2024-05-01 12:34 UTC" in text
        assert "Documents:     12" in text
        assert "Files:         (unknown)" in text
        assert "group organization" in text


class TestPublished:
    def _entries(self):
        return B.entries_from_list(
            [
                {"id": "p", "name": "pub", "isPublished": True},
                {"id": "u", "name": "unpub", "isPublished": False},
                {"id": "x", "name": "unknown"},
            ]
        )

    def test_is_published_is_read(self):
        f = B.entry_from_record
        assert f({"id": "d", "isPublished": True})["isPublished"] is True
        assert f({"id": "d", "isPublished": False})["isPublished"] is False
        assert f({"id": "d", "isPublished": "true"})["isPublished"] is True
        assert f({"id": "d"})["isPublished"] is False  # absent -> unpublished
        m = B.merge_entry(f({"id": "d"}), f({"id": "d", "isPublished": True}))
        assert m["isPublished"] is True
        text = "\n".join(B.details_text(f({"id": "d", "isPublished": True}), False))
        assert "Published:     Yes" in text
        assert B.entries_to_rows([f({"id": "d"})])[0][COLUMN_NAMES.index("Published")] == "No"

    def test_filter_sort_and_status(self):
        e = self._entries()

        def kept(p, u):
            return [x["id"] for x in B.filter_entries(e, p, u)]

        assert kept(True, True) == ["p", "u", "x"]
        assert kept(True, False) == ["p"]
        assert kept(False, True) == ["u", "x"]
        assert kept(False, False) == []
        assert [x["id"] for x in B.sort_entries(e, "Published", False)] == ["u", "x", "p"]
        assert [x["id"] for x in B.sort_entries(e, "Published", True)] == ["p", "u", "x"]
        assert B.count_status_text(3, 3) == "3 dataset(s)."
        assert B.count_status_text(1, 3) == "1 of 3 dataset(s) shown."

    def test_set_filter_keeps_all_entries(self):
        b = CloudDatasetBrowser(build=False)
        b.set_entries(self._entries())
        b.set_filter(False, True)
        assert [x["id"] for x in b.entries] == ["x", "u"]  # by Name: unknown, unpub
        b.set_sort("Name", True)  # sorting keeps the filter
        assert [x["id"] for x in b.entries] == ["u", "x"]
        b.set_filter(True, True)
        assert len(b.entries) == 3


class TestDeleteSelected:
    def _browser(self, monkeypatch, deleted):
        from ndi.cloud.api import datasets as datasets_api

        monkeypatch.setattr(datasets_api, "deleteDataset", lambda i, **k: deleted.append(i))
        monkeypatch.setattr(datasets_api, "getDataset", lambda i, **k: {"id": i})
        b = CloudDatasetBrowser(build=False)
        monkeypatch.setattr(b, "refresh", lambda: None)
        b.set_entries(B.entries_from_list([{"id": "d1", "name": "Alpha"}]))
        return b

    def test_nothing_selected_deletes_nothing(self, monkeypatch):
        deleted = []
        b = self._browser(monkeypatch, deleted)
        assert b.delete_selected(confirm=lambda e, g: True) is False
        assert deleted == []

    def test_a_declined_confirmation_deletes_nothing(self, monkeypatch):
        deleted = []
        b = self._browser(monkeypatch, deleted)
        b.select(0)
        assert b.delete_selected(confirm=lambda e, g: False) is False
        assert deleted == []

    def test_a_confirmed_delete_deletes_that_dataset(self, monkeypatch):
        deleted = []
        b = self._browser(monkeypatch, deleted)
        b.select(0)
        seen = []
        assert b.delete_selected(confirm=lambda e, g: seen.append((e["id"], g)) or True)
        assert deleted == ["d1"]
        # unknown organization -> the group confirmation is asked for
        assert seen == [("d1", True)]


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestWindow:
    def test_builds_without_loading_and_sorts(self):
        _qt_or_skip()
        b = CloudDatasetBrowser(load=False)
        b.set_entries(B.entries_from_list([{"id": "d1", "name": "b"}, {"id": "d2", "name": "a"}]))
        assert b.table.rowCount() == 2
        assert b.table.item(0, 0).text() == "a"
        assert not b.delete_button.isEnabled()
        assert not b.open_button.isVisible()  # no open_fcn

    def test_selecting_a_row_shows_details_and_enables_delete(self, monkeypatch):
        _qt_or_skip()
        from ndi.cloud.api import datasets as datasets_api

        monkeypatch.setattr(
            datasets_api,
            "getDataset",
            lambda i, **k: {"id": i, "documentCount": 7, "fileCount": 2},
        )
        b = CloudDatasetBrowser(load=False)
        b.set_entries(B.entries_from_list([{"id": "d1", "name": "Alpha"}]))
        b.table.selectRow(0)
        assert b.selected_index == 0
        assert b.id_field.text() == "d1"
        assert b.delete_button.isEnabled()
        assert b.table.item(0, 2).text() == "7"  # fetched by getDataset

    def test_include_checkboxes_filter_the_table(self):
        _qt_or_skip()
        b = CloudDatasetBrowser(load=False)
        b.set_entries(
            B.entries_from_list(
                [
                    {"id": "p", "name": "a", "isPublished": True},
                    {"id": "u", "name": "b", "isPublished": False},
                ]
            )
        )
        assert b.table.columnCount() == len(COLUMN_NAMES)
        assert b.table.item(0, COLUMN_NAMES.index("Published")).text() == "Yes"
        assert b.published_checkbox.isChecked() and b.unpublished_checkbox.isChecked()
        b.published_checkbox.setChecked(False)
        assert b.table.rowCount() == 1 and b.table.item(0, 0).text() == "b"
        assert "1 of 2" in b.status_label.text()
        b.set_filter(True, False)
        assert b.published_checkbox.isChecked() and not b.unpublished_checkbox.isChecked()
        assert b.table.rowCount() == 1 and b.table.item(0, 0).text() == "a"

    def test_sort_control_reorders(self):
        _qt_or_skip()
        b = CloudDatasetBrowser(load=False)
        b.set_entries(B.entries_from_list([{"id": "d1", "name": "b"}, {"id": "d2", "name": "a"}]))
        b.set_sort("Name", True)
        assert b.table.item(0, 0).text() == "b"
        assert b.sort_dir_button.text() == "Descending"


if __name__ == "__main__":
    pytest.main([__file__])
