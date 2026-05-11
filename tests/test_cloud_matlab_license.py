"""
Live tests for the MATLAB BYOL license endpoints.

Ported from MATLAB tests/+ndi/+unittest/+cloud/MatlabLicenseTest.m
(matlab HEAD 2566fe4d, 2026-05-11).

WHY THE EXTRA GUARDS:
These tests exercise allocate / set / clear of a real MATLAB license
registration. clearMatlabLicense releases the AWS ENI and removes the
license file the user uploaded to MathWorks's allocator. Running this
suite against a real account that has a real license configured would
silently destroy that license. The MATLAB side enforces an opt-in via
fatalAssert in TestClassSetup; we mirror that behaviour here with the
helper in tests._matlab_license_guard.

Environment variables consumed:
    NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD - skip if absent (standard
        live-test pattern, matches test_cloud_live.py).
    NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE - REQUIRED, see guard helper.
        "true"  -> only the read-only getMatlabLicense test runs.
        "false" -> destructive allocate/clear lifecycle runs end-to-end.
        unset   -> module fails to import (collection error).
"""

from __future__ import annotations

import os

import pytest

from tests._matlab_license_guard import (
    fatal_check_license_env,
    user_has_existing_license,
)

# ---------------------------------------------------------------------------
# Fatal license-deletion safety guard (runs at module import).
#
# An unset NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE is a CONFIGURATION ERROR,
# not a 'skip silently' condition. We raise here so pytest reports a
# collection failure rather than a green run that destroyed someone's
# license. This mirrors MATLAB fatalAssertNotEmpty in TestClassSetup.
# ---------------------------------------------------------------------------
fatal_check_license_env()

# ---------------------------------------------------------------------------
# Standard live-cloud skip (no creds -> module skipped). Order matters:
# the fatal check above runs first so that an unset HAS_LICENSE env var is
# reported even when credentials are also missing.
# ---------------------------------------------------------------------------
_has_creds = bool(
    os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD")
)
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")


USER_HAS_EXISTING_LICENSE = user_has_existing_license()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cloud_client():
    """Authenticated CloudClient, scoped to the module."""
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    config = CloudConfig.from_env()
    config = login(config=config)
    assert config.is_authenticated, "Login failed -- no token received"
    return CloudClient(config)


@pytest.fixture()
def destructive_teardown(cloud_client):
    """Per-test finalizer that defensively calls clearMatlabLicense.

    Mirrors MATLAB TestMethodTeardown.maybeClear: if the destructive test
    set the 'we allocated something' flag before failing mid-flight, the
    teardown still releases the ENI on the way out. The flag stays False
    by default so the teardown is a no-op when the test never allocated.

    The flag is exposed as a mutable holder so the test can flip it to
    True at the moment of allocation and back to False once it has
    successfully cleared the registration itself.

    NEVER runs effectively when NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE=true:
    in that mode the destructive tests are skipped entirely (see
    _require_no_existing_license) BEFORE the holder is ever flipped, so
    clear_on_teardown stays False and the teardown is a no-op. This
    guarantees we never call DELETE on an existing license we were
    supposed to preserve.
    """
    from ndi.cloud.api.users import clearMatlabLicense

    holder = {"clear_on_teardown": False}
    yield holder
    if holder["clear_on_teardown"]:
        try:
            clearMatlabLicense(client=cloud_client)
        except Exception:
            # Best-effort cleanup; the test itself will report the failure.
            pass


