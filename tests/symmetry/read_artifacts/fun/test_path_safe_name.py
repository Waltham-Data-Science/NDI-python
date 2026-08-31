"""Read and verify the pathSafeName symmetry artifacts written by both languages.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+fun/pathSafeName.m

Each check skips (not fails) when the required artifact is absent, so a run
that has not generated one yet is Incomplete rather than red.

The comparison is on the per-case signature: status, sanitized name, element
directory name, the legacy directory name as CODEPOINTS, and both length
counts. Error identifiers and messages are recorded but never compared --
MATLAB identifiers and Python exception names can never match, and pinning
them would make this a translation table instead of a behaviour check.

Both codepoint fields go through ``cases.as_row`` before comparison: MATLAB's
``jsonencode`` writes a one-element numeric array as a bare number, so a
single-codepoint case such as ``astralOnlyEmoji`` arrives here as ``129417``
rather than ``[129417]``. See ``as_row`` for why both readers need this.
"""

import json

from tests.symmetry.conftest import SYMMETRY_BASE, missing_artifact
from tests.symmetry.fun import cases

REL_PATH = ("fun", "pathSafeName", "testPathSafeNameArtifacts", "pathSafeNameCases.json")


def _artifact_file(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _load(source_type: str) -> dict[str, dict]:
    f = _artifact_file(source_type)
    if not f.is_file():
        missing_artifact(f"{source_type} pathSafeName artifact missing. Skipping.")
    return cases.index_by_name(json.loads(f.read_text(encoding="utf-8"))["cases"])


class TestPathSafeNameReadArtifacts:
    def test_python_artifacts_reproduce(self):
        """The recorded pythonArtifacts still match a fresh run."""
        recorded = _load("pythonArtifacts")
        fresh = cases.index_by_name(cases.run_path_safe_name_cases())
        assert set(recorded) == set(fresh), "Recorded and fresh case sets differ."
        for name in sorted(recorded):
            assert cases.path_safe_signature(recorded[name]) == cases.path_safe_signature(
                fresh[name]
            ), f"pathSafeName changed since the artifact was written, case {name!r}."

    def test_matlab_python_symmetry(self):
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        assert set(ml) == set(py), "MATLAB and Python ran different pathSafeName cases."
        for name in sorted(ml):
            assert cases.path_safe_signature(ml[name]) == cases.path_safe_signature(
                py[name]
            ), f"MATLAB vs Python pathSafeName mismatch for case {name!r}."

    def test_inputs_agree(self):
        """Both sides must have started from the same characters.

        The input is specified as Unicode scalar values precisely so this can
        be exact -- without it, the output comparison could pass while the two
        languages compared different inputs.
        """
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        for name in sorted(set(ml) & set(py)):
            assert cases.as_row(ml[name]["inputCodepoints"]) == cases.as_row(
                py[name]["inputCodepoints"]
            ), f"Input codepoints differ between languages for case {name!r}."
