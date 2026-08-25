"""Read + verify the ``pathSafeName`` / ``elementDirectoryName`` artifacts (fun namespace).

Python equivalent of (to be authored):
    tests/+ndi/+symmetry/+readArtifacts/+fun/pathSafeName.m

Two layers, following the ``read_artifacts/time/test_time_convert.py``
precedent:

  * Python self-consistency: re-run the shared case vector and confirm the
    current ``pathSafeName`` / ``elementDirectoryName`` still reproduce the
    recorded ``pythonArtifacts`` outputs.  A cross-run regression guard that
    needs no MATLAB.
  * Cross-language symmetry: if ``matlabArtifacts/fun/.../pathSafeNameCases.json``
    exists, assert MATLAB's outputs match Python's -- case by case, after first
    proving both languages ran the same input.  Skips until the MATLAB artifact
    exists; FULL closure needs the MATLAB runtime.

Run the matching ``make_artifacts`` test first to populate pythonArtifacts.
"""

import json

import pytest

from tests.symmetry._path_safe_name_cases import (
    run_element_directory_name_cases,
    run_path_safe_name_cases,
)
from tests.symmetry.conftest import MATLAB_ARTIFACTS, PYTHON_ARTIFACTS

_REL = "fun/pathSafeName/testPathSafeNameArtifacts/pathSafeNameCases.json"
PY_FILE = PYTHON_ARTIFACTS / _REL
ML_FILE = MATLAB_ARTIFACTS / _REL

_MAKE_HINT = "run make_artifacts/fun/test_path_safe_name.py first"


def _index(rows):
    return {row["id"]: row for row in rows}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_same_input(case_id, a, b, a_label, b_label):
    """Prove both sides ran the same input before comparing their outputs.

    UTF-16 code units are the comparison unit because that is the unit
    ``pathSafeName`` counts -- a non-BMP character is one Python code point but
    two MATLAB ``char`` elements, and the whole point of the astral cases is
    that both languages emit two ``'-'`` for it.  Comparing the decoded strings
    alone would let a transport that mangled a surrogate pair look like
    agreement.
    """
    assert a["input_utf16"] == b["input_utf16"], (
        f"case {case_id!r}: {a_label} and {b_label} ran different inputs.\n"
        f"  {a_label}: utf16={a['input_utf16']} str={a['input']!r}\n"
        f"  {b_label}: utf16={b['input_utf16']} str={b['input']!r}"
    )


class TestPathSafeNamePythonSelfConsistency:
    """The recorded pythonArtifacts still match what the code does today."""

    def _payload(self):
        if not PY_FILE.exists():
            pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
        return _load(PY_FILE)

    def test_path_safe_name_reproduces(self):
        recorded = _index(self._payload()["pathSafeName"])
        fresh = _index(run_path_safe_name_cases())
        assert recorded.keys() == fresh.keys()
        for case_id, rec in recorded.items():
            new = fresh[case_id]
            _assert_same_input(case_id, rec, new, "recorded", "fresh")
            assert rec["output"] == new["output"], (
                f"case {case_id!r}: recorded={rec['output']!r} "
                f"fresh={new['output']!r}"
            )

    def test_element_directory_name_reproduces(self):
        recorded = _index(self._payload()["elementDirectoryName"])
        fresh = _index(run_element_directory_name_cases())
        assert recorded.keys() == fresh.keys()
        for case_id, rec in recorded.items():
            new = fresh[case_id]
            _assert_same_input(case_id, rec, new, "recorded", "fresh")
            for field in ("dir_name", "legacy_dir_name"):
                assert rec[field] == new[field], (
                    f"case {case_id!r} {field}: recorded={rec[field]!r} "
                    f"fresh={new[field]!r}"
                )


class TestPathSafeNameMatlabPythonSymmetry:
    """MATLAB and Python agree, case by case."""

    def _payloads(self):
        if not ML_FILE.exists():
            pytest.skip(
                f"{ML_FILE} missing — MATLAB pathSafeName artifacts not generated "
                "yet (full cross-language closure needs the MATLAB runtime)"
            )
        if not PY_FILE.exists():
            pytest.skip(f"{PY_FILE} missing — {_MAKE_HINT}")
        return _load(PY_FILE), _load(ML_FILE)

    def test_path_safe_name_symmetry(self):
        py, ml = self._payloads()
        py_rows, ml_rows = _index(py["pathSafeName"]), _index(ml["pathSafeName"])
        assert py_rows.keys() == ml_rows.keys(), (
            "MATLAB and Python ran different pathSafeName cases: "
            f"python-only={sorted(py_rows.keys() - ml_rows.keys())} "
            f"matlab-only={sorted(ml_rows.keys() - py_rows.keys())}"
        )
        for case_id, p in py_rows.items():
            m = ml_rows[case_id]
            _assert_same_input(case_id, p, m, "python", "matlab")
            assert p["output"] == m["output"], (
                f"pathSafeName({p['input']!r}) [{case_id}]: "
                f"python={p['output']!r} matlab={m['output']!r} — {p['note']}"
            )

    def test_element_directory_name_symmetry(self):
        py, ml = self._payloads()
        py_rows = _index(py["elementDirectoryName"])
        ml_rows = _index(ml["elementDirectoryName"])
        assert py_rows.keys() == ml_rows.keys(), (
            "MATLAB and Python ran different elementDirectoryName cases: "
            f"python-only={sorted(py_rows.keys() - ml_rows.keys())} "
            f"matlab-only={sorted(ml_rows.keys() - py_rows.keys())}"
        )
        for case_id, p in py_rows.items():
            m = ml_rows[case_id]
            _assert_same_input(case_id, p, m, "python", "matlab")
            for field in ("dir_name", "legacy_dir_name"):
                assert p[field] == m[field], (
                    f"elementDirectoryName({p['input']!r}) [{case_id}] {field}: "
                    f"python={p[field]!r} matlab={m[field]!r} — {p['note']}"
                )
