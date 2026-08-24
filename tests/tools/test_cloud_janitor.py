"""Unit tests for the leftover-dataset janitor (``tests/tools/cloud_janitor.py``).

Every test here runs against an in-memory fake of ``ndi.cloud.api.datasets``.
Nothing touches the network, so this module runs in ordinary CI.

The regression these tests exist to prevent is documented in the August 2026
CI audit: the previous in-test janitor
(``tests/test_cloud_live.py::_cleanup_stale_pytest_datasets``) warned loudly
that it was "cleaning up N leftover datasets", called ``deleteDataset`` inside
``except Exception: pass``, and deleted **zero** of 294 datasets across three
days while still exiting green.  A janitor that cannot fail is not a janitor,
so the tests below pin three properties:

1. deletion is *verified* by re-listing afterwards, never assumed from the
   absence of an exception;
2. failures are reported per dataset with the underlying error text;
3. residual datasets can make the process exit non-zero.
"""

from __future__ import annotations

import types

import pytest

from ndi.cloud.exceptions import CloudAPIError
from tests.tools import cloud_janitor

# ---------------------------------------------------------------------------
# Fake API
# ---------------------------------------------------------------------------


class FakeDatasetsAPI:
    """In-memory stand-in for ``ndi.cloud.api.datasets``.

    ``delete_effect`` controls what ``deleteDataset`` does:
        "delete"  -- remove it from the store (a working server)
        "noop"    -- return success but leave the dataset in place
                     (the observed NDI Cloud behaviour for submitted datasets)
        "raise"   -- raise ``CloudAPIError`` with ``delete_status``
    """

    def __init__(self, datasets, delete_effect="delete", delete_status=500):
        self.store = {d["_id"]: dict(d) for d in datasets}
        self.delete_effect = delete_effect
        self.delete_status = delete_status
        self.calls: list[tuple] = []
        self.list_all_pages = 0

    # -- reads --------------------------------------------------------------

    def listAllDatasets(self, org_id=None, *, client=None):
        self.calls.append(("listAllDatasets", org_id))
        self.list_all_pages += 1
        return list(self.store.values())

    def listDatasets(self, org_id=None, page=1, page_size=1000, *, client=None):
        # Present so that a janitor reaching for the single-page endpoint is
        # detectable rather than an AttributeError.
        self.calls.append(("listDatasets", org_id))
        return {"datasets": list(self.store.values())}

    # -- writes -------------------------------------------------------------

    def unpublishDataset(self, dataset_id, *, client=None):
        self.calls.append(("unpublishDataset", dataset_id))
        self.store[dataset_id]["isPublished"] = False
        return {"message": "unpublished"}

    def updateDataset(self, dataset_id, *, client=None, **fields):
        self.calls.append(("updateDataset", dataset_id, fields))
        self.store[dataset_id].update(fields)
        return {"message": "updated"}

    def deleteDataset(self, dataset_id, when="7d", *, client=None):
        self.calls.append(("deleteDataset", dataset_id, when))
        if self.delete_effect == "raise":
            raise CloudAPIError("boom", status_code=self.delete_status)
        if self.delete_effect == "delete":
            self.store.pop(dataset_id, None)
        return {"message": "deleted"}

    # -- helpers ------------------------------------------------------------

    def names_called(self, name):
        return [c for c in self.calls if c[0] == name]


def _ds(ds_id, name="NDI_PYTEST_TEMP_DATASET", **extra):
    d = {"_id": ds_id, "name": name}
    d.update(extra)
    return d


@pytest.fixture()
def no_sleep():
    """Retry back-off must not actually sleep in unit tests."""
    return lambda _seconds: None


# ---------------------------------------------------------------------------
# select_stale
# ---------------------------------------------------------------------------


