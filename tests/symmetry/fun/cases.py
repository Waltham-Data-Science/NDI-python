"""Shared battery for the ``fun``-namespace symmetry artifacts.

The Python counterpart of ``tests/+ndi/+symmetry/+fun/cases.m``. The on-disk
contract both sides write is ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md`` in
NDI-matlab.

This module is a plain helper, not a test, so pytest never collects it.
"""

from __future__ import annotations

import math
from typing import Any

from ndi.fun.file import elementDirectoryName, pathSafeName, utf16_units
from ndi.fun.stimulus import whatIsConstant, whatVaries

# ---------------------------------------------------------------------------
# The canonical value grammar
#
# Every compared value is rendered to a string by this grammar first.
# Comparing rendered strings avoids the usual symmetry rot: MATLAB double vs
# Python int, MATLAB cell vs Python list, jsondecode collapsing a one-element
# array, and so on.
# ---------------------------------------------------------------------------


def num_token(x: float) -> str:
    """Canonical decimal token for one real number.

    The non-finite tokens are spelled MATLAB's way on purpose: MATLAB's ``%g``
    gives ``NaN``/``Inf`` where Python's gives ``nan``/``inf``. The schema
    fixes MATLAB's spelling and this side matches it.
    """
    x = float(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    return f"{x:.12g}"


def render(v: Any) -> str:
    """Canonical, language-neutral string form of a value.

    ``number scalar`` -> ``%.12g`` / ``NaN`` / ``Inf`` / ``-Inf``;
    ``bool`` -> ``true``/``false``; ``text`` -> ``'the text'``;
    ``sequence`` -> ``[e1, e2]``; ``mapping`` -> ``{key: value, ...}`` with
    **keys sorted**; anything else -> ``<typename>``.
    """
    # bool before number: in Python bool subclasses int, and True must render
    # 'true', not '1'.
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f"'{v}'"
    if isinstance(v, (int, float)):
        return num_token(v)
    if isinstance(v, dict):
        parts = [f"{k}: {render(v[k])}" for k in sorted(v)]
        return "{" + ", ".join(parts) + "}"
    if isinstance(v, (list, tuple)):
        return render_sequence(v)
    if v is None:
        return "<NoneType>"
    return f"<{type(v).__name__}>"


def render_sequence(v: Any) -> str:
    """Render *v* as a sequence, whatever container it is.

    For any value that is semantically a LIST even when one side hands back a
    scalar -- notably ``whatVaries``' ``values``, which MATLAB collapses to a
    bare scalar when a parameter takes only one distinct value.

    A bare ``str`` is **one** element, not a sequence of characters. No case
    in this battery reaches that today; the guard is here so a future case
    that does fails as a real behaviour difference rather than exploding into
    characters.
    """
    if isinstance(v, str) or isinstance(v, dict) or not isinstance(v, (list, tuple)):
        parts = [render(v)]
    else:
        parts = [render(e) for e in v]
    return "[" + ", ".join(parts) + "]"


def codepoints(s: str) -> list[int]:
    """Unicode scalar values of *s*."""
    return [ord(c) for c in s]


def from_codepoints(cp: list[int]) -> str:
    """Build a string from Unicode scalar values."""
    return "".join(chr(c) for c in cp)


def _cp(s: str) -> tuple[int, ...]:
    """Codepoints of a literal, so the table below stays readable."""
    return tuple(ord(c) for c in s)


# ---------------------------------------------------------------------------
# pathSafeName battery -- 22 cases
#
# The input is specified as CODEPOINTS, not as a literal: each side rebuilds
# its input from them, so neither has to trust a source-file encoding, and
# readArtifacts/fun/pathSafeName.testInputsAgree asserts the two sides really
# started from the same characters.
# ---------------------------------------------------------------------------

#: (name, input codepoints, expected pathSafeName, note)
PATH_SAFE_NAME_DEFS: list[tuple[str, tuple[int, ...], str, str]] = [
    ("emptyString", _cp(""), "x", "empty result becomes 'x'"),
    ("portablePassthrough", _cp("ctx_1-a.dat"), "ctx_1-a.dat", "portable set passes through"),
    ("elementBarSeparator", _cp("probe | 1"), "probe_-_1", "the element-string separator"),
    ("elementBarSeparatorUnderscored", _cp("ctx_|_1"), "ctx_-_1", "'|' is illegal on Windows"),
    ("singleSpace", _cp(" "), "_", "whitespace becomes '_'"),
    ("tabAndNewline", _cp("a\tb\nc"), "a_b_c", "control characters become '_'"),
    ("deleteControlChar", _cp("a\x7fb"), "a_b", "DEL (127) is a control character"),
    (
        "windowsForbiddenChars",
        _cp('a<b>c:d"e/f\\g|h?i*j'),
        "a-b-c-d-e-f-g-h-i-j",
        "every character Windows forbids becomes '-'",
    ),
    ("trailingDots", _cp("report..."), "report", "Windows strips trailing dots"),
    ("allDots", _cp("..."), "x", "dot strip runs BEFORE the empty check"),
    ("leadingDot", _cp(".hidden"), ".hidden", "base name before the first dot is empty"),
    ("reservedCON", _cp("CON"), "_CON", "reserved device name"),
    ("reservedLowerCon", _cp("con"), "_con", "reserved match is case-insensitive"),
    ("reservedCOM1", _cp("COM1"), "_COM1", "reserved device name"),
    ("reservedLPT9", _cp("LPT9"), "_LPT9", "reserved device name"),
    ("reservedWithExtension", _cp("CON.txt"), "_CON.txt", "reserved with an extension"),
    ("reservedTrailingDot", _cp("com1."), "_com1", "dot strip runs BEFORE the reserved check"),
    ("notReservedCOM0", _cp("COM0"), "COM0", "COM0 is NOT reserved"),
    ("bmpUnicodeAccent", (0x61, 0xE9, 0x62), "a-b", "BMP: 3 UTF-16 units, 3 codepoints"),
    (
        "astralUnicodeEmoji",
        (0x61, 0x1F600, 0x62),
        "a--b",
        "astral: surrogate PAIR gives TWO '-' -- 4 units, 3 codepoints",
    ),
    ("astralOnlyEmoji", (0x1F389,), "--", "astral alone: 2 units, 1 codepoint"),
    (
        "astralThenTrailingDot",
        (0x1F600, 0x002E),
        "--",
        "astral then a stripped trailing dot: 3 units, 2 codepoints",
    ),
]


def run_path_safe_name_cases() -> list[dict]:
    """Run the pathSafeName battery and return one record per case."""
    results = []
    for name, cps, _expected, note in PATH_SAFE_NAME_DEFS:
        text = from_codepoints(list(cps))
        record: dict[str, Any] = {
            "name": name,
            "status": "ok",
            "identifier": "",
            "message": "",
            "note": note,
            "input": text,
            "inputCodepoints": list(cps),
            "inputUtf16Units": len(utf16_units(text)),
            "inputCodepointCount": len(text),
            "pathSafeName": "",
            "elementDirName": "",
            "elementLegacyDirName": "",
            "elementLegacyDirNameCodepoints": [],
        }
        try:
            record["pathSafeName"] = pathSafeName(text)
            dir_name, legacy = elementDirectoryName(text)
            record["elementDirName"] = dir_name
            record["elementLegacyDirName"] = legacy
            record["elementLegacyDirNameCodepoints"] = codepoints(legacy)
        except Exception as exc:  # recorded, and asserted against MATLAB
            record["status"] = "error"
            record["identifier"] = type(exc).__name__
            record["message"] = str(exc)
        results.append(record)
    return results


def verify_path_safe_name_expected(results: list[dict]) -> list[str]:
    """Check every case against its expected value. Returns a list of problems.

    Python is not the reference side for ``pathSafeName`` -- MATLAB is -- but
    the expectations are identical and checking here means a regression fails
    in Python's own suite rather than only on the cross-language comparison.
    """
    expected = {name: exp for name, _cps, exp, _note in PATH_SAFE_NAME_DEFS}
    problems = []
    for r in results:
        name = r["name"]
        if r["status"] != "ok":
            problems.append(f"{name}: unexpected error {r['identifier']}: {r['message']}")
            continue
        if r["pathSafeName"] != expected[name]:
            problems.append(
                f"{name}: pathSafeName is {r['pathSafeName']!r}, expected {expected[name]!r}"
            )
        if r["elementDirName"] != r["pathSafeName"]:
            problems.append(
                f"{name}: elementDirName {r['elementDirName']!r} != "
                f"pathSafeName {r['pathSafeName']!r}"
            )
    return problems


def path_safe_signature(c: dict) -> tuple:
    """The per-case signature compared across languages.

    ``identifier`` and ``message`` are deliberately excluded: MATLAB
    identifiers and Python exception names can never match, and pinning them
    would make this a translation table instead of a behaviour check. Only
    the *fact* of an error is symmetric.
    """
    return (
        c["status"],
        c["pathSafeName"],
        c["elementDirName"],
        tuple(c["elementLegacyDirNameCodepoints"]),
        c["inputUtf16Units"],
        c["inputCodepointCount"],
    )


# ---------------------------------------------------------------------------
# whatVaries battery -- 18 cases
#
# Every nested list in a fixture has at least TWO elements, deliberately.
# MATLAB cannot tell a 1x1 struct array from a scalar struct, so a
# one-element nested list renders as a MAPPING there and a SEQUENCE here --
# and inputRendered is compared, so the two languages would fail against each
# other over a container shape rather than a behaviour.
# ---------------------------------------------------------------------------

NAN = float("nan")


def three_angle_stimuli() -> list[dict]:
    """The fixture shared by three of the MATLAB unit test methods."""
    return [{"parameters": {"angle": a, "contrast": 1, "sFrequency": 0.5}} for a in (0, 90, 180)]


def what_varies_input(name: str) -> tuple[Any, bool]:
    """Build the native input for one whatVaries case. Returns (stimuli, excludeBlank)."""
    if name == "stimuliStructArray":
        return three_angle_stimuli(), True
    if name == "valuesSortedAndUnique":
        return [{"parameters": {"angle": a, "contrast": 1}} for a in (180, 0, 90, 0)], True
    if name == "cellOfParameterStructs":
        return [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}], True
    if name == "structArrayOfParameterStructs":
        return [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}], True
    if name == "documentPropertiesShapedStruct":
        return {"stimulus_presentation": {"stimuli": three_angle_stimuli()}}, True
    if name == "poolingAcrossPresentations":
        # Presentation 2 carries TWO stimuli on purpose -- see the module note.
        second = [
            {"parameters": {"angle": a, "contrast": 1, "sFrequency": 0.5}} for a in (270, 315)
        ]
        return [
            {"stimulus_presentation": {"stimuli": three_angle_stimuli()}},
            {"stimulus_presentation": {"stimuli": second}},
        ], True
    if name == "fieldPresentInSomeStimuli":
        return [{"angle": 0, "contrast": 1}, {"angle": 0, "contrast": 1, "phase": 5}], True
    if name in ("blankStimuliExcludedByDefault", "blankStimuliIncludedWhenOptionFalse"):
        stimuli = [
            {"angle": 0, "contrast": 1},
            {"angle": 90, "contrast": 1},
            {"angle": 0, "contrast": 1, "isblank": 1},
        ]
        return stimuli, name == "blankStimuliExcludedByDefault"
    if name == "cellValuedConstantParameter":
        return [
            {"color": ["r", "g", "b"], "angle": 0},
            {"color": ["r", "g", "b"], "angle": 90},
        ], True
    if name == "vectorValuedVaryingParameter":
        return [{"rect": [0, 0, 100, 100]}, {"rect": [0, 0, 200, 200]}], True
    if name == "allBlankStimuli":
        return [{"angle": 0, "isblank": 1}, {"angle": 90, "isblank": 1}], True
    if name == "nonNumericValues":
        return [{"shape": "circle", "size": 5}, {"shape": "square", "size": 5}], True
    if name == "allConstantSingleStimulus":
        return {"angle": 0, "contrast": 1}, True
    if name == "emptyInput":
        return [], True
    if name == "allNaNParameter":
        return [{"angle": NAN, "contrast": 1}, {"angle": NAN, "contrast": 1}], True
    if name == "badInputNumeric":
        return 42, True
    if name == "badCellEntry":
        return [42], True
    raise ValueError(f"Unknown whatVaries case {name!r}.")


