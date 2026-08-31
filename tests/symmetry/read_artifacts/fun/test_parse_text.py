"""Read and verify the ndi.fun.parse_text symmetry artifacts written by both languages.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+fun/parseText.m

Each check skips (not fails) when the required artifact is absent, so a run
that has not generated one yet is Incomplete rather than red -- except under
``NDI_SYMMETRY_STRICT``, where a skip becomes a failure so a gated CI stage
cannot count a check that never ran as green.

What the signature compares, and why columnTypes is in it
---------------------------------------------------------
status, the Clean option, the row count, the column NAMES, the column MATLAB
CLASSES, and the rendered column VALUES. The classes are compared because
``parseText``'s final flattening pass is where the two languages are most
likely to drift, and a values-only comparison cannot see it: a column of empty
strings becoming a logical column of False is invisible in the values once
Clean has removed the column.

Error identifiers and messages are recorded but never compared -- MATLAB
identifiers and Python exception names can never match, and pinning them would
make this a translation table instead of a behaviour check.
"""

import json

from tests.symmetry.conftest import SYMMETRY_BASE, missing_artifact
from tests.symmetry.fun import parse_text_cases

REL_PATH = ("fun", "parseText", "testParseTextArtifacts", "parseTextCases.json")


def _artifact_file(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _load(source_type: str) -> dict[str, dict]:
    f = _artifact_file(source_type)
    if not f.is_file():
        missing_artifact(f"{source_type} parseText artifact missing. Skipping.")
    return parse_text_cases.index_by_name(json.loads(f.read_text(encoding="utf-8"))["cases"])


class TestParseTextReadArtifacts:
    def test_python_artifacts_reproduce(self):
        """The recorded pythonArtifacts still match a fresh run."""
        recorded = _load("pythonArtifacts")
        fresh = parse_text_cases.index_by_name(parse_text_cases.run_cases())
        assert set(recorded) == set(fresh), "Recorded and fresh case sets differ."
        for name in sorted(recorded):
            assert parse_text_cases.signature(recorded[name]) == parse_text_cases.signature(
                fresh[name]
            ), f"parse_text changed since the artifact was written, case {name!r}."

    def test_matlab_python_symmetry(self):
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        assert set(ml) == set(py), "MATLAB and Python ran different parseText cases."
        for name in sorted(ml):
            assert parse_text_cases.signature(ml[name]) == parse_text_cases.signature(
                py[name]
            ), f"MATLAB vs Python parseText mismatch for case {name!r}."

    def test_inputs_agree(self):
        """Both sides must have started from the same rules and the same text.

        Without this the output comparison could pass while the two languages
        compared two different batteries.
        """
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        for name in sorted(set(ml) & set(py)):
            assert parse_text_cases.input_signature(ml[name]) == parse_text_cases.input_signature(
                py[name]
            ), f"Inputs differ between languages for case {name!r}."


class TestReaderSurvivesMatlabJsonShapes:
    """The comparison must survive MATLAB's jsonencode collapsing a container.

    ``jsonencode`` cannot tell a 1x1 cell from a scalar, so MATLAB writes a
    one-element list as a bare value and an empty one as ``[]``. A
    single-column case therefore arrives here with ``columnNames`` as the
    string ``"Heat"`` rather than ``["Heat"]``. That exact collapse produced
    three spurious symmetry failures on NDI-python#75 before ``as_row`` was
    added for the codepoint fields; these tests keep the same trap from being
    re-set for parseText.

    Neither test needs an artifact, so both run everywhere -- including under
    NDI_SYMMETRY_STRICT, where the artifact-dependent tests above cannot.
    """

    @staticmethod
    def _collapse(value):
        if isinstance(value, list):
            if not value:
                return []
            if len(value) == 1:
                return value[0]
        return value

    def _matlab_shaped(self):
        """The Python records, reshaped the way MATLAB would have written them."""
        import copy

        records = []
        for record in parse_text_cases.run_cases():
            shaped = copy.deepcopy(record)
            for key in ("columnNames", "columnTypes", "columnValues", "inputRendered"):
                shaped[key] = self._collapse(shaped[key])
            records.append(shaped)
        # Round-trip through JSON exactly as the artifact does.
        return json.loads(json.dumps({"cases": records}, ensure_ascii=False))["cases"]

    def test_collapsed_containers_still_compare_equal(self):
        fresh = parse_text_cases.index_by_name(parse_text_cases.run_cases())
        shaped = parse_text_cases.index_by_name(self._matlab_shaped())
        assert set(fresh) == set(shaped)
        for name in sorted(fresh):
            assert parse_text_cases.signature(shaped[name]) == parse_text_cases.signature(
                fresh[name]
            ), f"MATLAB's container collapse changed the signature for {name!r}."
            assert parse_text_cases.input_signature(
                shaped[name]
            ) == parse_text_cases.input_signature(
                fresh[name]
            ), f"MATLAB's container collapse changed the inputs for {name!r}."

    def test_the_comparison_is_not_vacuous(self):
        """A tolerant reader that compared nothing would pass the test above."""
        fresh = parse_text_cases.index_by_name(parse_text_cases.run_cases())
        shaped = parse_text_cases.index_by_name(self._matlab_shaped())

        shaped["tokenNumeric"]["columnValues"] = "[12, 8]"
        assert parse_text_cases.signature(shaped["tokenNumeric"]) != parse_text_cases.signature(
            fresh["tokenNumeric"]
        ), "A changed value must change the signature."

        shaped["logicalMatch"]["columnTypes"] = "cell"
        assert parse_text_cases.signature(shaped["logicalMatch"]) != parse_text_cases.signature(
            fresh["logicalMatch"]
        ), "A changed column CLASS must change the signature -- this is why it is compared."
