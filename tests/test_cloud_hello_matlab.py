"""
Live test for the hello-matlab-v1 compute pipeline.

Ported from MATLAB tests/+ndi/+unittest/+cloud/+compute/HelloMatlabTest.m
(matlab HEAD 2566fe4d, 2026-05-11).

WHY TWO ENV-VAR GATES:
1. NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE -- same safety guard as
   test_cloud_matlab_license.py. This file imports the same fatal
   check so a misconfigured CI cannot run ANY MATLAB BYOL test
   without an explicit declaration of license state. With
   HAS_LICENSE=true we ASSUME a license is already present and SKIP
   any license-allocation steps (mirror of MATLAB semantics). With
   HAS_LICENSE=false we still require a registered license out-of-band
   (we do not auto-allocate one in this test), and skip gracefully if
   none is found.
2. NDI_CLOUD_RUN_HELLO_MATLAB -- opt-in because the pipeline launches a
   real EC2 instance (~2-4 min, billable). Matches MATLAB's
   ``assumeFail(isempty(getenv('NDI_CLOUD_RUN_HELLO_MATLAB')))``.
"""

from __future__ import annotations

import os

import pytest

from tests._matlab_license_guard import (
    fatal_check_license_env,
    user_has_existing_license,
)

# Fatal license-deletion safety guard (see _matlab_license_guard for
# rationale). Even though this test does not directly call
# clearMatlabLicense, it imports the same helper to force consistent CI
# configuration across all MATLAB BYOL tests.
fatal_check_license_env()

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")


USER_HAS_EXISTING_LICENSE = user_has_existing_license()


@pytest.fixture(scope="module")
def cloud_client():
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    config = CloudConfig.from_env()
    config = login(config=config)
    assert config.is_authenticated, "Login failed -- no token received"
    return CloudClient(config)


class TestHelloMatlab:
    """Mirror of MATLAB HelloMatlabTest."""

    def test_hello_matlab_flow(self, cloud_client):
        """Run hello-matlab-v1 end-to-end and verify success.

        Opt-in via NDI_CLOUD_RUN_HELLO_MATLAB (matches MATLAB). Requires
        a registered MATLAB BYOL license; we sanity-check that before
        starting the pipeline so a missing license fails with a clear
        message instead of a server-side MATLAB_LICENSE_REQUIRED error
        2 minutes later.
        """
        if not os.environ.get("NDI_CLOUD_RUN_HELLO_MATLAB", "").strip():
            pytest.skip(
                "Set NDI_CLOUD_RUN_HELLO_MATLAB=1 to run the hello-matlab-v1 "
                "end-to-end test (launches a real EC2 instance and requires "
                "a registered MATLAB BYOL license)."
            )

        # --- 1. Sanity-check that a license is registered. ---------------
        # When HAS_LICENSE=true we ASSUME a license already exists (this
        # mirrors MATLAB: with HAS_LICENSE=true the destructive
        # allocate/set steps are skipped and an existing registration is
        # taken as given). When HAS_LICENSE=false the user must still
        # have arranged for a license to be present out-of-band before
        # running this opt-in test; we verify and skip if not.
        from ndi.cloud.api.users import getMatlabLicense

        license_status = getMatlabLicense(client=cloud_client)
        assert isinstance(
            license_status, dict
        ), f"Expected dict from getMatlabLicense, got {type(license_status)}"
        files = license_status.get("files") or []
        if not files:
            pytest.skip(
                "No MATLAB license is registered for this user. Register "
                "one with ndi.cloud.api.users.allocateMatlabLicenseMac + "
                "setMatlabLicense before running this test. "
                f"getMatlabLicense response: {license_status}"
            )

        if USER_HAS_EXISTING_LICENSE:
            # HAS_LICENSE=true: assume the existing registration is the
            # one we want to use. Do NOT call allocate/set here.
            pass

        # --- 2. Run the hello-matlab-v1 pipeline end-to-end. -------------
        # The MATLAB test calls ndi.cloud.helloMatlab(). The Python port
        # of that orchestration helper has not landed yet; once it does
        # it is expected to expose a matching name on the ndi.cloud
        # package. Until then, skip cleanly so this test file is ready
        # to activate without modification.
        try:
            from ndi.cloud import helloMatlab
        except ImportError:
            pytest.skip(
                "ndi.cloud.helloMatlab has not yet been ported from MATLAB. "
                "This test file is ready to activate as soon as the "
                "orchestration helper lands."
            )

        result = helloMatlab(
            timeout_seconds=1200,
            poll_interval_seconds=15,
            verbose=True,
            client=cloud_client,
        )

        # helloMatlab return shape: MATLAB returns (success, sessionId,
        # statusMessage, sessionDoc); the Python wrapper is expected to
        # return a dict with the same fields. Support both forms here so
        # the test does not break on minor shape differences when the
        # port lands.
        if isinstance(result, dict):
            success = result.get("success")
            status_message = result.get("statusMessage", "")
        else:
            success = result[0]
            status_message = result[2] if len(result) > 2 else ""

        assert success, (
            "hello-matlab-v1 pipeline did not complete successfully. "
            f"statusMessage={status_message!r} full result={result}"
        )
