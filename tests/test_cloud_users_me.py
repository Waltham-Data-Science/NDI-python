"""Tests for ``ndi.cloud.api.users.me`` organization convenience fields.

Python equivalent of the MATLAB work in NDI-matlab ``f2b91923f`` (PR #858),
which taught ``ndi.cloud.api.implementation.users.Me`` to derive parallel
``organizationID`` / ``organizationName`` / ``organizationCanUploadDataset``
arrays from the raw ``organizations`` list returned by ``GET /users/me``.

No live cloud: the client's HTTP layer is mocked throughout.
"""

from __future__ import annotations

import json
import unittest.mock as mock

import pytest

from ndi.cloud.api.users import me


def _resp(status: int, body, reason: str = "OK"):
    """Build a fake ``requests.Response`` for ``CloudClient._handle_response``."""
    r = mock.MagicMock()
    r.status_code = status
    r.reason = reason
    text = json.dumps(body)
    r.text = text
    r.content = text.encode()
    r.headers = {}
    return r


def _client_returning(body):
    """A ``CloudClient`` whose ``requests.Session`` returns *body* for any call."""
    from ndi.cloud.client import CloudClient
    from ndi.cloud.config import CloudConfig

    client = CloudClient(CloudConfig(api_url="https://api.example.com", token="t"))
    session = mock.MagicMock()
    session.request.return_value = _resp(200, body)
    client._session = session
    return client


BASE_USER = {
    "id": "user-1",
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "isValidated": True,
    "isAdmin": False,
    "bookmarkedDatasetIds": [],
}


def _user(**overrides):
    payload = dict(BASE_USER)
    payload.update(overrides)
    return payload


TWO_ORGS = [
    {"id": "org-1", "name": "Rayo Lab", "canUploadDataset": True},
    {"id": "org-2", "name": "VH Lab", "canUploadDataset": False},
]


class TestMeOrganizationFields:
    def test_derives_parallel_organization_arrays(self):
        result = me(client=_client_returning(_user(organizations=TWO_ORGS)))

        assert result.get("organizationID") == ["org-1", "org-2"]
        assert result.get("organizationName") == ["Rayo Lab", "VH Lab"]
        assert result.get("organizationCanUploadDataset") == [True, False]

    def test_can_upload_entries_are_real_bools(self):
        """MATLAB casts with logical(); the Python port must not leak 1/0."""
        orgs = [{"id": "o", "name": "n", "canUploadDataset": 1}]
        result = me(client=_client_returning(_user(organizations=orgs)))

        flags = result.get("organizationCanUploadDataset")
        assert flags == [True]
        assert all(isinstance(f, bool) for f in flags)

    def test_ids_and_names_are_coerced_to_str(self):
        """Mirrors MATLAB's ``asChar = @(v) char(string(v))``."""
        orgs = [{"id": 12345, "name": 678, "canUploadDataset": True}]
        result = me(client=_client_returning(_user(organizations=orgs)))

        assert result.get("organizationID") == ["12345"]
        assert result.get("organizationName") == ["678"]

    def test_raw_organizations_are_left_untouched(self):
        """Callers that want the full structs still get them."""
        result = me(client=_client_returning(_user(organizations=TWO_ORGS)))

        assert result.get("organizations") == TWO_ORGS

    def test_missing_organizations_field_yields_empty_arrays(self):
        """MATLAB always defines the three fields, even with no organizations."""
        result = me(client=_client_returning(_user()))

        assert result.get("organizationID") == []
        assert result.get("organizationName") == []
        assert result.get("organizationCanUploadDataset") == []

    def test_empty_organizations_list_yields_empty_arrays(self):
        result = me(client=_client_returning(_user(organizations=[])))

        assert result.get("organizationID") == []
        assert result.get("organizationName") == []
        assert result.get("organizationCanUploadDataset") == []

    def test_single_organization_object_is_normalized(self):
        """A bare object, not a list — MATLAB's scalar-struct case."""
        result = me(client=_client_returning(_user(organizations=TWO_ORGS[0])))

        assert result.get("organizationID") == ["org-1"]
        assert result.get("organizationName") == ["Rayo Lab"]
        assert result.get("organizationCanUploadDataset") == [True]

    def test_non_object_entries_are_skipped(self):
        """MATLAB's ``if ~isstruct(org); continue; end``."""
        orgs = ["not-an-org", None, TWO_ORGS[0]]
        result = me(client=_client_returning(_user(organizations=orgs)))

        assert result.get("organizationID") == ["org-1"]
        assert result.get("organizationName") == ["Rayo Lab"]

    def test_organizations_of_an_unexpected_type_yield_empty_arrays(self):
        """A scalar where a list was expected must not raise."""
        result = me(client=_client_returning(_user(organizations="org-1")))

        assert result.get("organizationID") == []
        assert result.get("organizationName") == []
        assert result.get("organizationCanUploadDataset") == []

    @pytest.mark.parametrize("missing", ["id", "name", "canUploadDataset"])
    def test_a_missing_key_only_drops_that_field(self, missing):
        """MATLAB appends per field independently; absent keys are skipped."""
        org = {k: v for k, v in TWO_ORGS[0].items() if k != missing}
        result = me(client=_client_returning(_user(organizations=[org])))

        expected = {
            "id": "organizationID",
            "name": "organizationName",
            "canUploadDataset": "organizationCanUploadDataset",
        }[missing]
        assert result.get(expected) == []
        for field in ("organizationID", "organizationName", "organizationCanUploadDataset"):
            if field != expected:
                assert len(result.get(field)) == 1


class TestMeResponseShape:
    def test_still_returns_the_api_response_wrapper(self):
        """The derivation must not flatten away the APIResponse metadata."""
        from ndi.cloud.client import APIResponse

        result = me(client=_client_returning(_user(organizations=TWO_ORGS)))

        assert isinstance(result, APIResponse)
        assert result.success is True
        assert result.status_code == 200
        assert result.url.endswith("/users/me")

    def test_existing_user_fields_survive(self):
        result = me(client=_client_returning(_user(organizations=TWO_ORGS)))

        assert result.get("id") == "user-1"
        assert result.get("email") == "ada@example.com"
        assert result.get("name") == "Ada Lovelace"

    def test_non_dict_payload_does_not_raise(self):
        """A body that is not a JSON object is returned unchanged."""
        result = me(client=_client_returning(["unexpected"]))

        assert result.data == ["unexpected"]
