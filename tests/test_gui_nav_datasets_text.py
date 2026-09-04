"""Tests for the pure helpers of ndi.gui.nav.datasets_pane.

MATLAB counterpart: the static methods of ndi.gui.nav.datasetsPane

These are the places where a port bug is invisible rather than loud: an
off-by-one in a plural, a reversed enablement flag, a sort that is
case-sensitive on one side and not the other. None of them raise; they just
say the wrong thing. So every rule gets a test, including the boundaries
(0 / 1 / many) where the wording actually changes.
"""

from __future__ import annotations

import pytest

from ndi.gui.nav.datasets_text import (
    UNNAMED_DATASET,
    UNNAMED_SESSION,
    append_count_phrase,
    append_workspace_var_names,
    cloud_check_message,
    cloud_dataset_id_label,
    cloud_summary_message,
    dataset_label,
    dataset_menu_enable,
    first_field,
    normalize_cloud_list,
    occupied_folder_message,
    order_app_menu,
    session_label,
    sync_result_message,
)


class TestAppendCountPhrase:
    def test_singular_and_plural(self):
        assert append_count_phrase([], {"f": [1]}, "f", "doc", "docs") == ["1 doc"]
        assert append_count_phrase([], {"f": [1, 2]}, "f", "doc", "docs") == ["2 docs"]

    def test_zero_contributes_nothing(self):
        assert append_count_phrase([], {"f": []}, "f", "doc", "docs") == []

    def test_absent_field_contributes_nothing(self):
        assert append_count_phrase([], {}, "f", "doc", "docs") == []

    def test_non_mapping_report_contributes_nothing(self):
        assert append_count_phrase([], None, "f", "doc", "docs") == []

    def test_appends_to_existing(self):
        assert append_count_phrase(["x"], {"f": [1]}, "f", "doc", "docs") == ["x", "1 doc"]


class TestOccupiedFolderMessage:
    @pytest.mark.parametrize(
        "kind,expected",
        [
            ("session", "an NDI session"),
            ("dataset", "an NDI dataset"),
            ("unknown", "an NDI directory"),
            ("something-else", "an NDI directory"),
        ],
    )
    def test_names_what_is_there(self, kind, expected):
        msg = occupied_folder_message(kind)
        assert expected in msg
        assert "empty folder" in msg


class TestNormalizeCloudList:
    def test_wrapper_shape(self):
        assert normalize_cloud_list({"datasets": [{"id": "a"}]}) == [{"id": "a"}]

    def test_bare_list(self):
        assert normalize_cloud_list([{"id": "a"}]) == [{"id": "a"}]

    def test_single_record_is_wrapped_not_iterated(self):
        """A bare dict must become one record, not its keys."""
        assert normalize_cloud_list({"id": "a"}) == [{"id": "a"}]

    def test_a_string_is_not_split_into_characters(self):
        """The failure a bare list() would produce."""
        assert normalize_cloud_list("abc") == []

    def test_none_and_empty(self):
        assert normalize_cloud_list(None) == []
        assert normalize_cloud_list([]) == []
        assert normalize_cloud_list({"datasets": []}) == []


class TestFirstField:
    def test_first_non_empty_wins(self):
        assert first_field({"a": "", "b": "x", "c": "y"}, ("a", "b", "c")) == "x"

    def test_missing_everything(self):
        assert first_field({}, ("a",)) == ""

    def test_non_mapping(self):
        assert first_field(None, ("a",)) == ""

    def test_order_of_candidates_is_respected(self):
        assert first_field({"a": "1", "b": "2"}, ("b", "a")) == "2"


class TestCloudDatasetIdLabel:
    def test_name_and_id(self):
        assert cloud_dataset_id_label({"id": "7", "name": "mine"}) == ("7", "mine  (7)")

    def test_alternate_id_field(self):
        assert cloud_dataset_id_label({"_id": "9", "name": "n"})[0] == "9"

    def test_name_only(self):
        assert cloud_dataset_id_label({"name": "n"}) == ("", "n")

    def test_id_only_labels_by_id(self):
        assert cloud_dataset_id_label({"id": "7"}) == ("7", "7")

    def test_neither_gives_empty_not_punctuation(self):
        """Not '  ()' -- an empty record should look empty, not malformed."""
        assert cloud_dataset_id_label({}) == ("", "")


