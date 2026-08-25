"""Read + verify the whatVaries / whatIsConstant symmetry artifacts (fun namespace).

Python counterpart of MATLAB
``tests/+ndi/+symmetry/+readArtifacts/+fun/whatVaries.m``.

Checks, each skipping when the required artifact is absent (and
``NDI_SYMMETRY_REQUIRE_ARTIFACTS=1`` turns every one of those skips into a
failure -- see ``tests/symmetry/conftest.py``):

* ``test_python_artifacts_reproduce`` -- re-run the battery and confirm the
  current ``whatVaries`` reproduces the recorded ``pythonArtifacts`` outputs.
  EVERY case is compared here, divergences included: the allow-list is about the
  two languages disagreeing, and Python must at least agree with itself.
* ``test_matlab_python_symmetry`` -- assert MATLAB's outputs match Python's,
  EXCEPT the cases in ``_fun_cases.known_divergences()``, which are reported
  rather than failed.
* ``test_known_divergences_are_still_real`` -- report whether each listed
  divergence actually showed up.  A listed case that now AGREES means the
  upstream fix landed and the entry must be deleted; that is surfaced as a
  warning, not buried in stdout, because a stale allow-list is exactly how a
  symmetry suite goes quietly green over the bug it is supposed to be watching.

The comparison is on the per-case SIGNATURE built by
``_fun_cases.what_varies_signature``: status, excludeBlank, the rendered input,
the varying and constant parameter/value pairs, and the whatIsConstant result.
Error identifiers and messages are recorded but never compared -- MATLAB
identifiers (``ndi:fun:stimulus:whatVaries_parameterList:badInput``) and Python
exception names can never match, so only the fact of the error is symmetric.
The rendered INPUT is in the signature so that a battery which has drifted apart
between the two languages is caught as a mismatch instead of silently comparing
two different inputs.

Run the matching ``make_artifacts`` test first to populate pythonArtifacts.
"""

import warnings

import pytest

from tests.symmetry._fun_cases import (
    audit_known_divergences,
    compare_maps,
    envelope_problems,
    index_by_name,
    known_divergences,
    load_cases,
    load_payload,
    run_what_varies_cases,
    what_varies_signature,
)
from tests.symmetry.conftest import MATLAB_ARTIFACTS, PYTHON_ARTIFACTS

_REL = "fun/whatVaries/testWhatVariesArtifacts/whatVariesCases.json"
PY_FILE = PYTHON_ARTIFACTS / _REL
ML_FILE = MATLAB_ARTIFACTS / _REL

_MAKE_HINT = "run make_artifacts/fun/test_what_varies.py first"


def _python_cases():
    if not PY_FILE.exists():
        pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
    return index_by_name(load_cases(PY_FILE))


def _matlab_cases():
    if not ML_FILE.exists():
        pytest.skip(
            f"{ML_FILE} missing — MATLAB whatVaries artifacts not generated yet "
            "(full cross-language closure needs the MATLAB runtime)"
        )
    return index_by_name(load_cases(ML_FILE))


class TestWhatVariesPythonSelfConsistency:
    """The recorded pythonArtifacts still match what the code does today."""

    def test_envelope_is_well_formed(self):
        if not PY_FILE.exists():
            pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
        problems = envelope_problems(load_payload(PY_FILE), expected_language="python")
        assert not problems, "pythonArtifacts envelope problems:\n" + "\n".join(problems)

    def test_python_artifacts_reproduce(self):
        recorded = _python_cases()
        fresh = index_by_name(run_what_varies_cases())
        assert recorded.keys() == fresh.keys(), (
            "recorded and freshly computed Python whatVaries cases differ: "
            f"recorded-only={sorted(recorded.keys() - fresh.keys())} "
            f"fresh-only={sorted(fresh.keys() - recorded.keys())}"
        )
        # No divergence allow-list here: Python must reproduce itself.
        problems, _ = compare_maps(
            recorded, fresh, "Python recorded vs fresh", what_varies_signature
        )
        assert not problems, "\n".join(problems)


class TestWhatVariesMatlabPythonSymmetry:
    """MATLAB and Python agree wherever the allow-list does not say otherwise."""

    def test_matlab_python_symmetry(self, capsys):
        py, ml = _python_cases(), _matlab_cases()
        assert py.keys() == ml.keys(), (
            "MATLAB and Python ran different whatVaries cases: "
            f"python-only={sorted(py.keys() - ml.keys())} "
            f"matlab-only={sorted(ml.keys() - py.keys())}"
        )
        problems, reports = compare_maps(
            ml, py, "MATLAB vs Python", what_varies_signature, known_divergences()
        )
        with capsys.disabled():
            for line in reports:
                print(line)
        assert not problems, "\n".join(problems)

    def test_strict_cases_cannot_be_settled_by_silence(self):
        """A case the allow-list does not cover must actually have been compared.

        ``test_matlab_python_symmetry`` iterates MATLAB's cases, so a MATLAB
        artifact that simply omitted a case would contribute no mismatch and no
        failure.  Silence is not agreement: every non-allow-listed case Python
        ran must be present on the MATLAB side too.
        """
        py, ml = _python_cases(), _matlab_cases()
        allowed = set(known_divergences())
        missing = sorted(name for name in py if name not in allowed and name not in ml)
        assert not missing, (
            "MATLAB omitted these whatVaries cases, whose policy says the two "
            "languages must agree; a case cannot be settled by silence: "
            f"{missing}"
        )

    def test_matlab_artifact_contributed_comparisons(self):
        """A MATLAB artifact that compared nothing is not a pass."""
        py, ml = _python_cases(), _matlab_cases()
        allowed = set(known_divergences())
        compared = sorted((py.keys() & ml.keys()) - allowed)
        assert compared, (
            "the MATLAB whatVaries artifact exists but supplied no asserted case "
            "that Python also ran; nothing was actually compared."
        )

    def test_known_divergences_are_still_real(self, capsys):
        """Audit the allow-list. Reports; never fails.

        A ``knownDivergences`` entry that now agrees across the two languages
        means the upstream fix (``eqlen`` -> ``isequaln`` in
        ``local_varyingFields``) has landed, and the entry -- plus the matching
        ``divergence_expected`` flag -- should be deleted so the case becomes a
        hard assertion again.  The finding is raised as a warning as well as
        printed, so it survives a CI log nobody scrolls through.
        """
        py, ml = _python_cases(), _matlab_cases()
        stale, live = audit_known_divergences(ml, py)
        with capsys.disabled():
            for line in live:
                print(line)
            for line in stale:
                print(line)
        for line in stale:
            warnings.warn(line, stacklevel=1)
