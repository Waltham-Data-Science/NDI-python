"""Read and verify the whatVaries symmetry artifacts written by both languages.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+fun/whatVaries.m

``test_matlab_python_symmetry`` reports rather than fails on a case listed in
:func:`cases.known_divergences`, and fails on every other mismatch.

``test_audit_known_divergences`` is the twin of MATLAB's
``testKnownDivergencesAreStillReal``. It **fails** when a listed case starts
agreeing across languages: that means the upstream fix landed and the entry is
stale. A stale allow-list is how a symmetry suite goes quietly green over the
bug it exists to watch -- the same failure mode as a silently skipped test.
A case missing from either artifact only reports; that is list drift, which
the key-set check above already fails on.
"""

import json

from tests.symmetry.conftest import SYMMETRY_BASE, missing_artifact
from tests.symmetry.fun import cases

REL_PATH = ("fun", "whatVaries", "testWhatVariesArtifacts", "whatVariesCases.json")


def _artifact_file(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _load(source_type: str) -> dict[str, dict]:
    f = _artifact_file(source_type)
    if not f.is_file():
        missing_artifact(f"{source_type} whatVaries artifact missing. Skipping.")
    return cases.index_by_name(json.loads(f.read_text(encoding="utf-8"))["cases"])


class TestWhatVariesReadArtifacts:
    def test_python_artifacts_reproduce(self):
        recorded = _load("pythonArtifacts")
        fresh = cases.index_by_name(cases.run_what_varies_cases())
        assert set(recorded) == set(fresh), "Recorded and fresh case sets differ."
        for name in sorted(recorded):
            assert cases.what_varies_signature(recorded[name]) == cases.what_varies_signature(
                fresh[name]
            ), f"whatVaries changed since the artifact was written, case {name!r}."

    def test_matlab_python_symmetry(self):
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        assert set(ml) == set(py), "MATLAB and Python ran different whatVaries cases."
        allowed = set(cases.known_divergences())
        mismatches = []
        for name in sorted(ml):
            if cases.what_varies_signature(ml[name]) != cases.what_varies_signature(py[name]):
                if name in allowed:
                    print(f"known divergence {name!r} still diverges, as expected.")
                else:
                    mismatches.append(name)
        assert not mismatches, "MATLAB vs Python whatVaries mismatch: " + ", ".join(mismatches)

    def test_audit_known_divergences(self):
        """Fail on a stale allow-list entry. Twin of MATLAB's auditor."""
        ml = _load("matlabArtifacts")
        py = _load("pythonArtifacts")
        stale = []
        for name in cases.known_divergences():
            if name not in ml or name not in py:
                print(
                    f"knownDivergences entry {name!r} is not present in both artifacts -- "
                    "the case list and the divergence list have drifted."
                )
                continue
            if cases.what_varies_signature(ml[name]) == cases.what_varies_signature(py[name]):
                stale.append(name)
        assert not stale, (
            f"{len(stale)} knownDivergences entry/entries now agree across languages: "
            f"{', '.join(stale)}. The upstream fix has landed -- remove them from "
            "cases.known_divergences() so the cases are asserted again."
        )
