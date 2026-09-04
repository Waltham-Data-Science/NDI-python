"""Shared, self-describing ndi.fun.parse_text symmetry battery.

Python counterpart of:
    tests/+ndi/+symmetry/+fun/parseTextCases.m

Both language ports run the SAME case list -- each case identified by an ASCII
case NAME -- through their own real parseText, then write the recorded outputs
to

    <tempdir>/NDI/symmetryTest/<matlabArtifacts|pythonArtifacts>/fun/
             parseText/testParseTextArtifacts/parseTextCases.json

The on-disk schema is NDI-matlab's ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md``,
section 9. READ THAT FILE before changing anything here.

This is a separate module from :mod:`tests.symmetry.fun.cases` for the same
reason the MATLAB side is a separate class: ``cases`` is already large. The
canonical value grammar (:func:`~tests.symmetry.fun.cases.render` /
:func:`~tests.symmetry.fun.cases.render_sequence`) is imported from it, so the
grammar stays single-sourced and only the battery is new.

What the battery is for
-----------------------
Almost none of ``parseText``'s behaviour is written down: whether a rule yields
a logical or a token column is decided by scanning the *pattern text* for
``(``; whether a token becomes a number or a string is decided by a digit scan
and then ``str2double``; and the final column class is decided by a flattening
pass that can turn a column of empty strings into a logical column of ``False``.
Each case pins one of those decisions, and ``columnTypes`` is compared
precisely so the flattening pass cannot drift while the values still agree.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from tests.symmetry.fun import cases


def _case(
    name: str,
    note: str,
    clean: bool,
    rules: list[tuple[str, str]],
    input_rows: list[list[str]],
    expected_names: list[str] | None,
    expected_types: list[str] | None,
    expected_values: list[str] | None,
    deferred: bool = False,
) -> dict:
    return {
        "name": name,
        "note": note,
        "clean": clean,
        "rules": rules,
        "inputRows": input_rows,
        "expectedNames": expected_names or [],
        "expectedTypes": expected_types or [],
        "expectedValues": expected_values or [],
        "expectationDeferred": deferred,
    }


def definitions() -> list[dict]:
    """The 18-case battery. Order matches parseTextCases.definitions."""
    return [
        # --- logical (no capture group) rules ----------------------------
        _case(
            "logicalMatch",
            "A pattern whose only '(' is followed by '?' is an inline flag, not a "
            "group, so has_token is false and the rule yields a logical column.",
            True,
            [("Heat", r"(?i)heat")],
            [["sample_heat_1"], ["sample_cold_2"]],
            ["Heat"],
            ["logical"],
            ["[true, false]"],
        ),
        _case(
            "logicalAllFalseCleaned",
            "Clean removes every column that is all false. Both rules miss every "
            "row, so the result has NO columns at all.",
            True,
            [("Heat", r"(?i)heat"), ("Marker", "zzz")],
            [["cold_1"], ["cold_2"]],
            [],
            [],
            [],
        ),
        _case(
            "cleanFalseKeepsAllFalse",
            "The same rules and input as logicalAllFalseCleaned with Clean=false: "
            "the columns survive, which is what proves the previous case measured "
            "Clean and not a parse failure.",
            False,
            [("Heat", r"(?i)heat"), ("Marker", "zzz")],
            [["cold_1"], ["cold_2"]],
            ["Heat", "Marker"],
            ["logical", "logical"],
            ["[false, false]", "[false, false]"],
        ),
        _case(
            "nonCapturingGroupIsLogical",
            "(?:...) is a non-capturing group; the '(' is followed by '?' so "
            "has_token is false and this is a logical rule.",
            True,
            [("Kind", r"(?:alpha|beta)")],
            [["alpha run"], ["gamma run"]],
            ["Kind"],
            ["logical"],
            ["[true, false]"],
        ),
        _case(
            "columnsJoinedWithSpace",
            "Each row's columns are joined with a single space before matching, so "
            "a pattern may span the join.",
            True,
            [("Joined", r"data\sfile")],
            [["data", "file"], ["data", "other"]],
            ["Joined"],
            ["logical"],
            ["[true, false]"],
        ),
        # --- token rules: the numeric conversion -------------------------
        _case(
            "tokenNumeric",
            "A token containing digits that str2double accepts becomes a double.",
            True,
            [("Trial", r"experiment(\d+)")],
            [["experiment12"], ["experiment7"]],
            ["Trial"],
            ["double"],
            ["[12, 7]"],
        ),
        _case(
            "tokenUnderscoreDecimal",
            "Underscore is rewritten to '.' before str2double, so '3_5' is 3.5. "
            "This is the only reason the rewrite exists.",
            True,
            [("Hours", r"(\d+([._]\d+)?)[_ ]*(?:hr|hour)")],
            [["3_5 hr"], ["12 hour"]],
            ["Hours"],
            ["double"],
            ["[3.5, 12]"],
        ),
        _case(
            "tokenRomanNumeralString",
            "A token with no digit characters is stored as text, never parsed.",
            True,
            [("Repetition", r"Rep\s([IVXLCDM]+)")],
            [["Fig Rep IV a"], ["Fig Rep II b"]],
            ["Repetition"],
            ["cell"],
            ["['IV', 'II']"],
        ),
        _case(
            "tokenDigitBearingNotANumber",
            "'1B' has a digit, so str2double is tried; it returns NaN, so the TEXT "
            "is kept. The column is then mixed text/number and stays a cell -- the "
            "discriminating case for the flattening pass.",
            True,
            [("Label", r"label_([A-Za-z0-9]+)")],
            [["label_1B"], ["label_42"]],
            ["Label"],
            ["cell"],
            ["['1B', 42]"],
        ),
        # --- token rules: what a MISS records -----------------------------
        _case(
            "tokenMissingWithDigitPattern",
            "A miss records NaN when the pattern text contains '\\d' -- a literal "
            "substring test on the pattern, not on the match.",
            True,
            [("Trial", r"experiment(\d+)")],
            [["experiment12"], ["nothing here"]],
            ["Trial"],
            ["double"],
            ["[12, NaN]"],
        ),
        _case(
            "tokenMissingWithoutDigitPattern",
            "A miss records the empty string when the pattern has no '\\d'.",
            True,
            [("Repetition", r"Rep\s([IVX]+)")],
            [["Rep IV"], ["no rep marker"]],
            ["Repetition"],
            ["cell"],
            ["['IV', '']"],
        ),
        _case(
            "allMissesBecomeLogicalFalse",
            "THE SUBTLE ONE. isempty('') is true, so a column of nothing but empty "
            "strings satisfies the all-logical-or-empty test, every entry is "
            "replaced by false, and a TEXT rule ends up as a LOGICAL column -- "
            "which Clean then removes.",
            True,
            [("Repetition", r"Rep\s([IVX]+)")],
            [["nothing"], ["still nothing"]],
            [],
            [],
            [],
        ),
        _case(
            "allMissesLogicalVisibleWithoutClean",
            "The same rule and input as allMissesBecomeLogicalFalse with "
            "Clean=false, so the logical column is visible instead of removed. "
            "Without this case the previous one could not tell a dropped logical "
            "column from a dropped text column.",
            False,
            [("Repetition", r"Rep\s([IVX]+)")],
            [["nothing"], ["still nothing"]],
            ["Repetition"],
            ["logical"],
            ["[false, false]"],
        ),
        _case(
            "allMissesNaNCleaned",
            "A column of nothing but NaN is numeric, and Clean removes it.",
            True,
            [("Trial", r"experiment(\d+)")],
            [["nothing"], ["still nothing"]],
            [],
            [],
            [],
        ),
        # --- several rules and rows together ------------------------------
        _case(
            "multiRowMixedTypes",
            "Three rules of three different resulting classes over three rows, to "
            "pin column ORDER as well as content.",
            True,
            [("Heat", r"(?i)heat"), ("Trial", r"exp(\d+)"), ("Rep", r"Rep\s([IVX]+)")],
            [["heat exp1 Rep II"], ["cold exp2 Rep IV"], ["heat exp10 no rep"]],
            ["Heat", "Trial", "Rep"],
            ["logical", "double", "cell"],
            ["[true, false, true]", "[1, 2, 10]", "['II', 'IV', '']"],
        ),
        _case(
            "unicodeToken",
            "A non-ASCII token, to exercise the UTF-8 artifact path. Both "
            "characters are in the BMP, so this is not an astral case and MATLAB's "
            "UTF-16 char has no surrogate pair to expand.",
            True,
            [("Name", r"subject_([^_ ]+)")],
            [["subject_café"], ["subject_naïve"]],
            ["Name"],
            ["cell"],
            ["['café', 'naïve']"],
        ),
        # --- the two traps, both settled by the first real MATLAB run -----
        _case(
            "multipleGroupsFirstParticipatingGroupWins",
            "SETTLED BY THE FIRST REAL MATLAB RUN, against the prediction. Only "
            "the first PARTICIPATING capture group is read. Row 2 matches the "
            "second alternative, so group 1 is not part of the match at all: "
            "MATLAB's regexp(...,'tokens','once') returns tokens for the matched "
            "alternative alone and reads 7, where Python returns one entry per "
            "group in the whole pattern with None for the absentees. The "
            "prediction was that MATLAB recorded '' here; it does not, and the "
            "column is double rather than cell. The shipped XylidineDose rule in "
            "+setup/+conv/+babu/textParser.json has exactly this shape.",
            True,
            [("Dose", r"(\d+)MM|(\d+)\s+mM")],
            [["5MM"], ["7 mM"]],
            ["Dose"],
            ["double"],
            ["[5, 7]"],
        ),
        _case(
            "escapedParenTreatedAsToken",
            "SETTLED BY THE FIRST REAL MATLAB RUN, confirming the prediction. The "
            "'(' scan cannot tell an escaped paren from a capture group, so this "
            "is treated as a token rule even though it has no groups; the "
            "group-less match yields no tokens, so every row takes the miss "
            "branch and records NaN because the pattern text contains '\\d'.",
            False,
            [("Paren", r"value\(\d+\)")],
            [["value(5)"], ["value(9)"]],
            ["Paren"],
            ["double"],
            ["[NaN, NaN]"],
        ),
    ]


# ---------------------------------------------------------------------------
# running the battery
# ---------------------------------------------------------------------------


def rules_json(rules: list[tuple[str, str]]) -> str:
    """The parser file text for a list of (VariableName, StringFormat) pairs.

    Always a JSON **array**, never a bare object: MATLAB's ``jsonencode``
    collapses a 1x1 struct array to an object, so the single-rule cases would
    otherwise reach the two languages in different shapes.
    """
    return json.dumps(
        [{"VariableName": name, "StringFormat": pattern} for name, pattern in rules],
        indent=2,
        ensure_ascii=False,
    )


def rules_rendered(rules: list[tuple[str, str]]) -> str:
    """The rules in the canonical grammar, for comparison across languages."""
    return cases.render_sequence(
        [{"VariableName": name, "StringFormat": pattern} for name, pattern in rules]
    )


def input_rendered(input_rows: list[list[str]]) -> list[str]:
    """One rendered sequence per text row."""
    return [cases.render_sequence(row) for row in input_rows]


def describe_frame(frame: Any) -> tuple[list[str], list[str], list[str]]:
    """Column names, MATLAB classes, and rendered values of a parse_text result.

    Values are converted to plain Python types before rendering: a pandas bool
    column yields ``numpy.bool_``, which is not an ``isinstance`` of ``bool``,
    and would fall through the grammar to ``<bool_>`` instead of ``true``.
    """
    from ndi.fun.text import matlab_column_class

    names = [str(c) for c in frame.columns]
    types: list[str] = []
    values: list[str] = []
    for name in names:
        column = frame[name]
        kind = matlab_column_class(column)
        types.append(kind)
        if kind == "logical":
            values.append(cases.render_sequence([bool(x) for x in column]))
        elif kind == "double":
            values.append(cases.render_sequence([float(x) for x in column]))
        else:
            values.append(cases.render_sequence(list(column)))
    return names, types, values


def run_cases() -> list[dict]:
    """Run every case through ndi.fun.parse_text and record it.

    Errors are CAUGHT and recorded as ``status: 'error'`` rather than raised,
    for the reason in FUN_CASES_SCHEMA.md section 6: a generator that dies on
    one case writes no artifact at all and costs the suite every other case's
    coverage.
    """
    from ndi.fun.text import parse_text

    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="ndi-parsetext-rules-") as rule_dir:
        for defn in definitions():
            record = {
                "name": defn["name"],
                "note": defn["note"],
                "clean": bool(defn["clean"]),
                "rulesRendered": rules_rendered(defn["rules"]),
                "inputRendered": input_rendered(defn["inputRows"]),
                "status": "ok",
                "identifier": "",
                "message": "",
                "columnNames": [],
                "columnTypes": [],
                "columnValues": [],
                "rowCount": 0,
            }

            parser_file = Path(rule_dir) / f"{defn['name']}.json"
            parser_file.write_text(rules_json(defn["rules"]), encoding="utf-8")

            try:
                frame = parse_text(defn["inputRows"], str(parser_file), clean=defn["clean"])
                names, types, values = describe_frame(frame)
                record["columnNames"] = names
                record["columnTypes"] = types
                record["columnValues"] = values
                record["rowCount"] = int(len(frame))
            except Exception as exc:  # noqa: BLE001 - recorded, then compared
                record["status"] = "error"
                record["identifier"] = type(exc).__name__
                record["message"] = str(exc)

            results.append(record)
    return results


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def _as_list(v: Any) -> list[str]:
    """Normalize a decoded-JSON string list. MATLAB writes [] for an empty one."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


