"""Generate the ndi.fun.ensemble.filter symmetry artifact for cross-language comparison.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+fun/ensembleFilter.m

Runs the shared :mod:`tests.symmetry.fun.ensemble_filter_cases` battery through
the real ``ndi.fun.ensemble.filter`` and writes the inputs + computed outputs
to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/ensembleFilter/
             testEnsembleFilterArtifacts/ensembleFilterCases.json

The MATLAB counterpart writes the same structure under ``matlabArtifacts/``;
the readArtifacts tests on both sides compare them. The on-disk schema is
NDI-matlab's ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md``, section 10.

Like its parseText sibling, a case that RAISES is recorded as ``status:
'error'`` rather than failing the test: a generator that died on one case
would write no artifact at all and cost the suite every other case's coverage.
The error is still reported here, recorded in the artifact, and asserted
against MATLAB in the readArtifacts twin.
"""

import json
import shutil

from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.fun import ensemble_filter_cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "ensembleFilter" / "testEnsembleFilterArtifacts"


class TestEnsembleFilterMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.fun.ensembleFilter."""

    def test_ensemble_filter_artifacts(self):
        results = ensemble_filter_cases.run_cases()
        defs = ensemble_filter_cases.definitions()

        assert len(results) == len(defs), "Every definition must produce one record."

        problems = []
        for defn, record in zip(defs, results):
            ok, detail = ensemble_filter_cases.check_expected(defn, record)
            if not ok:
                problems.append(f"{record['name']}: {detail}")
        assert not problems, "ensemble.filter produced unexpected results:\n  " + "\n  ".join(
            problems
        )

        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "schemaVersion": 1,
            "description": "ndi.fun.ensemble.filter symmetry cases",
            "language": "python",
            "generator": "tests.symmetry.make_artifacts.fun.test_ensemble_filter",
            "cases": results,
        }

        out_file = artifact_dir / "ensembleFilterCases.json"
        # ensure_ascii=False for consistency with the other fun batteries;
        # this one has no non-ASCII content today, but keeping the writer
        # uniform means adding one later needs no change here.
        out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        assert out_file.is_file(), "Artifact file was not written."
        assert len(results) == 15, "Expected 15 recorded cases."
