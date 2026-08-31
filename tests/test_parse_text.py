"""Unit tests for ndi.fun.parse_text (MATLAB: ndi.fun.parseText).

The cross-language behaviour of parse_text is pinned by the symmetry battery
in tests/symmetry/fun/parse_text_cases.py, which runs the same 18 cases here
and in MATLAB and compares the results. These tests cover what that battery
cannot: the reasons this module depends on ``regex`` rather than the standard
library, and the input handling either side of the parse.
"""

import json
import re

import pytest

regex = pytest.importorskip("regex")
pytest.importorskip("pandas")

from ndi.fun.text import parse_text, parseText  # noqa: E402


def _rules_file(tmp_path, rules, name="rules.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps([{"VariableName": n, "StringFormat": p} for n, p in rules]),
        encoding="utf-8",
    )
    return str(path)


# Patterns taken verbatim from NDI-matlab's shipped parser files:
#   +ndi/+setup/+conv/+babu/textParser.json
#   +ndi/+setup/+conv/+dabrowska/dabrowska_fileManifest_ephys.json
# They are the reason this module uses `regex` and not `re`.
SHIPPED_PATTERNS_RE_CANNOT_COMPILE = [
    r"(?i)heat|(?<!\s+to\s+.*|\+)37",  # variable-width lookbehind
    r"(?<!To.*)(?i)WT",  # inline flag mid-pattern
    r"neurons/((?i)[a-z]{3} \d{1,2} \d{4})",  # inline flag mid-pattern
    r"(?<!To.*)P1(?!_?P2)",  # variable-width lookbehind
]


class TestRegexEngineRequirement:
    """Why this module depends on `regex`. These are the load-bearing tests."""

    @pytest.mark.parametrize("pattern", SHIPPED_PATTERNS_RE_CANNOT_COMPILE)
    def test_stdlib_re_cannot_compile_shipped_patterns(self, pattern):
        """The standard library rejects these outright -- not a style preference.

        If this ever stops raising, the standard library has grown the feature
        and the dependency can be revisited.
        """
        with pytest.raises(re.error):
            re.compile(pattern)

    @pytest.mark.parametrize("pattern", SHIPPED_PATTERNS_RE_CANNOT_COMPILE)
    def test_regex_module_compiles_shipped_patterns(self, pattern):
        assert regex.compile(pattern) is not None

    def test_hoisting_an_inline_flag_would_change_the_answer(self):
        """Rewriting patterns to satisfy `re` is not equivalent, it is a bug.

        MATLAB applies ``(?i)`` from that point onward, so the lookbehind in
        ``(?<!To.*)(?i)WT`` stays case-sensitive and ``toWT`` matches. Hoisting
        the flag to the front makes the lookbehind case-insensitive too and
        ``toWT`` stops matching -- a silently different answer, which is worse
        than a compile error.
        """
        as_written = r"(?<!To.*)(?i)WT"
        hoisted = r"(?i)(?<!To.*)WT"
        assert regex.search(as_written, "toWT") is not None
        assert regex.search(hoisted, "toWT") is None
        # Both agree on the cases that do not exercise the difference.
        for subject in ("WT", "ToWT", "wt"):
            assert (regex.search(as_written, subject) is None) == (
                regex.search(hoisted, subject) is None
            )

    def test_a_shipped_pattern_drives_a_real_rule(self, tmp_path):
        f = _rules_file(tmp_path, [("RecordingDate", r"neurons/((?i)[a-z]{3} \d{1,2} \d{4})")])
        frame = parse_text([["/data/neurons/Jan 5 2020/cell1"], ["/data/other"]], f)
        assert list(frame.columns) == ["RecordingDate"]
        values = list(frame["RecordingDate"])
        assert values[0] == "Jan 5 2020"
        # The pattern text contains '\\d', so a miss records NaN rather than ''.
        assert values[1] != values[1]