class TestAppendWorkspaceVarNames:
    def test_quotes_and_joins(self):
        assert append_workspace_var_names("myref", ["S", "S2"]) == 'myref "S", "S2"'

    def test_single(self):
        assert append_workspace_var_names("r", ["S"]) == 'r "S"'

    def test_empty_leaves_the_label_alone(self):
        """Not a trailing space: an undecorated node must look undecorated."""
        assert append_workspace_var_names("r", []) == "r"
        assert append_workspace_var_names("r", None) == "r"


class TestDatasetMenuEnable:
    def test_in_cloud_blocks_upload_and_allows_linked(self):
        assert dataset_menu_enable("incloud") == (False, True)

    def test_not_in_cloud_allows_upload_and_blocks_linked(self):
        assert dataset_menu_enable("notincloud") == (True, False)

    @pytest.mark.parametrize("state", ["unknown", "", None, "anything"])
    def test_unknown_blocks_nothing(self, state):
        """Deliberate: before the status is checked, disabling an action would
        block a user because we have not looked yet."""
        assert dataset_menu_enable(state) == (True, True)


class TestCloudSummaryMessage:
    def test_no_datasets(self):
        assert cloud_summary_message({"total": 0}) == "There are no datasets to check."

    def test_singular_noun(self):
        assert cloud_summary_message({"total": 1, "in_cloud": 1}) == (
            "1 of 1 dataset is in NDI Cloud."
        )

    def test_plural_noun(self):
        assert cloud_summary_message({"total": 5, "in_cloud": 3}) == (
            "3 of 5 datasets are in NDI Cloud."
        )

    def test_camel_case_key_is_accepted(self):
        assert "3 of 5" in cloud_summary_message({"total": 5, "inCloud": 3})

    def test_one_error_is_noted(self):
        msg = cloud_summary_message({"total": 5, "in_cloud": 3, "errors": 1})
        assert msg.endswith("1 dataset could not be checked.")

    def test_several_errors_are_noted(self):
        msg = cloud_summary_message({"total": 5, "in_cloud": 3, "errors": 2})
        assert msg.endswith("2 datasets could not be checked.")

    def test_zero_errors_adds_nothing(self):
        msg = cloud_summary_message({"total": 5, "in_cloud": 3, "errors": 0})
        assert "could not be checked" not in msg


class TestCloudCheckMessage:
    @pytest.mark.parametrize("side", ["remote", "local"])
    @pytest.mark.parametrize("count", [0, 1, 2])
    def test_every_branch_produces_a_sentence(self, side, count):
        msg = cloud_check_message(side, count)
        assert msg and msg.endswith(".")

    def test_remote_wording(self):
        assert "no new documents on the cloud" in cloud_check_message("remote", 0)
        assert cloud_check_message("remote", 1).startswith("There is 1 document")
        assert "There are 4 documents" in cloud_check_message("remote", 4)

    def test_local_wording(self):
        assert "no new local documents" in cloud_check_message("local", 0)
        assert cloud_check_message("local", 1).startswith("There is 1 local document")
        assert "There are 4 local documents" in cloud_check_message("local", 4)

    def test_bad_side_raises(self):
        with pytest.raises(ValueError, match="remote"):
            cloud_check_message("sideways", 1)


class TestSyncResultMessage:
    def test_no_changes(self):
        assert sync_result_message({}) == "Done. No changes were needed."
        assert sync_result_message(None) == "Done. No changes were needed."

    def test_all_zero_counts_still_says_no_changes(self):
        """Four zeroes must not print as four lines of nothing."""
        report = {
            "uploaded_document_ids": [],
            "downloaded_document_ids": [],
            "deleted_local_document_ids": [],
            "deleted_remote_document_ids": [],
        }
        assert sync_result_message(report) == "Done. No changes were needed."

    def test_one_phrase(self):
        assert sync_result_message({"uploaded_document_ids": ["a"]}) == (
            "Done. 1 document uploaded"
        )

    def test_several_phrases_in_report_order(self):
        report = {
            "downloaded_document_ids": ["a", "b"],
            "uploaded_document_ids": ["c"],
            "deleted_remote_document_ids": ["d"],
        }
        assert sync_result_message(report) == (
            "Done. 1 document uploaded\n2 documents downloaded\n1 remote document deleted"
        )

    def test_order_does_not_follow_the_dict(self):
        """Two reports with the same content in different key order must give
        the same message."""
        a = {"uploaded_document_ids": ["x"], "downloaded_document_ids": ["y"]}
        b = {"downloaded_document_ids": ["y"], "uploaded_document_ids": ["x"]}
        assert sync_result_message(a) == sync_result_message(b)


