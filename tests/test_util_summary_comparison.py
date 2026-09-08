"""ndi.util's four summary functions against MATLAB.

These four exist for one purpose -- comparing a MATLAB-produced summary
against a Python-produced one -- so a difference between the two comparison
functions is a difference in the answer the symmetry harness gets.
"""

from __future__ import annotations

import math

from ndi.util import (
    compareDatasetSummary,
    compareSessionSummary,
    datasetSummary,
)


def session(**overrides):
    base = {
        "reference": "ref",
        "sessionId": "s1",
        "files": [],
        "filesInDotNDI": [],
        "daqSystemNames": [],
        "daqSystemDetails": [],
        "probes": [],
    }
    base.update(overrides)
    return base


class TestOrderIndependence:
    """MATLAB sorts EVERY cell and struct array before comparing."""

    def test_a_reordered_file_list_is_not_a_difference(self):
        a = session(files=["a", "b", "c"])
        b = session(files=["c", "a", "b"])
        assert compareSessionSummary(a, b) == []

    def test_a_reordered_probe_list_is_not_a_difference(self):
        p1 = {"name": "p1", "reference": 1}
        p2 = {"name": "p2", "reference": 2}
        assert compareSessionSummary(session(probes=[p1, p2]), session(probes=[p2, p1])) == []

    def test_a_reordered_list_inside_a_nested_struct_is_not_a_difference(self):
        # This is the case the three hard-coded field names did not reach.
        a = session(daqSystemDetails=[{"epochNodes_daqsystem": ["e1", "e2"]}])
        b = session(daqSystemDetails=[{"epochNodes_daqsystem": ["e2", "e1"]}])
        assert compareSessionSummary(a, b) == []

    def test_a_genuinely_different_list_is_still_reported(self):
        a = session(files=["a", "b"])
        b = session(files=["a", "c"])
        assert compareSessionSummary(a, b) != []

    def test_a_different_length_is_still_reported(self):
        report = compareSessionSummary(session(files=["a"]), session(files=["a", "b"]))
        assert len(report) == 1
        assert "different lengths" in report[0]

    def test_unorderable_mixed_content_does_not_raise(self):
        a = session(files=[1, "a"])
        b = session(files=[1, "a"])
        assert compareSessionSummary(a, b) == []


class TestEmptyValues:
    """MATLAB's isempty covers '' as well as [] and {}."""

    def test_an_empty_string_against_an_empty_list_is_not_a_difference(self):
        # jsondecode turns an empty JSON array into [] on one side and a
        # 0x0 char on the other; MATLAB skips the pair, this reported it.
        assert compareSessionSummary(session(reference=""), session(reference=[])) == []

    def test_two_empty_lists_are_not_a_difference(self):
        assert compareSessionSummary(session(files=[]), session(files=[])) == []

    def test_zero_is_not_empty(self):
        report = compareSessionSummary(session(reference=0), session(reference=""))
        assert report != []


class TestNaNEquality:
    """MATLAB compares with isequaln, which holds NaN equal to NaN."""

    def test_two_nans_match(self):
        a = session(daqSystemDetails=[{"v": math.nan}])
        b = session(daqSystemDetails=[{"v": math.nan}])
        assert compareSessionSummary(a, b) == []

    def test_a_nan_against_a_number_is_still_a_difference(self):
        a = session(daqSystemDetails=[{"v": math.nan}])
        b = session(daqSystemDetails=[{"v": 1.0}])
        assert compareSessionSummary(a, b) != []


class TestFieldsPresence:
    def test_a_field_only_in_one_summary_is_reported(self):
        a = session(extra=1)
        b = session()
        report = compareSessionSummary(a, b)
        assert any("extra is in summary1 but not summary2" in r for r in report)

    def test_excludeFiles_filters_both_sides(self):
        a = session(files=["keep", "drop"])
        b = session(files=["keep"])
        assert compareSessionSummary(a, b, excludeFiles=["drop"]) == []


class TestCompareDatasetSummaryStopsEarly:
    """MATLAB returns on a session-count or session-id mismatch."""

    def test_a_numSessions_mismatch_returns_one_line(self):
        a = {"numSessions": 1, "sessionIds": ["x"], "references": ["r"]}
        b = {"numSessions": 2, "sessionIds": ["y", "z"], "references": ["q", "p"]}
        report = compareDatasetSummary(a, b)
        assert report == ["numSessions differs: 1 vs 2"]

    def test_a_missing_numSessions_is_its_own_message(self):
        report = compareDatasetSummary({"numSessions": 1}, {})
        assert report == ["numSessions field is missing from one summary"]

    def test_a_missing_field_no_longer_reads_as_zero_sessions(self):
        # `.get('numSessions', 0)` made {} equal to a zero-session dataset.
        assert compareDatasetSummary({"numSessions": 0}, {}) != []

    def test_a_sessionIds_mismatch_returns_immediately(self):
        a = {"numSessions": 1, "sessionIds": ["x"], "sessionSummaries": [session()]}
        b = {"numSessions": 1, "sessionIds": ["y"], "sessionSummaries": [session()]}
        report = compareDatasetSummary(a, b)
        assert len(report) == 1
        assert "sessionIds differ" in report[0]


