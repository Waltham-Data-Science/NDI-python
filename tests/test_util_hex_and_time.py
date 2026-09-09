"""``ndi.util`` hex/time helpers against ``+ndi/+util/``.

WHY THIS FILE EXISTS. ``tests/matlab_tests/test_utils.py`` lists
``hexDump, hexDiff, hexDiffBytes, getHexDiffFromFileObj`` and
``datestamp2datetime, rehydrateJSONNanNull, unwrapTableCellContent`` in its
module docstring as things it covers. It does not test any of them -- the
docstring is the only mention. Three defects were sitting behind that claim:

* ``getHexDiffFromFileObj`` could not be called AT ALL. Its file-object
  parameters were annotated ``typing.IO[bytes]``, and under
  ``@pydantic.validate_call`` that becomes ``isinstance(value, IO)``, which
  is False for ``io.BytesIO`` and for the ``BufferedReader`` that
  ``open(path, "rb")`` returns. Every call raised ValidationError before the
  body ran.
* ``getHexDiffFromFileObj`` also dropped MATLAB's two ``onCleanup`` objects,
  which rewind both files however the function exits.
* ``datestamp2datetime`` could not parse the repo's OWN datestamp format on
  Python 3.10 (a supported version), and silently read a datestamp with no
  offset as LOCAL time.
"""

from __future__ import annotations

import io
from datetime import timezone

import pytest

from ndi.util import (
    datestamp2datetime,
    getHexDiffFromFileObj,
    hexDiffBytes,
    rehydrateJSONNanNull,
    unwrapTableCellContent,
)


class TestDatestamp2Datetime:
    """MATLAB counterpart: ``+ndi/+util/datestamp2datetime.m``.

    MATLAB parses with ``InputFormat`` ``yyyy-MM-dd'T'HH:mm:ss.SSSXXX`` and
    ``TimeZone`` UTC. The ``XXX`` makes the offset part of the format, so a
    string without one does not parse.
    """

    def test_the_repos_own_datestamp_format_parses(self):
        """``ndi.common.timestamp`` writes a trailing 'Z', and so do the
        documents under ``ndi_common/`` (``2018-12-05T18:36:47.241Z``).

        ``datetime.fromisoformat`` did not accept 'Z' until Python 3.11, and
        this project supports 3.10 -- so the canonical format raised
        ValueError on a supported interpreter while working everywhere else.
        """
        dt = datestamp2datetime("2018-12-05T18:36:47.241Z")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2018, 12, 5, 18, 36)

    def test_an_explicit_offset_is_converted_to_utc(self):
        dt = datestamp2datetime("2023-01-01T12:00:00.000+09:00")
        assert dt.astimezone(timezone.utc).hour == 3

    def test_a_zero_offset_is_left_alone(self):
        assert datestamp2datetime("2023-01-01T12:00:00.000+00:00").hour == 12

    def test_a_datestamp_with_no_offset_is_refused(self):
        """The silent one. ``datetime.astimezone`` on a NAIVE datetime does
        not assume UTC -- it assumes the LOCAL SYSTEM timezone. The same
        string became 17:00Z in New York and 03:00Z in Tokyo, with nothing to
        say anything had been guessed. MATLAB's XXX-anchored format simply
        fails to parse it, and so does this."""
        with pytest.raises(ValueError, match="carries no UTC offset"):
            datestamp2datetime("2023-01-01T12:00:00.000")

    def test_an_unparseable_string_is_refused(self):
        with pytest.raises(ValueError):
            datestamp2datetime("not a datestamp")


