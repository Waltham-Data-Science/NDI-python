"""Shared, self-describing ``ndi.fun`` symmetry battery (Python side).

Python counterpart of MATLAB ``tests/+ndi/+symmetry/+fun/cases.m``.  The on-disk
contract both sides implement is ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md`` in
NDI-matlab.  **Read that file before changing anything here**: the two languages
are reconciled against it, and a change on this side that is not also a change
there is how a symmetry suite starts comparing two different things.

Both language ports run the SAME case list -- each case identified by an ASCII
case ``name``, and each ``pathSafeName`` input specified as a vector of Unicode
scalar values so neither language has to trust a source-file encoding -- through
their own real implementation, then write the recorded outputs to::

    <tempdir>/NDI/symmetryTest/<matlabArtifacts|pythonArtifacts>/fun/
             <className>/<testName>/<file>.json

Why values are compared as rendered strings
-------------------------------------------
``whatVaries`` returns language-native values: MATLAB numeric row vectors, cell
arrays and ``char``; Python lists, dicts and ``str``.  Comparing those across a
JSON round trip is where symmetry tests usually rot -- MATLAB ``double`` vs
Python ``int``, MATLAB cell vs Python list, ``jsondecode`` collapsing a
one-element array.  Instead each side renders every compared value with the SAME
small, language-neutral grammar (:func:`render`) and the two sides compare plain
strings.

The grammar deliberately does NOT distinguish a MATLAB cell array from a MATLAB
struct array from a numeric vector -- Python has one list type for all three, so
a grammar that told them apart could never match.  The MATLAB-side input shape is
recorded separately in each whatVaries case's ``shape`` field, which is *not*
compared.

Two consequences of the grammar are worth stating outright, because they are the
only reason this module can be short:

* Nothing non-finite ever reaches the JSON.  ``NaN`` is rendered as the string
  ``'NaN'`` before encoding, so the artifact is strict JSON without needing the
  ``"__NaN__"`` sentinel the pre-contract Python battery carried.
* Almost no shape normalization is needed on the read side.  ``cases`` is a cell
  of structs on the MATLAB side precisely so ``jsonencode`` cannot collapse it,
  and every compared value is already a string.  The one residual is documented
  at :func:`as_int_list`.

See also
--------
``tests/symmetry/make_artifacts/fun/test_path_safe_name.py``
``tests/symmetry/make_artifacts/fun/test_what_varies.py``
``tests/symmetry/read_artifacts/fun/test_path_safe_name.py``
``tests/symmetry/read_artifacts/fun/test_what_varies.py``
``tests/symmetry/test_fun_negative_controls.py``
"""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

import ndi.fun.file as ndi_fun_file
import ndi.fun.stimulus as ndi_stimulus

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# canonical value rendering
# ---------------------------------------------------------------------------


def num_token(x: Any) -> str:
    """Canonical decimal token for one real number.

    The non-finite tokens are spelled out because MATLAB's ``%g`` gives
    ``NaN``/``Inf`` while Python's gives ``nan``/``inf``; the schema fixes the
    MATLAB spelling and this side must match it.
    """
    value = float(x)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    return f"{value:.12g}"


def render(v: Any) -> str:
    """Canonical, language-neutral string form of a value.

    ==================  ====================================================
    kind                rendering
    ==================  ====================================================
    number, scalar      ``%.12g``, or ``NaN`` / ``Inf`` / ``-Inf``
    boolean, scalar     ``true`` / ``false``
    text                ``'the text'`` (single-quoted, no escaping)
    sequence            ``[e1, e2]``; empty -> ``[]``
    mapping             ``{key: value, ...}``, **keys sorted**
    anything else       ``<typename>``
    ==================  ====================================================

    Booleans are checked before numbers: in Python ``bool`` is a subclass of
    ``int``, and ``True`` must render ``true``, not ``1``.

    Only vectors are used by this battery.  A 2-D matrix would render in
    MATLAB's column-major order and Python's row-major order -- do not add one.
    """
    # bool before int: bool is a subclass of int in Python.
    if isinstance(v, (bool, np.bool_)):
        return "true" if v else "false"

    if isinstance(v, str):
        return "''" if v == "" else "'" + v + "'"

    if isinstance(v, Mapping):
        parts = [f"{key}: {render(v[key])}" for key in sorted(v)]
        return "{" + ", ".join(parts) + "}"

    if isinstance(v, np.ndarray):
        if v.ndim == 0:
            return render(v.item())
        return render_sequence(v.tolist())

    if isinstance(v, np.generic):
        return render(v.item())

    if isinstance(v, (int, float)):
        return num_token(v)

    if isinstance(v, Sequence) and not isinstance(v, (str, bytes)):
        return render_sequence(v)

    if isinstance(v, (set, frozenset)):
        # not reachable from this battery; rendered rather than crashing so a
        # future case that grows one is a visible mismatch, not a traceback.
        return render_sequence(sorted(v, key=repr))

    return "<" + type(v).__name__ + ">"


