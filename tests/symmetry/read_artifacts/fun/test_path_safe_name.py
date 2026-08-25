"""Read + verify the pathSafeName symmetry artifacts (fun namespace).

Python counterpart of MATLAB
``tests/+ndi/+symmetry/+readArtifacts/+fun/pathSafeName.m``.

Three checks, each skipping when the required artifact is absent (and
``NDI_SYMMETRY_REQUIRE_ARTIFACTS=1`` turns every one of those skips into a
failure -- see ``tests/symmetry/conftest.py``):

* ``test_python_artifacts_reproduce`` -- re-run the battery and confirm the
  current ``pathSafeName`` / ``elementDirectoryName`` reproduce the recorded
  ``pythonArtifacts`` outputs.  A cross-run regression guard, independent of
  MATLAB.
* ``test_matlab_python_symmetry`` -- assert MATLAB's sanitized names match
  Python's for the same cases.
* ``test_inputs_agree`` -- prove both languages started from the same input
  codepoints, or the output comparison means nothing.

The comparison is on the per-case SIGNATURE built by
``_fun_cases.path_safe_signature``: status, sanitized name, element directory
name, the legacy directory name as CODEPOINTS (so no JSON text-encoding
difference can masquerade as a behaviour difference), and both length counts.
Error identifiers and messages are recorded in the artifact but never compared:
MATLAB identifiers and Python exception names can never match, and pinning them
would make this a translation table instead of a behaviour check.

THE ASTRAL CASES ARE THE POINT.  MATLAB counts UTF-16 code units, so a character
above U+FFFF is a surrogate pair and sanitizes to TWO ``'-'``.  Python counts
code points.  ``inputUtf16Units`` and ``inputCodepointCount`` are both in the
signature, so if the two languages ever stop agreeing about the folder name for
an element, this test says so.

Run the matching ``make_artifacts`` test first to populate pythonArtifacts.
"""

import pytest

from tests.symmetry._fun_cases import (
    as_int_list,
    compare_maps,
    envelope_problems,
    index_by_name,
    load_cases,
    load_payload,
    path_safe_signature,
    run_path_safe_name_cases,
)
from tests.symmetry.conftest import MATLAB_ARTIFACTS, PYTHON_ARTIFACTS

_REL = "fun/pathSafeName/testPathSafeNameArtifacts/pathSafeNameCases.json"
PY_FILE = PYTHON_ARTIFACTS / _REL
ML_FILE = MATLAB_ARTIFACTS / _REL

_MAKE_HINT = "run make_artifacts/fun/test_path_safe_name.py first"


def _python_cases():
    if not PY_FILE.exists():
        pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
    return index_by_name(load_cases(PY_FILE))


def _matlab_cases():
    if not ML_FILE.exists():
        pytest.skip(
            f"{ML_FILE} missing — MATLAB pathSafeName artifacts not generated yet "
            "(full cross-language closure needs the MATLAB runtime)"
        )
    return index_by_name(load_cases(ML_FILE))


class TestPathSafeNamePythonSelfConsistency:
    """The recorded pythonArtifacts still match what the code does today."""

    def test_envelope_is_well_formed(self):
        if not PY_FILE.exists():
            pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
        problems = envelope_problems(load_payload(PY_FILE), expected_language="python")
        assert not problems, "pythonArtifacts envelope problems:\n" + "\n".join(problems)

    def test_python_artifacts_reproduce(self):
        recorded = _python_cases()
        fresh = index_by_name(run_path_safe_name_cases())
        assert recorded.keys() == fresh.keys(), (
            "recorded and freshly computed Python pathSafeName cases differ: "
            f"recorded-only={sorted(recorded.keys() - fresh.keys())} "
            f"fresh-only={sorted(fresh.keys() - recorded.keys())}"
        )
        problems, _ = compare_maps(recorded, fresh, "Python recorded vs fresh", path_safe_signature)
        assert not problems, "\n".join(problems)


class TestPathSafeNameMatlabPythonSymmetry:
    """MATLAB and Python agree, case by case."""

    def test_matlab_python_symmetry(self):
        py, ml = _python_cases(), _matlab_cases()
        assert py.keys() == ml.keys(), (
            "MATLAB and Python ran different pathSafeName cases: "
            f"python-only={sorted(py.keys() - ml.keys())} "
            f"matlab-only={sorted(ml.keys() - py.keys())}"
        )
        problems, _ = compare_maps(ml, py, "MATLAB vs Python", path_safe_signature)
        assert not problems, "\n".join(problems)

    def test_inputs_agree(self):
        """Both languages must have started from the same inputs.

        The input is specified as Unicode scalar values precisely so this check
        is exact: a transport that mangled a surrogate pair would otherwise look
        like agreement on the outputs.
        """
        py, ml = _python_cases(), _matlab_cases()
        problems = []
        for name in sorted(ml.keys() & py.keys()):
            a = as_int_list(ml[name]["inputCodepoints"])
            b = as_int_list(py[name]["inputCodepoints"])
            if a != b:
                problems.append(f"case {name!r}: matlab={a} python={b}")
        assert not problems, "input codepoints differ between languages:\n" + "\n".join(problems)

    def test_matlab_artifact_contributed_comparisons(self):
        """A MATLAB artifact that compared nothing is not a pass."""
        py, ml = _python_cases(), _matlab_cases()
        compared = sorted(py.keys() & ml.keys())
        assert compared, (
            "the MATLAB pathSafeName artifact exists but shares no case name with "
            "Python's; nothing was actually compared."
        )
