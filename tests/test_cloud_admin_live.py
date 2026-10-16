"""
Live tests for the organization and user admin endpoints.

Ported from NDI-matlab tests/+ndi/+unittest/+cloud/AdminOrganizationsTest.m
(9dc83026, NDI-matlab#1031). Exercises ndi.cloud.api.admin against the real
API (ndi-cloud-node admin.router.ts):

    GET    /admin/organizations
    GET    /admin/organizations/{organizationId}
    PATCH  /admin/organizations/{organizationId}
    POST   /admin/organizations/{organizationId}/members
    DELETE /admin/organizations/{organizationId}/members/{userId}
    GET    /admin/users
    GET    /admin/users/{userId}

Which tests run depends on the test account, read from users.me:

    - Every account: getUserOrganizations() with no user, which needs no
      administrator rights.
    - Accounts WITHOUT administrator rights: the admin endpoints must refuse
      them (403, CloudAuthError). The admin tests are skipped.
    - Accounts WITH administrator rights: the read-only admin tests run,
      and the refusal test is skipped.
    - Accounts WITH administrator rights, against the dev API (or with
      NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS=true): the tests that change
      organizations also run. They only touch a dedicated scratch
      organization, add the test account to it and remove it again. The
      API cannot delete organizations, so the scratch organization is
      created once and reused.

Where MATLAB checks ``b == false`` and a status code, Python checks the
exception the call raises, since every ndi.cloud.api function raises on a
non-2xx response.

Environment variables consumed:
    NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD -- skip if absent.
    CLOUD_API_ENVIRONMENT -- 'prod' (default) or 'dev'.
    NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS -- 'true' to run the tests that change
        organizations outside dev.
    NDI_CLOUD_TEST_ADMIN_ORGANIZATION_ID -- optional scratch organization id,
        instead of finding or creating one by name.
"""

from __future__ import annotations

import os
import uuid

import pytest

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")

#: Shared with NDI-matlab, so both suites reuse one scratch organization.
SCRATCH_ORGANIZATION_NAME = "NDI-matlab admin unittest scratch (safe to ignore)"
#: Valid 24-hex id that will not match any stored record.
NONEXISTENT_ID = "000000000000000000000000"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Authenticate once for the entire module and return a CloudClient."""
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    config = login(config=CloudConfig.from_env())
    assert config.is_authenticated, "Login failed -- no token received"
    return CloudClient(config)


@pytest.fixture(scope="module")
def me(client):
    """The test account. Admin status comes from the server's own record."""
    from ndi.cloud.api.users import me as users_me

    info = users_me(client=client)
    data = info.data if hasattr(info, "data") else info
    return {
        "id": str(data["id"]),
        "email": str(data["email"]),
        "is_admin": bool(data.get("isAdmin", False)),
        "organization_ids": sorted(str(o["id"]) for o in data.get("organizations") or []),
    }


@pytest.fixture(scope="module", autouse=True)
def endpoint_deployed(client):
    """Skip (rather than fail) where the admin endpoints are not deployed.

    There the API's catch-all answers 404, while a deployed endpoint
    answers 200 or 403. Mirrors AdminOrganizationsTest.checkEndpointDeployed.
    """
    from ndi.cloud.api.admin import listOrganizations
    from ndi.cloud.exceptions import CloudAuthError, CloudNotFoundError

    try:
        listOrganizations(page_size=1, client=client)
    except CloudNotFoundError:
        pytest.skip("The /admin endpoints are not deployed in this API environment")
    except CloudAuthError:
        pass


@pytest.fixture()
def admin_only(me):
    if not me["is_admin"]:
        pytest.skip("The test account is not an administrator")


@pytest.fixture()
def write_allowed(admin_only):
    allowed = os.environ.get("CLOUD_API_ENVIRONMENT", "").lower() == "dev" or (
        os.environ.get("NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS", "").lower() == "true"
    )
    if not allowed:
        pytest.skip(
            "Admin tests that change organizations run only against the dev API "
            "(or with NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS=true)"
        )


@pytest.fixture()
def scratch_organization(write_allowed, client, me):
    """The id of the scratch organization, found or created once."""
    from ndi.cloud.api.admin import createOrganization, listOrganizations

    org_id = os.environ.get("NDI_CLOUD_TEST_ADMIN_ORGANIZATION_ID", "")
    if not org_id:
        found = listOrganizations(query=SCRATCH_ORGANIZATION_NAME, page_size=100, client=client)
        for org in found.data.get("organizations") or []:
            if org.get("name") == SCRATCH_ORGANIZATION_NAME:
                org_id = str(org["id"])
                break
    if not org_id:
        org_id = str(createOrganization(SCRATCH_ORGANIZATION_NAME, client=client).data["id"])

    # Never add the account to, or remove it from, an organization it
    # really belongs to.
    assert org_id not in me["organization_ids"], (
        f"The scratch organization {org_id} is one the test account already "
        "belongs to. Point NDI_CLOUD_TEST_ADMIN_ORGANIZATION_ID at a dedicated "
        "organization."
    )
    return org_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_own_organizations_without_admin(client, me):
    from ndi.cloud.api.admin import getUserOrganizations

    result = getUserOrganizations(client=client)
    assert result.data["userID"] == me["id"]
    assert sorted(result.data["organizationID"]) == me["organization_ids"]
    assert len(result.data["organizationName"]) == len(result.data["organizationID"])


