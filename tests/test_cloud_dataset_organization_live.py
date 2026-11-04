"""
Live tests for moving a dataset between organizations.

Ported from NDI-matlab tests/+ndi/+unittest/+cloud/DatasetOrganizationTest.m
(47647f5). Exercises ndi.cloud.api.datasets.reassignDatasetOrganization, the
client wrapper around the admin-only endpoint

    POST /admin/datasets/{datasetId}/organization

and checks that the ordinary metadata update (updateDataset) cannot change
a dataset's organization. Organization membership is what grants access to
an unpublished dataset, so moving one changes who can see it; that is why
only administrators may do it.

Which tests run depends on the test account, read from users.me:

    - Every account: updateDataset must leave organizationId unchanged, and
      a blank reason is refused before any request.
    - Accounts WITHOUT administrator rights: the move must be refused (403,
      CloudAuthError). The admin tests are skipped.
    - Accounts WITH administrator rights: the tests of the server's input
      checks run (they change nothing), and the refusal test is skipped.
    - Accounts WITH administrator rights, against the dev API (or with
      NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS=true): the round-trip test also runs.
      It moves a dataset it created itself into the scratch organization
      shared with test_cloud_admin_live.py, moves it back, and deletes it.

Where MATLAB checks ``b == false`` and a status code, Python checks the
exception the call raises, since every ndi.cloud.api function raises on a
non-2xx response.

Environment variables consumed:
    NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD -- skip if absent.
    CLOUD_API_ENVIRONMENT -- 'prod' (default) or 'dev'.
    NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS -- 'true' to run the round trip
        outside dev.
    NDI_CLOUD_TEST_ADMIN_ORGANIZATION_ID -- optional scratch organization id,
        instead of finding or creating one by name.
"""

from __future__ import annotations

import os
import uuid

import pytest

from tests._cloud_organizations import testOrganizationID

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")

DATASET_NAME_PREFIX = "NDI_PYTEST_DATASET_ORG_"
#: Shared with NDI-matlab and test_cloud_admin_live.py, so all reuse one
#: scratch organization.
SCRATCH_ORGANIZATION_NAME = "NDI-matlab admin unittest scratch (safe to ignore)"
#: Valid 24-hex id that will not match any stored record.
NONEXISTENT_ID = "000000000000000000000000"
REASON = "NDI-python pytest test_cloud_dataset_organization_live"


def _data(result):
    return result.data if hasattr(result, "data") else result


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
def is_admin(client):
    """Admin status comes from the server's own record of the account."""
    from ndi.cloud.api.users import me

    return bool(_data(me(client=client)).get("isAdmin", False))


@pytest.fixture(scope="module")
def home_organization_id(client):
    return str(testOrganizationID(client))


@pytest.fixture(scope="module", autouse=True)
def endpoint_deployed(client):
    """Skip (rather than fail) where the endpoint is not deployed.

    There the API's catch-all answers 404. A deployed endpoint answers this
    call (empty reason) with 403 for non-admins or 400 for admins, before
    any lookup. Mirrors DatasetOrganizationTest.checkEndpointDeployed.
    """
    from ndi.cloud.exceptions import CloudError, CloudNotFoundError

    try:
        client.post(
            "/admin/datasets/{datasetId}/organization",
            json={"organizationId": NONEXISTENT_ID, "reason": ""},
            datasetId=NONEXISTENT_ID,
        )
    except CloudNotFoundError:
        pytest.skip(
            "POST /admin/datasets/{datasetId}/organization is not deployed "
            "in this API environment"
        )
    except CloudError:
        pass


@pytest.fixture()
def admin_only(is_admin):
    if not is_admin:
        pytest.skip("The test account is not an administrator")


@pytest.fixture()
def write_allowed(admin_only):
    allowed = os.environ.get("CLOUD_API_ENVIRONMENT", "").lower() == "dev" or (
        os.environ.get("NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS", "").lower() == "true"
    )
    if not allowed:
        pytest.skip(
            "Admin tests that move datasets run only against the dev API "
            "(or with NDI_CLOUD_ALLOW_ADMIN_WRITE_TESTS=true)"
        )


@pytest.fixture()
def temporary_dataset(client, home_organization_id):
    """A dataset in the home organization, deleted on teardown."""
    from ndi.cloud.api.datasets import createDataset, deleteDataset

    name = f"{DATASET_NAME_PREFIX}{uuid.uuid4().hex}"
    result = _data(createDataset(org_id=home_organization_id, name=name, client=client))
    dataset_id = str(result.get("_id", result.get("id", "")))
    assert dataset_id, f"Failed to create dataset {name}, response: {result}"
    yield dataset_id
    try:
        deleteDataset(dataset_id, when="now", client=client)
    except Exception:
        pass


