"""Unit tests for ndi.cloud.api.datasets — no network required.

A user may belong to several NDI Cloud organizations, so there is no
organization on the client: the user's organizations are cached at login
(``NDI_CLOUD_ORGANIZATIONS``) and each call names one or lets
:func:`ndi.cloud.internal.chooseOrganization` decide. The cache is set
directly here, and the token cleared, so nothing reaches the network.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ndi.cloud.exceptions import CloudOrganizationError

ALPHA = {"id": "org-abc", "name": "Alpha Lab", "canUploadDataset": True}
BETA = {"id": "org-def", "name": "Beta Institute", "canUploadDataset": True}
ARCHIVE = {"id": "org-ghi", "name": "Archive", "canUploadDataset": False}


@pytest.fixture
def organizations(monkeypatch):
    """Set the cached organization list; no token, so never a refresh or admin lookup."""
    monkeypatch.delenv("NDI_CLOUD_TOKEN", raising=False)

    def _set(*orgs):
        monkeypatch.setenv("NDI_CLOUD_ORGANIZATIONS", json.dumps(list(orgs)))

    return _set


def _make_client() -> MagicMock:
    """Return a mock CloudClient whose list call answers one dataset."""
    client = MagicMock()
    client.config.api_url = "https://api.ndi-cloud.com/v1"
    client.get.return_value = {
        "datasets": [{"id": "ds-1", "name": "Test"}],
        "totalNumber": 1,
    }
    return client


class TestListDatasets:
    """With an organization, one page of it; without, every organization."""

    def test_with_explicit_org_id(self, organizations):
        from ndi.cloud.api.datasets import listDatasets

        organizations(ALPHA, BETA)
        client = _make_client()
        result = listDatasets("org-explicit", client=client)

        client.get.assert_called_once()
        assert client.get.call_args.kwargs["organizationId"] == "org-explicit"
        assert result["datasets"][0]["name"] == "Test"

    def test_without_org_id_lists_every_organization(self, organizations):
        from ndi.cloud.api.datasets import listDatasets

        organizations(ALPHA, BETA)
        client = _make_client()
        pages = {
            "org-abc": {"datasets": [{"id": "ds-a", "name": "A"}], "totalNumber": 1},
            "org-def": {"datasets": [{"id": "ds-b", "name": "B"}], "totalNumber": 1},
        }
        client.get.side_effect = lambda path, **kw: pages[kw["organizationId"]]

        result = listDatasets(client=client)

        assert [d["id"] for d in result["datasets"]] == ["ds-a", "ds-b"]
        assert [d["organizationName"] for d in result["datasets"]] == [
            "Alpha Lab",
            "Beta Institute",
        ]
        assert [d["organizationId"] for d in result["datasets"]] == ["org-abc", "org-def"]
        assert result["totalNumber"] == 2
        assert result["page"] == 1

    def test_without_org_id_fetches_every_page(self, organizations):
        from ndi.cloud.api.datasets import listDatasets

        organizations(ALPHA)
        client = _make_client()
        client.get.side_effect = lambda path, params, **kw: {
            "datasets": [{"id": f"ds-{params['page']}"}],
            "totalNumber": 3,
        }

        result = listDatasets(client=client)

        assert [d["id"] for d in result["datasets"]] == ["ds-1", "ds-2", "ds-3"]


class TestListAllDatasets:
    def test_without_org_id_lists_every_organization(self, organizations):
        from ndi.cloud.api.datasets import listAllDatasets

        organizations(ALPHA, BETA)
        result = listAllDatasets(client=_make_client())

        assert len(result.data) == 2

    def test_with_org_id(self, organizations):
        from ndi.cloud.api.datasets import listAllDatasets

        organizations(ALPHA, BETA)
        client = _make_client()
        result = listAllDatasets("org-abc", client=client)

        assert len(result.data) == 1
        assert client.get.call_args.kwargs["organizationId"] == "org-abc"


class TestCreateDataset:
    """createDataset chooses the organization rather than assuming one."""

    def test_the_only_organization_is_used(self, organizations):
        from ndi.cloud.api.datasets import createDataset

        organizations(ALPHA)
        client = _make_client()
        client.post.return_value = {"id": "ds-new", "name": "NewDS"}
        createDataset(name="NewDS", client=client)

        assert client.post.call_args.kwargs["organizationId"] == "org-abc"

    def test_an_organization_can_be_named(self, organizations):
        from ndi.cloud.api.datasets import createDataset

        organizations(ALPHA, BETA)
        client = _make_client()
        createDataset(name="NewDS", organization_name="Beta Institute", client=client)

        assert client.post.call_args.kwargs["organizationId"] == "org-def"

    def test_several_organizations_need_a_choice(self, organizations):
        from ndi.cloud.api.datasets import createDataset

        organizations(ALPHA, BETA)
        client = _make_client()
        with pytest.raises(CloudOrganizationError) as excinfo:
            createDataset(name="NewDS", client=client)

        assert excinfo.value.identifier == "NDI:Cloud:OrganizationRequired"
        assert "Alpha Lab" in str(excinfo.value)
        client.post.assert_not_called()

    def test_an_organization_without_upload_is_refused(self, organizations):
        from ndi.cloud.api.datasets import createDataset

        organizations(ALPHA, ARCHIVE)
        client = _make_client()
        with pytest.raises(CloudOrganizationError) as excinfo:
            createDataset("org-ghi", name="NewDS", client=client)

        assert excinfo.value.identifier == "NDI:Cloud:OrganizationCannotUpload"
        client.post.assert_not_called()