class TestGetHexDiffFromFileObj:
    """MATLAB counterpart: ``+ndi/+util/getHexDiffFromFileObj.m``."""

    def test_real_file_objects_are_accepted(self, tmp_path):
        """The regression. ``typing.IO[bytes]`` under
        ``@pydantic.validate_call`` rejected every real file object, so this
        function could not be invoked at all."""
        a, b = tmp_path / "a.bin", tmp_path / "b.bin"
        a.write_bytes(b"hello world")
        b.write_bytes(b"hello world")
        with a.open("rb") as f1, b.open("rb") as f2:
            identical, diff = getHexDiffFromFileObj(f1, f2)
        assert identical is True
        assert diff == ""

    def test_bytesio_is_accepted(self):
        identical, diff = getHexDiffFromFileObj(io.BytesIO(b"abc"), io.BytesIO(b"abc"))
        assert (identical, diff) == (True, "")

    def test_both_objects_are_rewound_on_exit(self):
        """MATLAB installs two onCleanup objects that rewind both files
        however the function exits ("ensure rewind after we are done"). A
        caller that compares two files and then reads one would otherwise get
        nothing, both being at EOF."""
        f1, f2 = io.BytesIO(b"hello world"), io.BytesIO(b"hello world")
        getHexDiffFromFileObj(f1, f2)
        assert (f1.tell(), f2.tell()) == (0, 0)
        assert f1.read() == b"hello world"

    def test_rewound_after_a_difference_too(self):
        f1, f2 = io.BytesIO(b"hello"), io.BytesIO(b"HELLO")
        identical, diff = getHexDiffFromFileObj(f1, f2)
        assert identical is False
        assert diff
        assert (f1.tell(), f2.tell()) == (0, 0)

    def test_different_sizes_are_reported_with_the_sizes(self):
        identical, diff = getHexDiffFromFileObj(io.BytesIO(b"abc"), io.BytesIO(b"abcdef"))
        assert identical is False
        assert "different sizes (3 bytes vs 6 bytes)" in diff
        assert "Hexdiff of the start of the files:" in diff

    def test_a_difference_in_the_first_chunk_is_diffed(self):
        d1 = b"xxxxxxxxxxxxxxxx"
        d2 = b"yyyyyyyyyyyyyyyy"
        identical, diff = getHexDiffFromFileObj(io.BytesIO(d1), io.BytesIO(d2), chunkSize=16)
        assert identical is False
        assert "00000000:" in diff, diff

    def test_a_difference_after_the_first_chunk_reports_no_diff_text(self):
        """AN UPSTREAM MATLAB BUG, REPRODUCED FAITHFULLY -- not a porting
        defect, and deliberately not "fixed" here.

        hexDiffBytes uses StartOffset as BOTH the address it prints AND an
        index into the arrays it was handed (``getChunk`` does
        ``startIdx = startOffset + 1``), and it stops at ``maxSize - 1`` of
        those same arrays. getHexDiffFromFileObj hands it ONE chunk plus the
        absolute file offset, so as soon as the first differing chunk is not
        the first chunk, ``startByte > maxSize - 1`` and the loop body never
        runs. MATLAB returns '' there and so does this.

        The result: are_identical is correctly False, but diff_output is
        empty, where the MATLAB help says it "contains a hex diff of the
        first mismatched chunk". Diverging here would break the very
        correspondence the bridge exists to record, so this asserts the
        shared behaviour and the gap is reported upstream instead.
        """
        d1 = b"A" * 32 + b"xxxxxxxxxxxxxxxx"
        d2 = b"A" * 32 + b"yyyyyyyyyyyyyyyy"
        identical, diff = getHexDiffFromFileObj(io.BytesIO(d1), io.BytesIO(d2), chunkSize=16)
        assert identical is False
        assert diff == ""

    def test_hexdiffbytes_start_offset_indexes_the_arrays_it_is_given(self):
        """The mechanism behind the test above, pinned directly."""
        assert hexDiffBytes(b"x" * 16, b"y" * 16, StartOffset=32) == ""
        assert hexDiffBytes(b"x" * 16, b"y" * 16, StartOffset=0) != ""

    def test_a_non_stream_is_still_rejected(self):
        with pytest.raises(Exception):
            getHexDiffFromFileObj("not a file", io.BytesIO(b""))

    def test_a_non_positive_chunk_size_is_still_rejected(self):
        with pytest.raises(Exception):
            getHexDiffFromFileObj(io.BytesIO(b""), io.BytesIO(b""), chunkSize=0)


