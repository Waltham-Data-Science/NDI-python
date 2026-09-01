"""Tests for ndi.gui.preferences_editor.

MATLAB counterpart: ndi.gui.preferencesEditor

The weight is on the model half of the module. An editor bug is rarely an
exception: it is a row labelled with the wrong preference, a category node
that hides the items filed under its subcategories, a "500000000" that
reaches the JSON file as the string it was typed as, or -- worst -- a
keystroke that writes itself to disk before the user pressed Apply. Those are
all decisions about plain values, so plain values are what get tested.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import json

import pytest

from ndi.gui.preferences_editor import (
    DEFAULT_POSITION,
    WINDOW_TAG,
    ApplyResult,
    PreferenceRow,
    PreferencesEditor,
    PreferencesEditorState,
    build_tree,
    coerce_value,
    display_text,
    item_path,
    matching_indices,
    preferences_editor,
    preferencesEditor,
    row_label,
    widget_kind,
)
from ndi.preferences import ndi_preferences


def make_prefs(tmp_path):
    """A real preferences store on a temporary file.

    Real rather than faked so the Apply path is exercised against the code
    that actually writes the JSON. Two extra items are registered so the
    editor's three widget kinds -- numeric, checkbox, text -- all appear.
    """
    prefs = ndi_preferences(filename=tmp_path / "NDI_Preferences.json")
    prefs._add_item("Display", "", "Verbose", True, "bool", "Print more while working.")
    prefs._add_item("Display", "Theme", "Name", "light", "str", "Colour theme name.")
    return prefs


ITEMS = [
    {
        "category": "Cloud",
        "subcategory": "Download",
        "name": "Batch",
        "value": 1,
        "default_value": 1,
        "description": "d",
        "type": "int",
    },
    {
        "category": "Cloud",
        "subcategory": "Upload",
        "name": "Batch",
        "value": 2,
        "default_value": 2,
        "description": "u",
        "type": "int",
    },
    {
        "category": "Cloud",
        "subcategory": "",
        "name": "Token",
        "value": "x",
        "default_value": "x",
        "description": "t",
        "type": "str",
    },
    {
        "category": "Display",
        "subcategory": "",
        "name": "Verbose",
        "value": True,
        "default_value": True,
        "description": "v",
        "type": "bool",
    },
]


class TestItemPath:
    def test_two_part_path_when_no_subcategory(self):
        assert item_path(ITEMS[2]) == "Cloud.Token"

    def test_three_part_path_with_subcategory(self):
        assert item_path(ITEMS[1]) == "Cloud.Upload.Batch"

    def test_the_path_is_what_preferences_takes(self, tmp_path):
        """The point of the path: it round-trips through the store."""
        prefs = make_prefs(tmp_path)
        for item in prefs.list_items():
            assert prefs.has(item_path(item))


class TestBuildTree:
    def test_one_node_per_category_in_registration_order(self):
        nodes = build_tree(ITEMS)
        assert [n.text for n in nodes] == ["Cloud", "Display"]

    def test_subcategories_become_children(self):
        cloud = build_tree(ITEMS)[0]
        assert [c.text for c in cloud.children] == ["Download", "Upload"]
        assert all(c.category == "Cloud" for c in cloud.children)

    def test_items_without_a_subcategory_add_no_child(self):
        """'Cloud.Token' has no subcategory, so it must not produce an
        empty-named node that selects nothing."""
        cloud = build_tree(ITEMS)[0]
        assert "" not in [c.text for c in cloud.children]

    def test_a_category_node_carries_an_empty_subcategory(self):
        assert build_tree(ITEMS)[0].subcategory == ""

    def test_no_items_no_nodes(self):
        assert build_tree([]) == []


class TestMatchingIndices:
    def test_a_category_shows_its_subcategory_items_too(self):
        """The editor opens on a category node. If that node showed only the
        subcategory-less items, the store's preferences would all be
        invisible on first open."""
        assert matching_indices(ITEMS, "Cloud") == [0, 1, 2]

    def test_a_subcategory_narrows_to_itself(self):
        assert matching_indices(ITEMS, "Cloud", "Upload") == [1]

    def test_an_unknown_category_matches_nothing(self):
        assert matching_indices(ITEMS, "Nope") == []


class TestRowLabel:
    def test_plain_name_by_default(self):
        assert row_label(ITEMS[1]) == "Batch"

    def test_pending_marks_the_name(self):
        assert row_label(ITEMS[1], pending=True) == "Batch*"

    def test_the_prefix_goes_in_front_of_the_marked_name(self):
        """MATLAB marks the name, then prefixes the subcategory, so the
        asterisk ends the label rather than sitting mid-string."""
        assert row_label(ITEMS[1], pending=True, show_subcategory=True) == "Upload / Batch*"

    def test_no_prefix_for_an_item_with_no_subcategory(self):
        assert row_label(ITEMS[2], show_subcategory=True) == "Token"


class TestWidgetKind:
    @pytest.mark.parametrize("type_name", ["double", "single", "float", "int", "INT"])
    def test_numeric_types(self, type_name):
        assert widget_kind(type_name) == "numeric"

    @pytest.mark.parametrize("type_name", ["logical", "bool"])
    def test_boolean_types(self, type_name):
        assert widget_kind(type_name) == "bool"

    @pytest.mark.parametrize("type_name", ["str", "any", "", "struct", None])
    def test_everything_else_is_text(self, type_name):
        """MATLAB's otherwise branch: a type this editor was never taught
        is still editable as its printed form."""
        assert widget_kind(type_name) == "text"


class TestDisplayText:
    def test_a_string_passes_through(self):
        assert display_text("light") == "light"

    def test_none_is_empty(self):
        assert display_text(None) == ""

    def test_a_bool_prints_lowercase(self):
        assert display_text(True) == "true"
        assert display_text(False) == "false"

    def test_a_number_prints(self):
        assert display_text(500000000) == "500000000"


class TestCoerceValue:
    def test_int_from_text(self):
        assert coerce_value("10", "int") == 10
        assert isinstance(coerce_value("10", "int"), int)

    def test_int_accepts_a_whole_float(self):
        """A numeric field can hand back '10.0'; the preference is still int."""
        assert coerce_value("10.0", "int") == 10

    def test_int_rejects_a_fraction(self):
        with pytest.raises(ValueError):
            coerce_value("10.5", "int")

    def test_float_from_text(self):
        assert coerce_value("5e8", "float") == 5e8

    def test_a_number_stays_a_number_not_a_string(self):
        """The bug this guards: preferences.set stores what it is given, so
        an uncoerced field would put the string '500000000' in the JSON."""
        prefs_value = coerce_value("500000000", "float")
        assert prefs_value == 500000000.0
        assert not isinstance(prefs_value, str)

    def test_number_rejects_nonsense(self):
        with pytest.raises(ValueError):
            coerce_value("abc", "float")

    @pytest.mark.parametrize("raw,expected", [("true", True), ("0", False), (True, True)])
    def test_bool_from_widget_or_text(self, raw, expected):
        assert coerce_value(raw, "bool") is expected

    def test_bool_rejects_nonsense(self):
        with pytest.raises(ValueError):
            coerce_value("maybe", "bool")

    def test_str_stringifies(self):
        assert coerce_value(3, "str") == "3"

    def test_any_is_left_alone(self):
        marker = object()
        assert coerce_value(marker, "any") is marker


class TestState:
    def test_opens_on_the_first_category(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        assert state.selection == ("Cloud", "")

    def test_rows_cover_the_whole_category(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        assert [r.path for r in state.rows()] == [
            "Cloud.Download.Max_Document_Batch_Count",
            "Cloud.Upload.Max_Document_Batch_Count",
            "Cloud.Upload.Max_File_Batch_Size",
        ]

    def test_selecting_a_subcategory_narrows_the_rows(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        state.select("Cloud", "Upload")
        assert [r.label for r in state.rows()] == [
            "Max_Document_Batch_Count",
            "Max_File_Batch_Size",
        ]

    def test_rows_carry_the_kind_and_the_tooltip(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        state.select("Display")
        rows = {r.label: r for r in state.rows()}
        assert rows["Verbose"].kind == "bool"
        assert rows["Verbose"].description == "Print more while working."
        assert rows["Theme / Name"].kind == "text"

    def test_a_pending_edit_shows_in_the_row_and_nowhere_else(self, tmp_path):
        """THE contract of this editor: nothing reaches the store or the file
        before Apply."""
        prefs = make_prefs(tmp_path)
        state = PreferencesEditorState(prefs)
        state.select("Cloud", "Upload")
        index = state.rows()[1].index
        state.set_pending(index, "12345")

        row = [r for r in state.rows() if r.index == index][0]
        assert row.value == "12345"
        assert row.pending and row.label.endswith("*")
        assert prefs.get("Cloud.Upload.Max_File_Batch_Size") == 500_000_000
        assert not (tmp_path / "NDI_Preferences.json").exists()

    def test_set_pending_rejects_an_index_that_is_not_an_item(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        with pytest.raises(IndexError):
            state.set_pending(len(state.items), 1)

    def test_revert_drops_the_edits_without_touching_the_store(self, tmp_path):
        prefs = make_prefs(tmp_path)
        state = PreferencesEditorState(prefs)
        state.set_pending(0, "7")
        state.revert()
        assert state.pending == {}
        assert not any(r.pending for r in state.rows())
        assert prefs.get("Cloud.Download.Max_Document_Batch_Count") == 10000

    def test_apply_writes_through_the_store_and_the_file(self, tmp_path):
        prefs = make_prefs(tmp_path)
        state = PreferencesEditorState(prefs)
        state.select("Cloud", "Upload")
        index = [r for r in state.rows() if r.label == "Max_File_Batch_Size"][0].index
        state.set_pending(index, "12345")

        result = state.apply()

        assert result.ok and result.applied == ["Cloud.Upload.Max_File_Batch_Size"]
        assert prefs.get("Cloud.Upload.Max_File_Batch_Size") == 12345.0
        on_disk = json.loads((tmp_path / "NDI_Preferences.json").read_text())
        assert on_disk["Cloud__Upload__Max_File_Batch_Size"] == 12345.0

    def test_apply_clears_the_marks_and_refreshes_the_snapshot(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        state.set_pending(0, "42")
        state.apply()
        assert state.pending == {}
        rows = {r.label: r for r in state.rows()}
        assert rows["Download / Max_Document_Batch_Count"].value == 42
        assert not rows["Download / Max_Document_Batch_Count"].pending

    def test_apply_coerces_to_the_declared_type(self, tmp_path):
        """A text field hands back a string; an int preference must not
        become one."""
        prefs = make_prefs(tmp_path)
        state = PreferencesEditorState(prefs)
        state.set_pending(0, "42")
        state.apply()
        assert prefs.get("Cloud.Download.Max_Document_Batch_Count") == 42
        assert isinstance(prefs.get("Cloud.Download.Max_Document_Batch_Count"), int)

    def test_a_bad_value_stops_the_write_and_is_reported(self, tmp_path):
        """MATLAB aborts on the first failure, keeps what it already wrote,
        and leaves the pending edits alone so the user can fix the one
        offending value."""
        prefs = make_prefs(tmp_path)
        state = PreferencesEditorState(prefs)
        state.set_pending(0, "42")
        state.set_pending(1, "not a number")
        state.set_pending(2, "7")

        result = state.apply()

        assert not result.ok
        assert "Cloud.Upload.Max_Document_Batch_Count" in result.error
        assert result.applied == ["Cloud.Download.Max_Document_Batch_Count"]
        assert prefs.get("Cloud.Download.Max_Document_Batch_Count") == 42
        assert prefs.get("Cloud.Upload.Max_Document_Batch_Count") == 100000
        assert prefs.get("Cloud.Upload.Max_File_Batch_Size") == 500_000_000
        assert set(state.pending) == {0, 1, 2}

    def test_apply_with_nothing_pending_writes_nothing(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        result = state.apply()
        assert result == ApplyResult(applied=[], error=None)

    def test_rows_are_empty_with_no_preferences(self):
        class EmptyStore:
            def list_items(self):
                return []

        state = PreferencesEditorState(EmptyStore())
        assert state.selection is None
        assert state.rows() == []

    def test_a_row_is_a_plain_value(self, tmp_path):
        state = PreferencesEditorState(make_prefs(tmp_path))
        assert isinstance(state.rows()[0], PreferenceRow)


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


def _category_item(editor, text):
    """The top-level tree item for the category TEXT.

    Found by name rather than by index: the tree mirrors whatever
    preferences NDI registers, so a newly registered built-in category
    (GUI.Navigator.SessionAppPackages, say) must not shift these tests onto
    the wrong node.
    """
    tree = editor.tree_widget
    for i in range(tree.topLevelItemCount()):
        if tree.topLevelItem(i).text(0) == text:
            return tree.topLevelItem(i)
    raise AssertionError(f"no {text!r} category in the tree")


class TestWindow:
    def test_window_is_titled_and_tagged(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        assert editor.figure.windowTitle() == "NDI Preferences"
        assert editor.figure.objectName() == WINDOW_TAG

    def test_default_geometry_is_matlabs(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        assert DEFAULT_POSITION == (100, 100, 820, 540)
        assert editor.figure.width() == 820

    def test_the_tree_mirrors_the_model(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        tree = editor.tree_widget
        texts = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
        assert texts == [node.text for node in editor.state.tree()]
        assert texts[0] == "Cloud"
        assert "Display" in texts
        cloud = tree.topLevelItem(0)
        assert [cloud.child(i).text(0) for i in range(cloud.childCount())] == [
            "Download",
            "Upload",
        ]

    def test_one_widget_per_row(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        rows = editor.state.rows()
        assert len(editor.row_widgets) == len(rows) == 3
        assert set(editor.row_widgets) == {r.index for r in rows}

    def test_selecting_a_subcategory_redraws_the_rows(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        cloud = editor.tree_widget.topLevelItem(0)
        editor.tree_widget.setCurrentItem(cloud.child(1))  # Upload
        assert editor.state.selection == ("Cloud", "Upload")
        assert [lbl.text() for lbl in editor.row_labels.values()] == [
            "Max_Document_Batch_Count",
            "Max_File_Batch_Size",
        ]

    def test_the_widget_kind_follows_the_type(self, tmp_path):
        _qt_or_skip()
        from PySide6 import QtWidgets

        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        editor.tree_widget.setCurrentItem(_category_item(editor, "Display"))
        kinds = {editor.row_labels[i].text(): type(w) for i, w in editor.row_widgets.items()}
        assert kinds["Verbose"] is QtWidgets.QCheckBox
        assert kinds["Theme / Name"] is QtWidgets.QLineEdit

    def test_editing_a_field_marks_the_row_and_writes_nothing(self, tmp_path):
        _qt_or_skip()
        prefs = make_prefs(tmp_path)
        editor = PreferencesEditor(prefs=prefs)
        index, widget = next(iter(editor.row_widgets.items()))
        widget.setText("77")
        widget.editingFinished.emit()

        assert editor.state.pending[index] == "77"
        assert editor.row_labels[index].text().endswith("*")
        assert prefs.get("Cloud.Download.Max_Document_Batch_Count") == 10000

    def test_leaving_a_field_untouched_marks_nothing(self, tmp_path):
        """editingFinished also fires on plain focus loss. Recording that
        would asterisk every row the user tabbed across and hand Apply a
        pile of writes nobody made."""
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        index, widget = next(iter(editor.row_widgets.items()))
        widget.editingFinished.emit()
        assert editor.state.pending == {}
        assert not editor.row_labels[index].text().endswith("*")

    def test_a_second_edit_does_not_double_the_mark(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        index, widget = next(iter(editor.row_widgets.items()))
        widget.setText("77")
        widget.editingFinished.emit()
        widget.setText("78")
        widget.editingFinished.emit()
        assert not editor.row_labels[index].text().endswith("**")

    def test_a_checkbox_records_its_new_state(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        editor.tree_widget.setCurrentItem(_category_item(editor, "Display"))
        index = [r.index for r in editor.state.rows() if r.kind == "bool"][0]
        editor.row_widgets[index].setChecked(False)
        assert editor.state.pending[index] is False

    def test_apply_persists_and_clears_the_marks(self, tmp_path):
        _qt_or_skip()
        prefs = make_prefs(tmp_path)
        editor = PreferencesEditor(prefs=prefs)
        index, widget = next(iter(editor.row_widgets.items()))
        widget.setText("77")
        widget.editingFinished.emit()

        result = editor.on_apply()

        assert result.ok
        assert prefs.get("Cloud.Download.Max_Document_Batch_Count") == 77
        assert not any(lbl.text().endswith("*") for lbl in editor.row_labels.values())

    def test_revert_puts_the_saved_value_back_in_the_field(self, tmp_path):
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        index, widget = next(iter(editor.row_widgets.items()))
        widget.setText("77")
        widget.editingFinished.emit()

        editor.on_revert()

        assert editor.state.pending == {}
        assert editor.row_widgets[index].text() == "10000"

    def test_save_applies_then_closes(self, tmp_path):
        _qt_or_skip()
        prefs = make_prefs(tmp_path)
        editor = PreferencesEditor(prefs=prefs)
        editor.show()
        index, widget = next(iter(editor.row_widgets.items()))
        widget.setText("77")
        widget.editingFinished.emit()

        result = editor.on_save()

        assert result.ok
        assert prefs.get("Cloud.Download.Max_Document_Batch_Count") == 77
        assert not editor.is_open()

    def test_save_stays_open_when_a_value_will_not_convert(self, tmp_path, monkeypatch):
        """The window has to stay up: the value the user must fix is in it."""
        _qt_or_skip()
        editor = PreferencesEditor(prefs=make_prefs(tmp_path))
        editor.show()
        monkeypatch.setattr(editor, "_alert", lambda *a, **k: None)
        index = next(iter(editor.row_widgets))
        editor.state.set_pending(index, "not a number")

        result = editor.on_save()

        assert not result.ok
        assert editor.is_open()

    def test_the_function_form_returns_an_open_editor(self, tmp_path):
        _qt_or_skip()
        editor = preferences_editor(prefs=make_prefs(tmp_path))
        assert isinstance(editor, PreferencesEditor)
        assert editor.is_open()
        editor.close()

    def test_the_matlab_cased_alias_is_the_same_function(self):
        assert preferencesEditor is preferences_editor