class TestCompareDatasetSummaryMatchesBySessionId:
    """MATLAB looks each session up by the sessionId inside the summary."""

    def test_summaries_out_of_sessionIds_order_still_pair_correctly(self):
        s_a = session(sessionId="a", reference="A")
        s_b = session(sessionId="b", reference="B")
        first = {
            "numSessions": 2,
            "sessionIds": ["a", "b"],
            "references": ["A", "B"],
            "sessionSummaries": [s_a, s_b],
        }
        second = {
            "numSessions": 2,
            "sessionIds": ["a", "b"],
            "references": ["A", "B"],
            # Same content, opposite order -- positional zipping compared
            # session a against session b and reported two differences.
            "sessionSummaries": [s_b, s_a],
        }
        assert compareDatasetSummary(first, second) == []

    def test_a_missing_session_summary_is_named(self):
        first = {
            "numSessions": 1,
            "sessionIds": ["a"],
            "references": ["A"],
            "sessionSummaries": [session(sessionId="a")],
        }
        second = {
            "numSessions": 1,
            "sessionIds": ["a"],
            "references": ["A"],
            "sessionSummaries": [],
        }
        report = compareDatasetSummary(first, second)
        assert "No session summary found for session ID a in summary2" in report

    def test_a_real_session_difference_is_prefixed_with_the_session(self):
        first = {
            "numSessions": 1,
            "sessionIds": ["a"],
            "references": ["A"],
            "sessionSummaries": [session(sessionId="a", files=["x"])],
        }
        second = {
            "numSessions": 1,
            "sessionIds": ["a"],
            "references": ["A"],
            "sessionSummaries": [session(sessionId="a", files=["y"])],
        }
        report = compareDatasetSummary(first, second)
        assert len(report) == 1
        assert report[0].startswith("Session a: ")


class TestDocumentCounts:
    """MATLAB's step 5, which had no Python counterpart at all."""

    def _pair(self, c1, c2):
        base = {
            "numSessions": 1,
            "sessionIds": ["a"],
            "references": ["A"],
            "sessionSummaries": [session(sessionId="a")],
        }
        first = dict(base, documentCounts=[{"sessionId": "a", "count": c1}])
        second = dict(base, documentCounts=[{"sessionId": "a", "count": c2}])
        return first, second

    def test_a_mismatch_is_reported(self):
        first, second = self._pair(3, 4)
        assert compareDatasetSummary(first, second) == [
            "Document count mismatch for session a: 3 vs 4"
        ]

    def test_matching_counts_are_silent(self):
        first, second = self._pair(3, 3)
        assert compareDatasetSummary(first, second) == []

    def test_counts_on_only_one_side_are_ignored(self):
        first, second = self._pair(3, 4)
        del second["documentCounts"]
        assert compareDatasetSummary(first, second) == []


class TestDatasetSummaryDocumentCounts:
    """datasetSummary could not produce the field MATLAB's option produces."""

    class _Session:
        def __init__(self, sid, n):
            self._sid = sid
            self._n = n

        def database_search(self, query):
            return [object()] * self._n

    class _Dataset:
        def __init__(self, counts):
            self._counts = counts

        def session_list(self):
            ids = list(self._counts)
            return [f"ref_{i}" for i in ids], ids

        def open_session(self, sid):
            return TestDatasetSummaryDocumentCounts._Session(sid, self._counts[sid])

    def _patched(self, monkeypatch):
        monkeypatch.setattr("ndi.util.dataset_summary.sessionSummary", lambda s: {"sessionId": "x"})

    def test_the_option_exists_and_defaults_off(self, monkeypatch):
        self._patched(monkeypatch)
        summary = datasetSummary(self._Dataset({"a": 2}))
        assert "documentCounts" not in summary

    def test_it_counts_documents_per_session(self, monkeypatch):
        self._patched(monkeypatch)
        summary = datasetSummary(self._Dataset({"a": 2, "b": 5}), includeDocumentCounts=True)
        assert summary["documentCounts"] == [
            {"sessionId": "a", "count": 2},
            {"sessionId": "b", "count": 5},
        ]

    def test_the_rest_of_the_summary_is_unchanged(self, monkeypatch):
        self._patched(monkeypatch)
        summary = datasetSummary(self._Dataset({"a": 1}), includeDocumentCounts=True)
        assert summary["numSessions"] == 1
        assert summary["sessionIds"] == ["a"]
        assert summary["references"] == ["ref_a"]
