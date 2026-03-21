"""Unit tests for ndi.util.datasetSummary and ndi.util.compareDatasetSummary."""

from unittest.mock import MagicMock

from ndi.util import compareDatasetSummary, datasetSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session(reference="ref1", session_id="sid1", path="/tmp/sess"):
    """Create a mock session object with the fields sessionSummary expects."""
    sess = MagicMock()
    sess.reference = reference
    sess.id.return_value = session_id
    sess.path = path
    sess.daqsystem_load.return_value = []
    sess.getprobes.return_value = []
    return sess


def _mock_dataset(sessions):
    """Create a mock Dataset whose session_list/open_session work with the given sessions."""
    ds = MagicMock()
    refs = [s.reference for s in sessions]
    ids = [s.id() for s in sessions]
    ds.session_list.return_value = (refs, ids)

    def _open(sid):
        for s in sessions:
            if s.id() == sid:
                return s
        return None

    ds.open_session.side_effect = _open
    return ds


# ===========================================================================
# datasetSummary
# ===========================================================================


class TestDatasetSummary:
    def test_empty_dataset(self):
        ds = MagicMock()
        ds.session_list.return_value = ([], [])
        result = datasetSummary(ds)
        assert result["numSessions"] == 0
        assert result["references"] == []
        assert result["sessionIds"] == []
        assert result["sessionSummaries"] == []

    def test_single_session(self):
        sess = _mock_session("myref", "mysid", "/tmp/nonexistent")
        ds = _mock_dataset([sess])
        result = datasetSummary(ds)
        assert result["numSessions"] == 1
        assert result["references"] == ["myref"]
        assert result["sessionIds"] == ["mysid"]
        assert len(result["sessionSummaries"]) == 1
        assert result["sessionSummaries"][0]["reference"] == "myref"
        assert result["sessionSummaries"][0]["sessionId"] == "mysid"

    def test_multiple_sessions(self):
        s1 = _mock_session("ref_a", "id_a", "/tmp/a")
        s2 = _mock_session("ref_b", "id_b", "/tmp/b")
        ds = _mock_dataset([s1, s2])
        result = datasetSummary(ds)
        assert result["numSessions"] == 2
        assert result["references"] == ["ref_a", "ref_b"]
        assert result["sessionIds"] == ["id_a", "id_b"]
        assert len(result["sessionSummaries"]) == 2

    def test_returns_expected_keys(self):
        sess = _mock_session()
        ds = _mock_dataset([sess])
        result = datasetSummary(ds)
        assert set(result.keys()) == {
            "numSessions",
            "references",
            "sessionIds",
            "sessionSummaries",
        }


# ===========================================================================
# compareDatasetSummary
# ===========================================================================


class TestCompareDatasetSummary:
    def test_identical_summaries(self):
        summary = {
            "numSessions": 1,
            "references": ["ref1"],
            "sessionIds": ["sid1"],
            "sessionSummaries": [
                {
                    "reference": "ref1",
                    "sessionId": "sid1",
                    "files": [],
                    "filesInDotNDI": [],
                    "daqSystemNames": [],
                    "daqSystemDetails": [],
                    "probes": [],
                }
            ],
        }
        report = compareDatasetSummary(summary, summary)
        assert report == []

    def test_different_num_sessions(self):
        s1 = {"numSessions": 1, "references": ["r"], "sessionIds": ["s"], "sessionSummaries": []}
        s2 = {"numSessions": 2, "references": ["r"], "sessionIds": ["s"], "sessionSummaries": []}
        report = compareDatasetSummary(s1, s2)
        assert any("numSessions" in r for r in report)

    def test_different_references(self):
        s1 = {
            "numSessions": 1,
            "references": ["ref_a"],
            "sessionIds": ["s"],
            "sessionSummaries": [],
        }
        s2 = {
            "numSessions": 1,
            "references": ["ref_b"],
            "sessionIds": ["s"],
            "sessionSummaries": [],
        }
        report = compareDatasetSummary(s1, s2)
        assert any("references" in r for r in report)

    def test_different_session_ids(self):
        s1 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["id_a"],
            "sessionSummaries": [],
        }
        s2 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["id_b"],
            "sessionSummaries": [],
        }
        report = compareDatasetSummary(s1, s2)
        assert any("sessionIds" in r for r in report)

    def test_different_session_summary_count(self):
        ss = {
            "reference": "r",
            "sessionId": "s",
            "files": [],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        s1 = {"numSessions": 1, "references": ["r"], "sessionIds": ["s"], "sessionSummaries": [ss]}
        s2 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["s"],
            "sessionSummaries": [ss, ss],
        }
        report = compareDatasetSummary(s1, s2)
        assert any("sessionSummaries count" in r for r in report)

    def test_session_summary_field_diff(self):
        ss1 = {
            "reference": "ref1",
            "sessionId": "sid1",
            "files": ["a.txt"],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        ss2 = {
            "reference": "ref1",
            "sessionId": "sid1",
            "files": ["b.txt"],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        s1 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["sid1"],
            "sessionSummaries": [ss1],
        }
        s2 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["sid1"],
            "sessionSummaries": [ss2],
        }
        report = compareDatasetSummary(s1, s2)
        assert any("sessionSummaries" in r for r in report)

    def test_exclude_fields(self):
        s1 = {"numSessions": 1, "references": ["r"], "sessionIds": ["s"], "sessionSummaries": []}
        s2 = {"numSessions": 2, "references": ["x"], "sessionIds": ["y"], "sessionSummaries": []}
        report = compareDatasetSummary(
            s1,
            s2,
            excludeFields=["numSessions", "references", "sessionIds", "sessionSummaries"],
        )
        assert report == []

    def test_exclude_files_passed_to_session_compare(self):
        ss1 = {
            "reference": "r",
            "sessionId": "s",
            "files": ["keep.txt", "exclude.txt"],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        ss2 = {
            "reference": "r",
            "sessionId": "s",
            "files": ["keep.txt"],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        s1 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["s"],
            "sessionSummaries": [ss1],
        }
        s2 = {
            "numSessions": 1,
            "references": ["r"],
            "sessionIds": ["s"],
            "sessionSummaries": [ss2],
        }
        report = compareDatasetSummary(s1, s2, excludeFiles=["exclude.txt"])
        assert report == []

    def test_empty_summaries_match(self):
        s1 = {"numSessions": 0, "references": [], "sessionIds": [], "sessionSummaries": []}
        s2 = {"numSessions": 0, "references": [], "sessionIds": [], "sessionSummaries": []}
        report = compareDatasetSummary(s1, s2)
        assert report == []

    def test_session_id_matching(self):
        """Session summaries are matched by sessionId, not index order."""
        ss_a = {
            "reference": "ra",
            "sessionId": "id_a",
            "files": ["a.txt"],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        ss_b = {
            "reference": "rb",
            "sessionId": "id_b",
            "files": ["b.txt"],
            "filesInDotNDI": [],
            "daqSystemNames": [],
            "daqSystemDetails": [],
            "probes": [],
        }
        # summary1 has [a, b] order, summary2 has [b, a] order
        s1 = {
            "numSessions": 2,
            "references": ["ra", "rb"],
            "sessionIds": ["id_a", "id_b"],
            "sessionSummaries": [ss_a, ss_b],
        }
        s2 = {
            "numSessions": 2,
            "references": ["ra", "rb"],
            "sessionIds": ["id_b", "id_a"],
            "sessionSummaries": [ss_b, ss_a],
        }
        report = compareDatasetSummary(s1, s2)
        assert report == []
