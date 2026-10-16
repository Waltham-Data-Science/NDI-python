"""Unit tests for ndi.cloud.api.admin -- no network required.

Offline half of the port of NDI-matlab
``tests/+ndi/+unittest/+cloud/AdminOrganizationsTest.m`` (9dc83026,
NDI-matlab#1031); the live half is ``tests/test_cloud_admin_live.py``.

The client is a real :class:`CloudClient` over a stub transport, so the URL,
method, query, body and error mapping under test are the ones a caller
actually gets.
"""

from __future__ import annotations

import json
import types

import pydantic
import pytest

from ndi.cloud.api import admin
from ndi.cloud.client import CloudClient
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudAPIError, CloudAuthError, CloudError, CloudNotFoundError

API_URL = "https://api.example.test/v1"
ORG_ID = "65f0c0ffee0000000000aaaa"
USER_ID = "65f0c0ffee0000000000bbbb"
EMAIL = "person@example.com"


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
    """A stub ``requests.Session`` that records requests and replies in turn."""

    def __init__(self, *resps):
        self.resps = list(resps)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]


def make_client(*resps):
    client = CloudClient.__new__(CloudClient)
    client.config = CloudConfig(api_url=API_URL, token="test-token")
    client._session = Transport(*resps)
    client._can_reauth = False
    return client


def users_page(users, page=1, total_pages=1):
    return response(
        200,
        {
            "users": users,
            "page": page,
            "limit": 100,
            "total": len(users),
            "totalPages": total_pages,
        },
    )


def org(members=()):
    return {
        "id": ORG_ID,
        "name": "Lab",
        "canUploadDataset": False,
        "memberCount": len(members),
        "teams": [],
        "members": list(members),
    }


# ---------------------------------------------------------------------------
# Requests: method, path, query and body
# ---------------------------------------------------------------------------


class TestRequests:
    def test_list_organizations_defaults(self):
        client = make_client(response(200, {"organizations": [], "totalPages": 0}))
        b, answer, status, url = admin.listOrganizations(client=client)
        call = client._session.calls[0]
        assert call["method"] == "GET"
        assert call["url"] == f"{API_URL}/admin/organizations"
        # q is left out when the query is empty; page_size goes as limit.
        assert call["params"] == {"page": 1, "limit": 25}
        assert b is True and status == 200 and answer["organizations"] == []

    def test_list_users_sends_query(self):
        client = make_client(users_page([]))
        admin.listUsers(query="lab", page=2, page_size=100, client=client)
        call = client._session.calls[0]
        assert call["url"] == f"{API_URL}/admin/users"
        assert call["params"] == {"page": 2, "limit": 100, "q": "lab"}

    @pytest.mark.parametrize("page_size", [0, 101])
    def test_page_size_must_be_1_to_100(self, page_size):
        with pytest.raises(pydantic.ValidationError):
            admin.listOrganizations(page_size=page_size, client=make_client(response()))

    def test_get_organization(self):
        client = make_client(response(200, org()))
        result = admin.getOrganization(ORG_ID, client=client)
        assert client._session.calls[0]["url"] == f"{API_URL}/admin/organizations/{ORG_ID}"
        assert result.data["id"] == ORG_ID

    def test_create_organization(self):
        client = make_client(response(201, org(), "Created"))
        result = admin.createOrganization("Lab", can_upload_dataset=True, client=client)
        call = client._session.calls[0]
        assert call["method"] == "POST"
        assert call["json"] == {"name": "Lab", "canUploadDataset": True}
        assert result.status_code == 201

    def test_update_organization_sends_only_given_fields(self):
        client = make_client(response(200, org()))
        admin.updateOrganization(ORG_ID, can_upload_dataset=False, client=client)
        call = client._session.calls[0]
        assert call["method"] == "PATCH"
        assert call["url"] == f"{API_URL}/admin/organizations/{ORG_ID}"
        assert call["json"] == {"canUploadDataset": False}

    def test_update_organization_needs_a_field(self):
        client = make_client(response(200, org()))
        with pytest.raises(ValueError, match="at least one"):
            admin.updateOrganization(ORG_ID, client=client)
        assert client._session.calls == []

    def test_add_member(self):
        client = make_client(response(200, org([{"id": USER_ID}])))
        admin.addOrganizationMember(ORG_ID, USER_ID, client=client)
        call = client._session.calls[0]
        assert call["method"] == "POST"
        assert call["url"] == f"{API_URL}/admin/organizations/{ORG_ID}/members"
        assert call["json"] == {"userId": USER_ID}

    def test_remove_member(self):
        client = make_client(response(200, org()))
        admin.removeOrganizationMember(ORG_ID, USER_ID, client=client)
        call = client._session.calls[0]
        assert call["method"] == "DELETE"
        assert call["url"] == f"{API_URL}/admin/organizations/{ORG_ID}/members/{USER_ID}"

    def test_get_user(self):
        client = make_client(response(200, {"id": USER_ID, "email": EMAIL}))
        admin.getUser(USER_ID, client=client)
        assert client._session.calls[0]["url"] == f"{API_URL}/admin/users/{USER_ID}"


# ---------------------------------------------------------------------------
# Errors map as for every other ndi.cloud.api function
# ---------------------------------------------------------------------------


