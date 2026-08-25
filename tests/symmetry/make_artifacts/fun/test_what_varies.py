"""Generate symmetry artifacts for the ``whatVaries`` trio (fun namespace).

Computation-style pair, following the ``time/test_time_convert.py`` precedent.
Runs the shared ``tests/symmetry/_what_varies_scenarios`` battery through the
real ``ndi.fun.stimulus.whatVaries`` / ``whatIsConstant`` and writes:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/whatVaries/
             testWhatVariesArtifacts/whatVariesCases.json

The battery mirrors the inputs of all 17 test methods of MATLAB
``ndi.unittest.fun.stimulus.whatVariesTest``, plus four scenarios that pin the
divergences recorded in ``src/ndi/fun/ndi_matlab_python_bridge.yaml``.  Every
row carries a ``comparison_policy`` so the read side knows which cases must
agree and which are known to differ (or to make MATLAB error outright); a
MATLAB run may omit an ``expectedDivergence`` case entirely, and the read side
understands both an absent row and an explicit ``"omitted": true`` row.

MATLAB counterpart to author (FULL closure needs the MATLAB runtime):
    tests/+ndi/+symmetry/+makeArtifacts/+fun/whatVaries.m -- build the same
    scenario ids from the same input specs, run each through
    ndi.fun.stimulus.whatVaries / whatIsConstant inside a try/catch (recording
    the error identifier where it throws), and write
    matlabArtifacts/fun/.../whatVariesCases.json with the same schema.

The JSON is strict (``allow_nan=False``): NaN travels as the sentinel
``"__NaN__"``, because ``jsonencode(...,'ConvertInfAndNaN',true)`` writes NaN
as ``null`` and Python's ``allow_nan=True`` writes the non-standard ``NaN``
token, and neither survives the round trip.
"""

import json
import shutil

from tests.symmetry._what_varies_scenarios import (
    NAN_SENTINEL,
    SCENARIOS,
    run_scenarios,
)
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "whatVaries" / "testWhatVariesArtifacts"
ARTIFACT_FILE = ARTIFACT_DIR / "whatVariesCases.json"

SCHEMA_VERSION = 1


class TestWhatVaries:
    """Mirror of (to-be-authored) ndi.symmetry.makeArtifacts.fun.whatVaries."""

    def test_what_varies_artifacts(self):
        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

        results = run_scenarios()
        payload = {
            "description": (
                "ndi.fun.stimulus.whatVaries / whatIsConstant / "
                "whatVaries_parameterList symmetry cases"
            ),
            "schemaVersion": SCHEMA_VERSION,
            "language": "python",
            "nanSentinel": NAN_SENTINEL,
            "comparisonPolicies": {
                "strict": (
                    "both languages must have run this case and their outputs must "
                    "match; a MATLAB artifact that omits it is a failure"
                ),
                "expectedDivergence": (
                    "the languages are known to differ here (see divergence_note); "
                    "MATLAB may omit the case, or supply a row with "
                    '"omitted": true and an omitted_reason'
                ),
            },
            "cases": results,
        }
        ARTIFACT_FILE.write_text(
            json.dumps(payload, indent=2, allow_nan=False),
            encoding="utf-8",
        )

        assert ARTIFACT_FILE.exists()
        assert len(results) == len(SCENARIOS)

        ids = [row["id"] for row in results]
        assert len(set(ids)) == len(ids), f"duplicate whatVaries case ids: {ids}"

        # All 17 MATLAB whatVariesTest methods are represented.
        covered = {row["matlab_test"] for row in results if row["matlab_test"]}
        assert len(covered) == 17, f"expected all 17 MATLAB test methods, covered {sorted(covered)}"

        by_id = {row["id"]: row for row in results}

        # whatIsConstant is whatVaries's second output, for every case.
        for case_id, row in by_id.items():
            assert row["what_is_constant"] == row["constant"], (
                f"case {case_id!r}: whatIsConstant disagrees with whatVaries's "
                f"second output ({row['what_is_constant']} vs {row['constant']})"
            )

        # Load-bearing values, so a regression is obvious at the producing test.
        assert by_id["testStimuliStructArray"]["varies"] == [
            {"parameter": "angle", "values": [0, 90, 180]}
        ]
        assert by_id["testValuesSortedAndUnique"]["varies"] == [
            {"parameter": "angle", "values": [0, 90, 180]}
        ]
        assert by_id["testPoolingAcrossPresentations"]["varies"] == [
            {"parameter": "angle", "values": [0, 90, 180, 270]}
        ]
        assert by_id["testAllBlankStimuliGivesEmpty"]["varies"] == []
        assert by_id["testAllBlankStimuliGivesEmpty"]["constant"] == []
        assert by_id["testEmptyInput"]["varies"] == []

        # The error cases must actually have errored, with the MATLAB identifier.
        for case_id in ("testBadInputNumber", "testBadListEntry"):
            row = by_id[case_id]
            assert row["error"] is True, f"{case_id} was expected to raise"
            assert row["error_identifier"] == row["expected_error_identifier"], (
                f"{case_id}: identifier {row['error_identifier']!r} != "
                f"{row['expected_error_identifier']!r}"
            )

        # The divergence cases must carry a policy AND an explanation -- an
        # expectedDivergence row with no note is an unexplained mismatch wearing
        # a label, and the read side would wave it through.
        divergent = [row for row in results if row["comparison_policy"] == "expectedDivergence"]
        assert divergent, "the battery must carry the documented divergence cases"
        for row in divergent:
            assert row.get("divergence_note"), f"{row['id']} has no divergence_note"
            assert row.get("matlab_expected"), f"{row['id']} has no matlab_expected"

        # NaN crossed as the sentinel, not as a bare NaN token or as null.
        raw = ARTIFACT_FILE.read_text(encoding="utf-8")
        assert NAN_SENTINEL in raw, "the NaN scenarios did not reach the artifact"

        def _reject(token):
            raise AssertionError(
                f"the artifact contains the non-standard JSON token {token!r}; "
                f"MATLAB's jsondecode rejects it. NaN must travel as "
                f"{NAN_SENTINEL!r}."
            )

        # Re-parse in strict mode: json.loads accepts NaN/Infinity by default,
        # so only a parse_constant hook proves the file is portable JSON.
        json.loads(raw, parse_constant=_reject)
        assert by_id["allNaNValuedParameter"]["constant"] == [
            {"parameter": "angle", "value": NAN_SENTINEL},
            {"parameter": "contrast", "value": 1},
        ]
        assert by_id["nanAmongVaryingValues"]["varies"] == [
            {"parameter": "angle", "values": [0, 90, NAN_SENTINEL]}
        ]
