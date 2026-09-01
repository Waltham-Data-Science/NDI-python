"""Write this language's VHSB round-trip artifacts.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+element/vhsbRoundTrip.m

Writes every case in :mod:`tests.symmetry.element.vhsb_cases` as a real
``.vhsb`` file under

    <tempdir>/NDI/symmetryTest/pythonArtifacts/element/vhsbRoundTrip/
             testVhsbArtifacts/

The MATLAB counterpart writes the same case names under ``matlabArtifacts/``.
Unlike the other batteries here, what crosses the language boundary is the
BINARY itself, not a JSON transcript of results -- the readArtifacts tests on
both sides open the other language's files. See the case module for why.

Each file is read straight back and checked before being published, so a
generator that writes something unreadable fails here rather than looking
like a cross-language divergence later.
"""

import shutil

from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.element import vhsb_cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "element" / "vhsbRoundTrip" / "testVhsbArtifacts"


class TestVhsbRoundTripMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.element.vhsbRoundTrip."""

    def test_vhsb_artifacts(self):
        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        names = vhsb_cases.write_cases(ARTIFACT_DIR)

        assert len(names) == 9, "Expected 9 recorded cases."
        for name in names:
            assert (ARTIFACT_DIR / f"{name}.vhsb").is_file(), f"{name}.vhsb not written"

        # Read each one back with this language's reader before publishing it.
        problems = []
        for name in names:
            for problem in vhsb_cases.compare(name, ARTIFACT_DIR / f"{name}.vhsb"):
                problems.append(f"{name}: {problem}")
        assert not problems, "Python could not read back what it just wrote:\n  " + "\n  ".join(
            problems
        )

        assert (ARTIFACT_DIR / vhsb_cases.INDEX_FILE).is_file()