#: (name, shape token, which whatVariesTest method(s) the case mirrors)
WHAT_VARIES_DEFS: list[tuple[str, str, str]] = [
    (
        "stimuliStructArray",
        "stimuliStructArray",
        "testStimuliStructArray and testWhatIsConstantMatchesSecondOutput",
    ),
    ("valuesSortedAndUnique", "stimuliStructArray", "testValuesSortedAndUnique"),
    ("cellOfParameterStructs", "cellOfParameterStructs", "testCellOfParameterStructs"),
    (
        "structArrayOfParameterStructs",
        "structArrayOfParameterStructs",
        "testStructArrayOfParameterStructs",
    ),
    ("documentPropertiesShapedStruct", "documentProperties", "testDocumentPropertiesShapedStruct"),
    ("poolingAcrossPresentations", "documentPropertiesArray", "testPoolingAcrossPresentations"),
    ("fieldPresentInSomeStimuli", "cellOfParameterStructs", "testFieldPresentInSomeStimuli"),
    (
        "blankStimuliExcludedByDefault",
        "cellOfParameterStructs",
        "testBlankStimuliExcludedByDefault",
    ),
    (
        "blankStimuliIncludedWhenOptionFalse",
        "cellOfParameterStructs",
        "testBlankStimuliIncludedWhenOptionFalse",
    ),
    ("cellValuedConstantParameter", "cellOfParameterStructs", "testCellValuedConstantParameter"),
    ("vectorValuedVaryingParameter", "cellOfParameterStructs", "testVectorValuedVaryingParameter"),
    ("allBlankStimuli", "cellOfParameterStructs", "testAllBlankStimuliGivesEmpty"),
    ("nonNumericValues", "structArrayOfParameterStructs", "testNonNumericValuesReturnedAsCell"),
    ("allConstantSingleStimulus", "singleParameterStruct", "testAllConstantSingleStimulus"),
    ("emptyInput", "emptyCell", "testEmptyInput"),
    ("allNaNParameter", "cellOfParameterStructs", "none - added divergence probe"),
    ("badInputNumeric", "badInput", "testBadInputErrors, first assertion"),
    ("badCellEntry", "badInput", "testBadInputErrors, second assertion"),
]


