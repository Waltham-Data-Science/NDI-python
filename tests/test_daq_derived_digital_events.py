"""Events derived from a digital channel: dep, den, dimp, dimn.

Mirrors NDI-matlab tests/+ndi/+unittest/+daq/+reader/DigitalMarkEventsTest.m.
An event is timed at the first sample *after* the transition, as in
MATLAB's ``1 + find(d(1:end-1)==0 & d(2:end)==1)``: for a line that goes
high at t = 1.0 s, the rising edge is at 1.0 s, not one sample earlier.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.daq.mfdaq import ChannelInfo, ndi_daq_reader_mfdaq

SR = 1000.0
DURATION = 10.0


class _PulseReader(ndi_daq_reader_mfdaq):
    """di1 is 1 for 1.0 <= t < 1.1 and 3.0 <= t < 3.1, else 0 (1 kHz, 0..10 s)."""

    def t0_t1(self, epochfiles):
        return [(0.0, DURATION)]

    def getchannelsepoch(self, epochfiles):
        return [ChannelInfo(name="di1", type="digital_in", time_channel=1)]

    def samplerate(self, epochfiles, channeltype, channel):
        n = 1 if isinstance(channel, int) else len(channel)
        return np.full(n, SR)

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        # s0/s1 come from epochtimes2samples, which counts from t0 = 0.
        t = np.arange(s0, s1 + 1) / SR
        ct = channeltype if isinstance(channeltype, str) else channeltype[0]
        if ct in ("time", "t"):
            return t.reshape(-1, 1)
        d = (((t >= 1.0) & (t < 1.1)) | ((t >= 3.0) & (t < 3.1))).astype(float)
        return d.reshape(-1, 1)


@pytest.fixture
def reader():
    return _PulseReader()


def test_dimp_on_off(reader):
    t, d = reader.readevents_epochsamples("dimp", 1, ["mock"], 0.0, DURATION)
    np.testing.assert_allclose(t, [1.0, 1.1, 3.0, 3.1], atol=1e-9)
    np.testing.assert_array_equal(d, [1, -1, 1, -1])


def test_dimn_on_off(reader):
    # dimn: "on" is the 1->0 transition and "off" is the 0->1 transition.
    t, d = reader.readevents_epochsamples("dimn", 1, ["mock"], 0.0, DURATION)
    np.testing.assert_allclose(t, [1.0, 1.1, 3.0, 3.1], atol=1e-9)
    np.testing.assert_array_equal(d, [-1, 1, -1, 1])


def test_dep_rising_edges_only(reader):
    t, d = reader.readevents_epochsamples("dep", 1, ["mock"], 0.0, DURATION)
    np.testing.assert_allclose(t, [1.0, 3.0], atol=1e-9)
    np.testing.assert_array_equal(d, [1, 1])


def test_den_falling_edges_only(reader):
    t, d = reader.readevents_epochsamples("den", 1, ["mock"], 0.0, DURATION)
    np.testing.assert_allclose(t, [1.1, 3.1], atol=1e-9)
    np.testing.assert_array_equal(d, [1, 1])
