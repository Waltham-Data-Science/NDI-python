"""Exercise the NDI CED Spike2 reader against real sonpipe + CED's sonpy.

CED's sonpy has no wheel for CPython 3.10-3.13 on Linux or macOS, so the
main test matrix cannot run this. The ced-integration CI job runs this file
on 3.14 with `pip install ndr[ced]` (which pulls sonpipe from its git URL,
same install as `python -m ndr.setup.sonpipe`), against NDR-python's shipped
example.smr fixture. tests/test_cedspike2_sonpipe.py covers the wrapper on
every supported Python via a stand-in CLI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from ndi.daq.reader.mfdaq.cedspike2 import ndi_daq_reader_mfdaq_cedspike2


def _require_sonpipe():
    """Skip unless the real sonpipe CLI is reachable.

    NDI_REQUIRE_SONPIPE turns the skip into a failure; the ced-integration
    job sets it so a missing binary cannot report a vacuous pass.
    """
    from ndr.format.ced import sonpipe

    sonpipe.reset_cache()
    try:
        sonpipe.executable()
    except sonpipe.SonpipeNotFoundError:
        if os.environ.get("NDI_REQUIRE_SONPIPE"):
            raise
        pytest.skip("sonpipe CLI not installed; see ndr.format.ced.sonpipe.executable")


def _example_smr() -> Path:
    """Return NDR-python's shipped example.smr, or skip cleanly."""
    from ndr.globals import NDRGlobals

    g = NDRGlobals()
    path = Path(g.path["path"]) / "example_data" / "example.smr"
    if not path.exists():
        pytest.skip(f"NDR example.smr not found at {path}")
    return path


@pytest.fixture
def epochfiles() -> list[str]:
    _require_sonpipe()
    return [str(_example_smr())]


class TestRealChannelListing:
    def test_at_least_one_channel_and_names_are_shaped_correctly(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        channels = r.getchannelsepoch(epochfiles)
        assert channels, "example.smr should record at least one channel"
        for c in channels:
            assert c.type in {"analog_in", "event", "marker", "text", "time"}
            # Waveform channels carry a sample rate; the rest may not.
            if c.type == "analog_in":
                assert c.sample_rate is not None and c.sample_rate > 0
            # Names follow the prefix-plus-CED-number convention.
            prefix = {"analog_in": "ai", "event": "e", "marker": "mk", "text": "text", "time": "t"}[
                c.type
            ]
            assert c.name.startswith(prefix)


class TestRealSampleRateAndBounds:
    def test_waveform_channel_reports_positive_rate(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        wave = next((c for c in r.getchannelsepoch(epochfiles) if c.type == "analog_in"), None)
        if wave is None:
            pytest.skip("example.smr records no waveform channel")
        rate = r.samplerate(epochfiles, "ai", wave.number)
        assert rate.shape == (1,) and rate[0] > 0

    def test_t0_t1_is_a_positive_window(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        bounds = r.t0_t1(epochfiles)
        assert len(bounds) == 1
        t0, t1 = bounds[0]
        assert t0 == 0.0
        assert t1 > 0


class TestRealWaveformRead:
    def test_full_read_matches_header_num_samples(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        header = r._get_header(epochfiles)
        wave = next((e for e in header["channelinfo"] if int(e.get("kind", 0)) in (1, 9)), None)
        if wave is None:
            pytest.skip("example.smr records no waveform channel")
        total = int(wave["num_samples"])
        data = r.readchannels_epochsamples("ai", [int(wave["number"])], epochfiles, 1, total)
        assert data.shape == (total, 1)

    def test_window_matches_expected_length(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        header = r._get_header(epochfiles)
        wave = next((e for e in header["channelinfo"] if int(e.get("kind", 0)) in (1, 9)), None)
        if wave is None:
            pytest.skip("example.smr records no waveform channel")
        total = int(wave["num_samples"])
        count = min(100, total)
        data = r.readchannels_epochsamples("ai", [int(wave["number"])], epochfiles, 1, count)
        # The sample count comes back within one of what we asked for; sonpipe
        # rounds via floor(t*sr), so the boundary can slip by one.
        assert abs(data.shape[0] - count) <= 1

    def test_time_channeltype_returns_matching_axis(self, epochfiles):
        r = ndi_daq_reader_mfdaq_cedspike2()
        header = r._get_header(epochfiles)
        wave = next((e for e in header["channelinfo"] if int(e.get("kind", 0)) in (1, 9)), None)
        if wave is None:
            pytest.skip("example.smr records no waveform channel")
        sr = float(wave["samplerate"])
        t = r.readchannels_epochsamples("time", [int(wave["number"])], epochfiles, 1, 5)
        assert t.shape[0] >= 4
        # A time axis at rate `sr` should be evenly spaced.
        diffs = np.diff(t[:, 0])
        np.testing.assert_allclose(diffs, np.full_like(diffs, 1.0 / sr), rtol=1e-6)
