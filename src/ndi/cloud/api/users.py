"""
ndi.cloud.api.users - User management.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables.

MATLAB equivalents: +ndi/+cloud/+api/+users/*.m,
    +implementation/+users/*.m
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import SkipValidation, validate_call

from ..client import CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, NonEmptyStr

_Client = Annotated[CloudClient | None, SkipValidation()]


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def createUser(
    email: NonEmptyStr,
    name: NonEmptyStr,
    password: NonEmptyStr,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """POST /users -- Create a new user (no auth required)."""
    return client.post(
        "/users",
        json={"email": email, "name": name, "password": password},
    )


@_auto_client
def me(*, client: _Client = None) -> dict[str, Any]:
    """GET /users/me -- Get the authenticated user's profile.

    The response includes the user's organization memberships.
    """
    return client.get("/users/me")


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def GetUser(user_id: NonEmptyStr, *, client: _Client = None) -> dict[str, Any]:
    """GET /users/{userId}"""
    return client.get("/users/{userId}", userId=user_id)


# ---------------------------------------------------------------------------
# MATLAB BYOL license wrappers
#
# MATLAB equivalents:
#   +ndi/+cloud/+api/+users/getMatlabLicense.m
#   +ndi/+cloud/+api/+users/setMatlabLicense.m
#   +ndi/+cloud/+api/+users/clearMatlabLicense.m
#   +ndi/+cloud/+api/+users/allocateMatlabLicenseMac.m
# ---------------------------------------------------------------------------


@_auto_client
def getMatlabLicense(*, client: _Client = None) -> dict[str, Any]:
    """GET /users/me/matlab-license -- Retrieve the current MATLAB BYOL status.

    Returns the ``MatlabLicenseStatus`` document (``mode``, ``eniId``,
    ``macAddress``, ``subnetId``, ``registeredAt``, ``files``,
    ``instructions``). When no license is registered the server still
    returns 200 with ``mode == ""`` / ``None`` and an empty ``files``
    array.

    MATLAB equivalent: +cloud/+api/+users/getMatlabLicense.m
    """
    return client.get("/users/me/matlab-license")


@_auto_client
def allocateMatlabLicenseMac(*, client: _Client = None) -> dict[str, Any]:
    """POST /users/me/matlab-license -- Allocate an AWS ENI/MAC for dedicated MATLAB BYOL.

    Idempotent: returns the existing MAC if a dedicated registration
    already exists; otherwise allocates a new ENI in the configured
    subnet and returns its MAC address.

    The caller registers the returned MAC with MathWorks to obtain a
    ``.lic`` file, then uploads it via :func:`setMatlabLicense` with the
    matching ``release`` tag.

    Conflicts: returns HTTP 409 if a network license is currently
    registered; clear it first via :func:`clearMatlabLicense`.

    MATLAB equivalent: +cloud/+api/+users/allocateMatlabLicenseMac.m
    """
    return client.post("/users/me/matlab-license")


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def setMatlabLicense(
    license_file: NonEmptyStr,
    *,
    mode: Literal["dedicated", "network"] = "dedicated",
    release: str = "",
    client: _Client = None,
) -> dict[str, Any]:
    """PUT /users/me/matlab-license -- Upload a MATLAB BYOL license file.

    Args:
        license_file: Either the contents of the ``.lic`` file as a
            string, or a path to a ``.lic`` file on disk (auto-detected:
            a single-line argument that exists as a file is read in).
        mode: ``"dedicated"`` (default) — per-MAC license; requires a
            ``release`` tag (e.g. ``"R2024b"``) and a prior call to
            :func:`allocateMatlabLicenseMac` whose MAC the lic file's
            HOSTID matches.  ``"network"`` — license-server file
            containing a SERVER line; must not supply ``release``.
        release: Release tag (e.g. ``"R2024b"``) for dedicated mode.

    MATLAB equivalent: +cloud/+api/+users/setMatlabLicense.m
    """
    # If license_file looks like a path that exists on disk, read it in.
    license_text = license_file
    if "\n" not in license_file:
        try:
            p = Path(license_file)
            if p.is_file():
                license_text = p.read_text()
        except (OSError, ValueError):
            pass

    body: dict[str, Any] = {"licenseFile": license_text, "mode": mode}
    if release:
        body["release"] = release
    return client.put("/users/me/matlab-license", json=body)


@_auto_client
def clearMatlabLicense(
    *,
    release: str = "",
    client: _Client = None,
) -> dict[str, Any]:
    """DELETE /users/me/matlab-license -- Remove a MATLAB BYOL registration.

    Without ``release``, fully clears the user's registration (releasing
    the AWS ENI for dedicated mode).  With ``release`` set, only that
    release entry is removed from a dedicated registration; the MAC and
    remaining releases stay intact.

    Server returns 204 on full clear or empty registration, 200 with
    the remaining ``MatlabLicenseStatus`` when only one release was
    removed.

    MATLAB equivalent: +cloud/+api/+users/clearMatlabLicense.m
    """
    params: dict[str, str] | None = {"release": release} if release else None
    return client.delete("/users/me/matlab-license", params=params)
