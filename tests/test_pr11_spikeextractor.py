"""PR11 tests for ndi.app.spikeextractor.

Exercises the load-bearing scientific paths of the spike extractor port:
  * the grounded _dotdisc / _refractory helpers against hand-computed values
    and against the MATLAB/C ground-truth algorithm,
  * scipy-based filter design + zero-phase filtering, and
  * the full in-memory detect+extract pipeline on a synthetic trace with
    known spike locations.

The module is importable without vlt (helpers are pure numpy), but the
end-to-end extraction uses vlt.neuro.spikesorting.centerspikes_neg, so this
file skips cleanly when vlt is absent (the standard CI/sandbox env).
"""

import math

import numpy as np
import pytest

pytest.importorskip("vlt")
pytest.importorskip("scipy")

from ndi.app.spikeextractor import (  # noqa: E402
    _dotdisc,
    _refractory,
    ndi_app_spikeextractor,
)

# ---------------------------------------------------------------------------
# _dotdisc -- grounded against the MATLAB/C reference
# ---------------------------------------------------------------------------


def _c_dotdisc_reference(y, dots):
    """Direct transcription of vhlab-toolbox-matlab/+vlt/+signal/dotdisc.c."""
    y = np.asarray(y, dtype=float)
    dots = np.atleast_2d(np.asarray(dots, dtype=float))
    ylen = len(y)
    earlydot = int(min(0, dots[:, 2].min()))
    latedot = int(max(0, dots[:, 2].max()))
    out = []
    ptsgood = 0
    for i in range(-earlydot, ylen - latedot):
        m = 1
        for j in range(dots.shape[0]):
            off = int(dots[j, 2])
            thresh = dots[j, 0]
            sg = dots[j, 1]
            if sg > 0:
                m &= int(y[i + off] > thresh)
            else:
                m &= int(y[i + off] < thresh)
            if not m:
                break
        if (m == 0) and (ptsgood > 0):
            out.append(math.ceil(i - ptsgood / 2.0))
            ptsgood = 0
        elif m == 1:
            ptsgood += 1
    return np.asarray(out, dtype=float)


def test_dotdisc_matches_c_reference_negative_spikes():
    rng = np.random.default_rng(0)
    trace = np.zeros(2000)
    # four 3-sample-wide downward excursions
    for loc in (100, 300, 800, 1500):
        trace[loc : loc + 3] = -10.0
    trace += rng.normal(0, 0.05, trace.shape)

    dots = [[-5.0, -1.0, 0.0]]
    got = _dotdisc(trace, dots)
    ref = _c_dotdisc_reference(trace, dots)

    np.testing.assert_array_equal(np.sort(got), np.sort(ref))
    # 4 events; each run of 3 -> event at ceil(i_end - 3/2). Run [100,101,102]:
    # i_end = 103 (first non-match), ceil(103 - 1.5) = 102.
    assert got.size == 4
    np.testing.assert_array_equal(np.sort(got), [102.0, 302.0, 802.0, 1502.0])


def test_dotdisc_positive_sign_and_handcount():
    # A single 1-sample positive crossing: run length 1, i_end = loc+1,
    # event = ceil((loc+1) - 0.5) = loc+1.
    y = np.zeros(50)
    y[20] = 5.0
    got = _dotdisc(y, [[2.0, 1.0, 0.0]])
    assert got.tolist() == [21.0]


# ---------------------------------------------------------------------------
# _refractory -- grounded against the MATLAB algorithm
# ---------------------------------------------------------------------------


def test_refractory_handcomputed():
    # MATLAB refractory is round-based: each round keeps index 0 plus every
    # index k+1 where diff[k] > ref, then repeats on the survivors.
    # [0, 0.9, 1.8, 5, 5.4, 9], ref=1:
    #   round 1 diffs = [.9, .9, 3.2, .4, 3.6]; keep {0} + {k+1: d>1} = {0,3,5}
    #           -> [0, 5, 9]
    #   round 2 diffs = [5, 4] all > 1 -> done.
    out = _refractory([0, 0.9, 1.8, 5, 5.4, 9], 1.0)
    np.testing.assert_array_equal(out, [0.0, 5.0, 9.0])


