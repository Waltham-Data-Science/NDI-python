"""Read and verify the ndi.fun.ensemble.filter symmetry artifacts written by both languages.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+fun/ensembleFilter.m

Each artifact-dependent check skips (not fails) when the required artifact is
absent, so a run that has not generated one yet is Incomplete rather than red
-- except under ``NDI_SYMMETRY_STRICT``, where a skip becomes a failure so a
gated CI stage cannot count a check that never ran as green.

What the signature compares
---------------------------
status, num_neurons, the kept ids, the kept names, the surviving activity
matrix rendered ROW BY ROW, and the surviving activity SHAPE. The shape is in
the signature deliberately: the ``nothingKeptPreservesWidth`` case is 0-by-3
in both languages by design (MATLAB's isempty guard returns early, and the
Python port reproduces the asymmetry), and a row-only comparison could not tell
0-by-3 from 0-by-1.

Error identifiers and messages are recorded but never compared -- MATLAB
identifiers and Python exception names can never match, and pinning them would
make this a translation table instead of a behaviour check.
"""

import json

from tests.symmetry.conftest import SYMMETRY_BASE, missing_artifact
from tests.symmetry.fun import ensemble_filter_cases

REL_PATH = (
    "fun",
    "ensembleFilter",
    "testEnsembleFilterArtifacts",
    "ensembleFilterCases.json",
)


def _artifact_file(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _load(source_type: str) -> dict[str, dict]:
    f = _artifact_file(source_type)
    if not f.is_file():
        missing_artifact(f"{source_type} ensembleFilter artifact missing. Skipping.")
    return ensemble_filter_cases.index_by_name(json.loads(f.read_text(encoding="utf-8"))["cases"])


class TestEnsembleFilterReadArtifacts:
    def test_python_artifacts_reproduce(self):
        """The recorded pythonArtifacts still match a fresh run."""
        recorded = _load("pythonArtifacts")
        fresh = ensemble_filter_cases.index_by_name(ensemble_filter_cases.run_cases())
        assert set(recorded) == set(fresh), "Recorded and fresh case sets differ."
        for name in sorted(recorded):
            assert ensemble_filter_cases.signature(
                recorded[name]
            ) == ensemble_filter_cases.signature(
                fresh[name]
            ), f"ensemble.filter changed since the artifact was written, case {name!r}."

    def test_matlab_python_symmetry(self):
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        assert set(ml) == set(py), "MATLAB and Python ran different ensembleFilter cases."
        for name in sorted(ml):
            assert ensemble_filter_cases.signature(ml[name]) == ensemble_filter_cases.signature(
                py[name]
            ), f"MATLAB vs Python ensemble.filter mismatch for case {name!r}."

    def test_inputs_agree(self):
        """Both sides must have started from the same ensemble and options.

        Without this the output comparison could pass while the two languages
        compared two different batteries agreeing with themselves.
        """
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        for name in sorted(set(ml) & set(py)):
            assert ensemble_filter_cases.input_signature(
                ml[name]
            ) == ensemble_filter_cases.input_signature(
                py[name]
            ), f"Inputs differ between languages for case {name!r}."


class TestReaderSurvivesMatlabJsonShapes:
    """The comparison must survive MATLAB's jsonencode collapsing a container.

    ``jsonencode`` cannot tell a 1x1 cell from a scalar, so MATLAB writes a
    one-element list as a bare value and an empty one as ``[]``. A
    single-neuron case therefore arrives here with ``neuronIdsOut`` as the
    string ``"id4"`` rather than ``["id4"]``, and every empty option field
    (most cases have several) as ``[]``. That exact collapse produced three
    spurious symmetry failures on NDI-python#75 before ``as_row`` was added
    for the codepoint fields; these tests keep the same trap from being
    re-set for ensembleFilter.

    Neither test needs an artifact, so both run everywhere -- including under
    NDI_SYMMETRY_STRICT, where the artifact-dependent tests above cannot.
    """

    _COLLAPSE_KEYS = (
        "neuronIds",
        "neuronNames",
        "activity",
        "includeNames",
        "excludeNames",
        "includeIndex",
        "excludeIndex",
        "includeIds",
        "excludeIds",
        "keepLogical",
        "keepIndex",
        "neuronIdsOut",
        "neuronNamesOut",
        "activityOut",
        "shapeOut",
    )

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
        for record in ensemble_filter_cases.run_cases():
            shaped = copy.deepcopy(record)
            for key in self._COLLAPSE_KEYS:
                if key in shaped:
                    shaped[key] = self._collapse(shaped[key])
            records.append(shaped)
        # Round-trip through JSON exactly as the artifact does.
        return json.loads(json.dumps({"cases": records}, ensure_ascii=False))["cases"]

    def test_collapsed_containers_still_compare_equal(self):
        fresh = ensemble_filter_cases.index_by_name(ensemble_filter_cases.run_cases())
        shaped = ensemble_filter_cases.index_by_name(self._matlab_shaped())
        assert set(fresh) == set(shaped)
        for name in sorted(fresh):
            assert ensemble_filter_cases.signature(shaped[name]) == ensemble_filter_cases.signature(
                fresh[name]
            ), f"MATLAB's container collapse changed the signature for {name!r}."
            assert ensemble_filter_cases.input_signature(
                shaped[name]
            ) == ensemble_filter_cases.input_signature(
                fresh[name]
            ), f"MATLAB's container collapse changed the inputs for {name!r}."

    def test_the_comparison_is_not_vacuous(self):
        """A tolerant reader that compared nothing would pass the test above."""
        fresh = ensemble_filter_cases.index_by_name(ensemble_filter_cases.run_cases())
        shaped = ensemble_filter_cases.index_by_name(self._matlab_shaped())

        shaped["includeNamesBasic"]["neuronIdsOut"] = ["id2", "id3"]
        assert ensemble_filter_cases.signature(
            shaped["includeNamesBasic"]
        ) != ensemble_filter_cases.signature(
            fresh["includeNamesBasic"]
        ), "A changed id list must change the signature."

        shaped["nothingKeptPreservesWidth"]["shapeOut"] = [0, 1]
        assert ensemble_filter_cases.signature(
            shaped["nothingKeptPreservesWidth"]
        ) != ensemble_filter_cases.signature(
            fresh["nothingKeptPreservesWidth"]
        ), "A changed shape must change the signature -- this is why it is compared."
