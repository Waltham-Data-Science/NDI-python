"""Unit tests for ndi.cloud.api.datasets.reassignDatasetOrganization -- no network required.

Offline half of the port of NDI-matlab
``tests/+ndi/+unittest/+cloud/DatasetOrganizationTest.m`` (47647f5); the
live half is ``tests/test_cloud_dataset_organization_live.py``.

The client is a real :class:`CloudClient` over a stub transport, so the URL,
method, body and error mapping under test are the ones a caller actually
gets.
"""

from __future__ import annotations

import json
import types

import pydantic
import pytest

from ndi.cloud.api.datasets import reassignDatasetOrganization
from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudAPIError, CloudAuthError, CloudNotFoundError

API_URL = "https://api.example.test/v1"
DATASET_ID = "65f0c0ffee0000000000dddd"
ORG_ID = "65f0c0ffee0000000000aaaa"
REASON = "Lab merged into the Smith lab organization"


def response(status=200, body=None, reason=""):
    """Something shaped like a ``requests.Response``."""
    text = json.dumps(body) if body is not None else ""

    def _json():
        if body is None:
            raise ValueError("no json")
        return body

    return types.SimpleNamespace(
        status_code=status,
        reason=reason,
        json=_json,
        text=text,
        content=text.encode(),
        headers={},
        elapsed=None,
    )


class Transport:
    """A stub ``requests.Session`` that records requests and always gives one reply."""

    def __init__(self, resp):
        self.resp = resp
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.resp


def make_client(resp):
    client = CloudClient.__new__(CloudClient)
    client.config = CloudConfig(api_url=API_URL, token="test-token")
    client._session = Transport(resp)
    client._can_reauth = False
    return client


def test_posts_organization_and_reason_to_admin_endpoint():
    moved = {"id": DATASET_ID, "name": "ds", "organizationId": ORG_ID}
    client = make_client(response(200, moved))

    b, answer, status, url = reassignDatasetOrganization(DATASET_ID, ORG_ID, REASON, client=client)

    call = client._session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{API_URL}/admin/datasets/{DATASET_ID}/organization"
    assert call["json"] == {"organizationId": ORG_ID, "reason": REASON}
    assert b is True and status == 200
    assert answer["organizationId"] == ORG_ID


@pytest.mark.parametrize("reason", ["   ", "\t\n"])
def test_blank_reason_is_refused_before_any_request(reason):
    client = make_client(response(200, {}))
    with pytest.raises(ValueError):
        reassignDatasetOrganization(DATASET_ID, ORG_ID, reason, client=client)
    assert client._session.calls == []


@pytest.mark.parametrize(
    "args", [("", ORG_ID, REASON), (DATASET_ID, "", REASON), (DATASET_ID, ORG_ID, "")]
)
def test_empty_arguments_fail_validation(args):
    client = make_client(response(200, {}))
    with pytest.raises(pydantic.ValidationError):
        reassignDatasetOrganization(*args, client=client)
    assert client._session.calls == []


def test_non_admin_raises_auth_error():
    client = make_client(response(403, {"error": "Forbidden"}, "Forbidden"))
    with pytest.raises(CloudAuthError):
        reassignDatasetOrganization(DATASET_ID, ORG_ID, REASON, client=client)


def test_unknown_dataset_or_organization_raises_not_found():
    client = make_client(response(404, {"error": "Organization not found"}, "Not Found"))
    with pytest.raises(CloudNotFoundError):
        reassignDatasetOrganization(DATASET_ID, ORG_ID, REASON, client=client)


@pytest.mark.parametrize("status", [400, 409])
def test_refusals_raise_api_error_with_status(status):
    client = make_client(response(status, {"error": "refused"}))
    with pytest.raises(CloudAPIError) as info:
        reassignDatasetOrganization(DATASET_ID, ORG_ID, REASON, client=client)
    assert info.value.status_code == status
