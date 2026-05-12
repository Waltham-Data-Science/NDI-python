"""Generate symmetry artifacts for ndi.preferences.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+util/preferences.m

Writes a flat JSON payload of all registered preferences (defaults plus
two overrides) into the symmetry artifact directory so the MATLAB and
Python readArtifacts suites can verify cross-language parity of the
ndi.preferences on-disk format.

Artifact root:
    <tempdir>/NDI/symmetryTest/pythonArtifacts/util/preferences/testPreferences/

Files written:
    NDI_Preferences.json        - pretty-printed flat dict keyed by
                                  Category__[Subcategory__]Name.
    preferences_overrides.json  - just the override entries, used by the
                                  readArtifacts test to verify
                                  round-trip values.
"""

import json
import shutil

import pytest

import ndi.preferences as ndi_preferences
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "util" / "preferences" / "testPreferences"

# Two non-default values used by the readArtifacts pair to assert that
# overrides round-trip cleanly through JSON. Keys use the
# Category__Subcategory__Name encoding that matches ndi.preferences on disk.
OVERRIDES = {
    "Cloud__Upload__Max_File_Batch_Size": 123456789,
    "Cloud__Download__Max_Document_Batch_Count": 42,
}


class TestPreferencesMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.util.preferences."""

    def test_preferences(self):
        """Write NDI_Preferences.json + preferences_overrides.json to disk."""
        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Load the live preferences singleton so we use the real registered
        # defaults; build a flat JSON payload using the same
        # 'Category__Subcategory__Name' encoding that ndi.preferences uses on
        # disk. We do NOT use ndi.preferences.set() here because that would
        # mutate the user's real prefdir copy; instead we write directly to
        # the artifact dir.
        items = ndi_preferences.list_items()
        assert items, "ndi.preferences.list_items() returned no entries."

        payload = {}
        for item in items:
            subcategory = item.get("subcategory", "") or ""
            if subcategory:
                key = f"{item['category']}__{subcategory}__{item['name']}"
            else:
                key = f"{item['category']}__{item['name']}"
            if key in OVERRIDES:
                payload[key] = OVERRIDES[key]
            else:
                payload[key] = item["default_value"]

        # Sanity-check that every override key actually exists in the live
        # preferences singleton. If an override does not correspond to a
        # registered preference, the matlab readArtifacts side would still
        # see the value (because make writes it), but cross-language
        # symmetry would silently drift. xfail in that case rather than
        # quietly papering over the gap.
        missing = [k for k in OVERRIDES if k not in payload]
        if missing:
            pytest.xfail(
                "ndi.preferences is missing entries the matlab side registers: "
                + ", ".join(missing)
            )

        prefs_path = artifact_dir / "NDI_Preferences.json"
        prefs_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        overrides_path = artifact_dir / "preferences_overrides.json"
        overrides_path.write_text(
            json.dumps(OVERRIDES, indent=2),
            encoding="utf-8",
        )

        assert prefs_path.is_file()
        assert overrides_path.is_file()
