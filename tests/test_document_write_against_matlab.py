"""``ndi.document.write`` against ``ndi.document/write`` and its DocumentWriteTest.

WHAT WAS WRONG. MATLAB's ``write`` takes a file PREFIX and writes
``[FILEPREFIX '.json']``; the prefix names a SET of files, because each
associated file is written alongside as ``[FILEPREFIX '_' FILENAME]``. The
port treated the argument as a complete filename, so the two languages wrote
different paths from the same call and MATLAB's naming scheme for the
associated files had nowhere to come from.

``writeLocalFiles`` and ``session`` were not ported at all, so the document's
files were never written -- and MATLAB's own DocumentWriteTest is three
cases, of which only ``testWriteJSON`` had a Python counterpart.
``testWriteLocalFiles`` and ``testWriteSessionFiles`` had none.

The JSON itself also diverged. MATLAB encodes with ``'ConvertInfAndNaN',
true``, which writes ``null``. Python's ``json.dump`` writes the bare tokens
``NaN`` and ``Infinity``, which are not JSON -- so a document carrying an
unmeasured value produced a file that Python could read back and a
conforming parser could not.
"""

from __future__ import annotations

import io
import json
import math

import pytest

from ndi.document import ndi_document


@pytest.fixture
def doc():
    return ndi_document("base", **{"base.name": "test_doc"})


class TestThePrefixContract:
    """MATLAB: d.write(outputPrefix); isfile([outputPrefix '.json'])."""

    def test_json_is_appended_to_the_prefix(self, doc, tmp_path):
        prefix = tmp_path / "test_output"
        doc.write(str(prefix))
        assert (tmp_path / "test_output.json").is_file()

    def test_the_prefix_itself_is_not_written(self, doc, tmp_path):
        prefix = tmp_path / "test_output"
        doc.write(str(prefix))
        assert not prefix.is_file(), "the bare prefix must not be a file"

    def test_a_prefix_that_looks_like_a_filename_still_gets_json(self, doc, tmp_path):
        """The old contract's callers passed 'doc.json'; MATLAB makes that
        'doc.json.json'. Documented, because it is the visible break."""
        doc.write(str(tmp_path / "doc.json"))
        assert (tmp_path / "doc.json.json").is_file()

    def test_write_json_matlabs_own_case(self, doc, tmp_path):
        """DocumentWriteTest.testWriteJSON."""
        prefix = tmp_path / "test_output"
        doc.write(str(prefix))
        data = json.loads((tmp_path / "test_output.json").read_text())
        assert data["base"]["name"] == "test_doc"

    def test_the_id_survives(self, tmp_path):
        d = ndi_document("demoNDI")
        d.write(str(tmp_path / "out"))
        data = json.loads((tmp_path / "out.json").read_text())
        assert data["base"]["id"] == d.id

    def test_missing_parent_directories_are_created(self, doc, tmp_path):
        """Python-only convenience; MATLAB's fopen would fail. It cannot
        change WHERE the file lands, only whether the call succeeds."""
        doc.write(str(tmp_path / "sub" / "dir" / "out"))
        assert (tmp_path / "sub" / "dir" / "out.json").is_file()

    def test_indent_is_honoured(self, doc, tmp_path):
        doc.write(str(tmp_path / "out"), indent=4)
        assert "    " in (tmp_path / "out.json").read_text()


class TestNaNAndInfBecomeNull:
    """MATLAB: jsonencode(..., 'ConvertInfAndNaN', true)."""

    def _written(self, props, tmp_path):
        ndi_document(props).write(str(tmp_path / "out"))
        return (tmp_path / "out.json").read_text()

    def test_nan_is_written_as_null(self, tmp_path):
        text = self._written({"base": {"id": "1"}, "v": math.nan}, tmp_path)
        assert "NaN" not in text
        assert json.loads(text)["v"] is None

    def test_inf_is_written_as_null(self, tmp_path):
        text = self._written({"base": {"id": "1"}, "v": math.inf}, tmp_path)
        assert "Infinity" not in text
        assert json.loads(text)["v"] is None

    def test_nested_and_listed_nan_too(self, tmp_path):
        text = self._written(
            {"base": {"id": "1"}, "a": {"b": math.nan}, "c": [1.0, math.nan]}, tmp_path
        )
        data = json.loads(text)
        assert data["a"]["b"] is None
        assert data["c"] == [1.0, None]

    def test_the_result_is_strict_json(self, tmp_path):
        """json.load accepts NaN by default; a conforming parser does not."""
        text = self._written({"base": {"id": "1"}, "v": math.nan}, tmp_path)
        json.loads(text, parse_constant=lambda c: pytest.fail(f"non-JSON token {c}"))

    def test_ordinary_numbers_are_untouched(self, tmp_path):
        text = self._written({"base": {"id": "1"}, "v": 1.5, "n": 3}, tmp_path)
        data = json.loads(text)
        assert data["v"] == 1.5 and data["n"] == 3


