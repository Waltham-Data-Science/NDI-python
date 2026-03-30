"""
ndi.unittest.cloud.readIngested - Read an ingested dataset from the cloud.

Downloads the Carbon fiber microelectrode dataset, opens its session,
reads timeseries data from a carbon-fiber probe and a stimulator probe,
and verifies the returned values match expected results.

Requires environment variables:
    NDI_CLOUD_USERNAME  -- mapped from GitHub secret TEST_USER_2_USERNAME
    NDI_CLOUD_PASSWORD  -- mapped from GitHub secret TEST_USER_2_PASSWORD

Skipped automatically if credentials are not set.
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Skip entire module if no credentials
# ---------------------------------------------------------------------------

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")

CARBON_FIBER_ID = "668b0539f13096e04f1feccd"


@pytest.fixture(scope="module")
def cloud_client():
    """Authenticate with NDI Cloud and return a client."""
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient

    username = os.environ["NDI_CLOUD_USERNAME"]
    password = os.environ["NDI_CLOUD_PASSWORD"]
    config = login(username, password)
    assert config.is_authenticated, "Login failed -- no token received"
    return CloudClient(config)


@pytest.fixture(scope="module")
def dataset(cloud_client):
    """Download the Carbon fiber dataset to a temp directory."""
    from ndi.cloud.orchestration import downloadDataset

    with tempfile.TemporaryDirectory() as target_dir:
        D = downloadDataset(CARBON_FIBER_ID, target_dir, client=cloud_client)
        yield D


@pytest.fixture(scope="module")
def session(dataset):
    """Open the single session in the dataset."""
    refs, session_ids, *_ = dataset.session_list()
    assert len(session_ids) == 1, f"Expected 1 session, got {len(session_ids)}"
    S = dataset.open_session(session_ids[0])
    return S


class TestReadIngested:
    """ndi.unittest.cloud.readIngested — verify cloud dataset reads."""

    def test_session_list_has_one_entry(self, dataset):
        """session_list should return exactly one session."""
        refs, session_ids, *_ = dataset.session_list()
        assert len(session_ids) == 1

    def test_carbonfiber_probe_timeseries(self, session):
        """Read carbonfiber probe timeseries and check values."""
        p_cf = session.getprobes(name="carbonfiber", reference=1)
        assert len(p_cf) == 1, f"Expected 1 carbonfiber probe, got {len(p_cf)}"

        d1, t1, _ = p_cf[0].readtimeseries(epoch=1, t0=10, t1=20)

        assert (
            d1 is not None
        ), "readtimeseries returned None for data (binary files not accessible?)"
        assert t1 is not None, "readtimeseries returned None for times"

        # Check first time sample
        assert abs(t1[0] - 10.0) < 0.001, f"Expected t1[0] ≈ 10.0, got {t1[0]}"

        # Expected values for d1[0, :]
        expected_d1_row0 = np.array(
            [
                55.7700,
                253.3050,
                -43.2900,
                -9.5550,
                30.6150,
                23.4000,
                16.1850,
                -51.6750,
                -1.7550,
                -14.6250,
                -32.7600,
                45.6300,
                -7.2150,
                0.9750,
                -1.7550,
                45.0450,
            ]
        )

        actual_d1_row0 = d1[0, :]
        assert (
            actual_d1_row0.shape == expected_d1_row0.shape
        ), f"Expected {expected_d1_row0.shape} channels, got {actual_d1_row0.shape}"
        np.testing.assert_allclose(
            actual_d1_row0,
            expected_d1_row0,
            atol=0.001,
            err_msg="d1[0,:] values do not match expected",
        )

    def test_stimulator_probe_timeseries(self, session):
        """Read stimulator probe timeseries and check stimid and timing."""
        p_st = session.getprobes(type="stimulator")
        assert len(p_st) >= 1, "Expected at least 1 stimulator probe"

        ds, ts, _ = p_st[0].readtimeseries(epoch=1, t0=10, t1=20)

        assert ds is not None, "readtimeseries returned None for data"
        assert ts is not None, "readtimeseries returned None for times"

        # ds should be a dict with 'stimid'
        stimid = ds["stimid"]
        if hasattr(stimid, "size") and stimid.size == 0:
            pytest.fail("ds['stimid'] is empty — binary files may not be accessible from cloud")
        if hasattr(stimid, "__len__") and not isinstance(stimid, (int, float)):
            stimid = int(stimid[0]) if len(stimid) > 0 else stimid
        assert stimid == 31, f"Expected stimid == 31, got {stimid}"

        # ts.stimon should be 15.2590 (within 0.001)
        stimon = ts["stimon"]
        if hasattr(stimon, "size") and stimon.size == 0:
            pytest.fail("ts['stimon'] is empty — binary files may not be accessible from cloud")
        if hasattr(stimon, "__len__"):
            stimon_val = float(stimon) if np.ndim(stimon) == 0 else float(stimon[0])
        else:
            stimon_val = float(stimon)
        assert abs(stimon_val - 15.2590) < 0.001, f"Expected ts.stimon ≈ 15.2590, got {stimon_val}"
