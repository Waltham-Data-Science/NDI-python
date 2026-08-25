"""Shared scenario battery for the ``whatVaries`` trio symmetry pair (S3).

Both the make side (``make_artifacts/fun/test_what_varies.py``) and the read
side (``read_artifacts/fun/test_what_varies.py``) import this module, so the two
halves cannot drift; the MATLAB counterpart
(``+makeArtifacts/+fun/whatVaries.m``) builds the same scenarios from the same
case ids.

The battery mirrors the inputs of all 17 test methods of MATLAB
``ndi.unittest.fun.stimulus.whatVariesTest``, plus four scenarios that exist to
pin the divergences the port's bridge YAML already documents.

Comparison policy
-----------------
Not every scenario can be asserted equal across the two languages, and pretending
otherwise would either hide a real divergence or produce a permanently red test.
Every scenario therefore carries a ``comparison_policy``:

``strict``
    Both languages must have run the case, and their outputs must match.  A
    MATLAB artifact that omits a strict case is a failure -- silence is not
    agreement.
``expectedDivergence``
    The two languages are *known* to differ here (or MATLAB is expected to
    error outright), for a reason recorded in ``divergence_note`` and in
    ``src/ndi/fun/ndi_matlab_python_bridge.yaml``.  MATLAB may legitimately omit
    the case; if it does provide one, the read side reports what it found but
    does not require equality.

MATLAB omits a case by simply not writing a row for it, or by writing a row with
``"omitted": true`` and an ``omitted_reason``.  The read side understands both.

NaN transport
-------------
``jsonencode(...,'ConvertInfAndNaN',true)`` writes NaN as ``null`` while Python's
``json.dumps(allow_nan=True)`` writes the bare token ``NaN``, which is not
strict JSON and which MATLAB's ``jsondecode`` rejects.  Neither survives the
round trip, and ``null`` is ambiguous with an actual empty value.  So every NaN
travels as the sentinel string ``"__NaN__"`` and the artifact is written as
strict JSON (``allow_nan=False``).  This matters because two of the scenarios
exist precisely to pin NaN behaviour.
"""

from __future__ import annotations

import math
from typing import Any

import ndi.fun.stimulus as ndi_stimulus

NAN_SENTINEL = "__NaN__"

# --------------------------------------------------------------------------
# Scenario inputs
#
# Each scenario's "input" is a small spec that both languages can build the
# real argument from:
#
#   {"kind": "stimuli",            "stimuli": [params, ...]}
#       -> MATLAB: struct array with a .parameters field
#       -> Python: [{"parameters": params}, ...]
#   {"kind": "parameterList",      "parameters": [params, ...]}
#       -> MATLAB: cell array (or struct array) of parameter structs
#       -> Python: [params, ...]
#   {"kind": "documentProperties", "presentations": [[params, ...], ...]}
#       -> MATLAB: struct array of document_properties-shaped structs
#       -> Python: [{"stimulus_presentation": {"stimuli": [{"parameters": p}, ...]}}, ...]
#   {"kind": "single",             "parameters": params}
#       -> a lone parameter struct / dict
#   {"kind": "raw",                "value": <literal>}
#       -> passed straight through; used for the bad-input scenarios
# --------------------------------------------------------------------------

_THREE_ANGLES = [
    {"angle": 0, "contrast": 1, "sFrequency": 0.5},
    {"angle": 90, "contrast": 1, "sFrequency": 0.5},
    {"angle": 180, "contrast": 1, "sFrequency": 0.5},
]