class TestSelectStale:
    def test_selects_only_matching_prefix(self):
        datasets = [
            _ds("a" * 24, "NDI_PYTEST_TEMP_DATASET"),
            _ds("b" * 24, "NDI_PYTEST_WRITE_CHECK"),
            _ds("c" * 24, "Real Lab Dataset"),
            _ds("d" * 24, "prefixed NDI_PYTEST in the middle"),
        ]
        stale = cloud_janitor.select_stale(datasets, prefix="NDI_PYTEST")
        assert [d["_id"] for d in stale] == ["a" * 24, "b" * 24]

    def test_ignores_datasets_without_an_id(self):
        datasets = [_ds("", "NDI_PYTEST_TEMP_DATASET"), {"name": "NDI_PYTEST_NO_ID"}]
        assert cloud_janitor.select_stale(datasets, prefix="NDI_PYTEST") == []

    def test_accepts_id_key_as_well_as_underscore_id(self):
        datasets = [{"id": "e" * 24, "name": "NDI_PYTEST_TEMP_DATASET"}]
        stale = cloud_janitor.select_stale(datasets, prefix="NDI_PYTEST")
        assert cloud_janitor.dataset_id_of(stale[0]) == "e" * 24

    def test_min_age_excludes_recent_datasets(self):
        now = 1_000_000.0
        recent = _ds("a" * 24, createdAt="2026-08-24T00:00:00.000Z")
        old = _ds("b" * 24, createdAt="2026-08-01T00:00:00.000Z")
        datasets = [recent, old]
        # A 24-hour floor with "now" pinned just after the recent creation.
        selected = cloud_janitor.select_stale(
            datasets,
            prefix="NDI_PYTEST",
            min_age_hours=24.0,
            now=cloud_janitor.parse_timestamp("2026-08-24T06:00:00.000Z"),
        )
        assert [d["_id"] for d in selected] == ["b" * 24]
        assert now  # keeps the literal meaningful to readers

    def test_min_age_zero_selects_everything_matching(self):
        datasets = [_ds("a" * 24, createdAt="2026-08-24T00:00:00.000Z")]
        selected = cloud_janitor.select_stale(datasets, prefix="NDI_PYTEST", min_age_hours=0.0)
        assert len(selected) == 1

    def test_unknown_age_is_not_silently_deleted_under_an_age_floor(self):
        """A dataset with no parseable timestamp must not be assumed old."""
        datasets = [_ds("a" * 24)]  # no createdAt at all
        assert cloud_janitor.dataset_age_hours(datasets[0]) is None
        selected = cloud_janitor.select_stale(datasets, prefix="NDI_PYTEST", min_age_hours=24.0)
        assert selected == []


# ---------------------------------------------------------------------------
# purge_dataset
# ---------------------------------------------------------------------------


