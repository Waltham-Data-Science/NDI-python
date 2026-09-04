"""Exercise the NDI CED Spike2 reader against NDR-python's fake sonpipe CLI.

CED's sonpy has no wheel for CPython 3.10-3.13 on Linux or macOS, so the real
CLI cannot run in CI. NDR-python ships ``tests/fake_sonpipe.py`` for exactly
this: a stand-in that reproduces the CLI contract (JSON header/marker
payloads, little-endian binary sample stdout, completion sentinel). Pointing
NDI's wrapper at that CLI covers the whole call path -- header parsing,
sample-window arithmetic, event and marker dispatch -- without needing sonpy.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import numpy as np
import pytest
from ndr.format.ced import sonpipe

from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2

FAKE = Path(__file__).parents[1].parent / "NDR-python" / "tests" / "fake_sonpipe.py"

if not FAKE.exists():  # pragma: no cover - CI checkout layout differs
    pytest.skip(
        "NDR-python's fake_sonpipe.py is not available alongside this checkout; "
        "the CED reader is exercised in NDR-python's own test suite in that case.",
        allow_module_level=True,
    )

SR = 1000.0
N = 500


@pytest.fixture
def epochfiles(monkeypatch, tmp_path):
    """Point the sonpipe bridge at the stand-in CLI and hand back an epochfiles list."""
    monkeypatch.setenv("SONPIPE", shlex.join([sys.executable, str(FAKE)]))
    monkeypatch.delenv("FAKE_SONPIPE_FAULT", raising=False)
    sonpipe.reset_cache()
    yield [str(tmp_path / "recording.smrx")]
    sonpipe.reset_cache()


class TestChannelListing:
    def test_channels_cover_waveform_event_marker_and_time(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        channels = r.getchannelsepoch(epochfiles)
        by_name = {c.name: c for c in channels}
        assert set(by_name) == {"ai1", "e2", "mk3", "t1"}
        assert by_name["ai1"].type == "analog_in"
        assert by_name["ai1"].sample_rate == pytest.approx(SR)
        assert by_name["ai1"].time_channel == 1
        assert by_name["e2"].type == "event"
        assert by_name["mk3"].type == "marker"
        assert by_name["t1"].type == "time"


class TestSampleRate:
    def test_waveform_channel_reports_rate(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        np.testing.assert_allclose(r.samplerate(epochfiles, "ai", 1), [SR])

    def test_event_channel_reports_nan(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        rate = r.samplerate(epochfiles, "e", 2)
        assert np.isnan(rate[0])


class TestEpochBounds:
    def test_t0_t1_uses_max_recorded_time(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        assert r.t0_t1(epochfiles) == [(0.0, 1.0)]


class TestReadChannels:
    def test_full_waveform_read(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        data = r.readchannels_epochsamples("ai", [1], epochfiles, 1, N)
        assert data.shape == (N, 1)
        np.testing.assert_array_equal(data[:, 0], np.arange(N))

    def test_window_maps_to_sonpipe_start_and_count(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        # Sample i has value i in the fake CLI, so slips are visible.
        data = r.readchannels_epochsamples("ai", [1], epochfiles, 101, 200)
        np.testing.assert_array_equal(data[:, 0], np.arange(100, 200))

    def test_time_channeltype_returns_time_axis(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        t = r.readchannels_epochsamples("time", [1], epochfiles, 1, 5)
        np.testing.assert_allclose(t[:, 0], np.arange(5) / SR)


class TestReadEvents:
    def test_event_channel_returns_times(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        ts, data = r.readevents_epochsamples_native("e", 2, epochfiles, 0.0, float("inf"))
        np.testing.assert_allclose(ts, [0.1, 0.2, 0.35, 0.5, 0.75])
        np.testing.assert_allclose(data, ts)

    def test_marker_channel_returns_times_and_codes(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        ts, data = r.readevents_epochsamples_native("mk", 3, epochfiles, 0.0, float("inf"))
        np.testing.assert_allclose(ts, [0.15, 0.45, 0.85])
        np.testing.assert_allclose(data, [11, 22, 33])


class TestFailureHonesty:
    """Previously the reader swallowed everything to []; now it raises."""

    def test_missing_file_argument_raises(self):
        r = ndi_daq_reader_mfdaq_cedspike2()
        with pytest.raises(ValueError, match="exactly one .smr"):
            r.getchannelsepoch([])

    def test_two_ced_files_raises(self):
        r = ndi_daq_reader_mfdaq_cedspike2()
        with pytest.raises(ValueError, match="exactly one .smr"):
            r.getchannelsepoch(["a.smr", "b.smrx"])

    def test_missing_channel_raises(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        with pytest.raises(ValueError, match="not recorded"):
            r.samplerate(epochfiles, "ai", 99)

    def test_event_channel_cannot_be_read_as_waveform(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        with pytest.raises(ValueError, match="no waveform samples"):
            r.readchannels_epochsamples("ai", [2], epochfiles, 1, 10)
