"""Generate the time_convert symmetry artifact for cross-language comparison.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+time/timeConvert.m

Runs the shared :mod:`tests.symmetry._time_scenario` battery through the real
``ndi.time.syncgraph.time_convert`` and writes the scenario + computed outputs
to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/time/timeConvert/
             testTimeConvertArtifacts/timeConvertCases.json

The MATLAB counterpart writes the same structure under ``matlabArtifacts/``;
the readArtifacts tests on both sides compare them.

MATLAB is the symmetry reference: this test ASSERTS that every scenario case
converts without error and equals the expected reference output
(:func:`tests.symmetry._time_scenario.expected`) before writing the artifact, so
a time_convert regression fails here loudly rather than silently writing a
divergent artifact.
"""

import json
import shutil

from tests.symmetry import _time_scenario as scenario
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "time" / "timeConvert" / "testTimeConvertArtifacts"


class TestTimeConvertMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.time.timeConvert."""

    def test_time_convert_artifacts(self):
        results = scenario.run_cases()

        # MATLAB is the reference: assert every case converted without error AND
        # produced the expected (reference) value before writing the artifact.
        msgs = [r["msg"] for r in results if r["msg"]]
        assert not msgs, "time_convert produced error rows: " + "; ".join(msgs)
        scenario.verify_expected(results)

        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "description": "syncgraph time_convert symmetry cases",
            "scenario": scenario.SCENARIO,
            "cases": results,
        }

        out_file = artifact_dir / "timeConvertCases.json"
        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        assert out_file.is_file(), "Artifact file was not written."
        assert len(results) == 7, "Expected 7 recorded cases."