class TestHexDiffBytes:
    """MATLAB counterpart: ``+ndi/+util/hexDiffBytes.m``."""

    def test_identical_data_returns_an_empty_string(self):
        """getHexDiffFromFileObj relies on this: MATLAB's comment says
        "Return empty if no differences, as per getHexDiffFromFileObj's
        expectation"."""
        assert hexDiffBytes(b"abc", b"abc") == ""

    def test_the_header_appears_once_before_the_first_difference(self):
        out = hexDiffBytes(b"a" * 64, b"b" * 64)
        assert out.count("Offset(h)") == 1
        assert out.splitlines()[1] == "-" * 140

    def test_the_ascii_column_dots_unprintable_bytes(self):
        out = hexDiffBytes(bytes([0x00, 0x41]), bytes([0x01, 0x41]))
        assert "|.A" in out

    def test_a_short_chunk_is_padded_to_sixteen_columns(self):
        """MATLAB's getChunkString pads both the hex and the ASCII field to
        16 slots so the two sides stay aligned."""
        out = hexDiffBytes(b"ab", b"cd")
        line = out.splitlines()[-1]
        assert line.startswith("00000000:   ")
        # Two ASCII fields, each delimited by a pair of pipes, plus the
        # single "  |  " that separates the two sides.
        assert line.count("|") == 5
        assert "|ab              |" in line
        assert "|cd              |" in line


class TestRehydrateJSONNanNull:
    """MATLAB counterpart: ``+ndi/+util/rehydrateJSONNanNull.m``."""

    def test_the_three_default_sentinels_are_replaced(self):
        text = '{"a":"__NDI__NaN__","b":"__NDI__Infinity__","c":"__NDI__-Infinity__"}'
        assert rehydrateJSONNanNull(text) == '{"a":NaN,"b":Infinity,"c":-Infinity}'

    def test_the_negative_sentinel_is_not_damaged_by_the_positive_one(self):
        """The one place sequential replacement could have differed from
        MATLAB's single pass with the defaults: '"__NDI__Infinity__"' is not
        a substring of '"__NDI__-Infinity__"', so the order is immaterial."""
        assert rehydrateJSONNanNull('{"c":"__NDI__-Infinity__"}') == '{"c":-Infinity}'

    def test_text_with_no_sentinels_is_returned_unchanged(self):
        assert rehydrateJSONNanNull('{"a":1}') == '{"a":1}'

    def test_custom_sentinels_are_honoured(self):
        out = rehydrateJSONNanNull('{"v":"MY_NAN"}', nan_string='"MY_NAN"')
        assert out == '{"v":NaN}'


class TestUnwrapTableCellContent:
    """MATLAB counterpart: ``+ndi/+util/unwrapTableCellContent.m``."""

    def test_a_plain_value_passes_through(self):
        assert unwrapTableCellContent(42) == 42

    def test_nested_wrapping_is_unwrapped(self):
        assert unwrapTableCellContent([[["some_string"]]]) == "some_string"
        assert unwrapTableCellContent([[[[True]]]]) is True

    def test_an_empty_cell_becomes_nan(self):
        """MATLAB returns NaN for an empty cell or an empty `[]`."""
        assert unwrapTableCellContent([]) != unwrapTableCellContent([])  # NaN != NaN
        assert unwrapTableCellContent([[]]) != unwrapTableCellContent([[]])

    def test_none_becomes_nan(self):
        result = unwrapTableCellContent(None)
        assert result != result

    def test_an_empty_string_is_preserved(self):
        """MATLAB guards this explicitly: `isempty(x) && ~ischar(x)`, so ''
        survives where [] becomes NaN."""
        assert unwrapTableCellContent("") == ""
        assert unwrapTableCellContent([[""]]) == ""

    def test_unwrapping_stops_after_ten_levels(self):
        """MATLAB's max_unwrap safety break; a value still wrapped at that
        depth is returned as-is rather than looping."""
        deep = "x"
        for _ in range(12):
            deep = [deep]
        assert isinstance(unwrapTableCellContent(deep), list)
