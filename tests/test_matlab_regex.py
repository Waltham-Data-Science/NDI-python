"""Tests for ndi.util.matlab_regex.matlab_to_python_regex."""

from __future__ import annotations

import re

import pytest

from ndi.util.matlab_regex import matlab_to_python_regex


class TestMatlabToPythonRegex:
    def test_end_of_word_boundary(self):
        assert matlab_to_python_regex(r"foo\>") == r"foo\b"

    def test_start_of_word_boundary(self):
        assert matlab_to_python_regex(r"\<foo") == r"\bfoo"

    def test_both_boundaries(self):
        assert matlab_to_python_regex(r"\<foo\>") == r"\bfoo\b"

    def test_navigator_pattern_from_failing_symmetry_test(self):
        translated = matlab_to_python_regex(r"#_\d{8}_\d{6}\.rhd\>")
        assert translated == r"#_\d{8}_\d{6}\.rhd\b"
        # And it actually matches when the '#' is substituted.
        compiled = re.compile("^" + translated.replace("#", "(.+?)") + "$")
        m = compiled.match("A_20260101_120000.rhd")
        assert m is not None
        assert m.group(1) == "A"

    def test_named_group_translation(self):
        assert (
            matlab_to_python_regex(r"(?<year>\d{4})-(?<mon>\d{2})")
            == r"(?P<year>\d{4})-(?P<mon>\d{2})"
        )

    def test_named_group_actually_compiles(self):
        py = matlab_to_python_regex(r"(?<year>\d{4})")
        m = re.match(py, "2026")
        assert m is not None
        assert m.group("year") == "2026"

    def test_idempotent(self):
        once = matlab_to_python_regex(r"\<foo\>(?<name>\d+)")
        twice = matlab_to_python_regex(once)
        assert once == twice

    def test_passthrough_python_pattern(self):
        # Already-Python patterns must be left alone.
        assert matlab_to_python_regex(r"\bfoo\b") == r"\bfoo\b"
        assert matlab_to_python_regex(r"(?P<name>\d+)") == r"(?P<name>\d+)"

    def test_bare_angle_brackets_not_touched(self):
        # '<' and '>' not preceded by an odd number of backslashes
        # must NOT be converted.
        assert matlab_to_python_regex("a>b") == "a>b"
        assert matlab_to_python_regex("a<b") == "a<b"
        assert matlab_to_python_regex("[<>]") == "[<>]"

    def test_escaped_backslash_then_gt_left_alone(self):
        # r"\\>" is a literal backslash followed by '>' — NOT a word
        # boundary. Must stay as a literal-backslash + '>'.
        assert matlab_to_python_regex(r"\\>") == r"\\>"
        assert matlab_to_python_regex(r"\\<") == r"\\<"

    def test_odd_backslashes_before_gt_still_a_boundary(self):
        # r"\\\>" -> literal backslash + word boundary.
        # That is: two backslashes (literal '\') then '\>'.
        # Expected output: r"\\\b" (literal '\' + '\b').
        assert matlab_to_python_regex(r"\\\>") == r"\\\b"

    def test_lookbehind_not_renamed(self):
        # (?<=...) is a lookbehind, NOT a named group; must pass through.
        assert matlab_to_python_regex(r"(?<=foo)bar") == r"(?<=foo)bar"
        assert matlab_to_python_regex(r"(?<!foo)bar") == r"(?<!foo)bar"

    def test_empty_string(self):
        assert matlab_to_python_regex("") == ""

    def test_non_string_raises(self):
        with pytest.raises(TypeError):
            matlab_to_python_regex(123)  # type: ignore[arg-type]

    def test_combined_boundary_and_named_group(self):
        src = r"\<(?<prefix>[A-Z])_\d+\>"
        out = matlab_to_python_regex(src)
        assert out == r"\b(?P<prefix>[A-Z])_\d+\b"
        m = re.match(out, "A_123")
        assert m is not None
        assert m.group("prefix") == "A"
