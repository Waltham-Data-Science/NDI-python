"""Read and verify symmetry artifacts for ndi.cloud.profile.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+util/profile.m

Loads NDI_Cloud_Profiles.json from either pythonArtifacts (own pair) or
matlabArtifacts (cross-language) and verifies that the file describes
exactly one SymmetryTest profile with Stage='test' and no PasswordSecret.
The Profiles field is allowed to be a single dict (matlab encoding of one
struct) or a list of dicts (general case).
"""

import json

import pytest

from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    return request.param


class TestProfileReadArtifacts:
    """Mirror of ndi.symmetry.readArtifacts.util.profile."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE
            / source_type
            / "util"
            / "profile"
            / "testProfile"
        )

    def test_profile(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )

        profiles_file = artifact_dir / "NDI_Cloud_Profiles.json"
        assert profiles_file.is_file(), (
            f"NDI_Cloud_Profiles.json missing in {source_type}."
        )

        payload = json.loads(profiles_file.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), (
            f"Top-level payload should be a JSON object in {source_type}."
        )
        assert "Profiles" in payload, (
            f"Profiles field missing in {source_type}."
        )
        assert "DefaultUID" in payload, (
            f"DefaultUID field missing in {source_type}."
        )

        profiles = payload["Profiles"]
        if isinstance(profiles, dict):
            arr = [profiles]
        elif isinstance(profiles, list):
            arr = profiles
        else:
            pytest.fail(
                f"Unexpected Profiles type {type(profiles).__name__} in "
                f"{source_type}."
            )

        assert len(arr) == 1, (
            f"Expected exactly one profile entry in {source_type}, "
            f"got {len(arr)}."
        )
        p = arr[0]
        assert isinstance(p, dict), (
            f"Profile entry should be an object in {source_type}."
        )
        assert p.get("UID"), (
            f"UID missing in {source_type} profile."
        )
        assert p.get("Nickname") == "SymmetryTest", (
            f"Nickname mismatch in {source_type}."
        )
        assert p.get("Email") == "test@example.org", (
            f"Email mismatch in {source_type}."
        )
        assert p.get("Stage") == "test", (
            f"Stage should be 'test' in {source_type}."
        )
        assert "PasswordSecret" not in p, (
            f"PasswordSecret must not be persisted on disk in {source_type}."
        )
