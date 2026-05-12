"""Generate symmetry artifacts for ndi.cloud.profile.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+util/profile.m

Uses the in-memory backend so no AES file or OS keyring secret is ever
persisted. Writes a NDI_Cloud_Profiles.json file containing exactly one
profile with::

    Nickname = 'SymmetryTest'
    Email    = 'test@example.org'
    Stage    = 'test'      (forced; ndi.cloud.profile.set_stage only
                            accepts 'prod'/'dev', so we mutate the entry
                            in memory to satisfy the contract)

PasswordSecret is stripped before persisting; no secret leaves the process.
Artifact root:
    <tempdir>/NDI/symmetryTest/pythonArtifacts/util/profile/testProfile/
"""

import json
import shutil
from dataclasses import asdict

import pytest

import ndi.cloud.profile as ndi_profile
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "util" / "profile" / "testProfile"


class TestProfileMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.util.profile."""

    def test_profile(self):
        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Use the in-memory backend so no AES file or keyring secret is
        # persisted. Reset the singleton state so we start clean.
        ndi_profile.use_backend("memory")
        ndi_profile.reset()

        uid = ndi_profile.add("SymmetryTest", "test@example.org", "not-a-real-secret")
        ndi_profile.set_stage(uid, "dev")
        ndi_profile.set_stage(uid, "prod")

        # Per spec, Stage='test' is required even though set_stage only
        # accepts 'prod'/'dev'. Mutate the in-memory profile directly to
        # satisfy the symmetry contract.
        entry = ndi_profile.get(uid)
        entry_dict = asdict(entry)
        entry_dict["Stage"] = "test"
        # Do NOT persist PasswordSecret to disk; the readArtifacts side
        # asserts this field is absent.
        entry_dict.pop("PasswordSecret", None)

        payload = {
            "Profiles": entry_dict,
            "DefaultUID": "",
        }

        out_file = artifact_dir / "NDI_Cloud_Profiles.json"
        out_file.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        # Clean up the in-memory singleton state so other tests are not
        # affected. No secret leaves the process.
        ndi_profile.reset()

        assert out_file.is_file()
