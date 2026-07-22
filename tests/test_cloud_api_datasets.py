"""Unit tests for ndi.cloud.api.datasets — no network required."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_client(org_id: str = "org-123") -> MagicMock:
    """Return a mock CloudClient with a config carrying *org_id*."""
    client = MagicMock()
    client.config.org_id = org_id
    client.config.api_url = "https://api.ndi-cloud.com/v1"
    client.get.return_value = {
        "datasets": [{"id": "ds-1", "name": "Test"}],
        "totalNumber": 1,
    }
    return client


class TestListDatasets:
    """listDatasets should work with or without an explicit org_id."""

    def test_without_org_id_uses_client_config(self):
        """Calling listDatasets() with no org_id should resolve it from client config."""
        from ndi.cloud.api.datasets import listDatasets

        client = _make_client(org_id="org-abc")
        result = listDatasets(client=client)

        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert call_kwargs.kwargs["organizationId"] == "org-abc"
        assert result["datasets"][0]["name"] == "Test"

    def test_with_explicit_org_id(self):
        """Passing org_id explicitly should use that value."""
        from ndi.cloud.api.datasets import listDatasets

        client = _make_client(org_id="org-abc")
        listDatasets("org-explicit", client=client)

        call_kwargs = client.get.call_args
        assert call_kwargs.kwargs["organizationId"] == "org-explicit"

    def test_no_org_id_and_no_config_raises(self):
        """If org_id is omitted and client config has none, raise ValueError."""
        from ndi.cloud.api.datasets import listDatasets

        client = _make_client(org_id="")
        with pytest.raises(ValueError, match="org_id is required"):
            listDatasets(client=client)


class TestListAllDatasets:
    """listAllDatasets should work without an explicit org_id."""

    def test_without_org_id(self):
        from ndi.cloud.api.datasets import listAllDatasets

        client = _make_client(org_id="org-abc")
        result = listAllDatasets(client=client)

        assert len(result.data) == 1


class TestCreateDataset:
    """createDataset should work without an explicit org_id."""

    def test_without_org_id(self):
        from ndi.cloud.api.datasets import createDataset

        client = _make_client(org_id="org-abc")
        client.post.return_value = {"id": "ds-new", "name": "NewDS"}
        createDataset(name="NewDS", client=client)

        call_kwargs = client.post.call_args
        assert call_kwargs.kwargs["organizationId"] == "org-abc"

    def test_without_org_id_and_no_config_raises(self):
        from ndi.cloud.api.datasets import createDataset

        client = _make_client(org_id="")
        with pytest.raises(ValueError, match="org_id is required"):
            createDataset(name="NewDS", client=client)


class TestCreateDatasetBranch:
    def test_sends_branch_name(self):
        from ndi.cloud.api.datasets import createDatasetBranch

        client = MagicMock()
        client.post.return_value = {"ok": True}
        createDatasetBranch("66aabbccddeeff0011223344", "my-branch", client=client)

        client.post.assert_called_once()
        assert client.post.call_args.kwargs["json"] == {"branchName": "my-branch"}
        assert client.post.call_args.kwargs["datasetId"] == "66aabbccddeeff0011223344"

    def test_empty_branch_name_rejected(self):
        from ndi.cloud.api.datasets import createDatasetBranch

        client = MagicMock()
        with pytest.raises(Exception):
            createDatasetBranch("66aabbccddeeff0011223344", "", client=client)


class TestGetBranches:
    def test_unwraps_envelope(self):
        from ndi.cloud.api.datasets import getBranches

        client = MagicMock()
        client.get.return_value = {"branches": [{"datasetId": "d1"}, {"datasetId": "d2"}]}
        out = getBranches("66aabbccddeeff0011223344", client=client)
        assert isinstance(out, list)
        assert [b["datasetId"] for b in out] == ["d1", "d2"]

    def test_bare_list_passthrough(self):
        from ndi.cloud.api.datasets import getBranches

        client = MagicMock()
        client.get.return_value = [{"datasetId": "d1"}]
        out = getBranches("66aabbccddeeff0011223344", client=client)
        assert out == [{"datasetId": "d1"}]