class TestErrors:
    def test_non_admin_is_refused(self):
        client = make_client(response(403, {"message": {"error": "FORBIDDEN"}}))
        with pytest.raises(CloudAuthError):
            admin.listOrganizations(client=client)

    def test_unknown_organization(self):
        client = make_client(response(404, {"error": "Organization not found"}))
        with pytest.raises(CloudNotFoundError):
            admin.getOrganization(ORG_ID, client=client)

    def test_malformed_id(self):
        client = make_client(response(400, {"error": "Invalid organization id"}))
        with pytest.raises(CloudAPIError) as info:
            admin.getOrganization("not-an-id", client=client)
        assert info.value.status_code == 400


# ---------------------------------------------------------------------------
# findUserByEmail and the helpers built on it
# ---------------------------------------------------------------------------


class TestFindUserByEmail:
    def test_exact_match_ignoring_case(self):
        users = [
            {"id": "65f0c0ffee0000000000cccc", "email": "jim" + EMAIL},
            {"id": USER_ID, "email": EMAIL},
        ]
        client = make_client(users_page(users))
        result = admin.findUserByEmail("  PERSON@example.com ", client=client)
        assert result.data["id"] == USER_ID
        assert client._session.calls[0]["params"]["q"] == "PERSON@example.com"

    def test_pages_through_results(self):
        client = make_client(
            users_page([{"id": "65f0c0ffee0000000000cccc", "email": "jim" + EMAIL}], 1, 2),
            users_page([{"id": USER_ID, "email": EMAIL}], 2, 2),
        )
        result = admin.findUserByEmail(EMAIL, client=client)
        assert result.data["id"] == USER_ID
        assert [c["params"]["page"] for c in client._session.calls] == [1, 2]

    def test_no_match_raises(self):
        client = make_client(users_page([{"id": USER_ID, "email": "jim" + EMAIL}]))
        with pytest.raises(CloudNotFoundError, match="No active NDI Cloud user"):
            admin.findUserByEmail(EMAIL, client=client)

    def test_two_matches_raise(self):
        users = [
            {"id": USER_ID, "email": EMAIL},
            {"id": "65f0c0ffee0000000000cccc", "email": EMAIL},
        ]
        client = make_client(users_page(users))
        with pytest.raises(CloudError, match="2 NDI Cloud users"):
            admin.findUserByEmail(EMAIL, client=client)

    def test_empty_email_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            admin.findUserByEmail("", client=make_client(users_page([])))

    def test_add_member_by_email(self):
        client = make_client(
            users_page([{"id": USER_ID, "email": EMAIL}]),
            response(200, org([{"id": USER_ID, "email": EMAIL}])),
        )
        result = admin.addOrganizationMemberByEmail(ORG_ID, EMAIL, client=client)
        add = client._session.calls[1]
        assert add["method"] == "POST" and add["json"] == {"userId": USER_ID}
        assert result.data["memberCount"] == 1

    def test_remove_member_by_email(self):
        client = make_client(users_page([{"id": USER_ID, "email": EMAIL}]), response(200, org()))
        admin.removeOrganizationMemberByEmail(ORG_ID, EMAIL, client=client)
        remove = client._session.calls[1]
        assert remove["method"] == "DELETE"
        assert remove["url"].endswith(f"/members/{USER_ID}")

    def test_add_by_email_stops_when_not_found(self):
        client = make_client(users_page([]))
        with pytest.raises(CloudNotFoundError):
            admin.addOrganizationMemberByEmail(ORG_ID, EMAIL, client=client)
        assert len(client._session.calls) == 1


class TestGetUserOrganizations:
    ORGS = [{"id": ORG_ID, "name": "Lab"}, {"id": "65f0c0ffee0000000000dddd", "name": "Core"}]

    def expected(self):
        return {
            "userID": USER_ID,
            "email": EMAIL,
            "organizationID": [ORG_ID, "65f0c0ffee0000000000dddd"],
            "organizationName": ["Lab", "Core"],
        }

    def test_own_organizations_use_users_me(self):
        client = make_client(
            response(200, {"id": USER_ID, "email": EMAIL, "organizations": self.ORGS})
        )
        result = admin.getUserOrganizations(client=client)
        assert client._session.calls[0]["url"] == f"{API_URL}/users/me"
        assert result.data == self.expected()

    def test_by_user_id(self):
        client = make_client(
            response(200, {"id": USER_ID, "email": EMAIL, "organizations": self.ORGS})
        )
        result = admin.getUserOrganizations(USER_ID, client=client)
        assert client._session.calls[0]["url"] == f"{API_URL}/admin/users/{USER_ID}"
        assert result.data == self.expected()

    def test_by_email(self):
        client = make_client(
            users_page([{"id": USER_ID, "email": EMAIL}]),
            response(200, {"id": USER_ID, "email": EMAIL, "organizations": self.ORGS}),
        )
        result = admin.getUserOrganizations(EMAIL, client=client)
        assert client._session.calls[1]["url"] == f"{API_URL}/admin/users/{USER_ID}"
        assert result.data == self.expected()

    def test_no_organizations(self):
        client = make_client(response(200, {"id": USER_ID, "email": EMAIL, "organizations": []}))
        result = admin.getUserOrganizations(client=client)
        assert result.data["organizationID"] == [] and result.data["organizationName"] == []

    def test_blank_user_rejected(self):
        with pytest.raises(ValueError):
            admin.getUserOrganizations("  ", client=make_client(response()))
