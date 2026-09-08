"""``ndi.fun.session.diff`` and ``ndi.fun.dataset.diff`` against their MATLAB originals.

WHAT WAS WRONG. Both MATLAB functions say, in their own help text, that "the
comparison includes both the documents and the files". The Python ports
compared only the documents. The whole file half -- union the two documents'
file lists, resolve each name through ``get_fuid``, open both, record the
sizes, and hexdiff the bytes -- was absent, so two sessions whose documents
pointed at DIFFERENT STORED BYTES were reported equal.

``recheckFileReport`` was accepted by both and read by neither, so asking for
a targeted re-check of a previous report's file differences silently ran a
full comparison instead -- and, since the file comparison did not exist, one
that could not report a file difference at all.

``ndi.fun.dataset.diff`` was not MATLAB's algorithm. It delegated to
``session.diff`` on ``dataset.session``, so documents belonging to the
dataset's MEMBER sessions were never compared, and files owned by a member
session were never opened -- MATLAB reaches them via ``open_session``.
MATLAB also compares dataset documents with ``isequaln`` on the properties
minus ``files``, not through ``ndi.fun.doc.diff``, which is a different
question with different answers.

The report shape diverged too: MATLAB returns ``documentsInAOnly``,
``documentsInBOnly``, ``mismatchedDocuments`` and ``fileDifferences``, and
the ports returned ``only_in_s1`` / ``only_in_s2`` / ``common_count`` /
``mismatches`` -- so no MATLAB caller could read a Python report.

MATLAB's own ``diffTest`` has a ``testMismatchedFiles`` case in both the
session and dataset suites. Neither had a Python counterpart. The test that
would have caught this was the one that was dropped.
"""

from __future__ import annotations

import io
import math

import pytest

from ndi.fun.dataset import diff as dataset_diff
from ndi.fun.session import diff as session_diff


class FakeDoc:
    """Enough document for both diffs: id, session, properties, files."""

    def __init__(self, doc_id, session_id="S", props=None, files=None):
        self.id = doc_id
        self.session_id = session_id
        self.document_properties = (
            props if props is not None else {"base": {"id": doc_id, "session_id": session_id}}
        )
        self._files = files or {}

    def current_file_list(self):
        return list(self._files)

    def get_fuid(self, filename):
        entry = self._files.get(filename)
        return "" if entry is None else entry[0]


class FakeStore:
    """A database_search / openbinarydoc pair over a fixed list of documents."""

    def __init__(self, docs):
        self._docs = list(docs)
        self.opened = []
        self.closed = []

    def database_search(self, query):
        clause = query.search_structure[0]
        if clause["operation"] == "exact_string":
            return [d for d in self._docs if d.id == clause["param1"]]
        return list(self._docs)

    def database_openbinarydoc(self, doc, filename):
        payload = doc._files[filename][1]
        if payload is None:
            raise FileNotFoundError(f"no such file {filename}")
        self.opened.append((doc.id, filename))
        return io.BytesIO(payload)

    def database_closebinarydoc(self, handle):
        self.closed.append(handle)


class FakeDataset(FakeStore):
    """A dataset that owns some documents and delegates others to sessions."""

    def __init__(self, docs, dataset_id="D", sessions=None):
        super().__init__(docs)
        self._id = dataset_id
        self._sessions = sessions or {}

    def id(self):
        return self._id

    def open_session(self, session_id):
        return self._sessions.get(session_id)


def _f(uid, payload):
    """One file record: its uid, and the bytes behind it."""
    return (uid, payload)


# ---------------------------------------------------------------------------
# The report's shape -- MATLAB's four field names
# ---------------------------------------------------------------------------