class TestPurgeDataset:
    def test_plain_dataset_is_hard_deleted(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)])
        outcome = cloud_janitor.purge_dataset(_ds("a" * 24), api=api, client=None, sleep=no_sleep)
        assert outcome.status == "deleted"
        assert api.names_called("deleteDataset") == [("deleteDataset", "a" * 24, "now")]
        assert api.names_called("updateDataset") == []
        assert api.names_called("unpublishDataset") == []

    def test_published_dataset_is_unpublished_before_delete(self, no_sleep):
        ds = _ds("a" * 24, isPublished=True)
        api = FakeDatasetsAPI([ds])
        outcome = cloud_janitor.purge_dataset(ds, api=api, client=None, sleep=no_sleep)
        assert outcome.status == "deleted"
        order = [c[0] for c in api.calls]
        assert order.index("unpublishDataset") < order.index("deleteDataset")

    def test_submitted_dataset_is_unsubmitted_before_delete(self, no_sleep):
        """The observed leak source: submitted datasets refuse a hard delete."""
        ds = _ds("a" * 24, isSubmitted=True)
        api = FakeDatasetsAPI([ds])
        outcome = cloud_janitor.purge_dataset(ds, api=api, client=None, sleep=no_sleep)
        assert outcome.status == "deleted"
        order = [c[0] for c in api.calls]
        assert order.index("updateDataset") < order.index("deleteDataset")
        assert api.names_called("updateDataset")[0][2] == {"isSubmitted": False}
        assert "unsubmit" in outcome.steps

    def test_unsubmit_failure_is_recorded_but_delete_is_still_attempted(self, no_sleep):
        ds = _ds("a" * 24, isSubmitted=True)

        def failing_update(dataset_id, *, client=None, **fields):
            raise CloudAPIError("no un-submit endpoint", status_code=405)

        api = FakeDatasetsAPI([ds])
        api.updateDataset = failing_update
        outcome = cloud_janitor.purge_dataset(ds, api=api, client=None, sleep=no_sleep)
        assert outcome.status == "deleted"
        assert "unsubmit-failed" in outcome.steps
        assert "405" in outcome.detail
        assert api.names_called("deleteDataset")

    def test_delete_failure_surfaces_the_error_instead_of_swallowing_it(self, no_sleep):
        ds = _ds("a" * 24)
        api = FakeDatasetsAPI([ds], delete_effect="raise", delete_status=403)
        outcome = cloud_janitor.purge_dataset(ds, api=api, client=None, sleep=no_sleep)
        assert outcome.status == "failed"
        assert "403" in outcome.detail
        assert "boom" in outcome.detail

    def test_delete_is_retried_on_gateway_timeout(self, no_sleep):
        ds = _ds("a" * 24)
        api = FakeDatasetsAPI([ds])
        attempts = {"n": 0}
        real_delete = api.deleteDataset

        def flaky(dataset_id, when="7d", *, client=None):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise CloudAPIError("gateway timeout", status_code=504)
            return real_delete(dataset_id, when=when, client=client)

        api.deleteDataset = flaky
        outcome = cloud_janitor.purge_dataset(ds, api=api, client=None, sleep=no_sleep)
        assert outcome.status == "deleted"
        assert attempts["n"] == 3

    def test_non_retryable_status_is_not_retried(self, no_sleep):
        ds = _ds("a" * 24)
        api = FakeDatasetsAPI([ds], delete_effect="raise", delete_status=400)
        attempts = {"n": 0}
        raising = api.deleteDataset

        def counting(dataset_id, when="7d", *, client=None):
            attempts["n"] += 1
            return raising(dataset_id, when=when, client=client)

        api.deleteDataset = counting
        outcome = cloud_janitor.purge_dataset(ds, api=api, client=None, sleep=no_sleep)
        assert outcome.status == "failed"
        assert attempts["n"] == 1

    def test_dry_run_makes_no_write_calls(self, no_sleep):
        ds = _ds("a" * 24, isSubmitted=True, isPublished=True)
        api = FakeDatasetsAPI([ds])
        outcome = cloud_janitor.purge_dataset(
            ds, api=api, client=None, dry_run=True, sleep=no_sleep
        )
        assert outcome.status == "dry-run"
        assert api.calls == []


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------


