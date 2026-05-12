"""Generate symmetry artifacts for ndi.file.navigator.rhd_series.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+file/rhdSeriesNavigator.m

Builds two prefix groups of fake .rhd files (A_* and B_*) plus matching
_epochprobemap sidecars, runs ndi.file.navigator.rhd_series against
them, and writes::

    rhd_series_navigator.json   - navigator class, fileparameters, and
                                   per-epoch {epochid, files} entries.
    fixture/                     - copy of the on-disk .rhd / probemap
                                   files so the cross-language read side
                                   can re-walk them with a fresh navigator.

Artifact root:
    <tempdir>/NDI/symmetryTest/pythonArtifacts/file/rhdSeriesNavigator/
             testRhdSeriesNavigator/
"""

import json
import os
import shutil

import pytest

from ndi.file.navigator.rhd_series import ndi_file_navigator_rhd_series
from ndi.session.dir import ndi_session_dir
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = (
    PYTHON_ARTIFACTS
    / "file"
    / "rhdSeriesNavigator"
    / "testRhdSeriesNavigator"
)

# These patterns are identical to the matlab makeArtifacts pair so a
# matlab-written rhd_series_navigator.json round-trips cleanly. The first
# pattern groups .rhd files by their prefix (capture); the second matches
# the _epochprobemap.txt sidecar for the same prefix.
FILEPARAMETERS = [
    r"#_\d{8}_\d{6}\.rhd\>",
    r"#_\d{8}_\d{6}\._epochprobemap\.txt\>",
]

# Fake epoch fixture: two prefix groups (A, B), two .rhd files per group,
# one epochprobemap per group (matches the matlab fixture byte-for-byte).
FIXTURE_FILES = [
    "A_20260101_120000.rhd",
    "A_20260101_120500.rhd",
    "A_20260101_120000._epochprobemap.txt",
    "B_20260101_130000.rhd",
    "B_20260101_130500.rhd",
    "B_20260101_130000._epochprobemap.txt",
]


class TestRhdSeriesNavigatorMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.file.rhdSeriesNavigator."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a session dir populated with the fake .rhd fixture."""
        session_dir = tmp_path / "rhd_series_session"
        session_dir.mkdir()
        for name in FIXTURE_FILES:
            (session_dir / name).touch()
        self.session_path = session_dir
        self.session = ndi_session_dir("exp1", session_dir)

    def test_rhd_series_navigator(self):
        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Construct the navigator with the series + ancillary patterns.
        # MATLAB lookup: nav = ndi.file.navigator.rhd_series(session, fileparameters);
        nav = ndi_file_navigator_rhd_series(self.session, FILEPARAMETERS)

        groups = nav.selectfilegroups_disk()
        assert len(groups) == 2, (
            f"Expected 2 epoch groups from rhd_series navigator, got {len(groups)}."
        )

        epoch_info = []
        for i, files in enumerate(groups):
            eid = nav.epochid(i + 1, files)
            rel = [os.path.basename(f) for f in files]
            epoch_info.append({"epochid": eid, "files": rel})

        # Copy the on-disk fixture into the artifact dir so the matlab
        # readArtifacts side (and the python read side) can re-walk it.
        fixture_dir = artifact_dir / "fixture"
        fixture_dir.mkdir(exist_ok=True)
        for name in os.listdir(self.session_path):
            if name.startswith("."):
                continue
            src = self.session_path / name
            if src.is_file():
                shutil.copy2(str(src), str(fixture_dir / name))

        nav_doc = {
            "navigator_class": "ndi.file.navigator.rhd_series",
            "fileparameters": FILEPARAMETERS,
            "epochs": epoch_info,
        }
        nav_path = artifact_dir / "rhd_series_navigator.json"
        nav_path.write_text(
            json.dumps(nav_doc, indent=2, allow_nan=True),
            encoding="utf-8",
        )

        assert nav_path.is_file()
        assert fixture_dir.is_dir()
