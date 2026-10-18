"""Shared test setup for code that needs the user's NDI Cloud organizations.

A user may belong to several organizations, so nothing holds "the"
organization: the list is cached at login (``NDI_CLOUD_ORGANIZATIONS``), an
operation that creates a dataset asks
:func:`ndi.cloud.internal.chooseOrganization`, and file uploads use the
organization that owns the dataset, read from its record. Offline tests set
those up here instead of a client config.
"""

from __future__ import annotations

import json

import ndi.cloud.internal


def use_organizations(monkeypatch, *organizations, dataset_org_id=None):
    """Cache ORGANIZATIONS as the logged-in user's, with no token to refresh with.

    Each organization is a dict with ``id`` and optionally ``name`` and
    ``canUploadDataset``. Clearing the token keeps chooseOrganization and
    userIsAdmin off the network. File uploads are told every dataset belongs
    to DATASET_ORG_ID (default: the first organization's id).
    """
    monkeypatch.delenv("NDI_CLOUD_TOKEN", raising=False)
    monkeypatch.setenv("NDI_CLOUD_ORGANIZATIONS", json.dumps(list(organizations)))
    owner = dataset_org_id if dataset_org_id is not None else organizations[0]["id"]
    monkeypatch.setattr(
        ndi.cloud.internal,
        "_datasetOrganizationId",
        lambda dataset_id, client=None: owner,
    )


def testOrganizationID(client=None) -> str:
    """The NDI Cloud organization live tests create datasets in.

    MATLAB equivalent: ndi.unittest.cloud.testOrganizationID

    The id of the first organization the test account belongs to that allows
    dataset upload (any of its organizations, if the account is an NDI Cloud
    administrator, as the server allows). Test accounts may belong to several
    organizations, and a test cannot answer the organization prompt, so
    tests pass this id explicitly.
    """
    from ndi.cloud.internal import getOrganizations, userIsAdmin

    organizations = getOrganizations(client=client)
    uploadable = organizations
    if not userIsAdmin(client=client):
        uploadable = [o for o in organizations if o["canUploadDataset"]]
    if not uploadable:
        raise RuntimeError(
            "The NDI Cloud test account does not belong to any organization that "
            "allows dataset upload."
        )
    return uploadable[0]["id"]


# Collected by name otherwise: it is a helper, not a test.
testOrganizationID.__test__ = False
