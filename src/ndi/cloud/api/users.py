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

from ..client import APIResponse, CloudClient, _auto_client
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


def _add_organization_fields(payload: Any) -> Any:
    """Derive the ``organization*`` convenience arrays on a ``/users/me`` body.

    ``GET /users/me`` returns each organization as an ``OrganizationListItem``
    with ``id``, ``name`` and ``canUploadDataset`` (see the NDI Cloud API
    definition of ``UserWithOrganizations``). This adds three parallel lists
    derived from that raw ``organizations`` value, leaving ``organizations``
    itself untouched for callers that want the full objects.

    The three fields are always defined -- an empty list when the user belongs
    to no organizations, or when ``organizations`` is missing or of an
    unexpected type -- so callers never have to test for their presence.

    A non-object *payload* is returned unchanged.

    MATLAB equivalent: ``+cloud/+api/+implementation/+users/Me.m`` (NDI-matlab
    ``f2b91923f``, PR #858).
    """
    if not isinstance(payload, dict):
        return payload

    org_ids: list[str] = []
    org_names: list[str] = []
    org_can_upload: list[bool] = []

    orgs = payload.get("organizations")
    # Normalize to a list of objects so that a list (typical) and a single
    # bare object are handled identically; MATLAB does the same for a struct
    # array vs. a cell array of structs.
    if isinstance(orgs, dict):
        org_list: list[Any] = [orgs]
    elif isinstance(orgs, (list, tuple)):
        org_list = list(orgs)
    else:
        org_list = []

    for org in org_list:
        if not isinstance(org, dict):
            continue
        if "id" in org:
            org_ids.append(str(org["id"]))
        if "name" in org:
            org_names.append(str(org["name"]))
        if "canUploadDataset" in org:
            org_can_upload.append(bool(org["canUploadDataset"]))

    payload["organizationID"] = org_ids
    payload["organizationName"] = org_names
    payload["organizationCanUploadDataset"] = org_can_upload
    return payload


@_auto_client
def me(*, client: _Client = None) -> APIResponse | dict[str, Any]:
    """GET /users/me -- Get the authenticated user's profile.

    Returns the :class:`~ndi.cloud.client.APIResponse` wrapper that
    ``CloudClient.get`` produces (its ``.data`` carries the parsed body, and
    the wrapper proxies ``dict`` access, so ``result.get("email")`` works),
    or the bare payload when *client* is a stand-in whose ``get`` returns a
    plain ``dict`` rather than an ``APIResponse``.

    On success the response carries the fields the NDI Cloud API returns for
    the current user (``id``, ``name``, ``email``, ``isValidated``,
    ``isAdmin``, ``bookmarkedDatasetIds``, and ``organizations`` -- the raw
    organization objects, each with ``id``, ``name`` and
    ``canUploadDataset``), plus three convenience fields derived from
    ``organizations``:

    ``organizationID``
        List of the organization IDs (``str``) the user belongs to.
    ``organizationName``
        List of organization names (``str``), parallel to ``organizationID``.
    ``organizationCanUploadDataset``
        List of ``bool``, parallel to ``organizationID``, indicating upload
        permission.

    Example::

        info = me()
        for org_id, org_name in zip(
            info["organizationID"], info["organizationName"]
        ):
            print(f"{org_name} ({org_id})")

    MATLAB equivalent: ``+cloud/+api/+users/me.m``
    """
    result = client.get("/users/me")
    if hasattr(result, "data"):
        result.data = _add_organization_fields(result.data)
        return result
    return _add_organization_fields(result)


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


def _unwrap(result: Any) -> dict[str, Any]:
    # CloudClient verbs return APIResponse, whose .data is the parsed JSON
    # body. The BYOL wrappers advertise dict[str, Any] in their signature
    # and tests assert isinstance(result, dict), so unwrap once here.
    if isinstance(result, dict):
        return result
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    return {}


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
    return _unwrap(client.get("/users/me/matlab-license"))


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
    return _unwrap(client.post("/users/me/matlab-license"))


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
    return _unwrap(client.put("/users/me/matlab-license", json=body))


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
    return _unwrap(client.delete("/users/me/matlab-license", params=params))