class TestTokenConversion:
    def test_digits_become_a_number(self, tmp_path):
        f = _rules_file(tmp_path, [("Trial", r"exp(\d+)")])
        frame = parse_text([["exp12"], ["exp7"]], f)
        assert list(frame["Trial"]) == [12.0, 7.0]

    def test_underscore_is_read_as_a_decimal_point(self, tmp_path):
        f = _rules_file(tmp_path, [("Hours", r"(\d+([._]\d+)?)[_ ]*hr")])
        frame = parse_text([["3_5 hr"]], f)
        assert list(frame["Hours"]) == [3.5]

    def test_digit_bearing_non_number_stays_text(self, tmp_path):
        """'1B' has a digit so a number is attempted; str2double fails, text wins."""
        f = _rules_file(tmp_path, [("Label", r"label_([A-Za-z0-9]+)")])
        frame = parse_text([["label_1B"], ["label_42"]], f)
        assert list(frame["Label"]) == ["1B", 42.0]

    def test_non_participating_group_records_empty_string(self, tmp_path):
        """The one place a port diverges for free: regex gives None, MATLAB ''.

        Row 2 matches the second alternative, so group 1 did not participate.
        MATLAB records ''; without the mapping this side would record None and
        the two languages would disagree on a row that plainly matched.
        """
        f = _rules_file(tmp_path, [("Dose", r"(\d+)MM|(\d+)\s+mM")])
        frame = parse_text([["5MM"], ["7 mM"]], f)
        assert list(frame["Dose"]) == [5.0, ""]
        assert None not in list(frame["Dose"])


class TestMissesAndCleaning:
    def test_miss_records_nan_when_pattern_mentions_digits(self, tmp_path):
        f = _rules_file(tmp_path, [("Trial", r"exp(\d+)")])
        frame = parse_text([["exp12"], ["nothing"]], f)
        values = list(frame["Trial"])
        assert values[0] == 12.0
        assert values[1] != values[1]  # NaN

    def test_miss_records_empty_string_otherwise(self, tmp_path):
        f = _rules_file(tmp_path, [("Rep", r"Rep\s([IVX]+)")])
        frame = parse_text([["Rep IV"], ["nothing"]], f)
        assert list(frame["Rep"]) == ["IV", ""]

    def test_clean_drops_a_column_with_no_information(self, tmp_path):
        f = _rules_file(tmp_path, [("Heat", "(?i)heat"), ("Marker", "zzz")])
        assert list(parse_text([["cold"], ["colder"]], f).columns) == []
        assert list(parse_text([["cold"], ["colder"]], f, clean=False).columns) == [
            "Heat",
            "Marker",
        ]

    def test_all_empty_text_column_becomes_logical(self, tmp_path):
        """MATLAB's flattening treats '' as empty, so a text rule that never
        matched comes back as a logical column of False rather than as text."""
        f = _rules_file(tmp_path, [("Rep", r"Rep\s([IVX]+)")])
        frame = parse_text([["nothing"], ["still nothing"]], f, clean=False)
        assert frame["Rep"].dtype == bool
        assert list(frame["Rep"]) == [False, False]


class TestInputHandling:
    def test_row_columns_are_joined_with_one_space(self, tmp_path):
        f = _rules_file(tmp_path, [("Joined", r"data\sfile")])
        frame = parse_text([["data", "file"], ["data", "other"]], f, clean=False)
        assert list(frame["Joined"]) == [True, False]

    def test_a_flat_list_of_strings_is_one_column(self, tmp_path):
        f = _rules_file(tmp_path, [("Heat", "(?i)heat")])
        frame = parse_text(["heat a", "cold b"], f, clean=False)
        assert list(frame["Heat"]) == [True, False]

    def test_a_bare_string_is_one_row(self, tmp_path):
        f = _rules_file(tmp_path, [("Heat", "(?i)heat")])
        assert list(parse_text("heat a", f, clean=False)["Heat"]) == [True]

    def test_non_text_cell_is_rejected(self, tmp_path):
        """Mirrors cellstr(), which requires character vectors."""
        f = _rules_file(tmp_path, [("Heat", "(?i)heat")])
        with pytest.raises(TypeError, match="only strings"):
            parse_text([[42]], f)

    def test_a_bare_json_object_is_accepted_as_one_rule(self, tmp_path):
        """MATLAB's jsondecode returns a scalar struct for a bare object and
        numel() makes it work, so both file shapes are accepted here too."""
        path = tmp_path / "one.json"
        path.write_text(
            json.dumps({"VariableName": "Heat", "StringFormat": "(?i)heat"}),
            encoding="utf-8",
        )
        frame = parse_text([["heat"]], str(path))
        assert list(frame.columns) == ["Heat"]

    def test_row_count_survives_every_column_being_dropped(self, tmp_path):
        f = _rules_file(tmp_path, [("Heat", "(?i)heat")])
        frame = parse_text([["cold"], ["colder"], ["coldest"]], f)
        assert list(frame.columns) == []
        assert len(frame) == 3


def test_matlab_spelling_is_the_same_function():
    assert parseText is parse_text