class TestSweep:
    def test_uses_listAllDatasets_not_single_page_listDatasets(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)])
        cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        assert api.names_called("listAllDatasets")
        assert api.names_called("listDatasets") == []

    def test_clean_sweep_reports_no_residual_and_exits_zero(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24), _ds("b" * 24)])
        report = cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        assert report.targeted == 2
        assert report.deleted == 2
        assert report.failed == 0
        assert report.residual == []
        assert report.exit_code(fail_on_residual=True) == 0

    def test_a_delete_that_silently_does_nothing_is_reported_as_residual(self, no_sleep):
        """The exact August 2026 defect: 294 IDs 'deleted', 294 still present."""
        api = FakeDatasetsAPI([_ds("a" * 24), _ds("b" * 24)], delete_effect="noop")
        report = cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        # The API raised nothing, so a naive janitor would call this success.
        assert report.failed == 0
        # Verification by re-listing catches it anyway.
        assert sorted(cloud_janitor.dataset_id_of(d) for d in report.residual) == [
            "a" * 24,
            "b" * 24,
        ]
        assert report.exit_code(fail_on_residual=True) == 1
        assert report.exit_code(fail_on_residual=False) == 0

    def test_residual_only_counts_datasets_the_sweep_targeted(self, no_sleep):
        api = FakeDatasetsAPI(
            [_ds("a" * 24), _ds("c" * 24, "Real Lab Dataset")], delete_effect="noop"
        )
        report = cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        assert [cloud_janitor.dataset_id_of(d) for d in report.residual] == ["a" * 24]

    def test_failed_delete_appears_in_both_failed_and_residual(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)], delete_effect="raise", delete_status=403)
        report = cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        assert report.failed == 1
        assert len(report.residual) == 1
        assert report.exit_code(fail_on_residual=True) == 1

    def test_nothing_to_do_is_a_clean_zero(self, no_sleep):
        api = FakeDatasetsAPI([_ds("c" * 24, "Real Lab Dataset")])
        report = cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        assert report.targeted == 0
        assert report.exit_code(fail_on_residual=True) == 0
        assert api.names_called("deleteDataset") == []

    def test_dry_run_skips_verification_and_deletes_nothing(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)])
        report = cloud_janitor.sweep(
            api=api, client=None, org_id="org1", dry_run=True, sleep=no_sleep
        )
        assert report.targeted == 1
        assert report.deleted == 0
        assert report.residual == []
        assert api.names_called("deleteDataset") == []
        assert report.exit_code(fail_on_residual=True) == 0

    def test_render_names_every_residual_id(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)], delete_effect="noop")
        report = cloud_janitor.sweep(api=api, client=None, org_id="org1", sleep=no_sleep)
        text = report.render()
        assert "a" * 24 in text
        assert "residual" in text.lower()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_parser_defaults(self):
        args = cloud_janitor.build_parser().parse_args([])
        assert args.prefix == cloud_janitor.DEFAULT_PREFIX
        assert args.max_age == 0.0
        assert args.fail_on_residual is False
        assert args.dry_run is False

    def test_parser_flags(self):
        args = cloud_janitor.build_parser().parse_args(
            ["--org", "org1", "--prefix", "NDI_PYTEST_", "--max-age", "6", "--fail-on-residual"]
        )
        assert args.org == "org1"
        assert args.prefix == "NDI_PYTEST_"
        assert args.max_age == 6.0
        assert args.fail_on_residual is True

    def test_main_returns_one_when_residual_remains(self, capsys, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)], delete_effect="noop")
        rc = cloud_janitor.main(
            ["--org", "org1", "--fail-on-residual"],
            api=api,
            client=object(),
            sleep=no_sleep,
        )
        assert rc == 1
        assert "a" * 24 in capsys.readouterr().out

    def test_main_returns_zero_on_a_clean_sweep(self, no_sleep):
        api = FakeDatasetsAPI([_ds("a" * 24)])
        rc = cloud_janitor.main(
            ["--org", "org1", "--fail-on-residual"], api=api, client=object(), sleep=no_sleep
        )
        assert rc == 0

    def test_main_returns_two_when_the_listing_call_fails(self, no_sleep):
        api = FakeDatasetsAPI([])

        def exploding(org_id=None, *, client=None):
            raise CloudAPIError("service unavailable", status_code=503)

        api.listAllDatasets = exploding
        rc = cloud_janitor.main(
            ["--org", "org1", "--fail-on-residual"], api=api, client=object(), sleep=no_sleep
        )
        assert rc == 2

    def test_default_api_is_the_real_datasets_module(self):
        """Guard against the janitor silently binding to a stub."""
        api = cloud_janitor.default_api()
        assert isinstance(api, types.ModuleType)
        assert api.__name__ == "ndi.cloud.api.datasets"
        assert hasattr(api, "listAllDatasets")
