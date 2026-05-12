"""
Shared MATLAB BYOL test guard.

This module exists for ONE reason: to make it impossible for a misconfigured
CI run to silently destroy a real MATLAB BYOL license registration on the
test cloud account.

The MATLAB BYOL endpoints (allocate / set / clear) mutate user state that
lives outside the test sandbox -- a stale ENI or orphaned license costs real
money and time to recover. The MATLAB equivalent test
(tests/+ndi/+unittest/+cloud/MatlabLicenseTest.m) uses fatalAssert in
TestClassSetup to refuse to run when NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE
is unset. This helper mirrors that guard for pytest.

Semantics of NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE:
  - empty / unset  -> fail (configuration error; refuse to run at all)
  - "true" / "1"   -> the test account already has a license that MUST be
                      preserved; destructive tests skip themselves and the
                      teardown does NOT call clearMatlabLicense
  - "false" / "0"  -> the test account has no license; destructive tests
                      run end-to-end and the teardown cleans up

This module is shared between test_cloud_matlab_license.py and
test_cloud_hello_matlab.py so the same env-var contract is enforced
identically wherever the destructive endpoints might be touched.
"""

from __future__ import annotations

import os

ENV_VAR = "NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE"

_TRUE_VALUES = {"true", "1"}
_FALSE_VALUES = {"false", "0"}

_FATAL_MESSAGE = (
    "LOCAL CONFIGURATION ERROR: NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE is not set.\n"
    "This variable MUST be set explicitly for any MATLAB BYOL test to run, "
    "because these tests call DELETE /users/me/matlab-license and would "
    "otherwise silently destroy a real registered license file on a "
    "misconfigured CI account.\n"
    'Set it to "true" if the test account already has a MATLAB license '
    "(destructive tests will be skipped) or "
    '"false" if it does not (destructive tests will run and clean up).'
)


def _raw_value() -> str:
    return os.environ.get(ENV_VAR, "")


def fatal_check_license_env() -> None:
    """Raise RuntimeError if NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE is unset.

    Call at module import time so the failure surfaces as a collection
    error, mirroring MATLAB's fatalAssertNotEmpty in TestClassSetup.

    We intentionally raise RuntimeError instead of calling pytest.skip:
    an unset env var is a misconfiguration, not a 'no credentials
    available' no-op. Pytest treats an exception during collection as
    an ERROR rather than a SKIP, which is exactly what we want -- a
    green CI run that destroyed someone's license would be the
    nightmare scenario this guard prevents.
    """
    if not _raw_value().strip():
        raise RuntimeError(_FATAL_MESSAGE)


def user_has_existing_license() -> bool:
    """Return True iff env var explicitly says the test account has a license.

    Accepted true values: ``"true"``, ``"1"`` (case-insensitive).
    Anything else (including the false values) returns False. Matches
    the MATLAB check ``strcmpi(flag,"true") || flag=="1"``.
    """
    val = _raw_value().strip().lower()
    return val in _TRUE_VALUES


def env_value_is_recognized() -> bool:
    """True iff env var is set to one of the four recognized values."""
    val = _raw_value().strip().lower()
    return val in _TRUE_VALUES or val in _FALSE_VALUES
