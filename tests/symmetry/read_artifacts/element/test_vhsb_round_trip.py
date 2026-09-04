"""Read BOTH languages' VHSB files with this language's reader.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+element/vhsbRoundTrip.m

This is the cross-language check that matters for VHSB: NDI-matlab and
NDI-python both store an element's epoch as ``epoch_binary_data.vhsb``, so
each language must be able to read what the other wrote. Every other battery
here compares two JSON transcripts; this one opens the actual binaries.

The expected values are computed LOCALLY from the shared case list rather than
read out of the artifact, so no float is ever serialized to text and parsed
back. An exact equality assertion therefore means exactly what it says, and a
mismatch is a real difference in the file format rather than a formatting
artifact.
"""

import json

from tests.symmetry.conftest import SYMMETRY_BASE, missing_artifact
from tests.symmetry.element import vhsb_cases

REL_PATH = ("element", "vhsbRoundTrip", "testVhsbArtifacts")


def _artifact_dir(source_type: str):
    return SYMMETRY_BASE.joinpath(source_type, *REL_PATH)


def _require(source_type: str):
    d = _artifact_dir(source_type)
    if not (d / vhsb_cases.INDEX_FILE).is_file():
        missing_artifact(f"{source_type} VHSB artifacts missing. Skipping.")
    return d


def _check_all(source_type: str):
    """Read every case written by SOURCE_TYPE and compare against local values."""
    d = _require(source_type)
    problems = []
    for name in vhsb_cases.case_names():
        path = d / f"{name}.vhsb"
        if not path.is_file():
            problems.append(f"{name}: {source_type} wrote no {name}.vhsb")
            continue
        for problem in vhsb_cases.compare(name, path):
            problems.append(f"{name}: {problem}")
    assert (
        not problems
    ), f"Reading {source_type} VHSB files with this language's reader:\n  " + "\n  ".join(problems)


class TestVhsbRoundTripReadArtifacts:
    def test_python_artifacts_read_back(self):
        """This language reads its own files -- a cross-run regression guard."""
        _check_all("pythonArtifacts")

    def test_matlab_artifacts_read_back(self):
        """THE POINT: this language reads MATLAB's binaries.

        A failure here means the two languages do not agree on the VHSB file
        format -- header field order, sample stride, X storage, or the
        constant-interval flag -- rather than that one of them computed a
        different answer.
        """
        _check_all("matlabArtifacts")

    def test_case_sets_agree(self):
        """Both sides must have written the same cases.

        Without this, each language could read its own files happily while
        silently covering a different battery.
        """
        ml = json.loads((_require("matlabArtifacts") / vhsb_cases.INDEX_FILE).read_text())
        py = json.loads((_require("pythonArtifacts") / vhsb_cases.INDEX_FILE).read_text())
        assert sorted(ml["cases"]) == sorted(
            py["cases"]
        ), "MATLAB and Python wrote different VHSB case sets."
        assert sorted(py["cases"]) == vhsb_cases.case_names()