def test_refractory_zero_period_is_identity_sorted():
    out = _refractory([3, 1, 2], 0)
    np.testing.assert_array_equal(out, [1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# Filter design + application (scipy)
# ---------------------------------------------------------------------------


def test_makefilterstruct_cheby1high_matches_scipy():
    from scipy.signal import cheby1

    app = ndi_app_spikeextractor(session=None)
    params = app.default_extraction_parameters()
    sample_rate = 30000.0
    fs = app.makefilterstruct(params, sample_rate)

    wn = params["filter_high"] / (0.5 * sample_rate)
    b, a = cheby1(params["filter_order"], params["filter_ripple"], wn, btype="high")
    np.testing.assert_allclose(fs["b"], b)
    np.testing.assert_allclose(fs["a"], a)


def test_makefilterstruct_none_returns_none():
    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    params["filter_type"] = "none"
    assert app.makefilterstruct(params, 30000.0) is None


def test_filter_passthrough_when_none():
    app = ndi_app_spikeextractor(session=None)
    data = np.arange(10.0).reshape(-1, 1)
    out = app.filter(data, None)
    np.testing.assert_array_equal(out, data)


def test_filter_removes_dc_offset():
    # A high-pass filter should strip a large constant offset but preserve a
    # fast transient. Use the default cheby1 high-pass at 300 Hz.
    app = ndi_app_spikeextractor(session=None)
    params = app.default_extraction_parameters()
    sample_rate = 30000.0
    fs = app.makefilterstruct(params, sample_rate)

    n = 3000
    t = np.arange(n) / sample_rate
    signal = 50.0 + np.sin(2 * np.pi * 5000 * t)  # DC + 5 kHz tone
    out = app.filter(signal.reshape(-1, 1), fs).reshape(-1)
    # Interior mean (avoid edge transients) should be near zero after HP.
    assert abs(np.mean(out[500:-500])) < 1.0
    # The 5 kHz component (well above 300 Hz cutoff) should survive.
    assert np.std(out[500:-500]) > 0.5


# ---------------------------------------------------------------------------
# Full in-memory detect + extract pipeline on a synthetic trace
# ---------------------------------------------------------------------------


class _FakeTimeseries:
    """Minimal timeseries stub exposing the API extract() needs."""

    def __init__(self, data, sample_rate):
        self._data = np.asarray(data, dtype=float)
        if self._data.ndim == 1:
            self._data = self._data.reshape(-1, 1)
        self._sr = float(sample_rate)
        self.id = "fake_element_id"

    def samplerate(self, epoch=None):
        return self._sr

    def readtimeseries(self, epoch, t0, t1):
        n = self._data.shape[0]
        times = np.arange(n) / self._sr
        if t0 == -np.inf and t1 == np.inf:
            return self._data, times, None
        mask = (times >= t0) & (times <= t1)
        return self._data[mask], times[mask], None

    def epochid(self, epoch):
        return f"epoch_{epoch}"


def _make_synthetic_trace(sample_rate=30000.0, n=6000, spike_locs=(1000, 2500, 4200)):
    """Negative-going spikes (a sharp dip) at known sample locations."""
    rng = np.random.default_rng(42)
    trace = rng.normal(0, 0.2, n)
    # Build a small biphasic-ish negative spike shape.
    shape = np.array([-1, -4, -8, -10, -6, -2, 1, 2, 1, 0.5], dtype=float) * 3.0
    for loc in spike_locs:
        trace[loc : loc + len(shape)] += shape
    return trace, list(spike_locs)


def test_extract_epoch_inmemory_detects_known_spikes():
    sample_rate = 30000.0
    trace, spike_locs = _make_synthetic_trace(sample_rate=sample_rate)
    ts = _FakeTimeseries(trace, sample_rate)

    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    # Disable filtering so the injected spikes are detected directly and the
    # detection sample indices are easy to reason about.
    params["filter_type"] = "none"
    params["threshold_method"] = "standard_deviation"
    params["threshold_parameter"] = -4
    params["threshold_sign"] = -1

    waveforms, spiketimes, waveparams = app.extract_epoch_inmemory(
        ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf
    )

    # We injected exactly len(spike_locs) spikes; detection should find them.
    assert waveforms.ndim == 3  # (S, D, N)
    s, d, n = waveforms.shape
    assert d == 1
    assert n == len(spike_locs)
    assert spiketimes.shape == (n,)

    # Number of samples per waveform = S1 - S0 + 1.
    spike_sample_start = int(math.floor(params["spike_start_time"] * sample_rate))
    spike_sample_end = int(math.ceil(params["spike_end_time"] * sample_rate))
    assert s == spike_sample_end - spike_sample_start + 1
    assert waveparams["numchannels"] == 1
    assert waveparams["S0"] == spike_sample_start
    assert waveparams["S1"] == spike_sample_end

    # Each detected spike time should be near one of the injected spike
    # locations (the dip minimum is a few samples into the shape).
    injected_times = np.array(spike_locs) / sample_rate
    for st in spiketimes:
        assert np.min(np.abs(injected_times - st)) < (15 / sample_rate)


def test_extract_epoch_inmemory_absolute_threshold():
    sample_rate = 30000.0
    trace, spike_locs = _make_synthetic_trace(sample_rate=sample_rate)
    ts = _FakeTimeseries(trace, sample_rate)

    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    params["filter_type"] = "none"
    params["threshold_method"] = "absolute"
    params["threshold_parameter"] = -15.0  # below baseline noise, above spikes
    params["threshold_sign"] = -1

    waveforms, spiketimes, _ = app.extract_epoch_inmemory(
        ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf
    )
    assert waveforms.shape[2] == len(spike_locs)


def test_extract_epoch_inmemory_no_spikes_returns_empty():
    sample_rate = 30000.0
    rng = np.random.default_rng(7)
    trace = rng.normal(0, 0.2, 4000)  # pure noise, no spikes
    ts = _FakeTimeseries(trace, sample_rate)

    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    params["filter_type"] = "none"
    params["threshold_method"] = "absolute"
    params["threshold_parameter"] = -50.0  # nothing crosses this
    params["threshold_sign"] = -1

    waveforms, spiketimes, _ = app.extract_epoch_inmemory(
        ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf
    )
    assert waveforms.shape[2] == 0
    assert spiketimes.shape == (0,)


def test_refractory_merges_close_detections():
    # Two spikes closer than refractory_time collapse to one detection.
    sample_rate = 30000.0
    n = 4000
    rng = np.random.default_rng(11)
    trace = rng.normal(0, 0.2, n)
    shape = np.array([-2, -8, -12, -6, -1], dtype=float) * 3.0
    # Place two spikes only 5 samples apart (< refractory of ~30 samples).
    trace[2000 : 2000 + len(shape)] += shape
    trace[2005 : 2005 + len(shape)] += shape
    ts = _FakeTimeseries(trace, sample_rate)

    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    params["filter_type"] = "none"
    params["threshold_method"] = "absolute"
    params["threshold_parameter"] = -15.0
    params["threshold_sign"] = -1
    params["refractory_time"] = 0.001  # 30 samples @ 30 kHz

    waveforms, _, _ = app.extract_epoch_inmemory(
        ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf
    )
    # The two close events merge into a single detection.
    assert waveforms.shape[2] == 1


# ---------------------------------------------------------------------------
# MATLAB-parity spike-center index (round-half-away-from-zero, not banker's)
# ---------------------------------------------------------------------------


def test_spike_center_index_matlab_parity_odd_window():
    """The reported spike time uses MATLAB ``round(numel/2)`` for the window
    centre, which rounds half AWAY from zero. Python's built-in ``round`` uses
    banker's rounding (round-half-to-even), so for the DEFAULT extraction
    parameters -- which yield an ODD window of N=45 samples -- the two diverge
    by exactly one sample: MATLAB round(22.5)=23 (centre sample +8), Python
    round(22.5)=22 (centre sample +7). This regression pins the +1-sample
    correction so a single, sample-aligned negative spike is reported at its
    true peak sample rather than one sample early.
    """
    sample_rate = 30000.0
    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())

    # Confirm the default window is the odd N=45 that exposes the divergence.
    spike_sample_start = int(math.floor(params["spike_start_time"] * sample_rate))
    spike_sample_end = int(math.ceil(params["spike_end_time"] * sample_rate))
    n_spike_samples = spike_sample_end - spike_sample_start + 1
    assert n_spike_samples == 45  # odd: banker's vs away-from-zero differ
    selection = np.arange(spike_sample_start, spike_sample_end + 1)

    # MATLAB-parity centre (away-from-zero) vs the old Python banker's centre.
    matlab_center_pos = math.floor(n_spike_samples / 2.0 + 0.5) - 1
    banker_center_pos = int(round(n_spike_samples / 2.0)) - 1
    assert matlab_center_pos == banker_center_pos + 1  # the off-by-one
    matlab_center_in_samples = int(selection[matlab_center_pos])
    banker_center_in_samples = int(selection[banker_center_pos])
    assert matlab_center_in_samples - banker_center_in_samples == 1

    # A single, sharp, symmetric negative spike whose minimum sits exactly at a
    # known sample. centerspikes_neg finds zero net shift on a symmetric peak,
    # so the reported sample index is loc - 0 + centre_in_samples offset; with
    # the MATLAB centre it lands exactly on the true peak sample.
    n = 3000
    trace = np.zeros(n)
    shape = np.array([-1, -3, -8, -15, -8, -3, -1], dtype=float) * 2.0
    loc = 1500  # index of the (symmetric) minimum
    trace[loc - 3 : loc - 3 + len(shape)] += shape
    ts = _FakeTimeseries(trace, sample_rate)

    params["filter_type"] = "none"
    params["threshold_method"] = "absolute"
    params["threshold_parameter"] = -20.0
    params["threshold_sign"] = -1

    _, spiketimes, _ = app.extract_epoch_inmemory(
        ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf
    )
    assert spiketimes.shape == (1,)

    # times = arange(N)/sr, so time*sr is the reported (fractional) sample index.
    reported_sample = spiketimes[0] * sample_rate
    # MATLAB-parity: the spike is reported at its true peak sample (1500).
    assert reported_sample == pytest.approx(float(loc), abs=1e-6)
    # The pre-fix banker's centre would report exactly one sample EARLIER.
    banker_reported = reported_sample - (matlab_center_in_samples - banker_center_in_samples)
    assert banker_reported == pytest.approx(float(loc) - 1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Derived sample rate -- robustness to a missing per-epoch samplerate accessor
# (cloud-materialized elements return None even though readtimeseries is intact)
# ---------------------------------------------------------------------------


class _FakeTimeseriesNoRate(_FakeTimeseries):
    """Like _FakeTimeseries but with NO per-epoch samplerate metadata.

    Mirrors a cloud-materialized element whose ``samplerate(epoch)`` returns
    ``None`` (the per-epoch rate isn't populated in the materialized store)
    while ``readtimeseries`` and its time vector still read fine.
    """

    def samplerate(self, epoch=None):
        return None


def test_extract_epoch_inmemory_derives_rate_when_samplerate_missing():
    # When samplerate(epoch) is None, the extractor must recover the rate from
    # the readtimeseries time vector (fs = (N-1)/(t_last-t_first)) and detect
    # the same spikes as the accessor path.
    sample_rate = 30000.0
    trace, spike_locs = _make_synthetic_trace(sample_rate=sample_rate)
    ts = _FakeTimeseriesNoRate(trace, sample_rate)

    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    params["filter_type"] = "none"
    params["threshold_method"] = "standard_deviation"
    params["threshold_parameter"] = -4
    params["threshold_sign"] = -1

    waveforms, spiketimes, waveparams = app.extract_epoch_inmemory(
        ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf
    )

    # times = arange(N)/sr is uniformly sampled, so the derived rate equals the
    # true rate exactly; detection then matches the accessor path.
    assert waveparams["samplerate"] == pytest.approx(sample_rate)
    assert waveforms.shape[2] == len(spike_locs)
    assert spiketimes.shape == (len(spike_locs),)
    injected_times = np.array(spike_locs) / sample_rate
    for st in spiketimes:
        assert np.min(np.abs(injected_times - st)) < (15 / sample_rate)


def test_extract_epoch_inmemory_raises_when_rate_unresolvable():
    # No accessor rate AND a degenerate single-sample time vector -> the rate
    # cannot be derived, so the original ValueError is preserved.
    class _NoRateSingleSample(_FakeTimeseriesNoRate):
        def readtimeseries(self, epoch, t0, t1):
            return np.zeros((1, 1)), np.array([0.0]), None

    ts = _NoRateSingleSample(np.zeros(10), 30000.0)
    app = ndi_app_spikeextractor(session=None)
    params = dict(app.default_extraction_parameters())
    params["filter_type"] = "none"
    with pytest.raises(ValueError, match="positive sample rate"):
        app.extract_epoch_inmemory(ts, epoch=1, extraction_doc=params, t0=-np.inf, t1=np.inf)