class TestTheReportUsesMatlabsFieldNames:
    def test_session_report_has_matlabs_four_fields(self):
        a, b = FakeStore([FakeDoc("d1")]), FakeStore([FakeDoc("d1")])
        report = session_diff(a, b, verbose=False)
        for field in (
            "documentsInAOnly",
            "documentsInBOnly",
            "mismatchedDocuments",
            "fileDifferences",
        ):
            assert field in report, f"MATLAB's report has {field}"

    def test_dataset_report_has_matlabs_four_fields(self):
        a = FakeDataset([FakeDoc("d1", "D")])
        b = FakeDataset([FakeDoc("d1", "D")])
        report = dataset_diff(a, b, verbose=False)
        for field in (
            "documentsInAOnly",
            "documentsInBOnly",
            "mismatchedDocuments",
            "fileDifferences",
        ):
            assert field in report


# ---------------------------------------------------------------------------
# ndi.unittest.fun.session.diffTest
# ---------------------------------------------------------------------------


class TestSessionDiffAgainstMatlabsTests:
    def test_identical_sessions(self):
        """diffTest.testIdenticalSessions -- nothing in any of the four lists."""
        docs = [FakeDoc("d1"), FakeDoc("d2")]
        report = session_diff(FakeStore(docs), FakeStore(docs), verbose=False)
        assert report["documentsInAOnly"] == []
        assert report["documentsInBOnly"] == []
        assert report["mismatchedDocuments"] == []
        assert report["fileDifferences"] == []
        assert report["equal"] is True

    def test_documents_in_a_only(self):
        """diffTest.testDocumentsInAOnly."""
        a = FakeStore([FakeDoc("d1"), FakeDoc("shared")])
        b = FakeStore([FakeDoc("shared")])
        report = session_diff(a, b, verbose=False)
        assert report["documentsInAOnly"] == ["d1"]
        assert report["documentsInBOnly"] == []
        assert report["mismatchedDocuments"] == []

    def test_documents_in_b_only(self):
        """diffTest.testDocumentsInBOnly."""
        a = FakeStore([FakeDoc("shared")])
        b = FakeStore([FakeDoc("shared"), FakeDoc("d2")])
        report = session_diff(a, b, verbose=False)
        assert report["documentsInAOnly"] == []
        assert report["documentsInBOnly"] == ["d2"]

    def test_mismatched_documents_are_reported_by_id(self):
        """diffTest.testMismatchedDocuments -- entries carry MATLAB's 'id'."""
        a = FakeStore([FakeDoc("d1", props={"base": {"id": "d1"}, "v": {"x": 1}})])
        b = FakeStore([FakeDoc("d1", props={"base": {"id": "d1"}, "v": {"x": 2}})])
        report = session_diff(a, b, verbose=False)
        assert [m["id"] for m in report["mismatchedDocuments"]] == ["d1"]
        assert report["mismatchedDocuments"][0]["mismatch"]

    def test_mismatched_files(self):
        """diffTest.testMismatchedFiles -- THE CASE WITH NO PYTHON COUNTERPART.

        Same document id, same properties, different bytes behind the same
        file name. This reported ``equal`` before the port.
        """
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u1", b"AAAA")})])
        b = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u2", b"BBBB")})])
        report = session_diff(a, b, verbose=False)

        assert report["documentsInAOnly"] == []
        assert report["documentsInBOnly"] == []
        assert len(report["fileDifferences"]) == 1
        entry = report["fileDifferences"][0]
        assert entry["documentA_uid"] == "d1"
        assert entry["documentB_uid"] == "d1"
        assert entry["documentDiff"], "MATLAB requires a non-empty documentDiff"
        assert report["equal"] is False

    def test_identical_files_leave_no_trace(self):
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u1", b"same")})])
        b = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u2", b"same")})])
        report = session_diff(a, b, verbose=False)
        assert report["fileDifferences"] == []
        assert report["equal"] is True


