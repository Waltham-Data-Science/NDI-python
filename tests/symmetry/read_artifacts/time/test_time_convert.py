"""Read and verify the time_convert symmetry artifacts written by both languages.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+time/timeConvert.m

Two checks, each skipping (not failing) when the required artifact is absent:

  * ``test_artifacts_reproduce`` - re-run the scenario with the current Python
    ``time_convert`` and confirm it reproduces the recorded outputs for the given
    source (a regression guard for ``pythonArtifacts``; a cross-language
    symmetry assertion for ``matlabArtifacts``).
  * ``test_matlab_python_symmetry`` - assert MATLAB's recorded ``out_*`` values
    match Python's ``pythonArtifacts`` for the same cases.

MATLAB is the symmetry reference; Python must match it.
"""

import json
import math

import pytest

from tests.symmetry import _time_scenario as scenario
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE, missing_artifact

REL_PATH = ("time", "timeConvert", "testTimeConvertArtifacts", "timeConvertCases.json")


def _artifact_file(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _norm_txt(v) -> str:
    """Collapse empty/null text (None, "", missing) to a single token.

    Mirrors the MATLAB ``txt`` helper so an empty msg/epoch compares equal
    regardless of how each language rendered it across the JSON round-trip.
    """
    if v is None:
        return "<null>"
    s = str(v)
    return "<null>" if s == "" else s


def _num_val(v) -> float:
    """Coerce a recorded out_time (number or null) to float, null -> NaN."""
    if v is None:
        return math.nan
    return float(v)


def _case_key(c: dict) -> str:
    """Build the order-independent comparison key for a case (matches MATLAB)."""
    return "|".join(
        [
            _norm_txt(c.get("in_ref")),
            _norm_txt(c.get("in_clock")),
            _norm_txt(c.get("in_epoch")),
            f"{float(c['in_time']):.9g}",
            _norm_txt(c.get("out_ref")),
            _norm_txt(c.get("out_clock")),
        ]
    )


def _load_cases(file) -> dict:
    """Load a timeConvertCases.json into a map of caseKey -> case dict."""
    payload = json.loads(file.read_text(encoding="utf-8"))
    return {_case_key(c): c for c in payload["cases"]}


def _index_cases(results: list) -> dict:
    return {_case_key(c): c for c in results}


def _compare_maps(a: dict, b: dict, label: str) -> None:
    assert sorted(a.keys()) == sorted(b.keys()), f"{label}: case sets differ."
    for key, ca in a.items():
        cb = b[key]
        ta, tb = _num_val(ca.get("out_time")), _num_val(cb.get("out_time"))
        if math.isnan(ta) or math.isnan(tb):
            assert math.isnan(ta) and math.isnan(tb), f"{label} out_time null mismatch for {key}"
        else:
            assert abs(ta - tb) < 1e-6, f"{label} out_time mismatch for {key}"
        assert _norm_txt(ca.get("out_epoch")) == _norm_txt(
            cb.get("out_epoch")
        ), f"{label} out_epoch mismatch for {key}"
        assert _norm_txt(ca.get("msg")) == _norm_txt(
            cb.get("msg")
        ), f"{label} msg mismatch for {key}"


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestTimeConvertReadArtifacts:
    """Mirror of ndi.symmetry.readArtifacts.time.timeConvert."""

    def test_artifacts_reproduce(self, source_type):
        artifact_file = _artifact_file(source_type)
        if not artifact_file.is_file():
            missing_artifact(
                f"{source_type} time_convert artifact missing. "
                f"Run the corresponding makeArtifacts suite first."
            )

        recorded = _load_cases(artifact_file)
        fresh = _index_cases(scenario.run_cases())
        _compare_maps(recorded, fresh, f"{source_type} recorded vs fresh Python")

    def test_matlab_python_symmetry(self):
        ml_file = _artifact_file("matlabArtifacts")
        py_file = _artifact_file("pythonArtifacts")
        if not ml_file.is_file():
            missing_artifact("matlabArtifacts time_convert artifact missing.")
        if not py_file.is_file():
            missing_artifact("pythonArtifacts time_convert artifact missing.")

        ml = _load_cases(ml_file)
        py = _load_cases(py_file)
        _compare_maps(ml, py, "MATLAB vs Python")
