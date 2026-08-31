"""Generate the pathSafeName symmetry artifact for cross-language comparison.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+fun/pathSafeName.m

Runs the shared :mod:`tests.symmetry.fun.cases` battery through the real
``ndi.fun.file.pathSafeName`` and ``elementDirectoryName`` and writes the
inputs + computed outputs to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/pathSafeName/
             testPathSafeNameArtifacts/pathSafeNameCases.json

The MATLAB counterpart writes the same structure under ``matlabArtifacts/``;
the readArtifacts tests on both sides compare them. The on-disk schema is
NDI-matlab's ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md``.

MATLAB is the reference side for ``pathSafeName``, but the expectations are
identical, so this asserts every case before writing: a regression fails here
loudly rather than being quietly recorded and shipped as the new truth.
"""

import json
import shutil

from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.fun import cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "pathSafeName" / "testPathSafeNameArtifacts"


class TestPathSafeNameMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.fun.pathSafeName."""

    def test_path_safe_name_artifacts(self):
        results = cases.run_path_safe_name_cases()

        problems = cases.verify_path_safe_name_expected(results)
        assert not problems, "pathSafeName produced unexpected results:\n  " + "\n  ".join(problems)

        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "schemaVersion": 1,
            "description": "ndi.fun.file.pathSafeName / elementDirectoryName symmetry cases",
            "language": "python",
            "generator": "tests.symmetry.make_artifacts.fun.test_path_safe_name",
            "cases": results,
        }

        out_file = artifact_dir / "pathSafeNameCases.json"
        # ensure_ascii=False: the astral cases carry characters above U+00FF,
        # and the schema's comparison is on codepoints either way, but raw
        # UTF-8 is what both sides emit in practice.
        out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        assert out_file.is_file(), "Artifact file was not written."
        assert len(results) == 22, "Expected 22 recorded cases."
