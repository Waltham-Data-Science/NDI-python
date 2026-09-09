"""The diff reports still answer their pre-#252 key names, and say so.

NDI-python#252 renamed the report fields to MATLAB's, so that a report
written in one language reads in the other. That is a real break for anyone
who read the old ones, and a bare ``KeyError`` says nothing about what
replaced it -- the reader has to go find the commit.

So the old names keep working and warn once. The warning is a FutureWarning,
not a DeprecationWarning: these reports are read by analysis scripts, and
DeprecationWarning is hidden by default outside ``__main__``.

Membership and iteration deliberately do NOT accept the old names, so
``set(report)`` and ``"only_in_s1" in report`` still describe the real shape.
"""

from __future__ import annotations

import pytest

from ndi.fun.dataset import diff as dataset_diff
from ndi.fun.session import diff as session_diff


class FakeDoc:
    def __init__(self, doc_id, session_id="S", props=None):
        self.id = doc_id
        self.session_id = session_id
        self.document_properties = props or {"base": {"id": doc_id, "session_id": session_id}}

    def current_file_list(self):
        return []

    def get_fuid(self, filename):
        return ""


class FakeStore:
    def __init__(self, docs):
        self._docs = list(docs)

    def database_search(self, query):
        return list(self._docs)


class FakeDataset(FakeStore):
    def id(self):
        return "D"


def _session_report():
    return session_diff(
        FakeStore([FakeDoc("a"), FakeDoc("shared")]),
        FakeStore([FakeDoc("shared"), FakeDoc("b")]),
        verbose=False,
    )


class TestTheRenamedKeysStillResolve:
    def test_only_in_s1(self):
        report = _session_report()
        with pytest.warns(FutureWarning, match="documentsInAOnly"):
            assert report["only_in_s1"] == report["documentsInAOnly"] == ["a"]

    def test_only_in_s2(self):
        report = _session_report()
        with pytest.warns(FutureWarning, match="documentsInBOnly"):
            assert report["only_in_s2"] == ["b"]

    def test_the_warning_names_the_issue(self):
        report = _session_report()
        with pytest.warns(FutureWarning, match=r"NDI-python#252"):
            report["only_in_s1"]

    def test_common_count_never_moved(self):
        """It was kept as a Python-only extra, so it needs no alias."""
        report = _session_report()
        assert report["common_count"] == 1


class TestMismatchesIsReshapedNotJustRenamed:
    def _mismatched(self):
        return session_diff(
            FakeStore([FakeDoc("d1", props={"base": {"id": "d1"}, "v": 1})]),
            FakeStore([FakeDoc("d1", props={"base": {"id": "d1"}, "v": 2})]),
            verbose=False,
        )

    def test_it_returns_the_old_entry_shape(self):
        report = self._mismatched()
        with pytest.warns(FutureWarning):
            legacy = report["mismatches"]
        assert legacy[0]["doc_id"] == "d1"
        assert isinstance(legacy[0]["details"], list)

    def test_the_warning_says_the_entries_changed_too(self):
        """A rename the caller can absorb silently would be worse than one
        that says the entry keys moved as well."""
        report = self._mismatched()
        with pytest.warns(FutureWarning, match="doc_id"):
            report["mismatches"]

    def test_the_current_shape_is_unchanged(self):
        report = self._mismatched()
        assert report["mismatchedDocuments"][0]["id"] == "d1"
        assert isinstance(report["mismatchedDocuments"][0]["mismatch"], str)

    def test_an_empty_mismatch_gives_an_empty_detail_list(self):
        report = session_diff(FakeStore([]), FakeStore([]), verbose=False)
        with pytest.warns(FutureWarning):
            assert report["mismatches"] == []


class TestTheDatasetSelfAlias:
    def test_session_diff_resolves_to_the_report(self):
        """dataset.diff used to wrap a nested session report; it no longer
        delegates, so the fields are on the report itself."""
        report = dataset_diff(FakeDataset([]), FakeDataset([]), verbose=False)
        with pytest.warns(FutureWarning, match="no longer delegates"):
            assert report["session_diff"] is report

    def test_the_old_nested_access_pattern_still_reads(self):
        report = dataset_diff(FakeDataset([]), FakeDataset([]), verbose=False)
        with pytest.warns(FutureWarning):
            assert report["session_diff"]["equal"] is True

    def test_a_session_report_has_no_such_alias(self):
        """session.diff never returned a 'session_diff' key."""
        with pytest.raises(KeyError):
            _session_report()["session_diff"]


class TestGetIsRoutedToo:
    def test_get_resolves_a_legacy_name(self):
        """dict.get does not go through __missing__, so it is overridden.

        Without that, report.get('only_in_s1') returns None -- quieter than
        a KeyError and worse.
        """
        report = _session_report()
        with pytest.warns(FutureWarning):
            assert report.get("only_in_s1") == ["a"]

    def test_get_still_honours_a_default_for_a_real_miss(self):
        report = _session_report()
        assert report.get("no_such_key", "fallback") == "fallback"

    def test_get_does_not_warn_for_a_current_name(self):
        import warnings

        report = _session_report()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert report.get("documentsInAOnly") == ["a"]


class TestMembershipDescribesTheRealShape:
    def test_the_old_name_is_not_a_member(self):
        assert "only_in_s1" not in _session_report()

    def test_iteration_yields_only_current_names(self):
        assert set(_session_report()) == {
            "documentsInAOnly",
            "documentsInBOnly",
            "mismatchedDocuments",
            "fileDifferences",
            "common_count",
            "equal",
        }

    def test_an_unknown_key_is_still_a_plain_keyerror(self):
        with pytest.raises(KeyError):
            _session_report()["not_a_field_in_any_version"]


class TestTheReportIsStillADict:
    def test_it_compares_equal_to_the_plain_dict(self):
        report = _session_report()
        assert report == dict(report)

    def test_it_serialises(self):
        import json

        json.dumps(_session_report())