class TestTheFileDifferenceRecord:
    def test_it_carries_every_matlab_field(self):
        a = FakeStore([FakeDoc("d1", "SA", files={"raw.bin": _f("u1", b"AAAA")})])
        b = FakeStore([FakeDoc("d1", "SB", files={"raw.bin": _f("u2", b"BB")})])
        entry = session_diff(a, b, verbose=False)["fileDifferences"][0]
        assert set(entry) == {
            "documentA_uid",
            "documentB_uid",
            "sessionA_id",
            "sessionB_id",
            "documentA_fuid",
            "documentA_fname",
            "documentB_fuid",
            "documentB_fname",
            "documentA_size",
            "documentB_size",
            "documentA_errormsg",
            "documentB_errormsg",
            "documentDiff",
        }
        assert entry["sessionA_id"] == "SA"
        assert entry["sessionB_id"] == "SB"
        assert entry["documentA_fuid"] == "u1"
        assert entry["documentB_fuid"] == "u2"
        assert entry["documentA_size"] == 4
        assert entry["documentB_size"] == 2

    def test_a_missing_fuid_is_not_present_and_is_never_opened(self):
        """MATLAB checks the fuid FIRST and does not try to open the file."""
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("", b"AAAA")})])
        b = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u2", b"AAAA")})])
        report = session_diff(a, b, verbose=False)
        entry = report["fileDifferences"][0]
        assert entry["documentA_errormsg"] == "not present"
        assert math.isnan(entry["documentA_size"])
        assert a.opened == [], "the file with no fuid must not be opened"

    def test_a_file_only_one_side_declares_is_still_compared(self):
        """MATLAB unions the two file lists, so an extra file is reported."""
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u1", b"AAAA")})])
        b = FakeStore([FakeDoc("d1")])
        entry = session_diff(a, b, verbose=False)["fileDifferences"][0]
        assert entry["documentB_errormsg"] == "not present"

    def test_an_unreadable_file_is_recorded_not_raised(self):
        """MATLAB catches and stores e.message; it does not abandon the run."""
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u1", None)})])
        b = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u2", b"AAAA")})])
        entry = session_diff(a, b, verbose=False)["fileDifferences"][0]
        assert "no such file" in entry["documentA_errormsg"]
        assert entry["documentB_size"] == 4

    def test_handles_are_closed(self):
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u1", b"AAAA")})])
        b = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u2", b"BBBB")})])
        session_diff(a, b, verbose=False)
        assert len(a.closed) == 1 and len(b.closed) == 1


# ---------------------------------------------------------------------------
# recheckFileReport
# ---------------------------------------------------------------------------


class TestRecheckFileReport:
    def _prior(self):
        a = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u1", b"AAAA")})])
        b = FakeStore([FakeDoc("d1", files={"raw.bin": _f("u2", b"BBBB")})])
        return a, b, session_diff(a, b, verbose=False)

    def test_it_rechecks_only_the_named_files(self):
        a, b, prior = self._prior()
        a.opened.clear()
        b.opened.clear()
        again = session_diff(a, b, verbose=False, recheckFileReport=prior)
        assert len(again["fileDifferences"]) == 1
        assert a.opened == [("d1", "raw.bin")]

    def test_it_does_not_run_the_document_comparison(self):
        """MATLAB returns from the recheck branch before searching for docs."""
        a, b, prior = self._prior()
        again = session_diff(a, b, verbose=False, recheckFileReport=prior)
        assert again["documentsInAOnly"] == []
        assert again["mismatchedDocuments"] == []

    def test_a_now_fixed_file_drops_out_of_the_report(self):
        a, b, prior = self._prior()
        b._docs[0]._files["raw.bin"] = _f("u2", b"AAAA")
        again = session_diff(a, b, verbose=False, recheckFileReport=prior)
        assert again["fileDifferences"] == []
        assert again["equal"] is True

    def test_a_bare_list_of_entries_is_accepted(self):
        a, b, prior = self._prior()
        again = session_diff(a, b, verbose=False, recheckFileReport=prior["fileDifferences"])
        assert len(again["fileDifferences"]) == 1

    def test_a_vanished_document_is_skipped_not_raised(self):
        a, b, prior = self._prior()
        b._docs.clear()
        again = session_diff(a, b, verbose=False, recheckFileReport=prior)
        assert again["fileDifferences"] == []