def known_divergences() -> list[str]:
    """Cases where MATLAB main and this port are believed to disagree today.

    Both trace to one line: ``local_varyingFields`` in MATLAB's
    ``whatVaries.m`` compares with ``vlt.data.eqlen``, which bottoms out in a
    bare ``==``, while this port uses ``isequaln`` semantics throughout.

    - ``cellValuedConstantParameter``: MATLAB errors (``==`` is undefined for
      two cell arrays); Python succeeds and reports ``color`` constant.
    - ``allNaNParameter``: MATLAB reports ``angle`` varying
      (``eqlen(NaN, NaN)`` is false); Python reports it constant.

    A listed case that now AGREES means the upstream fix landed -- remove the
    entry. A stale allow-list is how a symmetry suite goes quietly green over
    the bug it exists to watch, which is why the auditor fails rather than
    prints.
    """
    return ["cellValuedConstantParameter", "allNaNParameter"]


def run_what_varies_cases() -> list[dict]:
    """Run the whatVaries battery and return one record per case.

    Errors are recorded rather than raised, by design: a generator that died
    on the already-known cell-valued case would write no artifact at all,
    costing every other case's coverage to report one documented bug. The
    error is not swallowed -- it is recorded as ``status: "error"`` and
    asserted against the other language at the comparison.
    """
    results = []
    for name, shape, mirrors in WHAT_VARIES_DEFS:
        stimuli, exclude_blank = what_varies_input(name)
        record: dict[str, Any] = {
            "name": name,
            "status": "ok",
            "identifier": "",
            "message": "",
            "shape": shape,
            "mirrors": mirrors,
            "excludeBlank": bool(exclude_blank),
            "inputRendered": render(stimuli),
            "variesParameters": [],
            "variesValues": [],
            "constantParameters": [],
            "constantValues": [],
            "whatIsConstantRendered": "",
        }
        try:
            varies, constant = whatVaries(stimuli, excludeBlank=exclude_blank)
            record["variesParameters"] = [v["parameter"] for v in varies]
            # 'values' is semantically a list even with one element.
            record["variesValues"] = [render_sequence(v["values"]) for v in varies]
            record["constantParameters"] = [c["parameter"] for c in constant]
            record["constantValues"] = [render(c["value"]) for c in constant]
            # whatIsConstant collapses one level up in MATLAB, so this goes
            # through render_sequence too: '[{...}]', never a bare '{...}'.
            record["whatIsConstantRendered"] = render_sequence(
                whatIsConstant(stimuli, excludeBlank=exclude_blank)
            )
        except Exception as exc:
            record["status"] = "error"
            record["identifier"] = type(exc).__name__
            record["message"] = str(exc)
        results.append(record)
    return results


def what_varies_signature(c: dict) -> tuple:
    """The per-case signature compared across languages.

    ``identifier``, ``message``, ``shape`` and ``mirrors`` are excluded --
    the first two can never match across languages, and the latter two record
    MATLAB-side container shape that Python's single list type cannot
    reproduce.
    """
    return (
        c["status"],
        bool(c["excludeBlank"]),
        c["inputRendered"],
        tuple(c["variesParameters"]),
        tuple(c["variesValues"]),
        tuple(c["constantParameters"]),
        tuple(c["constantValues"]),
        c["whatIsConstantRendered"],
    )


def index_by_name(cases: list[dict]) -> dict[str, dict]:
    """Index a case list by its join key. Cases are joined by name, not position."""
    return {c["name"]: c for c in cases}
