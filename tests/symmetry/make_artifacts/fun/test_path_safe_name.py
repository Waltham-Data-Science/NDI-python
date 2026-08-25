"""Generate the pathSafeName symmetry artifact (fun namespace).

Python counterpart of MATLAB
``tests/+ndi/+symmetry/+makeArtifacts/+fun/pathSafeName.m``.  Runs the shared
``tests/symmetry/_fun_cases`` battery through the real
``ndi.fun.file.pathSafeName`` and ``ndi.fun.file.elementDirectoryName`` and
writes::

    <tempdir>/NDI/symmetryTest/pythonArtifacts/fun/pathSafeName/
             testPathSafeNameArtifacts/pathSafeNameCases.json

The MATLAB counterpart writes the same structure under ``matlabArtifacts/``; the
readArtifacts tests on both sides compare them.  The on-disk schema is
``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md`` in NDI-matlab.  The ``pathSafeName``
/ ``testPathSafeNameArtifacts`` path segments are MATLAB-style on both sides by
design (schema section 1), matching the existing ``session/buildSession/
testBuildSessionArtifacts`` precedent.

Like its MATLAB sibling, this test ASSERTS that every case produces the expected
reference output before writing the artifact: every branch of ``pathSafeName`` is
deterministic and fully readable, so a regression must fail here loudly rather
than be quietly recorded and shipped to the other language as the new truth.
That follows ``makeArtifacts/time/timeConvert``, whose earlier ``assumeTrue``
skip silently masked a real ``time_convert`` bug.

WHY THE BATTERY CARRIES ASTRAL (above U+FFFF) CASES
MATLAB ``char`` arrays hold UTF-16 code units, so one astral character is a
surrogate PAIR and ``pathSafeName`` emits TWO ``'-'`` for it; a naive Python port
emits one.  For a FILENAME contract that divergence means the two languages
disagree about which folder an element's data lives in -- exactly the class of
bug ``pathSafeName`` was added to fix.  Each case records both counts
(``inputUtf16Units`` and ``inputCodepointCount``) so the artifact shows the
difference even when the sanitized names agree.
"""

import json

from tests.symmetry._fun_cases import (
    PATH_SAFE_NAME_DEFS,
    envelope,
    index_by_name,
    run_path_safe_name_cases,
    verify_path_safe_name_expected,
    write_cases,
)
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "fun" / "pathSafeName" / "testPathSafeNameArtifacts"
ARTIFACT_FILE = ARTIFACT_DIR / "pathSafeNameCases.json"

DESCRIPTION = "ndi.fun.file.pathSafeName / elementDirectoryName symmetry cases"
GENERATOR = "tests.symmetry.make_artifacts.fun.test_path_safe_name"


def generate() -> list:
    """Run the battery, verify it, and write the artifact.

    A function rather than a fixture so each test in this file stands alone: the
    two tests below must not depend on having been run in a particular order, or
    in the same process.
    """
    results = run_path_safe_name_cases()

    # Python is a reference side too: assert every case ran and produced the
    # expected value BEFORE the artifact is written.
    problems = verify_path_safe_name_expected(results)
    assert not problems, "pathSafeName reference mismatches:\n" + "\n".join(problems)

    write_cases(ARTIFACT_DIR, ARTIFACT_FILE.name, envelope(DESCRIPTION, GENERATOR, results))
    return results


class TestPathSafeName:
    """Mirror of ndi.symmetry.makeArtifacts.fun.pathSafeName."""

    def test_path_safe_name_artifacts(self):
        results = generate()

        assert ARTIFACT_FILE.exists()
        assert len(results) == 22, f"expected 22 recorded cases, got {len(results)}"

        # Cases are joined BY NAME across languages, so the names must be unique.
        names = [case["name"] for case in results]
        assert len(set(names)) == len(names), f"duplicate pathSafeName case names: {names}"
        assert names == [d[0] for d in PATH_SAFE_NAME_DEFS]

    def test_artifact_reparses_as_strict_json(self):
        """The written file must be readable by MATLAB's ``jsondecode``.

        Two things are checked, because writing succeeding proves neither:

        * strict JSON -- ``json.loads`` accepts the non-standard ``NaN`` /
          ``Infinity`` tokens by default, so only a ``parse_constant`` hook
          proves the file is portable.  Under the canonical grammar nothing
          non-finite should ever reach the encoder (``NaN`` is the *string*
          ``'NaN'``), so a hit here means the grammar was bypassed.
        * the envelope and every case field the schema requires survived the
          round trip, with every field present on every case.
        """
        generate()
        raw = ARTIFACT_FILE.read_text(encoding="utf-8")

        def _reject(token):
            raise AssertionError(
                f"the artifact contains the non-standard JSON token {token!r}; "
                "MATLAB's jsondecode rejects it, and under the canonical grammar "
                "no non-finite number should ever reach the encoder."
            )

        payload = json.loads(raw, parse_constant=_reject)

        assert payload["schemaVersion"] == 1
        assert payload["language"] == "python"
        assert payload["description"] == DESCRIPTION
        assert payload["generator"] == GENERATOR
        assert isinstance(payload["cases"], list)

        required = (
            "name",
            "status",
            "identifier",
            "message",
            "note",
            "input",
            "inputCodepoints",
            "inputUtf16Units",
            "inputCodepointCount",
            "pathSafeName",
            "elementDirName",
            "elementLegacyDirName",
            "elementLegacyDirNameCodepoints",
        )
        for case in payload["cases"]:
            missing = [field for field in required if field not in case]
            assert not missing, f"case {case.get('name')!r} is missing fields {missing}"

        # The astral cases are the point: they must have survived the encode.
        by_name = index_by_name(payload["cases"])
        assert by_name["astralUnicodeEmoji"]["inputCodepoints"] == [97, 128512, 98]
        assert by_name["astralUnicodeEmoji"]["inputUtf16Units"] == 4
        assert by_name["astralUnicodeEmoji"]["inputCodepointCount"] == 3
        assert by_name["astralUnicodeEmoji"]["pathSafeName"] == "a--b"
