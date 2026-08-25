"""Read + verify the ``whatVaries`` trio artifacts (fun namespace).

Python equivalent of (to be authored):
    tests/+ndi/+symmetry/+readArtifacts/+fun/whatVaries.m

Two layers, following the ``read_artifacts/time/test_time_convert.py``
precedent:

  * Python self-consistency: re-run the shared scenario battery and confirm the
    current ``whatVaries`` / ``whatIsConstant`` still reproduce the recorded
    ``pythonArtifacts`` outputs.
  * Cross-language symmetry: if ``matlabArtifacts/fun/.../whatVariesCases.json``
    exists, compare scenario by scenario, honouring each scenario's
    ``comparison_policy``.

Comparison policy, enforced here
--------------------------------
``strict``
    MATLAB must have run the case, must not have marked it omitted, and its
    ``varies`` / ``constant`` / ``what_is_constant`` must match Python's.
``expectedDivergence``
    MATLAB may omit the case (no row at all, or a row with ``"omitted": true``).
    If MATLAB did run it, no equality is required -- the divergence is the
    documented expectation -- but the outcome is surfaced in the test's own
    reporting so a *newly agreeing* case does not stay invisible forever.

MATLAB JSON shape
-----------------
``jsonencode`` collapses a 1x1 struct array to a bare object and a 1x1 numeric
array to a bare number, so MATLAB's ``varies`` for a single varying parameter
arrives as ``{...}`` rather than ``[{...}]`` and its ``values`` for a single
distinct value as ``5`` rather than ``[5]``.  Both are normalized before
comparison; without that every single-result scenario would report a spurious
mismatch.  Numbers are compared with a tolerance because MATLAB has only
doubles: its ``0`` and Python's ``0`` vs ``0.0`` are the same value.
"""

import json
import math

import pytest

from tests.symmetry._what_varies_scenarios import NAN_SENTINEL, run_scenarios
from tests.symmetry.conftest import MATLAB_ARTIFACTS, PYTHON_ARTIFACTS

_REL = "fun/whatVaries/testWhatVariesArtifacts/whatVariesCases.json"
PY_FILE = PYTHON_ARTIFACTS / _REL
ML_FILE = MATLAB_ARTIFACTS / _REL

_MAKE_HINT = "run make_artifacts/fun/test_what_varies.py first"

_RESULT_FIELDS = ("varies", "constant", "what_is_constant")

_TOL = 1e-9