def render_sequence(v: Any) -> str:
    """Render *v* as a sequence, whatever container it is.

    Use this for any value that is semantically a LIST even when the language
    hands it back as a scalar -- notably whatVaries' ``values`` field, which is
    the list of distinct values a parameter takes and which MATLAB collapses to a
    bare scalar when there is only one of them.  Rendering the MATLAB scalar as
    ``5`` instead of ``[5]`` would be a spurious mismatch against Python's
    one-element list.

    A ``str`` counts as ONE element here, not as a sequence of characters.  The
    MATLAB side iterates a ``char`` row vector character by character, so a
    single bare ``char`` reaching ``renderSequence`` would render as
    ``['c', 'i', ...]`` there and ``['circle']`` here.  No case in this battery
    reaches that: whatVaries returns non-numeric distinct values in a cell, so
    even one distinct string arrives as a one-element container on both sides.
    """
    if isinstance(v, np.ndarray):
        items: list[Any] = v.tolist() if v.ndim else [v.item()]
    elif isinstance(v, Mapping) or isinstance(v, (str, bytes)):
        items = [v]
    elif isinstance(v, Sequence):
        items = list(v)
    else:
        items = [v]
    return "[" + ", ".join(render(item) for item in items) + "]"


# ---------------------------------------------------------------------------
# unicode helpers
#
# MATLAB char arrays hold UTF-16 code units, so a character above U+FFFF
# occupies TWO chars and pathSafeName maps it to TWO '-'.  Python strings hold
# Unicode scalar values, so a naive port emits ONE '-'.  That divergence is why
# the astral cases are in this battery -- these helpers let both sides start
# from the same neutral codepoint vector and record both counts.
# ---------------------------------------------------------------------------


def codepoints(s: str) -> list[int]:
    """Unicode scalar values of *s* -- what Python's ``len`` counts."""
    return [ord(ch) for ch in s]


def from_codepoints(cp: Sequence[int]) -> str:
    """Build a string from Unicode scalar values."""
    return "".join(chr(int(c)) for c in cp)


def utf16_unit_count(s: str) -> int:
    """Number of UTF-16 code units in *s* -- what MATLAB's ``numel(char(s))``
    counts.  An astral character contributes two."""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in s)


# ---------------------------------------------------------------------------
# pathSafeName battery
# ---------------------------------------------------------------------------

_WINDOWS_FORBIDDEN = 'a<b>c:d"e/f\\g|h?i*j'

# (name, codepoints, expected_status, expected_name, expected_utf16_units, note)
#
# EXPECTED_NAME is the reference output.  MATLAB derived its copy of this column
# by reading src/ndi/+ndi/+fun/+file/pathSafeName.m branch by branch without a
# runtime; this side measures it, so a disagreement between the two columns is
# itself a finding.
PATH_SAFE_NAME_DEFS: tuple[tuple[str, tuple[int, ...], str, str, int, str], ...] = (
    # --- degenerate / passthrough -----------------------------------------
    ("emptyString", (), "ok", "x", 0, "an empty result becomes 'x'"),
    (
        "portablePassthrough",
        tuple(codepoints("ctx_1-a.dat")),
        "ok",
        "ctx_1-a.dat",
        11,
        "already inside [A-Za-z0-9._-]",
    ),
    # --- the element-string bug this sanitizer exists for ------------------
    (
        "elementBarSeparator",
        tuple(codepoints("probe | 1")),
        "ok",
        "probe_-_1",
        9,
        "ndi.element/elementstring form; '|' is illegal on Windows",
    ),
    (
        "elementBarSeparatorUnderscored",
        tuple(codepoints("ctx_|_1")),
        "ok",
        "ctx_-_1",
        7,
        "the pathSafeName docstring example",
    ),
    # --- whitespace and control characters -> '_' --------------------------
    (
        "singleSpace",
        tuple(codepoints(" ")),
        "ok",
        "_",
        1,
        "space maps to '_', so the result is not empty",
    ),
    (
        "tabAndNewline",
        (97, 9, 98, 10, 99),
        "ok",
        "a_b_c",
        5,
        "control characters below 32 map to '_'",
    ),
    (
        "deleteControlChar",
        (97, 127, 98),
        "ok",
        "a_b",
        3,
        "DEL (127) is the one control character above 31",
    ),
    # --- everything else outside the portable set -> '-' -------------------
    (
        "windowsForbiddenChars",
        tuple(codepoints(_WINDOWS_FORBIDDEN)),
        "ok",
        "a-b-c-d-e-f-g-h-i-j",
        19,
        "the nine characters Windows forbids outright",
    ),
    # --- trailing dots ------------------------------------------------------
    (
        "trailingDots",
        tuple(codepoints("report...")),
        "ok",
        "report",
        9,
        "Windows silently strips trailing dots",
    ),
    (
        "allDots",
        tuple(codepoints("...")),
        "ok",
        "x",
        3,
        "the dot strip runs BEFORE the empty check",
    ),
    (
        "leadingDot",
        tuple(codepoints(".hidden")),
        "ok",
        ".hidden",
        7,
        "base name before the first dot is empty, so no reserved prefix",
    ),
    # --- Windows reserved device names -------------------------------------
    ("reservedCON", tuple(codepoints("CON")), "ok", "_CON", 3, ""),
    (
        "reservedLowerCon",
        tuple(codepoints("con")),
        "ok",
        "_con",
        3,
        "reserved names are matched case-insensitively",
    ),
    ("reservedCOM1", tuple(codepoints("COM1")), "ok", "_COM1", 4, ""),
    ("reservedLPT9", tuple(codepoints("LPT9")), "ok", "_LPT9", 4, "top of the LPT range"),
    (
        "reservedWithExtension",
        tuple(codepoints("CON.txt")),
        "ok",
        "_CON.txt",
        7,
        "reserved with or without an extension",
    ),
    (
        "reservedTrailingDot",
        tuple(codepoints("com1.")),
        "ok",
        "_com1",
        5,
        "the dot strip runs first, so this becomes reserved",
    ),
    (
        "notReservedCOM0",
        tuple(codepoints("COM0")),
        "ok",
        "COM0",
        4,
        "COM0 and LPT0 are NOT reserved",
    ),
    # --- unicode ------------------------------------------------------------
    ("bmpUnicodeAccent", (97, 233, 98), "ok", "a-b", 3, "inside the BMP: one code unit, one '-'"),
    (
        "astralUnicodeEmoji",
        (97, 128512, 98),
        "ok",
        "a--b",
        4,
        "above U+FFFF: a surrogate PAIR in MATLAB, so TWO '-'",
    ),
    (
        "astralOnlyEmoji",
        (127881,),
        "ok",
        "--",
        2,
        "a lone astral character does not sanitize to empty in MATLAB",
    ),
    (
        "astralThenTrailingDot",
        (128512, 46),
        "ok",
        "--",
        3,
        "astral expansion, then the trailing-dot strip",
    ),
)