# ---------------------------------------------------------------------------
# ndi.unittest.fun.dataset.diffTest
# ---------------------------------------------------------------------------


class TestDatasetDiffAgainstMatlabsTests:
    def test_identical_datasets(self):
        docs = [FakeDoc("d1", "D"), FakeDoc("d2", "D")]
        report = dataset_diff(FakeDataset(docs), FakeDataset(docs), verbose=False)
        assert report["documentsInAOnly"] == []
        assert report["documentsInBOnly"] == []
        assert report["mismatchedDocuments"] == []
        assert report["fileDifferences"] == []

    def test_documents_in_a_only(self):
        a = FakeDataset([FakeDoc("d1", "D"), FakeDoc("shared", "D")])
        b = FakeDataset([FakeDoc("shared", "D")])
        report = dataset_diff(a, b, verbose=False)
        assert report["documentsInAOnly"] == ["d1"]
        assert report["documentsInBOnly"] == []

    def test_mismatched_documents_say_properties_do_not_match(self):
        """MATLAB's dataset mismatch text is fixed, unlike the session one."""
        a = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "v": 1})])
        b = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "v": 2})])
        report = dataset_diff(a, b, verbose=False)
        assert report["mismatchedDocuments"] == [
            {"id": "d1", "mismatch": "Document properties do not match."}
        ]

    def test_mismatched_files(self):
        """dataset diffTest.testMismatchedFiles -- also had no counterpart."""
        a = FakeDataset([FakeDoc("d1", "D", files={"raw.bin": _f("u1", b"AAAA")})])
        b = FakeDataset([FakeDoc("d1", "D", files={"raw.bin": _f("u2", b"BBBB")})])
        report = dataset_diff(a, b, verbose=False)
        assert len(report["fileDifferences"]) == 1
        assert report["fileDifferences"][0]["documentDiff"]

    def test_files_are_compared_not_the_properties_files_field(self):
        """MATLAB drops 'files' before isequaln -- differing uids alone are not
        a property mismatch, because the bytes are compared separately."""
        a = FakeDataset(
            [
                FakeDoc(
                    "d1",
                    "D",
                    props={"base": {"id": "d1"}, "files": {"file_info": [{"name": "raw.bin"}]}},
                    files={"raw.bin": _f("u1", b"same")},
                )
            ]
        )
        b = FakeDataset(
            [
                FakeDoc(
                    "d1",
                    "D",
                    props={"base": {"id": "d1"}, "files": {"file_info": [{"name": "OTHER"}]}},
                    files={"raw.bin": _f("u2", b"same")},
                )
            ]
        )
        report = dataset_diff(a, b, verbose=False)
        assert report["mismatchedDocuments"] == []
        assert report["fileDifferences"] == []


