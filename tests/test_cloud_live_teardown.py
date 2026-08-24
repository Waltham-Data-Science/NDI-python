"""Offline tests for the cleanup helpers in ``tests/test_cloud_live.py``.

The live cloud tests themselves are credential-gated and never run here, but
their *teardown* is the thing that leaked 298 datasets into the prod and dev
tenancies while reporting nothing.  These tests pin the two properties that
failed before:

* the teardown reads the dataset's current state, so a submitted dataset gets
  un-submitted instead of hitting a delete the server silently refuses;
* a purge that did not end in a deletion produces a loud warning rather than
  ``except Exception: pass``.
"""

from __future__ import annotations

import types

import pytest

import tests.test_cloud_live as live
from ndi.cloud.exceptions import CloudAPIError
from tests.test_cloud_live import _purge_dataset_by_id, _report_purge
from tests.tools.cloud_janitor import DatasetOutcome

# NOTE: `_cleanup_stale_pytest_datasets` is reached through the module object,
# never imported by name. Importing a fixture into a test module re-registers
# it here -- and that one is module-scoped autouse, so every test in this file
# would demand the live `client` fixture and error at setup.

DS_ID = "a" * 24


class _RecordingAPI:
    def __init__(self, datasets=()):
        self.calls = []
        self.datasets = [dict(d) for d in datasets]

    def listAllDatasets(self, org_id=None, *, client=None):
        self.calls.append(("listAllDatasets", org_id))
        return list(self.datasets)

    def unpublishDataset(self, dataset_id, *, client=None):
        self.calls.append(("unpublishDataset", dataset_id))
        return {}

    def updateDataset(self, dataset_id, *, client=None, **fields):
        self.calls.append(("updateDataset", dataset_id, fields))
        return {}

    def deleteDataset(self, dataset_id, when="7d", *, client=None):
        self.calls.append(("deleteDataset", dataset_id, when))
        return {}


@pytest.fixture()
def recording_api(monkeypatch):
    api = _RecordingAPI()
    monkeypatch.setattr("tests.tools.cloud_janitor.default_api", lambda: api)
    return api


class TestPurgeDatasetById:
    def test_submitted_dataset_is_unsubmitted_before_delete(self, recording_api):
        def fake_get(dataset_id, *, client=None):
            return {"_id": dataset_id, "name": "NDI_PYTEST_TEMP_DATASET", "isSubmitted": True}

        outcome = _purge_dataset_by_id(DS_ID, client=None, getDataset=fake_get)

        assert outcome.status == "deleted"
        order = [c[0] for c in recording_api.calls]
        assert order == ["updateDataset", "deleteDataset"]

    def test_delete_still_attempted_when_state_read_fails(self, recording_api):
        def fake_get(dataset_id, *, client=None):
            raise CloudAPIError("not found", status_code=404)

        outcome = _purge_dataset_by_id(DS_ID, client=None, getDataset=fake_get)

        assert outcome.status == "deleted"
        assert recording_api.calls == [("deleteDataset", DS_ID, "now")]

    def test_delete_uses_when_now_not_the_default_seven_days(self, recording_api):
        def fake_get(dataset_id, *, client=None):
            return {"_id": dataset_id, "name": "NDI_PYTEST_TEMP_DATASET"}

        _purge_dataset_by_id(DS_ID, client=None, getDataset=fake_get)

        assert recording_api.calls == [("deleteDataset", DS_ID, "now")]


class TestReportPurge:
    def test_successful_purge_is_silent(self, recwarn):
        _report_purge(DatasetOutcome(DS_ID, "NDI_PYTEST_TEMP_DATASET", "deleted"))
        assert len(recwarn) == 0

    def test_failed_purge_warns_with_the_underlying_error(self):
        outcome = DatasetOutcome(
            DS_ID,
            "NDI_PYTEST_TEMP_DATASET",
            "failed",
            detail="delete: CloudAPIError(status=403): submitted datasets cannot be deleted",
            steps=("unsubmit-failed", "delete-failed"),
        )
        with pytest.warns(ResourceWarning) as record:
            _report_purge(outcome)
        message = str(record[0].message)
        assert DS_ID in message
        assert "403" in message
        assert "unsubmit-failed" in message


def _drain_fixture(fixture_func, **kwargs):
    """Run a yield-fixture's setup and teardown outside pytest's machinery."""
    raw = getattr(fixture_func, "__wrapped__", fixture_func)
    gen = raw(**kwargs)
    next(gen)
    try:
        next(gen)
    except StopIteration:
        pass


class TestStaleSweepRespectsReadonly:
    """The module-scoped sweep is autouse, so it fires in the read-only job too.

    That job runs against the production catalog and promises not to write. A
    sweep that deletes there -- even deleting only test litter -- makes the
    promise false, so read-only mode downgrades it to a dry run.
    """

    @pytest.fixture()
    def api_with_orphan(self, monkeypatch):
        api = _RecordingAPI([{"_id": DS_ID, "name": "NDI_PYTEST_TEMP_DATASET"}])
        monkeypatch.setattr("tests.tools.cloud_janitor.default_api", lambda: api)
        return api

    def test_readonly_sweep_deletes_nothing_but_still_reports(self, api_with_orphan, monkeypatch):
        monkeypatch.setenv("NDI_CLOUD_READONLY", "1")
        config = types.SimpleNamespace(org_id="org1")

        with pytest.warns(ResourceWarning) as record:
            _drain_fixture(live._cleanup_stale_pytest_datasets, client=None, cloud_config=config)

        assert [c[0] for c in api_with_orphan.calls] == ["listAllDatasets"]
        message = str(record[0].message)
        assert "read-only" in message
        assert DS_ID in message

    def test_normal_sweep_deletes(self, api_with_orphan, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_READONLY", raising=False)
        config = types.SimpleNamespace(org_id="org1")

        with pytest.warns(ResourceWarning):
            _drain_fixture(live._cleanup_stale_pytest_datasets, client=None, cloud_config=config)

        assert ("deleteDataset", DS_ID, "now") in api_with_orphan.calls