_NAN = float("nan")

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "testStimuliStructArray",
        "matlab_test": "testStimuliStructArray",
        "description": "angle varies; contrast and sFrequency constant",
        "input": {"kind": "stimuli", "stimuli": _THREE_ANGLES},
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testValuesSortedAndUnique",
        "matlab_test": "testValuesSortedAndUnique",
        "description": "out-of-order values with a repeat come back sorted and deduped",
        "input": {
            "kind": "stimuli",
            "stimuli": [
                {"angle": 180, "contrast": 1},
                {"angle": 0, "contrast": 1},
                {"angle": 90, "contrast": 1},
                {"angle": 0, "contrast": 1},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testCellOfParameterStructs",
        "matlab_test": "testCellOfParameterStructs",
        "description": "a cell array of parameter structs",
        "input": {
            "kind": "parameterList",
            "parameters": [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testStructArrayOfParameterStructs",
        "matlab_test": "testStructArrayOfParameterStructs",
        "description": (
            "a struct array of parameter structs. MATLAB's cell and struct-array "
            "branches collapse onto one Python list, so this scenario and "
            "testCellOfParameterStructs are the same call in Python; both are kept "
            "so the MATLAB side still exercises both of its branches."
        ),
        "input": {
            "kind": "parameterList",
            "parameters": [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testDocumentPropertiesShapedStruct",
        "matlab_test": "testDocumentPropertiesShapedStruct",
        "description": "a document_properties-shaped struct",
        "input": {"kind": "documentProperties", "presentations": [_THREE_ANGLES]},
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testPoolingAcrossPresentations",
        "matlab_test": "testPoolingAcrossPresentations",
        "description": "two presentations are pooled into one comparison",
        "input": {
            "kind": "documentProperties",
            "presentations": [
                _THREE_ANGLES,
                [{"angle": 270, "contrast": 1, "sFrequency": 0.5}],
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testFieldPresentInSomeStimuli",
        "matlab_test": "testFieldPresentInSomeStimuli",
        "description": "a parameter present in some stimuli but not all is varying",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"angle": 0, "contrast": 1},
                {"angle": 0, "contrast": 1, "phase": 5},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testBlankStimuliExcludedByDefault",
        "matlab_test": "testBlankStimuliExcludedByDefault",
        "description": "a blank (control) stimulus is dropped before comparing",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"angle": 0, "contrast": 1},
                {"angle": 90, "contrast": 1},
                {"angle": 0, "contrast": 1, "isblank": 1},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testBlankStimuliIncludedWhenOptionFalse",
        "matlab_test": "testBlankStimuliIncludedWhenOptionFalse",
        "description": "excludeBlank=false lets the blank stimulus participate",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"angle": 0, "contrast": 1},
                {"angle": 90, "contrast": 1},
                {"angle": 0, "contrast": 1, "isblank": 1},
            ],
        },
        "exclude_blank": False,
        "comparison_policy": "strict",
    },
    {
        "id": "testCellValuedConstantParameter",
        "matlab_test": "testCellValuedConstantParameter",
        "description": "a parameter whose constant value is a cell array",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"color": ["r", "g", "b"], "angle": 0},
                {"color": ["r", "g", "b"], "angle": 90},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "expectedDivergence",
        "matlab_expected": "error",
        "divergence_note": (
            "MATLAB compares values with vlt.data.eqlen, which reduces to a bare "
            "`x==y`; `==` on two cell arrays is undefined in MATLAB, so "
            "local_varyingFields is expected to THROW whenever a cell-valued "
            "parameter appears in two or more stimuli -- the same class of failure "
            "1103b9481 fixed on the struct-assembly side but apparently not on the "
            "comparison side. Python uses a recursive isequaln-style comparison and "
            "reports 'color' as constant. This is a source-read claim (no MATLAB on "
            "the porting machine), which is exactly why the case is carried here: "
            "the MATLAB artifact settles it. See the whatVaries decision_log in "
            "src/ndi/fun/ndi_matlab_python_bridge.yaml."
        ),
    },
    {
        "id": "testVectorValuedVaryingParameter",
        "matlab_test": "testVectorValuedVaryingParameter",
        "description": "a non-scalar varying parameter keeps its distinct values whole",
        "input": {
            "kind": "parameterList",
            "parameters": [{"rect": [0, 0, 100, 100]}, {"rect": [0, 0, 200, 200]}],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testAllBlankStimuliGivesEmpty",
        "matlab_test": "testAllBlankStimuliGivesEmpty",
        "description": "every stimulus blank leaves nothing to compare",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"angle": 0, "isblank": 1},
                {"angle": 90, "isblank": 1},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testNonNumericValuesReturnedAsCell",
        "matlab_test": "testNonNumericValuesReturnedAsCell",
        "description": "string-valued varying parameter",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"shape": "circle", "size": 5},
                {"shape": "square", "size": 5},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testAllConstantSingleStimulus",
        "matlab_test": "testAllConstantSingleStimulus",
        "description": "a single stimulus: nothing can vary",
        "input": {"kind": "single", "parameters": {"angle": 0, "contrast": 1}},
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testEmptyInput",
        "matlab_test": "testEmptyInput",
        "description": "an empty input yields two empty results",
        "input": {"kind": "parameterList", "parameters": []},
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testWhatIsConstantMatchesSecondOutput",
        "matlab_test": "testWhatIsConstantMatchesSecondOutput",
        "description": (
            "whatIsConstant must equal whatVaries's second output. Every row "
            "records what_is_constant, so this holds for the whole battery; the "
            "scenario is kept for traceability to the MATLAB test method."
        ),
        "input": {"kind": "stimuli", "stimuli": _THREE_ANGLES},
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "testBadInputNumber",
        "matlab_test": "testBadInputErrors",
        "description": "a bare number is not an accepted input shape",
        "input": {"kind": "raw", "value": 42},
        "exclude_blank": True,
        "comparison_policy": "strict",
        "expected_error_identifier": "ndi:fun:stimulus:whatVaries_parameterList:badInput",
    },
    {
        "id": "testBadListEntry",
        "matlab_test": "testBadInputErrors",
        "description": "a list entry that is not a document or a parameter struct",
        "input": {"kind": "raw", "value": [42]},
        "exclude_blank": True,
        "comparison_policy": "strict",
        "expected_error_identifier": "ndi:fun:stimulus:whatVaries_parameterList:badCellEntry",
    },
    # ---- scenarios that exist to pin documented divergences -----------------
    {
        "id": "allNaNValuedParameter",
        "matlab_test": None,
        "description": "a parameter that is NaN in every stimulus",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"angle": _NAN, "contrast": 1},
                {"angle": _NAN, "contrast": 1},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "expectedDivergence",
        "matlab_expected": "angle reported as VARYING",
        "divergence_note": (
            "MATLAB's vlt.data.eqlen bottoms out in `x==y`, and NaN ~= NaN, so an "
            "all-NaN parameter is expected to report as VARYING in MATLAB. Python "
            "uses isequaln semantics (NaN equals NaN) -- matching the documented "
            "intent and matching local_uniqueValues, which already uses isequaln -- "
            "so it reports 'angle' as CONSTANT with a NaN value. The MATLAB "
            "artifact settles which behaviour upstream actually has."
        ),
    },
    {
        "id": "nanAmongVaryingValues",
        "matlab_test": None,
        "description": "repeated NaNs collapse to one and sort last",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"angle": 0},
                {"angle": _NAN},
                {"angle": 90},
                {"angle": _NAN},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "strict",
    },
    {
        "id": "singleElementVectorValues",
        "matlab_test": None,
        "description": "a one-element vector value",
        "input": {
            "kind": "parameterList",
            "parameters": [{"gain": [2]}, {"gain": [10]}],
        },
        "exclude_blank": True,
        "comparison_policy": "expectedDivergence",
        "matlab_expected": "values sorted ascending ([2 10]) via the numeric-scalar path",
        "divergence_note": (
            "MATLAB isscalar() is true for a 1x1 array, so a one-element vector "
            "takes local_uniqueValues' sorted-numeric path. In Python a "
            "one-element list/tuple/ndarray is a vector, not a scalar, so it takes "
            "the first-appearance path and the values stay wrapped. Recorded in the "
            "whatVaries decision_log; the ordering can differ even though the "
            "distinct values do not."
        ),
    },
    {
        "id": "cellValuedVaryingParameter",
        "matlab_test": None,
        "description": "a cell-valued parameter that actually varies",
        "input": {
            "kind": "parameterList",
            "parameters": [
                {"color": ["r", "g"], "angle": 0},
                {"color": ["b", "y"], "angle": 0},
            ],
        },
        "exclude_blank": True,
        "comparison_policy": "expectedDivergence",
        "matlab_expected": "error",
        "divergence_note": (
            "Same root cause as testCellValuedConstantParameter: local_varyingFields "
            "compares the two cell values with `==`. Kept separate because the "
            "varying case reaches local_uniqueValues' cell branch as well, so a "
            "MATLAB run that survives the comparison still has a second place to "
            "diverge."
        ),
    },
)


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------