def signature(c: dict) -> str:
    """The compared part of one recorded case.

    ``identifier`` and ``message`` are deliberately absent: MATLAB identifiers
    and Python exception names can never match, and pinning them would make
    this a translation table instead of a behaviour check. Only the FACT of an
    error is symmetric.
    """
    return "; ".join(
        [
            f"status={c['status']}",
            f"clean={cases.render(bool(c['clean']))}",
            f"rows={cases.render(float(c['rowCount']))}",
            f"names={'|'.join(_as_list(c['columnNames']))}",
            f"types={'|'.join(_as_list(c['columnTypes']))}",
            f"values={'|'.join(_as_list(c['columnValues']))}",
        ]
    )


def input_signature(c: dict) -> str:
    """The inputs, so a green run cannot be two different batteries agreeing."""
    return "; ".join(
        [
            f"rules={c['rulesRendered']}",
            f"input={'|'.join(_as_list(c['inputRendered']))}",
        ]
    )


def check_expected(defn: dict, record: dict) -> tuple[bool, str]:
    """Compare one recorded case against its expected table.

    A deferred case always passes -- see the module docstring and section 9 of
    the schema for why the two traps carry no predicted value.
    """
    if defn["expectationDeferred"]:
        return True, "expectation deferred"
    want = "; ".join(
        [
            f"names={'|'.join(defn['expectedNames'])}",
            f"types={'|'.join(defn['expectedTypes'])}",
            f"values={'|'.join(defn['expectedValues'])}",
        ]
    )
    got = "; ".join(
        [
            f"names={'|'.join(_as_list(record['columnNames']))}",
            f"types={'|'.join(_as_list(record['columnTypes']))}",
            f"values={'|'.join(_as_list(record['columnValues']))}",
        ]
    )
    ok = want == got and record["status"] == "ok"
    return ok, f"expected [{want}], got [{got}] status={record['status']}"


def index_by_name(recorded: list[dict]) -> dict[str, dict]:
    """Case name -> case record. Cases are joined by name, never by position."""
    return {c["name"]: c for c in recorded}


__all__ = [
    "check_expected",
    "definitions",
    "describe_frame",
    "index_by_name",
    "input_rendered",
    "input_signature",
    "rules_json",
    "rules_rendered",
    "run_cases",
    "signature",
]
