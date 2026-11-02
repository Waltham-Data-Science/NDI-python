"""Stimulus decoding of ndi.setup.daq.reader.mfdaq.stimulus.vhlabvisspike2.

MATLAB counterpart: ``+ndi/+setup/+daq/+reader/+mfdaq/+stimulus/vhlabvisspike2.m``
(``readevents_epochsamples_native``). Each test writes a small synthetic
epoch directory -- ``stimtimes.txt`` as the VH Lab Spike2 script writes it,
and a minimal ``stims.mat`` holding a ``saveScript`` and an ``MTI2`` cell
array -- and reads the stimulus channels back through the reader.
"""

from __future__ import annotations

import numpy as np
import pytest

scipy_io = pytest.importorskip("scipy.io")
pytest.importorskip("vhlib.StimDecode")

from ndi.setup.daq.reader.mfdaq.stimulus.vhlabvisspike2 import (  # noqa: E402
    VHLabVisSpike2StimulusMismatchError,
    ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2,
)

# Stimulus-computer clock: trigger (startStopTimes[1]) at 100 + 10*k, with
# setup 0.5 s before, off 2 s after, clear 2.5 s after.
MAC_T0 = 100.0
SPIKE2_T0 = 5.0


def _mti_entry(k: int, stimid: int) -> dict:
    trig = MAC_T0 + 10.0 * k
    return {
        "stimid": float(stimid),
        "startStopTimes": np.array([trig - 0.5, trig, trig + 2.0, trig + 2.5]),
    }


def _make_epoch(
    tmp_path,
    spike2_ids,
    mti_ids,
    name="t00006",
    stimtimes_mapping=None,
    mti_mapping=None,
):
    """Write an epoch directory; Spike2 trigger k is at SPIKE2_T0 + 10*k."""
    d = tmp_path / name
    d.mkdir()
    lines = []
    for k, sid in enumerate(spike2_ids):
        t = SPIKE2_T0 + 10.0 * k
        frames = [t + 0.01, t + 0.02]
        lines.append(" ".join(f"{v:.6f}" for v in [sid, t, *frames]))
    (d / "stimtimes.txt").write_text("\n".join(lines) + "\n")

    mti = np.empty(len(mti_ids), dtype=object)
    for k, sid in enumerate(mti_ids):
        mti[k] = _mti_entry(k, sid)
    scipy_io.savemat(
        str(d / "stims.mat"),
        {"saveScript": {"name": "synthetic"}, "MTI2": mti},
    )
    (d / "verticalblanking.txt").write_text("5.0\n5.5\n6.0\n")
    (d / "reference.txt").write_text("")

    if stimtimes_mapping is not None:
        (d / "stimtimes2stimtimes_mapping.txt").write_text(
            "\n".join(str(v) for v in stimtimes_mapping) + "\n"
        )
    if mti_mapping is not None:
        (d / "mti2stimtimes_mapping.txt").write_text("\n".join(str(v) for v in mti_mapping) + "\n")

    epochfiles = [
        str(d / f)
        for f in (
            "reference.txt",
            "stimtimes.txt",
            "verticalblanking.txt",
            "stims.mat",
            "spike2data.smr",
        )
    ]
    return d, epochfiles


@pytest.fixture
def reader():
    return ndi_setup_daq_reader_mfdaq_stimulus_vhlabvisspike2()


def test_channels(reader):
    names = [c.name for c in reader.getchannelsepoch([])]
    assert names == ["mk1", "mk2", "mk3", "e1", "e2", "e3"]
    assert np.isnan(reader.samplerate([], "mk", [1, 2])).all()