def encode(value: Any) -> Any:
    """Replace NaN with :data:`NAN_SENTINEL`, recursively, for strict JSON."""
    if isinstance(value, float) and math.isnan(value):
        return NAN_SENTINEL
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value: Any) -> Any:
    """Inverse of :func:`encode`."""
    if value == NAN_SENTINEL:
        return float("nan")
    if isinstance(value, dict):
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def build_input(spec: dict[str, Any]) -> Any:
    """Build the real ``whatVaries`` argument from a scenario's input spec."""
    kind = spec["kind"]
    if kind == "stimuli":
        return [{"parameters": dict(p)} for p in spec["stimuli"]]
    if kind == "parameterList":
        return [dict(p) for p in spec["parameters"]]
    if kind == "documentProperties":
        return [
            {"stimulus_presentation": {"stimuli": [{"parameters": dict(p)} for p in presentation]}}
            for presentation in spec["presentations"]
        ]
    if kind == "single":
        return dict(spec["parameters"])
    if kind == "raw":
        return spec["value"]
    raise ValueError(f"unknown scenario input kind: {kind!r}")


def _error_identifier(exc: Exception) -> str:
    """The MATLAB error identifier the Python message is prefixed with.

    The port deliberately prefixes each message with the MATLAB identifier
    (``ndi:fun:stimulus:whatVaries_parameterList:badInput: ...``) so the parity
    is greppable from either side; this pulls it back out so the two languages
    can be compared on the identifier alone rather than on prose.
    """
    message = str(exc)
    head = message.split(": ", 1)[0]
    return head if head.startswith("ndi:") else ""