def _error_identifier(exc: BaseException) -> str:
    """The recorded, never-compared identifier for a raised exception.

    The port prefixes each raised message with the MATLAB error identifier
    (``ndi:fun:stimulus:whatVaries_parameterList:badInput: ...``) where it has
    one, so the identifier is greppable from either side.  Where it does not --
    ``pathSafeName`` raises a bare ``TypeError`` -- the exception class name is
    recorded instead.  Neither is ever compared across languages: MATLAB
    identifiers and Python exception names can never match, and pinning them
    would make the symmetry test a translation table instead of a behaviour
    check.  Only the *fact* of an error (``status``) is symmetric.
    """
    head = str(exc).split(": ", 1)[0]
    if head.startswith("ndi:"):
        return head
    return type(exc).__name__


def run_path_safe_name_cases() -> list[dict[str, Any]]:
    """Run every pathSafeName case through the real
    ``ndi.fun.file.pathSafeName`` / ``elementDirectoryName``.

    Every case is wrapped in try/except: a case that raises is RECORDED as
    ``status='error'`` rather than aborting the battery.
    """
    results: list[dict[str, Any]] = []
    for name, cp, _status, _expected, _units, note in PATH_SAFE_NAME_DEFS:
        input_str = from_codepoints(cp)

        case: dict[str, Any] = {
            "name": name,
            "status": "ok",
            "identifier": "",
            "message": "",
            "note": note,
            "input": input_str,
            "inputCodepoints": list(cp),
            "inputUtf16Units": utf16_unit_count(input_str),
            "inputCodepointCount": len(input_str),
            "pathSafeName": "",
            "elementDirName": "",
            "elementLegacyDirName": "",
            "elementLegacyDirNameCodepoints": [],
        }

        try:
            psn = ndi_fun_file.pathSafeName(input_str)
            dir_name, legacy_dir_name = ndi_fun_file.elementDirectoryName(input_str)
            case["pathSafeName"] = psn
            case["elementDirName"] = dir_name
            case["elementLegacyDirName"] = legacy_dir_name
            case["elementLegacyDirNameCodepoints"] = codepoints(legacy_dir_name)
        except Exception as exc:  # noqa: BLE001 -- the error IS the recorded result
            case["status"] = "error"
            case["identifier"] = _error_identifier(exc)
            case["message"] = str(exc)

        results.append(case)
    return results


