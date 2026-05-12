"""Read and verify symmetry artifacts for ndi.preferences.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+util/preferences.m

Loads NDI_Preferences.json and preferences_overrides.json from either the
pythonArtifacts root (own pair) or the matlabArtifacts root (cross-language)
and asserts:

- every key in the JSON file matches the Category__[Subcategory__]Name
  encoding;
- every override key from preferences_overrides.json is present in
  NDI_Preferences.json with the same value;
- every registered ndi.preferences default key has a corresponding entry
  in the JSON payload (sanity check that the make side wrote a complete
  snapshot of the singleton).
"""

import json

import pytest

import ndi.preferences as ndi_preferences
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestPreferencesReadArtifacts:
    """Mirror of ndi.symmetry.readArtifacts.util.preferences."""

    def _artifact_dir(self, source_type: str):
        return SYMMETRY_BASE / source_type / "util" / "preferences" / "testPreferences"

    def test_preferences(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )

        prefs_path = artifact_dir / "NDI_Preferences.json"
        assert prefs_path.is_file(), f"NDI_Preferences.json missing in {source_type}."

        payload = json.loads(prefs_path.read_text(encoding="utf-8"))
        assert isinstance(
            payload, dict
        ), f"NDI_Preferences.json in {source_type} did not decode to a dict."
        assert payload, f"No preference keys in {source_type}."

        # Every key must use the Category__[Subcategory__]Name encoding
        # (2 or 3 components when split on '__').
        for key in payload:
            parts = key.split("__")
            assert len(parts) in (2, 3), (
                f"Preference key {key!r} does not match "
                f"Category__[Subcategory__]Name in {source_type}."
            )

        # Load override metadata and verify round-trip values
        overrides_path = artifact_dir / "preferences_overrides.json"
        if overrides_path.is_file():
            overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
            assert isinstance(overrides, dict)
            for okey, oval in overrides.items():
                assert okey in payload, f"Override key {okey} missing from prefs in {source_type}."
                assert payload[okey] == oval, (
                    f"Override value mismatch for {okey} in {source_type}: "
                    f"expected {oval!r}, got {payload[okey]!r}."
                )

        # The live ndi.preferences defaults should all appear in the file.
        # This is the symmetry check: if the matlab side writes a key the
        # python side does not register (or vice versa), we want a clear
        # signal. Missing-on-python keys are tolerated by recording them
        # via pytest's verbose output, since the make-side may have been
        # written by a different language with a richer preference set.
        items = ndi_preferences.list_items()
        for item in items:
            subcategory = item.get("subcategory", "") or ""
            if subcategory:
                key = f"{item['category']}__{subcategory}__{item['name']}"
            else:
                key = f"{item['category']}__{item['name']}"
            assert key in payload, (
                f"Python-registered preference {key!r} missing from " f"{source_type} payload."
            )