def test_non_admin_is_forbidden(client, me):
    from ndi.cloud.api import admin
    from ndi.cloud.exceptions import CloudAuthError

    if me["is_admin"]:
        pytest.skip("The test account is an administrator")

    calls = [
        lambda: admin.listOrganizations(client=client),
        lambda: admin.listUsers(client=client),
        lambda: admin.getUser(me["id"], client=client),
        lambda: admin.getOrganization(NONEXISTENT_ID, client=client),
        lambda: admin.addOrganizationMember(NONEXISTENT_ID, me["id"], client=client),
        lambda: admin.removeOrganizationMember(NONEXISTENT_ID, me["id"], client=client),
        lambda: admin.addOrganizationMemberByEmail(NONEXISTENT_ID, me["email"], client=client),
    ]
    for call in calls:
        with pytest.raises(CloudAuthError):
            call()


def test_list_organizations(client, admin_only):
    from ndi.cloud.api.admin import listOrganizations

    result = listOrganizations(page_size=2, client=client)
    assert result.status_code == 200
    for field in ("organizations", "page", "limit", "total", "totalPages"):
        assert field in result.data
    assert len(result.data["organizations"]) <= 2
    assert result.data["total"] >= len(result.data["organizations"])
    assert result.data["limit"] == 2


def test_list_users_and_find_user_by_email(client, me, admin_only):
    from ndi.cloud.api.admin import findUserByEmail, listUsers
    from ndi.cloud.exceptions import CloudNotFoundError

    result = listUsers(query=me["email"], client=client)
    assert me["id"] in [str(u["id"]) for u in result.data["users"]]

    found = findUserByEmail(me["email"].upper(), client=client)
    assert str(found.data["id"]) == me["id"]

    with pytest.raises(CloudNotFoundError):
        findUserByEmail(f"no-such-user-{uuid.uuid4()}@example.invalid", client=client)


def test_get_user_organizations(client, me, admin_only):
    from ndi.cloud.api.admin import getUser, getUserOrganizations

    user = getUser(me["id"], client=client)
    assert user.data["email"] == me["email"]
    assert sorted(str(o["id"]) for o in user.data["organizations"]) == me["organization_ids"]

    for who in (me["id"], me["email"]):
        result = getUserOrganizations(who, client=client)
        assert result.data["userID"] == me["id"]
        assert sorted(result.data["organizationID"]) == me["organization_ids"]


def test_invalid_ids(client, admin_only):
    from ndi.cloud.api.admin import addOrganizationMember, getOrganization
    from ndi.cloud.exceptions import CloudAPIError, CloudNotFoundError

    with pytest.raises(CloudAPIError) as info:
        getOrganization("not-an-id", client=client)
    assert info.value.status_code == 400

    with pytest.raises(CloudNotFoundError):
        getOrganization(NONEXISTENT_ID, client=client)

    with pytest.raises(CloudNotFoundError):
        addOrganizationMember(NONEXISTENT_ID, NONEXISTENT_ID, client=client)


def test_add_and_remove_member_by_email(client, me, scratch_organization):
    from ndi.cloud.api import admin
    from ndi.cloud.exceptions import CloudError

    org_id = scratch_organization

    def member_ids(org):
        return [str(m["id"]) for m in org.data.get("members") or []]

    try:
        org = admin.removeOrganizationMember(org_id, me["id"], client=client)
        assert me["id"] not in member_ids(org)
        count_before = org.data["memberCount"]

        org = admin.addOrganizationMemberByEmail(org_id, me["email"], client=client)
        assert me["id"] in member_ids(org)
        assert org.data["memberCount"] == count_before + 1

        org = admin.addOrganizationMember(org_id, me["id"], client=client)
        assert org.data["memberCount"] == count_before + 1

        mine = admin.getUserOrganizations(me["id"], client=client)
        assert org_id in mine.data["organizationID"]

        org = admin.removeOrganizationMemberByEmail(org_id, me["email"], client=client)
        assert me["id"] not in member_ids(org)
        assert org.data["memberCount"] == count_before

        mine = admin.getUserOrganizations(me["email"], client=client)
        assert org_id not in mine.data["organizationID"]
    finally:
        try:
            admin.removeOrganizationMember(org_id, me["id"], client=client)
        except CloudError:
            pass


def test_update_organization(client, scratch_organization):
    from ndi.cloud.api.admin import getOrganization, updateOrganization

    org = getOrganization(scratch_organization, client=client)
    updated = updateOrganization(
        scratch_organization,
        name=org.data["name"],
        can_upload_dataset=bool(org.data["canUploadDataset"]),
        client=client,
    )
    assert updated.data["name"] == org.data["name"]
    assert bool(updated.data["canUploadDataset"]) == bool(org.data["canUploadDataset"])

    with pytest.raises(ValueError):
        updateOrganization(scratch_organization, client=client)
