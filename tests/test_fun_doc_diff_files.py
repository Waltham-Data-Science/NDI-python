"""``ndi.fun.doc.diff``'s ``checkFiles`` step, against ``+ndi/+fun/+doc/diff.m``.

WHAT WAS WRONG. Step 5 of MATLAB's ``diff`` compares the documents' binary
files. It was not ported, and its absence was silent: ``checkFiles``,
``session1`` and ``session2`` were all accepted as parameters and none of the
three was ever read. So::

    diff(doc_a, doc_b, checkFiles=True)   ->   {'equal': True, 'details': []}

for documents whose files differ, or for no sessions at all -- where MATLAB
raises "If checkFiles is true, session1 and session2 must be provided."

A difference-finder that answers "equal" for a comparison it never ran is the
exact failure the bridge guard exists to catch, and it was inside the
function whose job is to find differences.

The ported step goes through ``ndi.util.getHexDiffFromFileObj``, the same
helper MATLAB uses here -- and this is that helper's only caller on either
side, which is why nothing noticed it was itself unusable until #219.
"""

from __future__ import annotations

import io

import pytest

from ndi.fun.doc import diff


class FakeDoc:
    """Just enough document for ``diff``: properties and a file list."""

    def __init__(self, props: dict, files: dict[str, bytes] | None = None):
        self.document_properties = props
        self._files = files or {}

    def current_file_list(self) -> list[str]:
        return list(self._files)


class FakeSession:
    """Hands back a BytesIO per (doc, filename), like database_openbinarydoc."""

    def __init__(self):
        self.closed: list[io.BytesIO] = []

    def database_openbinarydoc(self, doc: FakeDoc, filename: str) -> io.BytesIO:
        return io.BytesIO(doc._files[filename])

    def database_closebinarydoc(self, handle) -> None:
        self.closed.append(handle)


BASE = {"base": {"id": "1"}}


class TestTheGuard:
    def test_check_files_without_sessions_is_refused(self):
        """MATLAB errors; this used to return equal without looking."""
        a, b = FakeDoc(BASE), FakeDoc(BASE)
        with pytest.raises(ValueError, match="session1 and session2 must be provided"):
            diff(a, b, checkFiles=True)

    def test_one_session_is_not_enough(self):
        a, b = FakeDoc(BASE), FakeDoc(BASE)
        with pytest.raises(ValueError, match="must be provided"):
            diff(a, b, checkFiles=True, session1=FakeSession())

    def test_check_files_defaults_off_and_nothing_changes(self):
        a, b = FakeDoc(BASE), FakeDoc(BASE)
        assert diff(a, b) == {"equal": True, "details": []}


class TestFileContentComparison:
    def test_identical_files_compare_equal(self):
        a = FakeDoc(BASE, {"f.bin": b"hello world"})
        b = FakeDoc(BASE, {"f.bin": b"hello world"})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert out["equal"] is True

    def test_differing_content_is_reported(self):
        """The regression: this used to come back equal."""
        a = FakeDoc(BASE, {"f.bin": b"hello world"})
        b = FakeDoc(BASE, {"f.bin": b"HELLO WORLD"})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert out["equal"] is False
        assert "File f.bin content mismatch." in out["details"]

    def test_a_size_mismatch_is_reported_with_both_sizes(self):
        """MATLAB checks size before content and says both numbers."""
        a = FakeDoc(BASE, {"f.bin": b"abc"})
        b = FakeDoc(BASE, {"f.bin": b"abcdef"})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert out["equal"] is False
        assert "File f.bin size mismatch: 3 vs 6." in out["details"]

    def test_a_file_present_in_only_one_document_is_reported(self):
        """MATLAB takes the UNION of both file lists so a file missing from
        either side is named, then skips content for it."""
        a = FakeDoc(BASE, {"only_a.bin": b"x"})
        b = FakeDoc(BASE, {})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert out["equal"] is False
        assert "File only_a.bin present in doc1 but not doc2." in out["details"]

    def test_the_other_direction_too(self):
        a = FakeDoc(BASE, {})
        b = FakeDoc(BASE, {"only_b.bin": b"x"})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert "File only_b.bin present in doc2 but not doc1." in out["details"]

    def test_several_files_are_all_compared(self):
        a = FakeDoc(BASE, {"one.bin": b"aaa", "two.bin": b"bbb"})
        b = FakeDoc(BASE, {"one.bin": b"aaa", "two.bin": b"zzz"})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert out["details"] == ["File two.bin content mismatch."]

    def test_both_handles_are_closed(self):
        """MATLAB calls database_closebinarydoc on each side."""
        a = FakeDoc(BASE, {"f.bin": b"x"})
        b = FakeDoc(BASE, {"f.bin": b"x"})
        s1, s2 = FakeSession(), FakeSession()
        diff(a, b, checkFiles=True, session1=s1, session2=s2)
        assert len(s1.closed) == 1
        assert len(s2.closed) == 1

    def test_an_open_failure_is_recorded_not_raised(self):
        """MATLAB wraps each file in try/catch and records the message."""

        class Broken(FakeSession):
            def database_openbinarydoc(self, doc, filename):
                raise OSError("disk gone")

        a = FakeDoc(BASE, {"f.bin": b"x"})
        b = FakeDoc(BASE, {"f.bin": b"x"})
        out = diff(a, b, checkFiles=True, session1=Broken(), session2=FakeSession())
        assert out["equal"] is False
        assert any("Error comparing file f.bin" in d for d in out["details"])

    def test_property_differences_are_still_reported_alongside(self):
        a = FakeDoc({"base": {"id": "1"}, "x": 1}, {"f.bin": b"x"})
        b = FakeDoc({"base": {"id": "1"}, "x": 2}, {"f.bin": b"y"})
        out = diff(a, b, checkFiles=True, session1=FakeSession(), session2=FakeSession())
        assert out["equal"] is False
        assert any("x:" in d for d in out["details"])
        assert "File f.bin content mismatch." in out["details"]
