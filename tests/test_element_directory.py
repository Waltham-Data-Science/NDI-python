"""Unit tests for ndi.fun.file.pathSafeName / elementDirectoryName.

The cross-language symmetry battery (tests/symmetry/fun/cases.py) pins the
22 cases both languages compare. This file carries the extra coverage the
schema deliberately keeps out of that battery -- notably the near-miss
reserved device names, of which the battery exercises only ``COM0``.
"""

from __future__ import annotations

import pytest

from ndi.fun.file import elementDirectoryName, pathSafeName, utf16_units


class TestReservedNames:
    """Windows device names are illegal with or without an extension."""

    @pytest.mark.parametrize("name", ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"])
    def test_reserved_gets_underscore(self, name):
        assert pathSafeName(name) == "_" + name

    @pytest.mark.parametrize("name", ["con", "Prn", "aUx", "com1", "lpt9"])
    def test_reserved_is_case_insensitive(self, name):
        assert pathSafeName(name) == "_" + name

    @pytest.mark.parametrize(
        "name",
        [
            "COM0",  # digit 0 is not a device
            "LPT0",
            "COM10",  # two digits is not a device
            "CONS",  # longer word beginning with a device name
            "CONSOLE",
            "AUXX",
            "NULL",
            "COM",  # bare prefix without a digit
            "LPT",
        ],
    )
    def test_near_misses_are_not_reserved(self, name):
        assert pathSafeName(name) == name

    def test_reserved_with_extension(self):
        assert pathSafeName("CON.txt") == "_CON.txt"

    def test_reserved_only_checks_before_the_first_dot(self):
        # 'a.CON' has base name 'a', which is not reserved.
        assert pathSafeName("a.CON") == "a.CON"


class TestSanitizing:
    def test_empty_becomes_x(self):
        assert pathSafeName("") == "x"

    def test_whitespace_and_control_become_underscore(self):
        assert pathSafeName("a b\tc\nd\re\x00f\x7fg") == "a_b_c_d_e_f_g"

    def test_windows_forbidden_become_dash(self):
        assert pathSafeName('<>:"/\\|?*') == "---------"

    def test_portable_set_passes_through(self):
        name = "abcXYZ019._-"
        assert pathSafeName(name) == name

    def test_trailing_dots_stripped(self):
        assert pathSafeName("report...") == "report"

    def test_leading_dot_kept(self):
        assert pathSafeName(".hidden") == ".hidden"

    def test_dots_stripped_before_empty_check(self):
        assert pathSafeName("...") == "x"

    def test_dots_stripped_before_reserved_check(self):
        assert pathSafeName("com1.") == "_com1"

    def test_non_text_rejected(self):
        with pytest.raises(TypeError):
            pathSafeName(42)


class TestUtf16Counting:
    """A filename contract: both languages must agree on the folder name.

    MATLAB char arrays hold UTF-16 code units, so a character above U+FFFF is
    a surrogate pair and sanitizes to TWO '-'. This port reproduces that on
    purpose; counting code points instead would put an element's data in a
    differently-named folder in each language.
    """

    def test_bmp_character_is_one_unit(self):
        assert utf16_units("é") == [0xE9]
        assert pathSafeName("aéb") == "a-b"

    def test_astral_character_is_a_surrogate_pair(self):
        units = utf16_units("\U0001f600")
        assert len(units) == 2
        assert 0xD800 <= units[0] <= 0xDBFF
        assert 0xDC00 <= units[1] <= 0xDFFF

    def test_astral_character_sanitizes_to_two_dashes(self):
        assert pathSafeName("a\U0001f600b") == "a--b"

    def test_astral_alone(self):
        assert pathSafeName("\U0001f389") == "--"

    def test_astral_then_trailing_dot(self):
        assert pathSafeName("\U0001f600.") == "--"


class TestElementDirectoryName:
    def test_element_string_input(self):
        dir_name, legacy = elementDirectoryName("ctx | 1")
        assert dir_name == "ctx_-_1"
        assert legacy == "ctx_|_1"

    def test_legacy_changes_only_spaces(self):
        _, legacy = elementDirectoryName("a b<c")
        assert legacy == "a_b<c"

    def test_object_with_elementstring(self):
        class FakeElement:
            def elementstring(self):
                return "ctx | 1"

        dir_name, legacy = elementDirectoryName(FakeElement())
        assert dir_name == "ctx_-_1"
        assert legacy == "ctx_|_1"

    def test_dir_name_equals_path_safe_name_of_input(self):
        """pathSafeName maps space to '_' too, so the legacy step is invisible."""
        for name in ["ctx | 1", "a b", "probe|2", "x"]:
            dir_name, _ = elementDirectoryName(name)
            assert dir_name == pathSafeName(name)
