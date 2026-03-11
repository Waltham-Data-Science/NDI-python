"""Unit tests for ndi.cloud.api.datasets — no network required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        result = createDataset(name="NewDS", client=client)

        call_kwargs = client.post.call_args
        assert call_kwargs.kwargs["organizationId"] == "org-abc"

    def test_without_org_id_and_no_config_raises(self):
        from ndi.cloud.api.datasets import createDataset

        client = _make_client(org_id="")
        with pytest.raises(ValueError, match="org_id is required"):
            createDataset(name="NewDS", client=client)
