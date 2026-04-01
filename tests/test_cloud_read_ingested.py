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

        probe = p_cf[0]
        print(f"  Probe class: {type(probe).__name__}")
        print(f"  Probe MRO: {[c.__name__ for c in type(probe).__mro__[:5]]}")

        # Diagnostic: check epoch table
        et, _ = probe.epochtable()
        print(f"  Probe epochtable has {len(et)} entries")
        for i, e in enumerate(et):
            print(f"  epoch[{i}]: id={e.get('epoch_id')}")
        if et:
            e = et[0]
            print(f"  epoch_id: {e.get('epoch_id')}")
            epm = e.get("epochprobemap")
            print(f"  epochprobemap type: {type(epm).__name__}, value: {epm}")
            underlying = e.get("underlying_epochs", {})
            if underlying:
                u = underlying.get("underlying")
                print(f"  underlying type: {type(u).__name__}")
                print(f"  underlying epoch_id: {underlying.get('epoch_id')}")

        # Diagnostic: check devinfo
        try:
            devinfo = probe.getchanneldevinfo(1)
            print(f"  devinfo type: {type(devinfo).__name__}, value: {devinfo}")
        except Exception as exc:
            pytest.fail(f"getchanneldevinfo(1) raised {type(exc).__name__}: {exc}")

        if devinfo is None:
            pytest.fail("getchanneldevinfo(1) returned None")

        # Try the full readtimeseries path with explicit error propagation
        if isinstance(devinfo, tuple):
            dev, devepoch, channeltype, channellist = devinfo
        elif isinstance(devinfo, dict):
            dev = devinfo.get("daqsystem")
            devepoch = devinfo.get("device_epoch_id")
            print(f"  devinfo is dict, dev={type(dev).__name__}, devepoch={devepoch}")
            pytest.fail(
                f"getchanneldevinfo returned dict (base probe class), not tuple. "
                f"Probe class {type(probe).__name__} may not override getchanneldevinfo."
            )
        else:
            pytest.fail(f"getchanneldevinfo returned unexpected type: {type(devinfo).__name__}")

        print(f"  dev={type(dev).__name__}, devepoch={devepoch}")
        print(f"  channeltype={channeltype}, channellist={channellist}")

        # Diagnostic: try reading channel_list.bin directly
        diag = []
        if (
            hasattr(dev, "_filenavigator")
            and dev._filenavigator is not None
            and hasattr(dev, "_getepochfiles")
        ):
            epochfiles = dev._getepochfiles(devepoch)
            diag.append(f"epochfiles={epochfiles[:2]}")
            is_ingested = epochfiles and epochfiles[0].startswith("epochid://")
            diag.append(f"is_ingested={is_ingested}")
            if is_ingested and hasattr(dev, "_daqreader"):
                try:
                    ingested_doc = dev._daqreader.getingesteddocument(epochfiles, session)
                    diag.append(f"doc_class={ingested_doc.doc_class()}")
                    props = ingested_doc.document_properties
                    prop_keys = [
                        k for k in props if "ingested" in k.lower() or "daqreader" in k.lower()
                    ]
                    diag.append(f"ingested_keys={prop_keys}")
                    for pk in prop_keys:
                        if isinstance(props[pk], dict):
                            diag.append(f"{pk}.keys={list(props[pk].keys())}")
                    files = props.get("files", {})
                    diag.append(f"files.keys={list(files.keys())}")
                    fi = files.get("file_info", [])
                    diag.append(f"file_info_count={len(fi)}")
                    if fi and isinstance(fi[0], dict):
                        diag.append(f"fi[0].name={fi[0].get('name')}")
                        locs = fi[0].get("locations", [])
                        if locs:
                            diag.append(f"fi[0].loc[0]={locs[0].get('location', '')[:60]}")
                    try:
                        fobj = session.database_openbinarydoc(ingested_doc, "channel_list.bin")
                        diag.append(f"channel_list.bin=OK:{fobj.name}")
                        fobj.close()
                    except Exception as exc2:
                        diag.append(f"channel_list.bin=FAILED:{type(exc2).__name__}:{exc2}")
                except Exception as exc:
                    diag.append(f"getingesteddocument=FAILED:{exc}")

        # Try epochtimes2samples explicitly to see any error
        try:
            samples = dev.epochtimes2samples(
                channeltype, channellist, devepoch, np.array([10.0, 20.0])
            )
            print(f"  samples={samples}")
        except Exception as exc:
            pytest.fail(
                f"dev.epochtimes2samples raised {type(exc).__name__}: {exc}\n"
                f"  dev type: {type(dev).__name__}\n"
                f"  diag: {'; '.join(diag)}"
            )

        # Debug: read first 9 samples from t=0 to check alignment
        d_first, t_first, _ = probe.readtimeseries(epoch=1, t0=0, t1=0.001)
        if d_first is not None:
            print("  ALIGNMENT CHECK: first 9 samples from t=0:")
            print(f"  d_first.shape={d_first.shape}")
            n = min(9, d_first.shape[0])
            vals = [f"{d_first[i,0]:.4f}" for i in range(n)]
            times = [f"{t_first[i]:.6f}" for i in range(n)]
            print(f"  values: {vals}")
            print(f"  times:  {times}")
            print(
                "  EXPECTED: [2.0475, 0.4760, -0.1080, -0.1020, -0.0528, 0.0006, 0.0242, 0.1517, 0.0909]"
            )

        d1, t1, _ = probe.readtimeseries(epoch=1, t0=10, t1=20)

        assert (
            d1 is not None
        ), "readtimeseries returned None for data (binary files not accessible?)"
        assert t1 is not None, "readtimeseries returned None for times"

        # Check data isn't all NaN
        if np.all(np.isnan(d1)):
            pytest.fail(
                f"readtimeseries returned all NaN data. shape={d1.shape}. "
                f"Segment file reading likely failed — check warnings in log."
            )

        # Debug: print raw values, shape, and scale/offset info
        print(f"  d1.shape={d1.shape}, t1.shape={t1.shape}")
        print(f"  d1[0,:5]={d1[0,:5]}")
        print(f"  t1[0]={t1[0]}")
        # Get scale/offset from channel info
        epochfiles = dev._getepochfiles(devepoch)
        sr_arr, off_arr, sc_arr = dev._daqreader.samplerate_ingested(
            epochfiles, channeltype, channellist, session
        )
        print(f"  sr={sr_arr[0]}, offset={off_arr[:3]}, scale={sc_arr[:3]}")
        t0t1 = dev._daqreader.t0_t1_ingested(epochfiles, session)
        print(f"  t0_t1={t0t1}")
        # Debug: print raw data near expected position
        print(f"  d1[0,:5]={d1[0,:5]}")
        if d1.shape[0] > 1:
            print(f"  d1[1,:5]={d1[1,:5]}")
        # Read one sample earlier to check alignment
        d_check, t_check, _ = probe.readtimeseries(epoch=1, t0=9.99995, t1=10.0001)
        if d_check is not None:
            print(f"  d_check.shape={d_check.shape}")
            for i in range(min(5, d_check.shape[0])):
                print(f"  d_check[{i},0]={d_check[i,0]:.3f} t={t_check[i]:.6f}")

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

        stim = p_st[0]
        print(f"  Stimulator probe: {stim}")
        print(f"  Stimulator class: {type(stim).__name__}")

        # Diagnostic: check what getchanneldevinfo returns
        devinfo = stim.getchanneldevinfo(1)
        if devinfo is None:
            pytest.fail("stimulator getchanneldevinfo(1) returned None")
        print(f"  devinfo keys: {list(devinfo.keys())}")
        dev = devinfo.get("daqsystem")
        devepoch = devinfo.get("device_epoch_number", devinfo.get("device_epoch_id"))
        ct = devinfo.get("channeltype", [])
        ch = devinfo.get("channel", [])
        print(f"  dev={type(dev).__name__}, devepoch={devepoch}")
        print(f"  channeltype={ct}, channel={ch}")
        # Print ALL epochprobemaps from underlying epoch
        et_stim, _ = stim.epochtable()
        if et_stim:
            underlying = et_stim[0].get("underlying_epochs", {})
            all_epms = underlying.get("epochprobemap", [])
            if not isinstance(all_epms, list):
                all_epms = [all_epms]
            print(f"  underlying epochprobemaps count: {len(all_epms)}")
            for i, m in enumerate(all_epms):
                ds = getattr(m, "devicestring", "?")
                nm = getattr(m, "name", "?")
                print(f"  epm[{i}]: name={nm} devicestring={ds}")
                match = stim.epochprobemapmatch(m) if hasattr(stim, "epochprobemapmatch") else "?"
                print(f"    matches this probe: {match}")

        # Try readevents directly (without md channels, matching stimulator)
        non_md_ct = [c for c in ct if c != "md"]
        non_md_ch = [ch[i] for i, c in enumerate(ct) if c != "md"]
        print(f"  non-md channeltype={non_md_ct}, channel={non_md_ch}")
        if dev is not None and non_md_ct:
            try:
                evt_result = dev.readevents_epochsamples(non_md_ct, non_md_ch, devepoch, 10, 20)
                print(f"  readevents result type: {type(evt_result)}")
                if isinstance(evt_result, tuple):
                    ts_r, data_r = evt_result
                    print(f"  timestamps type: {type(ts_r)}, data type: {type(data_r)}")
                    if isinstance(ts_r, list):
                        for i in range(len(ts_r)):
                            t_i, d_i = ts_r[i], data_r[i]
                            t_s = getattr(
                                t_i, "shape", len(t_i) if hasattr(t_i, "__len__") else "?"
                            )
                            d_s = getattr(
                                d_i, "shape", len(d_i) if hasattr(d_i, "__len__") else "?"
                            )
                            label = (
                                f"{non_md_ct[i]}{non_md_ch[i]}" if i < len(non_md_ct) else f"[{i}]"
                            )
                            print(f"  ch[{i}] ({label}): ts={t_s}, data={d_s}")
                    elif hasattr(ts_r, "shape"):
                        print(f"  timestamps shape: {ts_r.shape}")
            except Exception as exc:
                pytest.fail(
                    f"readevents_epochsamples raised {type(exc).__name__}: {exc}\n"
                    f"  channeltype={non_md_ct}, channel={non_md_ch}, devepoch={devepoch}"
                )

        ds, ts, _ = stim.readtimeseries(epoch=1, t0=10, t1=20)

        assert ds is not None, "readtimeseries returned None for data"
        assert ts is not None, "readtimeseries returned None for times"

        # ds should be a dict with 'stimid'
        stimid = ds["stimid"]
        if hasattr(stimid, "size") and stimid.size == 0:
            pytest.fail(
                f"ds['stimid'] is empty. ds keys={list(ds.keys())}, "
                f"ds values sizes={{ k: (v.size if hasattr(v, 'size') else len(v) if hasattr(v, '__len__') else v) for k, v in ds.items() }}, "
                f"ts keys={list(ts.keys())}, "
                f"ts values sizes={{ k: (v.size if hasattr(v, 'size') else len(v) if hasattr(v, '__len__') else v) for k, v in ts.items() }}"
            )
        # Extract scalar stimid from potentially nested array
        stimid_val = np.asarray(stimid).ravel()
        if stimid_val.size > 0:
            stimid_val = int(stimid_val[0])
        else:
            pytest.fail(f"stimid is empty after ravel: {stimid}")
        assert stimid_val == 31, f"Expected stimid == 31, got {stimid_val} (raw: {stimid})"

        # ts.stimon should be 15.2590 (within 0.001)
        stimon = ts["stimon"]
        if hasattr(stimon, "size") and stimon.size == 0:
            pytest.fail("ts['stimon'] is empty — binary files may not be accessible from cloud")
        if hasattr(stimon, "__len__"):
            stimon_val = float(stimon) if np.ndim(stimon) == 0 else float(stimon[0])
        else:
            stimon_val = float(stimon)
        assert abs(stimon_val - 15.2590) < 0.001, f"Expected ts.stimon ≈ 15.2590, got {stimon_val}"