class TestOrderAppMenu:
    def test_empty(self):
        assert order_app_menu([]) == []
        assert order_app_menu(None) == []

    def test_uncategorised_apps_sort_alphabetically(self):
        apps = [{"Label": "Zeta"}, {"Label": "Alpha"}]
        assert [e["label"] for e in order_app_menu(apps)] == ["Alpha", "Zeta"]

    def test_categories_and_apps_interleave(self):
        apps = [
            {"Label": "Zebra"},
            {"Label": "One", "Category": "Analysis"},
            {"Label": "Mango"},
        ]
        assert [e["label"] for e in order_app_menu(apps)] == [
            "Analysis",
            "Mango",
            "Zebra",
        ]

    def test_sorting_is_case_insensitive(self):
        """A case-SENSITIVE sort puts every capitalised name before every
        lowercase one, so the two ports would order the same menu differently
        while both looking sorted."""
        apps = [{"Label": "banana"}, {"Label": "Apple"}, {"Label": "cherry"}]
        assert [e["label"] for e in order_app_menu(apps)] == [
            "Apple",
            "banana",
            "cherry",
        ]

    def test_apps_within_a_category_are_sorted(self):
        apps = [
            {"Label": "zed", "Category": "Tools"},
            {"Label": "Ant", "Category": "Tools"},
        ]
        entries = order_app_menu(apps)
        assert len(entries) == 1
        assert entries[0]["kind"] == "category"
        assert [a["Label"] for a in entries[0]["apps"]] == ["Ant", "zed"]

    def test_a_category_appears_once(self):
        apps = [
            {"Label": "a", "Category": "C"},
            {"Label": "b", "Category": "C"},
            {"Label": "c", "Category": "C"},
        ]
        entries = order_app_menu(apps)
        assert len(entries) == 1
        assert len(entries[0]["apps"]) == 3

    def test_uncategorised_entry_carries_its_record(self):
        app = {"Label": "Solo"}
        entry = order_app_menu([app])[0]
        assert entry["kind"] == "app"
        assert entry["apps"] is app

    def test_empty_category_string_counts_as_uncategorised(self):
        entries = order_app_menu([{"Label": "X", "Category": ""}])
        assert entries[0]["kind"] == "app"


class TestLabels:
    def test_dataset_label_from_a_callable_reference(self):
        class DS:
            def reference(self):
                return "ref1"

        assert dataset_label(DS()) == "ref1"

    def test_dataset_label_from_a_plain_attribute(self):
        class DS:
            reference = "ref2"

        assert dataset_label(DS()) == "ref2"

    def test_dataset_label_falls_back_when_blank(self):
        class DS:
            reference = ""

        assert dataset_label(DS()) == UNNAMED_DATASET

    def test_dataset_label_falls_back_to_the_class_name_when_raising(self):
        """MATLAB uses class(ds) here, NOT the unnamed placeholder -- a broken
        object still says what kind of thing it is, which is more useful than
        "(unnamed dataset)". The placeholder is only for a blank reference."""

        class DS:
            @property
            def reference(self):
                raise RuntimeError("no")

        assert dataset_label(DS()) == "DS"

    def test_session_label_falls_back_to_the_class_name_when_raising(self):
        class S:
            @property
            def reference(self):
                raise RuntimeError("no")

        assert session_label(S()) == "S"

    def test_session_label(self):
        class S:
            reference = "sess"

        assert session_label(S()) == "sess"

    def test_session_label_falls_back(self):
        class S:
            reference = ""

        assert session_label(S()) == UNNAMED_SESSION
