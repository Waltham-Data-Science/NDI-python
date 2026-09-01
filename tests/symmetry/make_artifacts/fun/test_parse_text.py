"""Generate the ndi.fun.parse_text symmetry artifact for cross-language comparison.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+fun/parseText.m

Runs the shared :mod:`tests.symmetry.fun.parse_text_cases` battery through the
real ``ndi.fun.parse_text`` and writes the inputs + computed outputs to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/parseText/
             testParseTextArtifacts/parseTextCases.json

The MATLAB counterpart writes the same structure under ``matlabArtifacts/``;
the readArtifacts tests on both sides compare them. The on-disk schema is
NDI-matlab's ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md``, section 9.

Like its whatVaries sibling and unlike pathSafeName, a case that RAISES is
recorded as ``status: 'error'`` rather than failing the test: a generator that
died on one case would write no artifact at all and cost the suite every other
case's coverage. The error is still reported here, recorded in the artifact,
and asserted against MATLAB in the readArtifacts twin.
"""

import json
import shutil

from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.fun import parse_text_cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "parseText" / "testParseTextArtifacts"


class TestParseTextMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.fun.parseText."""

    def test_parse_text_artifacts(self):
        results = parse_text_cases.run_cases()
        defs = parse_text_cases.definitions()

        assert len(results) == len(defs), "Every definition must produce one record."

        problems = []
        for defn, record in zip(defs, results):
            ok, detail = parse_text_cases.check_expected(defn, record)
            if not ok:
                problems.append(f"{record['name']}: {detail}")
        assert not problems, "parse_text produced unexpected tables:\n  " + "\n  ".join(problems)

        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "schemaVersion": 1,
            "description": "ndi.fun.parseText symmetry cases",
            "language": "python",
            "generator": "tests.symmetry.make_artifacts.fun.test_parse_text",
            "cases": results,
        }

        out_file = artifact_dir / "parseTextCases.json"
        # ensure_ascii=False: unicodeToken carries characters above U+007F, and
        # raw UTF-8 is what both sides emit in practice.
        out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        assert out_file.is_file(), "Artifact file was not written."
        assert len(results) == 18, "Expected 18 recorded cases."