def verify_path_safe_name_expected(results: Sequence[Mapping[str, Any]]) -> list[str]:
    """Check *results* against the reference expectations, returning problems.

    Python is a reference side for ``pathSafeName`` too -- every branch is
    deterministic and fully readable -- so the make-side test asserts this list
    is empty before writing the artifact.  A regression fails loudly at the
    producing test rather than being quietly recorded and shipped to MATLAB as
    the new truth.
    """
    problems: list[str] = []
    if len(results) != len(PATH_SAFE_NAME_DEFS):
        problems.append(
            f"expected {len(PATH_SAFE_NAME_DEFS)} pathSafeName results, got {len(results)}"
        )
    for index, definition in enumerate(PATH_SAFE_NAME_DEFS):
        if index >= len(results):
            break
        name, cp, expected_status, expected_name, expected_units, _note = definition
        case = results[index]
        if case["name"] != name:
            problems.append(f"pathSafeName case {index} name: {case['name']!r} != {name!r}")
            continue
        if case["status"] != expected_status:
            problems.append(
                f"pathSafeName case {name!r} status: {case['status']!r} != "
                f"{expected_status!r} ({case['message']})"
            )
            continue
        if expected_status != "ok":
            continue
        if case["pathSafeName"] != expected_name:
            problems.append(
                f"pathSafeName case {name!r}: {case['pathSafeName']!r} != {expected_name!r}"
            )
        # elementDirectoryName maps space->'_' before delegating, and
        # pathSafeName maps space->'_' too, so the two must agree on every input.
        if case["elementDirName"] != case["pathSafeName"]:
            problems.append(
                f"pathSafeName case {name!r}: elementDirectoryName "
                f"{case['elementDirName']!r} disagrees with pathSafeName "
                f"{case['pathSafeName']!r}"
            )
        if case["inputUtf16Units"] != expected_units:
            problems.append(
                f"pathSafeName case {name!r}: UTF-16 code units "
                f"{case['inputUtf16Units']} != {expected_units}"
            )
        if case["inputCodepointCount"] != len(cp):
            problems.append(
                f"pathSafeName case {name!r}: codepoint count "
                f"{case['inputCodepointCount']} != {len(cp)}"
            )
        # the legacy name is the input with U+0020 -> U+005F, nothing else
        expected_legacy = [95 if c == 32 else int(c) for c in cp]
        if as_int_list(case["elementLegacyDirNameCodepoints"]) != expected_legacy:
            problems.append(
                f"pathSafeName case {name!r}: legacy directory name codepoints "
                f"{case['elementLegacyDirNameCodepoints']} != {expected_legacy}"
            )
    return problems


def path_safe_signature(case: Mapping[str, Any]) -> str:
    """The comparable content of one pathSafeName case.

    ``identifier`` and ``message`` are deliberately NOT part of the signature
    (see :func:`_error_identifier`).  ``status`` is compared; the text is
    recorded for humans.
    """
    return "|".join(
        [
            f"status={as_text(case['status'])}",
            f"pathSafeName={as_text(case['pathSafeName'])}",
            f"elementDirName={as_text(case['elementDirName'])}",
            "legacyCodepoints="
            + render_sequence(as_int_list(case["elementLegacyDirNameCodepoints"])),
            f"utf16Units={num_token(case['inputUtf16Units'])}",
            f"codepointCount={num_token(case['inputCodepointCount'])}",
        ]
    )


# ---------------------------------------------------------------------------
# whatVaries battery
# ---------------------------------------------------------------------------


def _three_angle_stimuli() -> list[dict[str, Any]]:
    """The fixture shared by three of the MATLAB unit test methods: a
    ``stimulus_presentation.stimuli``-shaped list where angle varies and
    contrast / sFrequency are constant."""
    return [
        {"parameters": {"angle": 0, "contrast": 1, "sFrequency": 0.5}},
        {"parameters": {"angle": 90, "contrast": 1, "sFrequency": 0.5}},
        {"parameters": {"angle": 180, "contrast": 1, "sFrequency": 0.5}},
    ]