class TestWriteLocalFiles:
    """DocumentWriteTest.testWriteLocalFiles -- no Python counterpart before."""

    def _doc_with_file(self, tmp_path, content=b"Hello World"):
        source = tmp_path / "dummy.txt"
        source.write_bytes(content)
        d = ndi_document("demoNDI", **{"demoNDI.value": 1})
        d.add_file("filename1.ext", str(source))
        return d

    def test_the_file_is_written_beside_the_json(self, tmp_path):
        d = self._doc_with_file(tmp_path)
        prefix = tmp_path / "test_output_local"
        d.write(str(prefix), writeLocalFiles=True)

        assert (tmp_path / "test_output_local.json").is_file()
        target = tmp_path / "test_output_local_filename1.ext"
        assert target.is_file(), "MATLAB names it [FILEPREFIX '_' FILENAME]"
        assert target.read_bytes() == b"Hello World"

    def test_nothing_extra_is_written_when_the_flag_is_off(self, tmp_path):
        d = self._doc_with_file(tmp_path)
        prefix = tmp_path / "off"
        d.write(str(prefix))
        assert not (tmp_path / "off_filename1.ext").exists()

    def test_a_url_location_is_not_copied_but_warns(self, tmp_path):
        """MATLAB only copies a location whose location_type is 'file'."""
        d = ndi_document("demoNDI", **{"demoNDI.value": 1})
        d.add_file("filename1.ext", "https://example.invalid/x.bin")
        with pytest.warns(UserWarning, match="Could not find local file location"):
            d.write(str(tmp_path / "u"), writeLocalFiles=True)
        assert not (tmp_path / "u_filename1.ext").exists()
        assert (tmp_path / "u.json").is_file(), "the JSON is still written"


class TestWriteSessionFiles:
    """DocumentWriteTest.testWriteSessionFiles -- no Python counterpart before."""

    class FakeSession:
        def __init__(self, payload):
            self.payload = payload
            self.closed = []

        def database_openbinarydoc(self, doc, filename):
            self.requested = (doc, filename)
            return io.BytesIO(self.payload)

        def database_closebinarydoc(self, handle):
            self.closed.append(handle)

    def _doc(self, tmp_path):
        source = tmp_path / "ingest.txt"
        source.write_bytes(b"ignored -- the session is the source")
        d = ndi_document("demoNDI", **{"base.name": "session_doc", "demoNDI.value": 1})
        d.add_file("filename1.ext", str(source))
        return d

    def test_the_bytes_come_from_the_session(self, tmp_path):
        d = self._doc(tmp_path)
        session = self.FakeSession(b"Session Content")
        prefix = tmp_path / "test_output_session"
        d.write(str(prefix), writeLocalFiles=True, session=session)

        target = tmp_path / "test_output_session_filename1.ext"
        assert target.is_file()
        assert target.read_bytes() == b"Session Content"

    def test_the_handle_is_closed(self, tmp_path):
        session = self.FakeSession(b"x")
        self._doc(tmp_path).write(str(tmp_path / "p"), writeLocalFiles=True, session=session)
        assert len(session.closed) == 1

    def test_the_session_wins_over_the_recorded_location(self, tmp_path):
        """With a session, MATLAB never looks at the document's locations."""
        d = self._doc(tmp_path)
        session = self.FakeSession(b"from session")
        d.write(str(tmp_path / "p"), writeLocalFiles=True, session=session)
        assert (tmp_path / "p_filename1.ext").read_bytes() == b"from session"


class TestDocumentsWithoutFiles:
    def test_a_document_that_accepts_no_files_writes_only_json(self, doc, tmp_path):
        doc.write(str(tmp_path / "plain"), writeLocalFiles=True)
        assert (tmp_path / "plain.json").is_file()
        assert list(tmp_path.iterdir()) == [tmp_path / "plain.json"]