def _index(cases):
    return {case["id"]: case for case in cases}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _as_list(value):
    """MATLAB jsonencode collapses a 1x1 struct array to a bare object."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [value]


def _numbers_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    fa, fb = float(a), float(b)
    if math.isnan(fa) or math.isnan(fb):
        return math.isnan(fa) and math.isnan(fb)
    return abs(fa - fb) <= _TOL * max(1.0, abs(fa), abs(fb))


def _values_equal(a, b):
    """Deep equality across the MATLAB/Python JSON shapes.

    ``NAN_SENTINEL`` is treated as a NaN rather than as the string it is
    transported as, so a NaN on one side and a NaN on the other compare equal
    while a NaN against a real value does not.
    """
    if a == NAN_SENTINEL or b == NAN_SENTINEL:
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _numbers_equal(a, b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(_values_equal(a[k], b[k]) for k in a)
    return a == b


def _normalized_entries(entries):
    """Normalize one ``varies`` / ``constant`` list for comparison."""
    entries = _as_list(entries)
    if entries is None:
        return None
    out = []
    for entry in entries:
        entry = dict(entry)
        if "values" in entry:
            entry["values"] = _as_list(entry["values"])
        out.append(entry)
    return out


def _entries_equal(a, b):
    a, b = _normalized_entries(a), _normalized_entries(b)
    if a is None or b is None:
        return a == b
    return _values_equal(a, b)


class TestWhatVariesPythonSelfConsistency:
    """The recorded pythonArtifacts still match what the code does today."""

    def _cases(self):
        if not PY_FILE.exists():
            pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
        return _index(_load(PY_FILE)["cases"])

    def test_scenarios_reproduce(self):
        recorded = self._cases()
        fresh = _index(run_scenarios())
        assert recorded.keys() == fresh.keys()
        for case_id, rec in recorded.items():
            new = fresh[case_id]
            assert rec["error"] == new["error"], f"case {case_id!r}: error flag changed"
            assert rec["error_identifier"] == new["error_identifier"], (
                f"case {case_id!r}: error identifier "
                f"recorded={rec['error_identifier']!r} fresh={new['error_identifier']!r}"
            )
            for field in _RESULT_FIELDS:
                assert rec[field] == new[field], (
                    f"case {case_id!r} {field}: recorded={rec[field]} fresh={new[field]}"
                )

    def test_comparison_policy_is_declared_for_every_case(self):
        """No case may reach the read side without a policy and, if divergent, a reason.

        This is the guard on the guard: an ``expectedDivergence`` label is how a
        case opts out of the equality assertion, so a case that acquired the
        label without an explanation would be a silent hole in the symmetry
        proof rather than a documented gap in it.
        """
        for case_id, case in self._cases().items():
            policy = case.get("comparison_policy")
            assert policy in ("strict", "expectedDivergence"), (
                f"case {case_id!r} has comparison_policy {policy!r}"
            )
            if policy == "expectedDivergence":
                assert case.get("divergence_note"), f"case {case_id!r} has no divergence_note"
                assert case.get("matlab_expected"), f"case {case_id!r} has no matlab_expected"


class TestWhatVariesMatlabPythonSymmetry:
    """MATLAB and Python agree wherever the policy says they must."""

    def _payloads(self):
        if not ML_FILE.exists():
            pytest.skip(
                f"{ML_FILE} missing — MATLAB whatVaries artifacts not generated yet "
                "(full cross-language closure needs the MATLAB runtime)"
            )
        if not PY_FILE.exists():
            pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
        return _index(_load(PY_FILE)["cases"]), _index(_load(ML_FILE)["cases"])

    @staticmethod
    def _matlab_omitted(row):
        return row is None or bool(row.get("omitted"))

    def test_strict_cases_agree(self):
        py, ml = self._payloads()
        strict = {
            case_id: case
            for case_id, case in py.items()
            if case["comparison_policy"] == "strict"
        }
        assert strict, "the Python artifact declared no strict cases to compare"

        missing = [
            case_id for case_id in strict if self._matlab_omitted(ml.get(case_id))
        ]
        assert not missing, (
            "MATLAB omitted these strict whatVaries cases; a case whose policy says "
            "the languages must agree cannot be settled by silence: "
            f"{sorted(missing)}"
        )

        problems = []
        for case_id, p in strict.items():
            m = ml[case_id]
            if p["error"] != m["error"]:
                problems.append(
                    f"{case_id}: error flag python={p['error']} matlab={m['error']} "
                    f"(python msg={p.get('error_message')!r}, "
                    f"matlab msg={m.get('error_message')!r})"
                )
                continue
            if p["error"]:
                if p["error_identifier"] != m["error_identifier"]:
                    problems.append(
                        f"{case_id}: error identifier python={p['error_identifier']!r} "
                        f"matlab={m['error_identifier']!r}"
                    )
                continue
            for field in _RESULT_FIELDS:
                if not _entries_equal(p[field], m[field]):
                    problems.append(
                        f"{case_id} {field}: python={p[field]} matlab={m[field]} "
                        f"({p['description']})"
                    )
        assert not problems, "whatVaries strict-case mismatches:\n" + "\n".join(problems)

    def test_divergent_cases_are_reported_not_asserted(self):
        """Surface what MATLAB did with each documented-divergence case.

        No equality is required.  What IS required is that the case is still
        declared divergent on both sides when both ran it -- a MATLAB artifact
        that quietly reclassified one of these as strict would otherwise slip
        past ``test_strict_cases_agree``, which only looks at Python's policy.
        """
        py, ml = self._payloads()
        divergent = {
            case_id: case
            for case_id, case in py.items()
            if case["comparison_policy"] == "expectedDivergence"
        }
        assert divergent, "the Python artifact declared no divergence cases"

        for case_id, p in divergent.items():
            m = ml.get(case_id)
            if self._matlab_omitted(m):
                continue
            assert m["comparison_policy"] == "expectedDivergence", (
                f"case {case_id!r} is expectedDivergence in Python but "
                f"{m['comparison_policy']!r} in MATLAB; the two sides disagree about "
                f"whether this case is allowed to differ. Python note: "
                f"{p['divergence_note']}"
            )

    def test_matlab_ran_something(self):
        """A MATLAB artifact that contributed no comparisons is not a pass."""
        py, ml = self._payloads()
        compared = [
            case_id
            for case_id, case in py.items()
            if case["comparison_policy"] == "strict" and not self._matlab_omitted(ml.get(case_id))
        ]
        assert compared, (
            "the MATLAB whatVaries artifact exists but supplied no strict case that "
            "Python also ran; nothing was actually compared."
        )
