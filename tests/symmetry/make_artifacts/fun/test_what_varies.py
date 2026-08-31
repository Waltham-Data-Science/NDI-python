"""Generate the whatVaries symmetry artifact for cross-language comparison.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+fun/whatVaries.m

Runs the shared :mod:`tests.symmetry.fun.cases` battery through the real
``ndi.fun.stimulus.whatVaries`` and ``whatIsConstant`` and writes the inputs +
computed outputs to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/whatVaries/
             testWhatVariesArtifacts/whatVariesCases.json

Unlike the pathSafeName generator, this one wraps every case in try/except
**by design** and records a throwing case as ``status: "error"``. If it failed
instead, a generator that died on the already-known cell-valued case would
write no artifact at all -- costing the symmetry suite every other case's
coverage to report one bug that is already documented. The error is not
swallowed: it is recorded, and asserted against MATLAB in the readArtifacts
comparison, where the two languages can actually be held against each other.
"""

import json
import shutil

from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.fun import cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "whatVaries" / "testWhatVariesArtifacts"


class TestWhatVariesMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.fun.whatVaries."""

    def test_what_varies_artifacts(self):
        results = cases.run_what_varies_cases()

        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "schemaVersion": 1,
            "description": "ndi.fun.stimulus.whatVaries / whatIsConstant symmetry cases",
            "language": "python",
            "generator": "tests.symmetry.make_artifacts.fun.test_what_varies",
            "cases": results,
        }

        out_file = artifact_dir / "whatVariesCases.json"
        out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        assert out_file.is_file(), "Artifact file was not written."
        assert len(results) == 18, "Expected 18 recorded cases."

        # The errors are printed, not hidden -- the generator records them, but
        # a reader of the CI log should see which cases threw.
        for r in results:
            if r["status"] == "error":
                print(f"whatVaries case {r['name']}: {r['identifier']}: {r['message']}")