class TestDatasetReachesMemberSessions:
    """MATLAB opens a document's files through the session that OWNS them.

    The delegating port compared ``dataset.session`` only, so a document
    belonging to a member session was invisible -- and its files, which live
    behind ``open_session``, were never opened.
    """

    def _dataset(self, payload):
        member_doc = FakeDoc("d1", "MEMBER", files={"raw.bin": _f("u1", payload)})
        member = FakeStore([member_doc])
        return (
            FakeDataset([member_doc], dataset_id="D", sessions={"MEMBER": member}),
            member,
        )

    def test_a_member_sessions_files_are_opened_through_that_session(self):
        a, member_a = self._dataset(b"AAAA")
        b, member_b = self._dataset(b"BBBB")
        report = dataset_diff(a, b, verbose=False)

        assert len(report["fileDifferences"]) == 1
        assert member_a.opened == [("d1", "raw.bin")]
        assert a.opened == [], "the dataset must not open a member session's file"

    def test_an_unopenable_member_session_is_recorded_not_raised(self):
        doc = FakeDoc("d1", "GONE", files={"raw.bin": _f("u1", b"AAAA")})
        a = FakeDataset([doc], dataset_id="D", sessions={})
        b = FakeDataset([doc], dataset_id="D", sessions={})
        entry = dataset_diff(a, b, verbose=False)["fileDifferences"][0]
        assert "not open in this dataset" in entry["documentA_errormsg"]

    def test_common_ids_are_ordered_by_owning_session(self):
        """MATLAB sorts by session_id so consecutive docs share an open session."""
        docs = [
            FakeDoc("d3", "S2"),
            FakeDoc("d1", "S1"),
            FakeDoc("d2", "S1"),
        ]
        sessions = {"S1": FakeStore(docs), "S2": FakeStore(docs)}
        a = FakeDataset(docs, sessions=sessions)
        b = FakeDataset(docs, sessions=sessions)
        report = dataset_diff(a, b, verbose=False)
        # No differences, but the ordering must not have raised or reordered
        # the id lists that the report exposes.
        assert report["mismatchedDocuments"] == []


class TestIsEqualN:
    """MATLAB compares dataset documents with isequaln, where NaN == NaN."""

    def test_nan_equals_nan(self):
        props = {"base": {"id": "d1"}, "rate": math.nan}
        a = FakeDataset([FakeDoc("d1", "D", props=props)])
        b = FakeDataset([FakeDoc("d1", "D", props=dict(props))])
        assert dataset_diff(a, b, verbose=False)["mismatchedDocuments"] == []

    def test_nested_nan_equals_nan(self):
        a = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "x": [1.0, math.nan]})])
        b = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "x": [1.0, math.nan]})])
        assert dataset_diff(a, b, verbose=False)["mismatchedDocuments"] == []

    def test_a_real_difference_still_shows(self):
        a = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "x": [1.0, 2.0]})])
        b = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "x": [1.0, 3.0]})])
        assert len(dataset_diff(a, b, verbose=False)["mismatchedDocuments"]) == 1

    def test_true_is_not_one(self):
        """A guard on the NaN shortcut: Python's True == 1, MATLAB's is not."""
        a = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "x": True})])
        b = FakeDataset([FakeDoc("d1", "D", props={"base": {"id": "d1"}, "x": 1})])
        assert len(dataset_diff(a, b, verbose=False)["mismatchedDocuments"]) == 1


class TestTheQueryMatchesMatlabs:
    def test_documents_are_found_with_base_id_regexp(self):
        """MATLAB uses ndi.query('base.id','regexp','(.*)'); the port used
        ndi_query('').isa('base'), which asks a different question."""
        seen = []

        class Recording(FakeStore):
            def database_search(self, query):
                seen.append(query.search_structure[0])
                return super().database_search(query)

        session_diff(Recording([FakeDoc("d1")]), Recording([FakeDoc("d1")]), verbose=False)
        assert seen[0]["field"] == "base.id"
        assert seen[0]["operation"] == "regexp"
        assert seen[0]["param1"] == "(.*)"


class TestVerbose:
    def test_it_prints_matlabs_counts(self, capsys):
        a = FakeStore([FakeDoc("d1")])
        b = FakeStore([FakeDoc("d1")])
        session_diff(a, b, verbose=True)
        out = capsys.readouterr().out
        assert "Found 1 documents in the first session and 1 documents in the second." in out
        assert "Comparing 1 common documents..." in out

    def test_quiet_by_request(self, capsys):
        session_diff(FakeStore([]), FakeStore([]), verbose=False)
        assert capsys.readouterr().out == ""


@pytest.mark.parametrize("fn", [session_diff, dataset_diff])
def test_empty_containers_compare_equal(fn):
    make = FakeDataset if fn is dataset_diff else FakeStore
    assert fn(make([]), make([]), verbose=False)["equal"] is True
