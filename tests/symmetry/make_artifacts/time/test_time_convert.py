"""Generate symmetry artifacts for syncgraph ``time_convert`` (time namespace).

Python side of the cross-language time/syncgraph symmetry check. Runs the shared
``tests/symmetry/_time_scenario`` battery through the real
``ndi.time.syncgraph.time_convert`` and writes the self-describing scenario plus
the computed outputs to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/time/timeConvert/
             testTimeConvertArtifacts/timeConvertCases.json

MATLAB counterpart to author (FULL closure needs the MATLAB runtime):
    tests/+ndi/+symmetry/+makeArtifacts/+time/timeConvert.m -- build the same
    SCENARIO referents, run CASES through ndi.time.syncgraph/time_convert, and
    write matlabArtifacts/time/.../timeConvertCases.json with identical out_* values.
"""

import json
import shutil

from tests.symmetry._time_scenario import CASES, SCENARIO, run_cases
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "time" / "timeConvert" / "testTimeConvertArtifacts"
ARTIFACT_FILE = ARTIFACT_DIR / "timeConvertCases.json"


class TestTimeConvert:
    """Mirror of (to-be-authored) ndi.symmetry.makeArtifacts.time.timeConvert."""

    def test_time_convert_artifacts(self):
        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

        results = run_cases()
        payload = {
            "description": "syncgraph time_convert symmetry cases",
            "scenario": SCENARIO,
            "cases": results,
        }
        ARTIFACT_FILE.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")

        # Sanity: every input case produced a recorded output row.
        assert ARTIFACT_FILE.exists()
        assert len(results) == len(CASES)
        # The conversions in this scenario all succeed (no error rows).
        assert all(r["msg"] == "" for r in results)
        # A couple of the load-bearing numbers, so a regression here is obvious.
        by = {(r["in_clock"], r["in_epoch"], r["in_time"], r["out_clock"]): r for r in results}
        assert by[("dev_local_time", "ep1", 5.0, "exp_global_time")]["out_time"] == 105.0
        assert by[("exp_global_time", None, 202.5, "exp_global_time")]["out_epoch"] == "ep2"
