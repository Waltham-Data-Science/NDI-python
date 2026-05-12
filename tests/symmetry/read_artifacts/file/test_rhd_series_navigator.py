"""Read and verify symmetry artifacts for ndi.file.navigator.rhd_series.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+file/rhdSeriesNavigator.m

Loads rhd_series_navigator.json plus the fixture/ subdirectory written
by the make pair (in either pythonArtifacts or matlabArtifacts), re-walks
the fixture with a fresh ndi.file.navigator.rhd_series, and asserts that:

- the navigator_class field is ndi.file.navigator.rhd_series;
- the same number of epoch groups is produced;
- the same set of epoch IDs is produced;
- the lexicographically-first file in each group matches.
"""

import json
import os
import shutil

import pytest

from ndi.file.navigator.rhd_series import ndi_file_navigator_rhd_series
from ndi.session.dir import ndi_session_dir
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    return request.param


class TestRhdSeriesNavigatorReadArtifacts:
    """Mirror of ndi.symmetry.readArtifacts.file.rhdSeriesNavigator."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE
            / source_type
            / "file"
            / "rhdSeriesNavigator"
            / "testRhdSeriesNavigator"
        )

    def test_rhd_series_navigator(self, tmp_path, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )

        nav_json = artifact_dir / "rhd_series_navigator.json"
        assert nav_json.is_file(), (
            f"rhd_series_navigator.json missing in {source_type} artifact dir."
        )

        expected = json.loads(nav_json.read_text(encoding="utf-8"))
        assert expected.get("navigator_class") == "ndi.file.navigator.rhd_series", (
            f"Navigator class mismatch in {source_type}: "
            f"got {expected.get('navigator_class')!r}."
        )

        fixture_dir = artifact_dir / "fixture"
        assert fixture_dir.is_dir(), (
            f"fixture directory missing in {source_type}."
        )

        # Copy the fixture into a clean per-test session dir and re-walk
        # with a fresh navigator. This mirrors the matlab pair which
        # creates tempdir()/NDI/test_rhdSeriesNavigator_read for the same
        # purpose.
        session_path = tmp_path / "rhd_series_session_read"
        session_path.mkdir()
        for name in os.listdir(fixture_dir):
            if name.startswith("."):
                continue
            src = fixture_dir / name
            if src.is_file():
                shutil.copy2(str(src), str(session_path / name))
        session = ndi_session_dir("exp1", session_path)

        # The matlab side may have JSON-encoded a single-element cell as a
        # bare string instead of a list; coerce to list either way.
        fileparameters = expected.get("fileparameters", [])
        if isinstance(fileparameters, str):
            fileparameters = [fileparameters]
        else:
            fileparameters = list(fileparameters)

        nav = ndi_file_navigator_rhd_series(session, fileparameters)
        groups = nav.selectfilegroups_disk()

        expected_epochs = expected.get("epochs", [])
        assert len(groups) == len(expected_epochs), (
            f"Number of epoch groups mismatch in {source_type}: "
            f"actual={len(groups)} expected={len(expected_epochs)}."
        )

        actual_ids = sorted(
            nav.epochid(i + 1, files) for i, files in enumerate(groups)
        )
        expected_ids = sorted(str(e["epochid"]) for e in expected_epochs)
        assert actual_ids == expected_ids, (
            f"Epoch ids mismatch in {source_type}: "
            f"actual={actual_ids!r} expected={expected_ids!r}."
        )

        actual_firsts = sorted(os.path.basename(files[0]) for files in groups)
        expected_firsts = []
        for e in expected_epochs:
            files = e.get("files", [])
            if isinstance(files, str):
                expected_firsts.append(files)
            elif files:
                expected_firsts.append(str(files[0]))
        expected_firsts.sort()
        assert actual_firsts == expected_firsts, (
            f"Group first-file mismatch in {source_type}: "
            f"actual={actual_firsts!r} expected={expected_firsts!r}."
        )