@pytest.fixture()
def scratch_organization(write_allowed, client, home_organization_id):
    """The id of the scratch organization, found or created."""
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
    assert org_id != home_organization_id, (
        "The scratch organization is the test account's own dataset organization. "
        "Point NDI_CLOUD_TEST_ADMIN_ORGANIZATION_ID at a dedicated organization."
    )
    return org_id


def _organization_of(client, dataset_id):
    from ndi.cloud.api.datasets import getDataset

    return str(_data(getDataset(dataset_id, client=client))["organizationId"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_update_dataset_cannot_change_organization(client, temporary_dataset, home_organization_id):
    from ndi.cloud.api.datasets import getDataset, updateDataset

    assert _organization_of(client, temporary_dataset) == home_organization_id

    new_name = f"{DATASET_NAME_PREFIX}renamed_{uuid.uuid4().hex}"
    updateDataset(temporary_dataset, name=new_name, organizationId=NONEXISTENT_ID, client=client)

    ds = _data(getDataset(temporary_dataset, client=client))
    assert ds["name"] == new_name, "the update was not applied"
    assert str(ds["organizationId"]) == home_organization_id, "updateDataset moved the dataset"


def test_blank_reason_is_refused_locally(client):
    from ndi.cloud.api.datasets import reassignDatasetOrganization

    with pytest.raises(ValueError):
        reassignDatasetOrganization(NONEXISTENT_ID, NONEXISTENT_ID, "   ", client=client)


def test_non_admin_is_forbidden(client, is_admin, temporary_dataset, home_organization_id):
    from ndi.cloud.api.datasets import reassignDatasetOrganization
    from ndi.cloud.exceptions import CloudAuthError

    if is_admin:
        pytest.skip("The test account is an administrator")

    with pytest.raises(CloudAuthError):
        reassignDatasetOrganization(temporary_dataset, NONEXISTENT_ID, REASON, client=client)
    assert _organization_of(client, temporary_dataset) == home_organization_id


def test_server_input_checks(client, admin_only, home_organization_id):
    from ndi.cloud.api.datasets import reassignDatasetOrganization
    from ndi.cloud.exceptions import CloudAPIError, CloudNotFoundError

    for dataset_id, org_id in (("not-an-id", NONEXISTENT_ID), (NONEXISTENT_ID, "not-an-id")):
        with pytest.raises(CloudAPIError) as info:
            reassignDatasetOrganization(dataset_id, org_id, REASON, client=client)
        assert info.value.status_code == 400

    # The wrapper refuses a blank reason itself; go round it to check the
    # server refuses one too.
    with pytest.raises(CloudAPIError) as info:
        client.post(
            "/admin/datasets/{datasetId}/organization",
            json={"organizationId": home_organization_id, "reason": ""},
            datasetId=NONEXISTENT_ID,
        )
    assert info.value.status_code == 400

    # Unknown organization, then unknown dataset.
    with pytest.raises(CloudNotFoundError):
        reassignDatasetOrganization(NONEXISTENT_ID, NONEXISTENT_ID, REASON, client=client)
    with pytest.raises(CloudNotFoundError):
        reassignDatasetOrganization(NONEXISTENT_ID, home_organization_id, REASON, client=client)


def test_reassign_round_trip(client, scratch_organization, temporary_dataset, home_organization_id):
    from ndi.cloud.api.datasets import reassignDatasetOrganization
    from ndi.cloud.exceptions import CloudAPIError

    # Already in that organization.
    with pytest.raises(CloudAPIError) as info:
        reassignDatasetOrganization(temporary_dataset, home_organization_id, REASON, client=client)
    assert info.value.status_code == 400

    moved = reassignDatasetOrganization(
        temporary_dataset, scratch_organization, REASON, client=client
    )
    assert str(moved.data["id"]) == temporary_dataset
    assert str(moved.data["organizationId"]) == scratch_organization
    assert _organization_of(client, temporary_dataset) == scratch_organization

    back = reassignDatasetOrganization(
        temporary_dataset, home_organization_id, REASON, client=client
    )
    assert str(back.data["organizationId"]) == home_organization_id
    assert _organization_of(client, temporary_dataset) == home_organization_id