def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run one scenario, returning a JSON-ready result row."""
    row: dict[str, Any] = {
        "id": scenario["id"],
        "matlab_test": scenario.get("matlab_test"),
        "description": scenario["description"],
        "input": encode(scenario["input"]),
        "exclude_blank": scenario["exclude_blank"],
        "comparison_policy": scenario["comparison_policy"],
        "omitted": False,
    }
    for optional in ("matlab_expected", "divergence_note", "expected_error_identifier"):
        if optional in scenario:
            row[optional] = scenario[optional]

    try:
        argument = build_input(scenario["input"])
        varies, constant = ndi_stimulus.whatVaries(
            argument, exclude_blank=scenario["exclude_blank"]
        )
        what_is_constant = ndi_stimulus.whatIsConstant(
            build_input(scenario["input"]), exclude_blank=scenario["exclude_blank"]
        )
    except Exception as exc:  # noqa: BLE001 -- the error IS the recorded result
        row["error"] = True
        row["error_identifier"] = _error_identifier(exc)
        row["error_type"] = type(exc).__name__
        row["error_message"] = str(exc)
        row["varies"] = None
        row["constant"] = None
        row["what_is_constant"] = None
        return row

    row["error"] = False
    row["error_identifier"] = ""
    row["varies"] = encode(varies)
    row["constant"] = encode(constant)
    row["what_is_constant"] = encode(what_is_constant)
    return row


def run_scenarios() -> list[dict[str, Any]]:
    """Run the whole battery."""
    return [run_scenario(scenario) for scenario in SCENARIOS]
