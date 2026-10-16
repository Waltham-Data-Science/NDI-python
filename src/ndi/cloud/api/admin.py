"""
ndi.cloud.api.admin - Organization and user administration.

These call the ``/admin`` endpoints (ndi-cloud-node ``admin.router.ts``),
which the server allows only for accounts with ``isAdmin`` set. Any other
account gets HTTP 403, which raises
:class:`~ndi.cloud.exceptions.CloudAuthError`. The one exception is
:func:`getUserOrganizations` with no user, which lists the logged-in
user's own organizations through ``/users/me`` and needs no admin rights.

Users must already have an NDI Cloud account to be added to an
organization; there is no invitation by email. The API cannot delete an
organization.

All functions accept an optional ``client`` keyword argument. When omitted,
a client is created automatically from environment variables. Each returns
an :class:`~ndi.cloud.client.APIResponse`, so
``b, answer, status, url = listOrganizations()`` unpacks like MATLAB's
``[b, answer, apiResponse, apiURL]``. Where MATLAB returns ``b = false``,
Python raises, as every other ndi.cloud.api function does.

MATLAB equivalents: +ndi/+cloud/+api/+admin/*.m,
    +implementation/+admin/*.m
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ..exceptions import CloudError, CloudNotFoundError
from ._validators import VALIDATE_CONFIG, AdminPageSize, CloudId, NonEmptyStr, PageNumber

_Client = Annotated[CloudClient | None, SkipValidation()]


def _list_params(query: str, page: int, page_size: int) -> dict[str, Any]:
    """The search and paging query of an admin list endpoint.

    MATLAB equivalent: ``ndi.cloud.api.implementation.admin.addQuery``.
    The server takes q (case-insensitive substring), page (1-based) and
    limit (1-100); q is sent only when QUERY is not empty.
    """
    params: dict[str, Any] = {"page": page, "limit": page_size}
    if query:
        params["q"] = query
    return params


def _with_data(result: Any, data: Any) -> APIResponse:
    """An APIResponse carrying DATA and the request metadata of RESULT."""
    return APIResponse(
        data,
        success=True,
        status_code=getattr(result, "status_code", 200),
        url=getattr(result, "url", ""),
        headers=getattr(result, "headers", None),
        reason=getattr(result, "reason", ""),
        elapsed=getattr(result, "elapsed", None),
        http_response=getattr(result, "http_response", None),
    )


def _payload(result: Any) -> Any:
    return result.data if isinstance(result, APIResponse) else result


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listOrganizations(
    *,
    query: str = "",
    page: PageNumber = 1,
    page_size: AdminPageSize = 25,
    client: _Client = None,
) -> APIResponse:
    """GET /admin/organizations -- List NDI Cloud organizations (admin only).

    Lists one page of all organizations, sorted by name.

    Args:
        query: Case-insensitive substring of the organization name.
            Default ``""`` (all organizations).
        page: 1-based page number.
        page_size: Organizations per page, 1-100. Sent as the server's
            ``limit`` parameter.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is a dict with
        ``organizations`` (each with ``id``, ``name``, ``canUploadDataset``,
        ``memberCount`` and ``teams``), ``page``, ``limit``, ``total`` and
        ``totalPages``.
    """
    return client.get("/admin/organizations", params=_list_params(query, page, page_size))


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getOrganization(organization_id: CloudId, *, client: _Client = None) -> APIResponse:
    """GET /admin/organizations/{organizationId} -- An organization and its members (admin only).

    Args:
        organization_id: The organization's id.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the
        organization: ``id``, ``name``, ``canUploadDataset``,
        ``memberCount``, ``teams`` and ``members`` (each with ``id``,
        ``name`` and ``email``). A malformed id raises
        :class:`~ndi.cloud.exceptions.CloudAPIError` with ``status_code``
        400; an unknown one, :class:`~ndi.cloud.exceptions.CloudNotFoundError`.

    Python-specific Notes:
        MATLAB also adds parallel ``memberID`` / ``memberName`` /
        ``memberEmail`` cell arrays built from ``members``, a MATLAB idiom
        for reaching into an array of structs; the list of dicts is the
        same information in the shape Python already has, as for
        ``ndi.cloud.api.users.me``.
    """
    return client.get("/admin/organizations/{organizationId}", organizationId=organization_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def createOrganization(
    name: NonEmptyStr,
    *,
    can_upload_dataset: bool = False,
    client: _Client = None,
) -> APIResponse:
    """POST /admin/organizations -- Create an organization with no members (admin only).

    The API has no endpoint for deleting an organization, so an
    organization created here can only be renamed afterwards, not removed.
    Organization names are not required to be unique.

    Args:
        name: The organization's name.
        can_upload_dataset: Whether members may upload datasets.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` (HTTP 201) whose ``data`` is
        the new organization, with its ``id``.
    """
    return client.post(
        "/admin/organizations",
        json={"name": name, "canUploadDataset": can_upload_dataset},
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def updateOrganization(
    organization_id: CloudId,
    *,
    name: NonEmptyStr | None = None,
    can_upload_dataset: bool | None = None,
    client: _Client = None,
) -> APIResponse:
    """PATCH /admin/organizations/{organizationId} -- Rename an organization or change its upload permission (admin only).

    Only the fields given are changed; at least one must be given.

    Args:
        organization_id: The organization's id.
        name: New organization name.
        can_upload_dataset: Whether members may upload datasets.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the
        updated organization.

    Raises:
        ValueError: if neither ``name`` nor ``can_upload_dataset`` is given
            (MATLAB: ``NDI:Cloud:Admin:NoUpdates``).
    """
    updates: dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if can_upload_dataset is not None:
        updates["canUploadDataset"] = can_upload_dataset
    if not updates:
        raise ValueError("Give at least one of 'name' or 'can_upload_dataset'.")
    return client.patch(
        "/admin/organizations/{organizationId}",
        json=updates,
        organizationId=organization_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def addOrganizationMember(
    organization_id: CloudId,
    user_id: CloudId,
    *,
    client: _Client = None,
) -> APIResponse:
    """POST /admin/organizations/{organizationId}/members -- Add a user to an organization by user id (admin only).

    Adding a user who is already a member succeeds and changes nothing.
    To add a user by email address, use :func:`addOrganizationMemberByEmail`.

    Args:
        organization_id: The organization's id.
        user_id: The user's id.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the
        organization with its updated member list (see
        :func:`getOrganization`). An unknown user or organization raises
        :class:`~ndi.cloud.exceptions.CloudNotFoundError`.
    """
    return client.post(
        "/admin/organizations/{organizationId}/members",
        json={"userId": user_id},
        organizationId=organization_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def removeOrganizationMember(
    organization_id: CloudId,
    user_id: CloudId,
    *,
    client: _Client = None,
) -> APIResponse:
    """DELETE /admin/organizations/{organizationId}/members/{userId} -- Remove a user from an organization by user id (admin only).

    Removing a user who is not a member succeeds and changes nothing.

    Args:
        organization_id: The organization's id.
        user_id: The user's id.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the
        organization with its updated member list (see
        :func:`getOrganization`).
    """
    return client.delete(
        "/admin/organizations/{organizationId}/members/{userId}",
        organizationId=organization_id,
        userId=user_id,
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listUsers(
    *,
    query: str = "",
    page: PageNumber = 1,
    page_size: AdminPageSize = 25,
    client: _Client = None,
) -> APIResponse:
    """GET /admin/users -- List NDI Cloud users (admin only).

    Lists one page of active (not disabled) users, sorted by email.

    Args:
        query: Case-insensitive substring matched against the user's name
            or email. Default ``""`` (all users). This is a substring
            match: to find one user by exact email, use
            :func:`findUserByEmail`.
        page: 1-based page number.
        page_size: Users per page, 1-100. Sent as the server's ``limit``
            parameter.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is a dict with
        ``users`` (each with ``id``, ``name``, ``email``, ``isAdmin``,
        ``isValidated`` and other account flags), ``page``, ``limit``,
        ``total`` and ``totalPages``.
    """
    return client.get("/admin/users", params=_list_params(query, page, page_size))


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getUser(user_id: CloudId, *, client: _Client = None) -> APIResponse:
    """GET /admin/users/{userId} -- A user, including their organizations (admin only).

    To look up your own account, use :func:`ndi.cloud.api.users.me`, which
    needs no administrator rights.

    Args:
        user_id: The user's id.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the user:
        ``id``, ``name``, ``email``, ``isAdmin``, ``isValidated``,
        ``isDisabled`` and ``organizations`` (each with ``id`` and ``name``).

    Python-specific Notes:
        MATLAB also adds parallel ``organizationID`` / ``organizationName``
        cell arrays built from ``organizations``; see :func:`getOrganization`.
    """
    return client.get("/admin/users/{userId}", userId=user_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def findUserByEmail(email: NonEmptyStr, *, client: _Client = None) -> APIResponse:
    """Find an NDI Cloud user by exact email address (admin only).

    The API has no lookup by email, so this searches with :func:`listUsers`
    and keeps only the user whose email equals EMAIL, ignoring case. (The
    search itself is a substring match: ``"bob@lab.edu"`` also matches
    ``"jimbob@lab.edu"``.) Disabled users are not found.

    Args:
        email: The user's email address.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the user dict
        from :func:`listUsers` (with ``id``, ``name``, ``email``, ...), with
        the request metadata of the last :func:`listUsers` call.

    Raises:
        CloudNotFoundError: if no active user has this email (MATLAB:
            ``b = false`` with an ``error`` field).
        CloudError: if more than one user has it.
    """
    email = email.strip()
    matches: list[dict[str, Any]] = []
    page = 1
    while True:
        result = listUsers(query=email, page=page, page_size=100, client=client)
        data = _payload(result) or {}
        for user in data.get("users") or []:
            if isinstance(user, dict) and str(user.get("email", "")).lower() == email.lower():
                matches.append(user)
        if page >= int(data.get("totalPages") or 0):
            break
        page += 1

    if not matches:
        raise CloudNotFoundError(f"No active NDI Cloud user has the email address {email}.")
    if len(matches) > 1:
        raise CloudError(f"{len(matches)} NDI Cloud users have the email address {email}.")
    return _with_data(result, matches[0])


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def addOrganizationMemberByEmail(
    organization_id: CloudId,
    email: NonEmptyStr,
    *,
    client: _Client = None,
) -> APIResponse:
    """Add a user to an NDI Cloud organization by email address (admin only).

    Looks the user up with :func:`findUserByEmail` and then calls
    :func:`addOrganizationMember`. The user must already have an NDI Cloud
    account; this does not send an invitation.

    Args:
        organization_id: The organization's id.
        email: The user's email address (exact, any case).
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the
        organization with its updated member list. Raises as
        :func:`findUserByEmail` and :func:`addOrganizationMember` do.
    """
    user = findUserByEmail(email, client=client)
    return addOrganizationMember(organization_id, user.data["id"], client=client)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def removeOrganizationMemberByEmail(
    organization_id: CloudId,
    email: NonEmptyStr,
    *,
    client: _Client = None,
) -> APIResponse:
    """Remove a user from an NDI Cloud organization by email address (admin only).

    Looks the user up with :func:`findUserByEmail` and then calls
    :func:`removeOrganizationMember`.

    Args:
        organization_id: The organization's id.
        email: The user's email address (exact, any case).
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is the
        organization with its updated member list. Raises as
        :func:`findUserByEmail` and :func:`removeOrganizationMember` do.
    """
    user = findUserByEmail(email, client=client)
    return removeOrganizationMember(organization_id, user.data["id"], client=client)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getUserOrganizations(user: str | None = None, *, client: _Client = None) -> APIResponse:
    """List the organizations a user belongs to.

    With no ``user``, lists the organizations of the logged-in user, using
    :func:`ndi.cloud.api.users.me`. This form needs no administrator rights.

    With ``user``, lists the organizations of that user, using
    :func:`getUser`. This form requires administrator rights. ``user`` is
    either a user id or an email address (anything containing ``"@"`` is
    treated as an email address and looked up with :func:`findUserByEmail`).

    Args:
        user: The user's id or email address.
        client: Authenticated cloud client.

    Returns:
        :class:`~ndi.cloud.client.APIResponse` whose ``data`` is a dict with
        ``userID``, ``email``, ``organizationID`` (list of organization ids)
        and ``organizationName`` (list of names, parallel to
        ``organizationID``) -- the same fields as MATLAB's answer struct.
    """
    if user is None:
        from .users import me

        result = me(client=client)
    else:
        user = user.strip()
        if not user:
            raise ValueError("user must be a non-empty user id or email address.")
        user_id = user
        if "@" in user:
            user_id = findUserByEmail(user, client=client).data["id"]
        result = getUser(user_id, client=client)

    info = _payload(result) or {}
    organizations = [org for org in info.get("organizations") or [] if isinstance(org, dict)]
    return _with_data(
        result,
        {
            "userID": str(info.get("id", "")),
            "email": str(info.get("email", "")),
            "organizationID": [str(org.get("id", "")) for org in organizations],
            "organizationName": [str(org.get("name", "")) for org in organizations],
        },
    )