def _require_no_existing_license():
    """Skip a destructive test when the account has a real license to preserve."""
    if USER_HAS_EXISTING_LICENSE:
        pytest.skip(
            "Skipped: NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE=true. "
            "Destructive allocate/clear would mutate an existing "
            "registration that must be preserved."
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMatlabLicense:
    """Mirror of MATLAB MatlabLicenseTest."""

    def test_getMatlabLicense(self, cloud_client):
        """Read-only check that runs in BOTH modes.

        Asserts that the server returns a sane MatlabLicenseStatus dict
        and that its ``files`` array agrees with the env-var declaration:
            HAS_LICENSE=true  -> files must be non-empty
            HAS_LICENSE=false -> files must be empty (else the env var is
                                 lying and the destructive tests would
                                 destroy a real license).
        """
        from ndi.cloud.api.users import getMatlabLicense

        answer = getMatlabLicense(client=cloud_client)
        assert isinstance(answer, dict), f"Expected dict, got {type(answer)}"

        files = answer.get("files") or []
        has_files = bool(files)

        if USER_HAS_EXISTING_LICENSE:
            assert has_files, (
                "NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE=true but the user "
                f"has no registered files. Response: {answer}"
            )
        else:
            assert not has_files, (
                "Expected an empty registration but the test user already "
                "has MATLAB license files registered. Set "
                "NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE=true to preserve "
                f"them. Response: {answer}"
            )

    def test_allocate_and_clear_lifecycle(self, cloud_client, destructive_teardown):
        """POST -> GET -> DELETE -> GET round-trip.

        Skipped when HAS_LICENSE=true (DELETE would destroy a real
        registration). The teardown finalizer releases the ENI we
        ourselves allocated if any of the intermediate asserts fail.
        """
        _require_no_existing_license()

        from ndi.cloud.api.users import (
            allocateMatlabLicenseMac,
            clearMatlabLicense,
            getMatlabLicense,
        )

        # --- allocate -------------------------------------------------------
        alloc = allocateMatlabLicenseMac(client=cloud_client)
        # From here on, a failure MUST trigger teardown cleanup so we don't
        # strand an ENI in our AWS account.
        destructive_teardown["clear_on_teardown"] = True

        assert isinstance(alloc, dict), f"allocate returned {type(alloc)}: {alloc}"
        assert alloc.get("macAddress"), (
            f"Allocate response did not include a macAddress: {alloc}"
        )

        # --- get reflects the allocation -----------------------------------
        after_alloc = getMatlabLicense(client=cloud_client)
        assert isinstance(after_alloc, dict)
        if "mode" in after_alloc and after_alloc["mode"] is not None:
            assert str(after_alloc["mode"]) == "dedicated", (
                f"Expected mode=dedicated after allocate, got {after_alloc}"
            )
        if "macAddress" in after_alloc and after_alloc["macAddress"]:
            assert str(after_alloc["macAddress"]) == str(alloc["macAddress"]), (
                f"MAC mismatch: allocate={alloc} get={after_alloc}"
            )

        # --- clear (releases the ENI) --------------------------------------
        clearMatlabLicense(client=cloud_client)
        # The clear just succeeded; the teardown clear is now redundant.
        destructive_teardown["clear_on_teardown"] = False

        # --- get reflects empty --------------------------------------------
        after_clear = getMatlabLicense(client=cloud_client)
        assert isinstance(after_clear, dict)
        files_after = after_clear.get("files") or []
        assert not files_after, (
            "Files array should be empty after clearMatlabLicense. "
            f"Response: {after_clear}"
        )

    def test_setMatlabLicense_rejects_invalid_file(
        self, cloud_client, destructive_teardown
    ):
        """Negative test: PUT with a bogus lic body should return HTTP 400.

        Skipped when HAS_LICENSE=true (even a 400-rejected PUT could
        disturb an existing registration if server semantics change).
        Requires a prior allocate so the server actually reaches file
        validation rather than rejecting on 'no MAC allocated'.
        """
        _require_no_existing_license()

        from ndi.cloud.api.users import (
            allocateMatlabLicenseMac,
            setMatlabLicense,
        )
        from ndi.cloud.exceptions import CloudAPIError

        # Allocate a MAC so the PUT exercises *file* validation.
        alloc = allocateMatlabLicenseMac(client=cloud_client)
        assert isinstance(alloc, dict), f"allocate returned {type(alloc)}: {alloc}"
        destructive_teardown["clear_on_teardown"] = True

        bogus_file = "this is not a real MATLAB license file"
        with pytest.raises(CloudAPIError) as excinfo:
            setMatlabLicense(
                bogus_file, mode="dedicated", release="R2024b", client=cloud_client
            )
        # Verify the server actually rejected the FILE (HTTP 400), not the
        # request shape or auth.
        assert excinfo.value.status_code == 400, (
            f"Expected HTTP 400 for invalid lic; got {excinfo.value.status_code}: "
            f"{excinfo.value}"
        )
