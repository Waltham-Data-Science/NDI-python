"""Offline tests for the NDI Cloud organization helpers.

MATLAB counterpart: tests/+ndi/+unittest/OrganizationsTest.m

Exercises ndi.cloud.internal.normalizeOrganizations, setOrganizations,
getOrganizations (cache path), chooseOrganization and
ndi.cloud.ui.dialog.organizationLabels / selectOrganization, plus the login
and logout ends of the cache. The token is cleared for every test so nothing
reaches the network.
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from ndi.cloud import auth, internal
from ndi.cloud.config import CloudConfig
from ndi.cloud.exceptions import CloudOrganizationError
from ndi.cloud.internal import (
    chooseOrganization,
    getOrganizations,
    normalizeOrganizations,
    setOrganizations,
)
from ndi.cloud.ui.dialog import organizationLabels, selectOrganization

THREE = [
    {"id": "org-1", "name": "Alpha Lab", "canUploadDataset": True},
    {"id": "org-2", "name": "Beta Institute", "canUploadDataset": True},
    {"id": "org-3", "name": "Gamma Archive", "canUploadDataset": False},
]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    for name in ("NDI_CLOUD_TOKEN", "NDI_CLOUD_ORGANIZATIONS", "NDI_CLOUD_ORGANIZATION_ID"):
        monkeypatch.delenv(name, raising=False)


def _identifier(call) -> str:
    with pytest.raises(CloudOrganizationError) as excinfo:
        call()
    return excinfo.value.identifier


class TestNormalize:
    def test_a_list_of_dicts(self):
        orgs = normalizeOrganizations(THREE)
        assert [o["id"] for o in orgs] == ["org-1", "org-2", "org-3"]
        assert [o["canUploadDataset"] for o in orgs] == [True, True, False]

    def test_missing_fields_and_entries_without_an_id(self):
        orgs = normalizeOrganizations([{"id": 7, "name": None}, {"name": "dropped"}, "junk"])
        assert orgs == [{"id": "7", "name": "", "canUploadDataset": True}]

    def test_a_single_dict_and_empty(self):
        assert normalizeOrganizations({"id": "org-1"})[0]["id"] == "org-1"
        assert normalizeOrganizations(None) == []
        assert normalizeOrganizations([]) == []

    def test_anything_else_is_refused(self):
        assert _identifier(lambda: normalizeOrganizations(42)) == "NDI:Cloud:InvalidOrganizations"


class TestCache:
    def test_round_trip(self):
        setOrganizations(THREE)
        assert getOrganizations() == normalizeOrganizations(THREE)

    def test_empty_clears(self):
        setOrganizations(THREE)
        setOrganizations(None)
        assert "NDI_CLOUD_ORGANIZATIONS" not in os.environ

    def test_an_empty_cache_is_fetched_and_kept(self):
        with mock.patch("ndi.cloud.api.users.me", return_value={"organizations": THREE[:1]}):
            assert [o["id"] for o in getOrganizations()] == ["org-1"]
        assert [o["id"] for o in getOrganizations()] == ["org-1"]  # from the cache now


class TestChoose:
    def test_the_only_organization(self):
        setOrganizations(THREE[:1])
        assert chooseOrganization(interactive=False) == ("org-1", "Alpha Lab")

    def test_by_name_and_by_id(self):
        setOrganizations(THREE)
        assert chooseOrganization("Beta Institute", interactive=False) == (
            "org-2",
            "Beta Institute",
        )
        assert chooseOrganization(organization_id="org-3", interactive=False)[0] == "org-3"

    def test_several_need_a_choice_when_no_one_can_be_asked(self):
        setOrganizations(THREE)
        assert (
            _identifier(lambda: chooseOrganization(interactive=False))
            == "NDI:Cloud:OrganizationRequired"
        )

    def test_require_upload_narrows_the_candidates(self):
        orgs = [dict(o) for o in THREE]
        orgs[1]["canUploadDataset"] = False
        setOrganizations(orgs)
        assert chooseOrganization(require_upload=True, interactive=False)[0] == "org-1"

    def test_require_upload_refuses_a_read_only_organization(self):
        setOrganizations(THREE)
        assert (
            _identifier(
                lambda: chooseOrganization("Gamma Archive", require_upload=True, interactive=False)
            )
            == "NDI:Cloud:OrganizationCannotUpload"
        )

    def test_an_administrator_may_upload_anywhere(self):
        setOrganizations(THREE[2:])
        with mock.patch.object(internal, "userIsAdmin", return_value=True):
            assert chooseOrganization(require_upload=True, interactive=False)[0] == "org-3"

    def test_no_uploadable_organization(self):
        setOrganizations(THREE[2:])
        assert (
            _identifier(lambda: chooseOrganization(require_upload=True, interactive=False))
            == "NDI:Cloud:NoUploadableOrganization"
        )

    def test_unknown_and_ambiguous(self):
        setOrganizations(THREE)
        assert (
            _identifier(lambda: chooseOrganization("Nope", interactive=False))
            == "NDI:Cloud:UnknownOrganization"
        )
        twins = [dict(o) for o in THREE]
        twins[1]["name"] = "Alpha Lab"
        setOrganizations(twins)
        assert (
            _identifier(lambda: chooseOrganization("Alpha Lab", interactive=False))
            == "NDI:Cloud:AmbiguousOrganization"
        )

    def test_name_and_id_are_mutually_exclusive(self):
        setOrganizations(THREE)
        assert (
            _identifier(lambda: chooseOrganization("Alpha Lab", "org-1", interactive=False))
            == "NDI:Cloud:OrganizationArguments"
        )

    def test_no_organizations_at_all(self):
        with mock.patch("ndi.cloud.api.users.me", return_value={"organizations": []}):
            assert (
                _identifier(lambda: chooseOrganization(interactive=False))
                == "NDI:Cloud:NoOrganizations"
            )


class TestAsking:
    def test_the_chooser_sees_names_and_its_index_picks(self):
        setOrganizations(THREE)
        seen = {}

        def chooser(labels, prompt):
            seen["labels"], seen["prompt"] = labels, prompt
            return 1

        assert chooseOrganization(interactive=True, chooser=chooser)[0] == "org-2"
        assert seen["labels"] == ["Alpha Lab", "Beta Institute", "Gamma Archive"]
        assert seen["prompt"] == "Select an organization:"

    def test_cancelling_is_its_own_error(self):
        setOrganizations(THREE)
        assert (
            _identifier(lambda: chooseOrganization(interactive=True, chooser=lambda *_: None))
            == "NDI:CloudDialog:UserCanceled"
        )

    def test_the_console_counts_from_one(self, monkeypatch, capsys):
        setOrganizations(THREE)
        answers = iter(["9", "3"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
        assert chooseOrganization(interactive=True)[0] == "org-3"
        assert "  1. Alpha Lab" in capsys.readouterr().out

    def test_select_organization_always_asks(self):
        setOrganizations(THREE[:1])
        asked = []
        selectOrganization(
            auto_select_single=False, chooser=lambda labels, p: asked.append(labels) or 0
        )
        assert asked == [["Alpha Lab"]]


class TestLabels:
    def test_names_ids_and_duplicates(self):
        assert organizationLabels(["Alpha", "Beta"], ["o1", "o2"]) == ["Alpha", "Beta"]
        assert organizationLabels(["", "Beta"], ["o1", "o2"]) == ["o1", "Beta"]
        assert organizationLabels(["Same", "Same"], ["o1", "o2"]) == [
            "Same  (o1)",
            "Same  (o2)",
        ]
        assert organizationLabels(["Only"], ["o1", "o2"]) == ["Only", "o2"]


class TestLoginAndLogout:
    def test_login_caches_every_organization(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"token": "tok", "user": {"organizations": THREE}}
        with mock.patch("requests.post", return_value=response):
            config = auth.login("a@example.com", "pw", CloudConfig(api_url="https://x.invalid"))
        assert config.token == "tok"
        assert [o["id"] for o in json.loads(os.environ["NDI_CLOUD_ORGANIZATIONS"])] == [
            "org-1",
            "org-2",
            "org-3",
        ]

    def test_logout_clears_the_cache(self):
        setOrganizations(THREE)
        with mock.patch("requests.post"):
            auth.logout(CloudConfig(api_url="https://x.invalid", token="tok"))
        assert internal._cachedOrganizations() == []


class TestDatasetOrganization:
    def test_read_from_the_dataset_record(self):
        client = mock.MagicMock()
        client.get.return_value = {"organizationId": "org-2"}
        assert internal._datasetOrganizationId("65a1b2c3d4e5f60718293a4b", client=client) == "org-2"

    def test_a_record_without_one_is_an_error(self):
        client = mock.MagicMock()
        client.get.return_value = {}
        assert (
            _identifier(
                lambda: internal._datasetOrganizationId("65a1b2c3d4e5f60718293a4b", client=client)
            )
            == "NDI:Cloud:NoOrganizations"
        )