def test_records_agree(reader, tmp_path):
    # 300 is sent to Spike2 as 300 mod 256 = 44; the full id comes back.
    _, ef = _make_epoch(tmp_path, [1, 2, 44], [1, 2, 300])

    ts, d = reader.readevents_epochsamples("mk", [2], ef, -np.inf, np.inf)
    np.testing.assert_allclose(ts, [5.0, 15.0, 25.0])
    np.testing.assert_array_equal(d, [1, 2, 300])

    # on/off alternate; off = trigger + 2 in Spike2 time.
    ts, d = reader.readevents_epochsamples("mk", [1], ef, -np.inf, np.inf)
    np.testing.assert_allclose(ts, [5.0, 7.0, 15.0, 17.0, 25.0, 27.0])
    np.testing.assert_array_equal(d, [1, -1, 1, -1, 1, -1])

    # setup/clear = trigger - 0.5 / + 2.5.
    ts, d = reader.readevents_epochsamples("mk", [3], ef, -np.inf, np.inf)
    np.testing.assert_allclose(ts, [4.5, 7.5, 14.5, 17.5, 24.5, 27.5])
    np.testing.assert_array_equal(d, [1, -1, 1, -1, 1, -1])

    # events: frames, vertical blanking, simulated pretime trigger.
    tss, ds = reader.readevents_epochsamples(["e", "e", "e"], [1, 2, 3], ef, -np.inf, np.inf)
    np.testing.assert_allclose(tss[0], [5.01, 5.02, 15.01, 15.02, 25.01, 25.02])
    np.testing.assert_allclose(tss[1], [5.0, 5.5, 6.0])
    np.testing.assert_allclose(tss[2], [4.5, 14.5, 24.5])
    assert all((x == 1).all() for x in ds)


def test_time_window(reader, tmp_path):
    _, ef = _make_epoch(tmp_path, [1, 2, 3], [1, 2, 3])
    ts, d = reader.readevents_epochsamples("mk", [2], ef, 10.0, 25.0)
    np.testing.assert_allclose(ts, [15.0, 25.0])
    np.testing.assert_array_equal(d, [2, 3])


def test_count_mismatch(reader, tmp_path):
    d, ef = _make_epoch(tmp_path, [1, 2], [1, 2, 3])
    with pytest.raises(ValueError, match=r"stimtimes.txt file \(2\).*stims.mat file \(3\)"):
        reader.readevents_epochsamples("mk", [1], ef, -np.inf, np.inf)


def test_stimulus_id_mismatch_names_epoch(reader, tmp_path):
    d, ef = _make_epoch(tmp_path, [1, 5, 3], [1, 2, 3], name="t00006")
    with pytest.raises(VHLabVisSpike2StimulusMismatchError) as exc_info:
        reader.readevents_epochsamples("mk", [1], ef, -np.inf, np.inf)
    msg = str(exc_info.value)
    assert msg.startswith("Epoch t00006: stimulus number 2 does not line up")
    assert "Spike2 says 5 while stimulus computer says 2" in msg
    assert str(d) in msg
    assert "stimtimes2stimtimes_mapping.txt" in msg and "mti2stimtimes_mapping.txt" in msg
    assert exc_info.value.identifier == (
        "ndi:setup:daq:reader:mfdaq:stimulus:vhlabvisspike2:StimulusMismatch"
    )
    assert isinstance(exc_info.value, ValueError)


def test_mapping_fixes_stopped_early_run(reader, tmp_path):
    # The run was stopped early: Spike2 saw 3 triggers, stims.mat lists 5;
    # the first 3 agree. Without a mapping the counts differ.
    (tmp_path / "a").mkdir()
    _, ef = _make_epoch(tmp_path / "a", [7, 8, 9], [7, 8, 9, 10, 11])
    with pytest.raises(ValueError, match="differs"):
        reader.readevents_epochsamples("mk", [2], ef, -np.inf, np.inf)

    (tmp_path / "b").mkdir()
    _, ef = _make_epoch(tmp_path / "b", [7, 8, 9], [7, 8, 9, 10, 11], mti_mapping=[1, 2, 3])
    ts, d = reader.readevents_epochsamples("mk", [2], ef, -np.inf, np.inf)
    np.testing.assert_allclose(ts, [5.0, 15.0, 25.0])
    np.testing.assert_array_equal(d, [7, 8, 9])


def test_stimtimes_mapping_drops_nan(reader, tmp_path):
    # A spurious second Spike2 trigger is dropped by the stimtimes mapping;
    # NaN entries in a mapping file are ignored, as vlt.data.dropnan does.
    _, ef = _make_epoch(
        tmp_path,
        [1, 99, 2],
        [1, 2],
        stimtimes_mapping=[1, "NaN", 3],
    )
    ts, d = reader.readevents_epochsamples("mk", [2], ef, -np.inf, np.inf)
    np.testing.assert_allclose(ts, [5.0, 25.0])
    np.testing.assert_array_equal(d, [1, 2])
    tf, _ = reader.readevents_epochsamples("e", [1], ef, -np.inf, np.inf)
    np.testing.assert_allclose(tf, [5.01, 5.02, 25.01, 25.02])