def what_varies_input(name: str) -> tuple[Any, bool]:
    """Build the native input for one whatVaries case.

    Returns ``(stimuli, exclude_blank)``.  The case names mirror the method
    names of MATLAB ``tests/+ndi/+unittest/+fun/+stimulus/whatVariesTest.m``;
    see the mapping table in FUN_CASES_SCHEMA.md.

    The container choices here are not free: ``inputRendered`` is compared, so
    each case must be built in the shape whose rendering matches the MATLAB
    fixture.  ``documentPropertiesShapedStruct`` is a bare dict (MATLAB: a 1x1
    struct, which renders as a mapping) while ``poolingAcrossPresentations`` is
    a list of two (MATLAB: a 1x2 struct array, which renders as a sequence).
    """
    if name == "stimuliStructArray":
        return _three_angle_stimuli(), True

    if name == "valuesSortedAndUnique":
        return [
            {"parameters": {"angle": 180, "contrast": 1}},
            {"parameters": {"angle": 0, "contrast": 1}},
            {"parameters": {"angle": 90, "contrast": 1}},
            {"parameters": {"angle": 0, "contrast": 1}},
        ], True

    if name == "cellOfParameterStructs":
        return [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}], True

    if name == "structArrayOfParameterStructs":
        # MATLAB's cell and struct-array branches collapse onto one Python list,
        # so this case and cellOfParameterStructs are the same call here; both
        # are kept so the MATLAB side still exercises both of its branches, and
        # the shared `shape` field records which one MATLAB used.
        return [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}], True

    if name == "documentPropertiesShapedStruct":
        return {"stimulus_presentation": {"stimuli": _three_angle_stimuli()}}, True

    if name == "poolingAcrossPresentations":
        return [
            {"stimulus_presentation": {"stimuli": _three_angle_stimuli()}},
            {
                "stimulus_presentation": {
                    "stimuli": [{"parameters": {"angle": 270, "contrast": 1, "sFrequency": 0.5}}]
                }
            },
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
        return [
            {"angle": float("nan"), "contrast": 1},
            {"angle": float("nan"), "contrast": 1},
        ], True

    if name == "badInputNumeric":
        return 42, True

    if name == "badCellEntry":
        return [42], True

    raise ValueError(f"unknown whatVaries case {name!r}")


# (name, shape, mirrors, expected_status, expected_varies, expected_varies_values,
#  expected_constant, expected_constant_values, divergence_expected)
#
# The expectations are PYTHON's, measured.  MATLAB's copy of this table carries
# MATLAB's predicted expectations and differs on the two divergenceExpected
# cases.  MATLAB skips those two in its own make-side check because it cannot
# measure them; this side does not -- Python has a runtime, so all 18 are
# asserted here and the allow-list governs only the CROSS-LANGUAGE comparison.
WHAT_VARIES_DEFS: tuple[tuple[str, str, str, str, tuple, tuple, tuple, tuple, bool], ...] = (
    (
        "stimuliStructArray",
        "stimuliStructArray",
        "testStimuliStructArray + testWhatIsConstantMatchesSecondOutput",
        "ok",
        ("angle",),
        ("[0, 90, 180]",),
        ("contrast", "sFrequency"),
        ("1", "0.5"),
        False,
    ),
    (
        "valuesSortedAndUnique",
        "stimuliStructArray",
        "testValuesSortedAndUnique",
        "ok",
        ("angle",),
        ("[0, 90, 180]",),
        ("contrast",),
        ("1",),
        False,
    ),
    (
        "cellOfParameterStructs",
        "cellOfParameterStructs",
        "testCellOfParameterStructs",
        "ok",
        ("angle",),
        ("[0, 90]",),
        ("contrast",),
        ("1",),
        False,
    ),
    (
        "structArrayOfParameterStructs",
        "structArrayOfParameterStructs",
        "testStructArrayOfParameterStructs",
        "ok",
        ("angle",),
        ("[0, 90]",),
        ("contrast",),
        ("1",),
        False,
    ),
    (
        "documentPropertiesShapedStruct",
        "documentProperties",
        "testDocumentPropertiesShapedStruct",
        "ok",
        ("angle",),
        ("[0, 90, 180]",),
        ("contrast", "sFrequency"),
        ("1", "0.5"),
        False,
    ),
    (
        "poolingAcrossPresentations",
        "documentPropertiesArray",
        "testPoolingAcrossPresentations",
        "ok",
        ("angle",),
        ("[0, 90, 180, 270]",),
        ("contrast", "sFrequency"),
        ("1", "0.5"),
        False,
    ),
    (
        "fieldPresentInSomeStimuli",
        "cellOfParameterStructs",
        "testFieldPresentInSomeStimuli",
        "ok",
        ("phase",),
        ("[5]",),
        ("angle", "contrast"),
        ("0", "1"),
        False,
    ),
    (
        "blankStimuliExcludedByDefault",
        "cellOfParameterStructs",
        "testBlankStimuliExcludedByDefault",
        "ok",
        ("angle",),
        ("[0, 90]",),
        ("contrast",),
        ("1",),
        False,
    ),
    (
        "blankStimuliIncludedWhenOptionFalse",
        "cellOfParameterStructs",
        "testBlankStimuliIncludedWhenOptionFalse",
        "ok",
        ("angle", "isblank"),
        ("[0, 90]", "[1]"),
        ("contrast",),
        ("1",),
        False,
    ),
    (
        "cellValuedConstantParameter",
        "cellOfParameterStructs",
        "testCellValuedConstantParameter",
        "ok",
        ("angle",),
        ("[0, 90]",),
        ("color",),
        ("['r', 'g', 'b']",),
        True,
    ),
    (
        "vectorValuedVaryingParameter",
        "cellOfParameterStructs",
        "testVectorValuedVaryingParameter",
        "ok",
        ("rect",),
        ("[[0, 0, 100, 100], [0, 0, 200, 200]]",),
        (),
        (),
        False,
    ),
    (
        "allBlankStimuli",
        "cellOfParameterStructs",
        "testAllBlankStimuliGivesEmpty",
        "ok",
        (),
        (),
        (),
        (),
        False,
    ),
    (
        "nonNumericValues",
        "structArrayOfParameterStructs",
        "testNonNumericValuesReturnedAsCell",
        "ok",
        ("shape",),
        ("['circle', 'square']",),
        ("size",),
        ("5",),
        False,
    ),
    (
        "allConstantSingleStimulus",
        "singleParameterStruct",
        "testAllConstantSingleStimulus",
        "ok",
        (),
        (),
        ("angle", "contrast"),
        ("0", "1"),
        False,
    ),
    ("emptyInput", "emptyCell", "testEmptyInput", "ok", (), (), (), (), False),
    (
        "allNaNParameter",
        "cellOfParameterStructs",
        "none - added to pin the eqlen(NaN,NaN) divergence",
        "ok",
        (),
        (),
        ("angle", "contrast"),
        ("NaN", "1"),
        True,
    ),
    (
        "badInputNumeric",
        "badInput",
        "testBadInputErrors (first assertion)",
        "error",
        (),
        (),
        (),
        (),
        False,
    ),
    (
        "badCellEntry",
        "badInput",
        "testBadInputErrors (second assertion)",
        "error",
        (),
        (),
        (),
        (),
        False,
    ),
)


def known_divergences() -> tuple[str, ...]:
    """whatVaries cases where MATLAB main and this port are believed to disagree
    TODAY.

    Both entries trace to one line: ``local_varyingFields`` in
    ``src/ndi/+ndi/+fun/+stimulus/whatVaries.m`` compares with
    ``vlt.data.eqlen`` (which bottoms out in a bare ``==``), while
    ``local_uniqueValues`` in the same file already uses ``isequaln`` and this
    port uses ``isequaln`` semantics throughout.

    ``cellValuedConstantParameter``
        ``==`` is undefined for two cell arrays, so MATLAB is expected to ERROR
        where Python succeeds and reports ``color`` constant.
    ``allNaNParameter``
        ``eqlen(NaN, NaN)`` is false, so MATLAB is expected to report an all-NaN
        parameter as VARYING where Python reports it CONSTANT.

    Both are SOURCE-READ predictions about MATLAB, not measurements.  The first
    real run settles them: ``read_artifacts/fun/test_what_varies.py`` reports,
    for each listed case, whether the divergence actually showed up.  **A listed
    case that now agrees means the upstream fix landed** -- delete the entry here
    and clear ``divergence_expected`` in :data:`WHAT_VARIES_DEFS` (and do the same
    on the MATLAB side) so the case becomes a hard assertion again.  A stale
    allow-list is how a symmetry suite goes quietly green over the bug it exists
    to watch.
    """
    return ("cellValuedConstantParameter", "allNaNParameter")


def _param_names(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """The ``parameter`` field of every entry of a whatVaries / whatIsConstant
    result."""
    return [str(entry["parameter"]) for entry in entries]


def _rendered_list(entries: Sequence[Mapping[str, Any]], field: str) -> list[str]:
    """Render *field* of every entry as a SEQUENCE (used for whatVaries'
    ``values``, which is a list even when MATLAB collapses it to a scalar)."""
    return [render_sequence(entry[field]) for entry in entries]


def _rendered_scalar(entries: Sequence[Mapping[str, Any]], field: str) -> list[str]:
    """Render *field* of every entry as a single value (used for
    whatIsConstant's ``value``)."""
    return [render(entry[field]) for entry in entries]


def run_what_varies_cases() -> list[dict[str, Any]]:
    """Run every whatVaries case through the real ``ndi.fun.stimulus.whatVaries``
    / ``whatIsConstant``.

    EVERY case is wrapped in try/except BY DESIGN: whatVaries on current MATLAB
    main is expected to throw on at least one case (see
    :func:`known_divergences`), and an exception must be recorded as data so the
    artifact still gets written and the other side still has something to compare
    against.  The input is rendered BEFORE the call, in its own try, so an error
    case still carries a comparable ``inputRendered``.
    """
    results: list[dict[str, Any]] = []
    for definition in WHAT_VARIES_DEFS:
        name, shape, mirrors = definition[0], definition[1], definition[2]

        case: dict[str, Any] = {
            "name": name,
            "status": "ok",
            "identifier": "",
            "message": "",
            "shape": shape,
            "mirrors": mirrors,
            "excludeBlank": True,
            "inputRendered": "",
            "variesParameters": [],
            "variesValues": [],
            "constantParameters": [],
            "constantValues": [],
            "whatIsConstantRendered": "",
        }

        try:
            stimuli, exclude_blank = what_varies_input(name)
            case["excludeBlank"] = bool(exclude_blank)
            case["inputRendered"] = render(stimuli)
        except Exception as exc:  # noqa: BLE001 -- the error IS the recorded result
            case["status"] = "error"
            case["identifier"] = _error_identifier(exc)
            case["message"] = str(exc)
            results.append(case)
            continue

        try:
            varies, constant = ndi_stimulus.whatVaries(stimuli, exclude_blank=case["excludeBlank"])
            constant2 = ndi_stimulus.whatIsConstant(stimuli, exclude_blank=case["excludeBlank"])
            case["variesParameters"] = _param_names(varies)
            case["variesValues"] = _rendered_list(varies, "values")
            case["constantParameters"] = _param_names(constant)
            case["constantValues"] = _rendered_scalar(constant, "value")
            # renderSequence, not render: whatIsConstant returns a LIST of
            # {parameter, value} entries, and a one-entry result must still
            # bracket. See FUN_CASES_SCHEMA.md ambiguity note in the porting log.
            case["whatIsConstantRendered"] = render_sequence(constant2)
        except Exception as exc:  # noqa: BLE001 -- the error IS the recorded result
            case["status"] = "error"
            case["identifier"] = _error_identifier(exc)
            case["message"] = str(exc)

        results.append(case)
    return results


def verify_what_varies_expected(results: Sequence[Mapping[str, Any]]) -> list[str]:
    """Check *results* against the Python reference expectations."""
    problems: list[str] = []
    if len(results) != len(WHAT_VARIES_DEFS):
        problems.append(f"expected {len(WHAT_VARIES_DEFS)} whatVaries results, got {len(results)}")
    for index, definition in enumerate(WHAT_VARIES_DEFS):
        if index >= len(results):
            break
        (
            name,
            _shape,
            _mirrors,
            expected_status,
            expected_varies,
            expected_varies_values,
            expected_constant,
            expected_constant_values,
            _divergence,
        ) = definition
        case = results[index]
        if case["name"] != name:
            problems.append(f"whatVaries case {index} name: {case['name']!r} != {name!r}")
            continue
        if case["status"] != expected_status:
            problems.append(
                f"whatVaries case {name!r} status: {case['status']!r} != "
                f"{expected_status!r} ({case['message']})"
            )
            continue
        if expected_status != "ok":
            continue
        for field, expected in (
            ("variesParameters", expected_varies),
            ("variesValues", expected_varies_values),
            ("constantParameters", expected_constant),
            ("constantValues", expected_constant_values),
        ):
            actual = as_text_list(case[field])
            if actual != list(expected):
                problems.append(f"whatVaries case {name!r} {field}: {actual} != {list(expected)}")
    return problems


def _pairs(names: Sequence[Any], values: Sequence[Any]) -> str:
    """``name=value; name=value`` for two parallel string lists."""
    n, v = as_text_list(names), as_text_list(values)
    parts = [f"{a}={b}" for a, b in zip(n, v)]
    out = "; ".join(parts)
    if len(n) != len(v):
        out += " <<PARALLEL ARRAYS OF DIFFERENT LENGTH>>"
    return out


def what_varies_signature(case: Mapping[str, Any]) -> str:
    """The comparable content of one whatVaries case.

    ``identifier`` and ``message`` are deliberately NOT in the signature (see
    :func:`_error_identifier`).  ``excludeBlank`` and ``inputRendered`` ARE, so a
    battery that has drifted apart between the two languages is caught as a
    mismatch instead of silently comparing two different inputs.
    """
    return "|".join(
        [
            f"status={as_text(case['status'])}",
            f"excludeBlank={render(bool(case['excludeBlank']))}",
            f"input={as_text(case['inputRendered'])}",
            "varies=" + _pairs(case["variesParameters"], case["variesValues"]),
            "constant=" + _pairs(case["constantParameters"], case["constantValues"]),
            f"whatIsConstant={as_text(case['whatIsConstantRendered'])}",
        ]
    )


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def compare_maps(
    a: Mapping[str, Mapping[str, Any]],
    b: Mapping[str, Mapping[str, Any]],
    label: str,
    signature,
    allowed_divergences: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """Compare every case in *a* against *b* by rendered signature.

    Returns ``(problems, reports)``.  A case whose name is in
    *allowed_divergences* is REPORTED rather than failed; every other mismatch,
    and every case missing from *b*, is a problem.  Returning the two lists --
    rather than asserting in place -- is what lets
    ``tests/symmetry/test_fun_negative_controls.py`` prove this comparison
    actually detects a perturbation.
    """
    problems: list[str] = []
    reports: list[str] = []
    for key in sorted(a):
        if key not in b:
            problems.append(f"{label}: case {key!r} is missing from the second artifact")
            continue
        sig_a, sig_b = signature(a[key]), signature(b[key])
        if key in allowed_divergences:
            if sig_a != sig_b:
                reports.append(
                    f"{label}: case {key!r} diverges as expected.\n  A: {sig_a}\n  B: {sig_b}"
                )
            continue
        if sig_a != sig_b:
            problems.append(f"{label} mismatch for case {key!r}:\n  A: {sig_a}\n  B: {sig_b}")
    return problems, reports


def audit_known_divergences(
    a: Mapping[str, Mapping[str, Any]],
    b: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    """Audit the allow-list against what the two artifacts actually show.

    Returns ``(stale, live)``.  *stale* holds a line per listed case that now
    AGREES across the two languages -- meaning the upstream fix landed and the
    entry must be deleted; *live* holds a line per case that still diverges.
    A stale allow-list is how a symmetry suite goes quietly green over the bug it
    is supposed to be watching, so a stale entry is surfaced as a warning by the
    read side rather than left to a log nobody reads.
    """
    stale: list[str] = []
    live: list[str] = []
    for key in known_divergences():
        if key not in a or key not in b:
            live.append(
                f"knownDivergences entry {key!r} is not present in both artifacts -- "
                "the case list and the divergence list have drifted."
            )
            continue
        sig_a, sig_b = what_varies_signature(a[key]), what_varies_signature(b[key])
        if sig_a == sig_b:
            stale.append(
                f"knownDivergences entry {key!r} now AGREES across languages. "
                "DELETE THE ALLOW-LIST ENTRY: remove it from "
                "tests/symmetry/_fun_cases.known_divergences (and MATLAB's "
                "ndi.symmetry.fun.cases.knownDivergences) and clear "
                "divergence_expected in WHAT_VARIES_DEFS / whatVariesDefs so the "
                "case is asserted again."
            )
        else:
            live.append(
                f"knownDivergences entry {key!r} still diverges:\n  A: {sig_a}\n  B: {sig_b}"
            )
    return stale, live


# ---------------------------------------------------------------------------
# small shared utilities
# ---------------------------------------------------------------------------


def as_text(v: Any) -> str:
    """Normalize a decoded JSON string (which can arrive as ``null``) to a str."""
    return "" if v is None else str(v)


def as_text_list(v: Any) -> list[str]:
    """Normalize a decoded JSON string array to a list of str."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [as_text(item) for item in v]


def as_int_list(v: Any) -> list[int]:
    """Normalize a decoded JSON number array to a list of int.

    This is the ONE piece of MATLAB-shape normalization the canonical grammar
    does not remove.  ``inputCodepoints`` and ``elementLegacyDirNameCodepoints``
    are MATLAB ``double`` arrays rather than cells, so ``jsonencode`` writes a
    one-element one as a bare number (``127881``, the astralOnlyEmoji case) and
    an empty one as ``[]``.  Everything else compared by this battery is either a
    string or a cell, neither of which ``jsonencode`` collapses.
    """
    if v is None:
        return []
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [int(v)]
    return [int(item) for item in v]


def index_by_name(cases: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Map case name -> case.  Cases are joined BY NAME, never by position."""
    return {as_text(case["name"]): case for case in cases}


def envelope(
    description: str, generator: str, cases: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The common artifact envelope (FUN_CASES_SCHEMA.md section 2)."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "description": description,
        "language": "python",
        "generator": generator,
        "cases": list(cases),
    }


def write_cases(artifact_dir: Path, file_name: str, payload: Mapping[str, Any]) -> Path:
    """(Re)create *artifact_dir* and write *payload* as pretty UTF-8 JSON.

    ``allow_nan=False`` is not a precaution here, it is a proof: every compared
    value has already been rendered to a string, so a non-finite number reaching
    the encoder would mean the grammar was bypassed somewhere.
    """
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out_file = artifact_dir / file_name
    out_file.write_text(
        json.dumps(payload, indent=2, allow_nan=False, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_file


def load_cases(path: Path) -> list[Mapping[str, Any]]:
    """Read an artifact JSON and return its ``cases`` array."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if cases is None:
        return []
    if isinstance(cases, Mapping):
        # jsonencode never collapses a cell, but a hand-edited artifact might.
        return [cases]
    return list(cases)


def load_payload(path: Path) -> Mapping[str, Any]:
    """Read a whole artifact JSON (envelope included)."""
    return json.loads(path.read_text(encoding="utf-8"))


def envelope_problems(
    payload: Mapping[str, Any], expected_language: str | None = None
) -> list[str]:
    """Check the common envelope of a loaded artifact."""
    problems: list[str] = []
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        problems.append(
            f"schemaVersion is {payload.get('schemaVersion')!r}, expected {SCHEMA_VERSION}"
        )
    for field in ("description", "language", "generator"):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            problems.append(f"envelope field {field!r} is missing or not a non-empty string")
    if not isinstance(payload.get("cases"), list):
        problems.append("envelope field 'cases' is not a JSON array")
    if expected_language is not None and payload.get("language") != expected_language:
        problems.append(f"language is {payload.get('language')!r}, expected {expected_language!r}")
    return problems
