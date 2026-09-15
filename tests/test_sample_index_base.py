"""Pin the sample-index base: 0-based in Python, 1-based in MATLAB.

Issue: Waltham-Data-Science/NDI-python#313.

The `s0`/`s1` of `readchannels_epochsamples[_ingested]`, the return of
`epochtimes2samples[_ingested]`, and the argument to
`epochsamples2times[_ingested]` are 0-based in Python but 1-based in
NDI-matlab (`src/ndi/+ndi/+daq/+reader/mfdaq.m::epochtimes2samples`
comment: "Entries of T that are -Inf are clamped to the first sample of
the epoch (sample 1)"). This is a **deliberate**, documented divergence
-- see section 1 of `docs/developer_notes/ndi_xlang_principles.md` and
the decision_log entries on the six `epoch*samples*` methods in
`src/ndi/daq/ndi_matlab_python_bridge.yaml` -- but it is also a
portability trap: a caller literally translating a MATLAB `s0=1` into
Python `s0=1` would read the *second* sample rather than the first.

The tests below assert the Python contract in a form that names the
MATLAB counterpart explicitly, so a future refactor that quietly flips
the base on one side has to update this file and cannot do so silently.

The tests use the same mocking approach as
`tests/test_daq.py::TestIngestedDataMethods`, both to avoid a
session-on-disk fixture and to keep the pinning targeted at the
sample-index-base contract rather than any I/O behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from ndi.daq.mfdaq import ndi_daq_reader_mfdaq

SR = 1_000.0  # samples/second
T0 = 0.0
T1 = 1.999  # 2000 samples at 1 kHz, 0-based indices 0..1999
N_SAMPLES = 2000  # so t0 -> 0, t1 -> N_SAMPLES - 1 = 1999


class _MinimalReader(ndi_daq_reader_mfdaq):
    """Concrete stand-in that answers `samplerate` and `t0_t1`.

    The ingested methods (`samplerate_ingested`, `t0_t1_ingested`) are
    stubbed on the instance in each test.
    """

    def getchannelsepoch(self, epochfiles):
        return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        raise NotImplementedError

    def samplerate(self, epochfiles, channeltype, channel):
        if isinstance(channel, int):
            channel = [channel]
        return np.full(len(channel), SR)

    def t0_t1(self, epochfiles):
        return [(T0, T1)]


def _reader() -> _MinimalReader:
    r = _MinimalReader()
    r.samplerate_ingested = MagicMock(
        return_value=(np.array([SR]), np.array([0.0]), np.array([1.0])),
    )
    r.t0_t1_ingested = MagicMock(return_value=[(T0, T1)])
    r.getingesteddocument = MagicMock()
    return r


# =============================================================================
# epochtimes2samples: Python returns 0, MATLAB returns 1
# =============================================================================


class TestEpochTimes2SamplesIsZeroBased:
    """`t = t0` -> `s = 0` in Python; MATLAB returns `s = 1` for the same input.

    NDI-matlab `epochtimes2samples` uses `s = 1 + round((t-t0)*sr)`;
    Python uses `s = round((t-t0)*sr)`. That one-line difference is the
    portability trap this file pins.
    """

    def test_t_equal_t0_maps_to_sample_zero_not_one(self):
        # MATLAB divergence: NDI-matlab returns 1 for t = t0.
        reader = _MinimalReader()
        samples = reader.epochtimes2samples("ai", 1, ["f.dat"], np.array([T0]))
        assert samples[0] == 0

    def test_t_equal_t1_maps_to_last_zero_based_sample(self):
        # MATLAB divergence: NDI-matlab returns N_SAMPLES for t = t1.
        reader = _MinimalReader()
        samples = reader.epochtimes2samples("ai", 1, ["f.dat"], np.array([T1]))
        assert samples[0] == N_SAMPLES - 1

    def test_neg_inf_clamps_to_first_python_sample_zero(self):
        # MATLAB divergence: NDI-matlab clamps -Inf to sample 1
        # ("Entries of T that are -Inf are clamped to the first sample
        # of the epoch (sample 1)", mfdaq.m::epochtimes2samples).
        reader = _MinimalReader()
        samples = reader.epochtimes2samples("ai", 1, ["f.dat"], np.array([-np.inf]))
        assert samples[0] == 0

    def test_pos_inf_clamps_to_last_python_sample_n_minus_one(self):
        # MATLAB divergence: NDI-matlab clamps +Inf to sample N.
        reader = _MinimalReader()
        samples = reader.epochtimes2samples("ai", 1, ["f.dat"], np.array([np.inf]))
        assert samples[0] == N_SAMPLES - 1

    def test_epochtimes2samples_of_t0_t1_span_returns_zero_to_n_minus_one(self):
        # MATLAB divergence: NDI-matlab returns [1, N] for the same input.
        # This is the value that reaches readchannels_epochsamples_ingested
        # as abs_s (see mfdaq.py:798-803), and the reader's clamp depends
        # on it being 0-based.
        reader = _MinimalReader()
        samples = reader.epochtimes2samples("ai", 1, ["f.dat"], np.array([T0, T1]))
        assert samples[0] == 0
        assert samples[1] == N_SAMPLES - 1


class TestEpochTimes2SamplesIngestedIsZeroBased:
    """Same contract on the ingested path (`epochtimes2samples_ingested`)."""

    def test_t_equal_t0_maps_to_sample_zero_not_one(self):
        reader = _reader()
        samples = reader.epochtimes2samples_ingested(
            "ai", 1, ["epochid://x"], np.array([T0]), MagicMock()
        )
        assert samples[0] == 0

    def test_t_equal_t1_maps_to_last_zero_based_sample(self):
        reader = _reader()
        samples = reader.epochtimes2samples_ingested(
            "ai", 1, ["epochid://x"], np.array([T1]), MagicMock()
        )
        assert samples[0] == N_SAMPLES - 1

    def test_neg_inf_clamps_to_first_python_sample_zero(self):
        reader = _reader()
        samples = reader.epochtimes2samples_ingested(
            "ai", 1, ["epochid://x"], np.array([-np.inf]), MagicMock()
        )
        assert samples[0] == 0

    def test_pos_inf_clamps_to_last_python_sample_n_minus_one(self):
        reader = _reader()
        samples = reader.epochtimes2samples_ingested(
            "ai", 1, ["epochid://x"], np.array([np.inf]), MagicMock()
        )
        assert samples[0] == N_SAMPLES - 1


# =============================================================================
# epochsamples2times: sample 0 -> t = t0 in Python; sample 1 -> t = t0 in MATLAB
# =============================================================================


class TestEpochSamples2TimesIsZeroBased:
    """`s = 0` -> `t = t0` in Python; MATLAB gives `t = t0` for `s = 1`.

    NDI-matlab `epochsamples2times` uses `t = t0 + (s-1)/sr`; Python
    uses `t = t0 + s/sr`.
    """

    def test_sample_zero_maps_to_t0(self):
        # MATLAB divergence: NDI-matlab gives t = t0 - 1/sr for s = 0.
        reader = _MinimalReader()
        times = reader.epochsamples2times("ai", 1, ["f.dat"], np.array([0]))
        assert times[0] == T0

    def test_sample_one_is_one_period_past_t0(self):
        # MATLAB divergence: NDI-matlab gives t = t0 for s = 1 (the
        # "first sample" in its 1-based convention).
        reader = _MinimalReader()
        times = reader.epochsamples2times("ai", 1, ["f.dat"], np.array([1]))
        assert times[0] == T0 + 1.0 / SR

    def test_sample_n_minus_one_maps_to_t1(self):
        # MATLAB divergence: NDI-matlab uses s = N for the last sample.
        reader = _MinimalReader()
        times = reader.epochsamples2times("ai", 1, ["f.dat"], np.array([N_SAMPLES - 1]))
        np.testing.assert_allclose(times[0], T1)


class TestEpochSamples2TimesIngestedIsZeroBased:
    """Same contract on the ingested path."""

    def test_sample_zero_maps_to_t0(self):
        reader = _reader()
        times = reader.epochsamples2times_ingested(
            "ai", 1, ["epochid://x"], np.array([0]), MagicMock()
        )
        assert times[0] == T0

    def test_sample_one_is_one_period_past_t0(self):
        reader = _reader()
        times = reader.epochsamples2times_ingested(
            "ai", 1, ["epochid://x"], np.array([1]), MagicMock()
        )
        assert times[0] == T0 + 1.0 / SR

    def test_sample_n_minus_one_maps_to_t1(self):
        reader = _reader()
        times = reader.epochsamples2times_ingested(
            "ai", 1, ["epochid://x"], np.array([N_SAMPLES - 1]), MagicMock()
        )
        np.testing.assert_allclose(times[0], T1)


# =============================================================================
# The round trip: samples -> times -> samples is the identity, for both bases
# =============================================================================


class TestSampleTimeRoundTrip:
    """A round trip pins the two formulas against each other.

    If a future refactor flipped only one direction (e.g. added `+1` to
    `epochtimes2samples` but not `epochsamples2times`), one of the two
    round-trip tests above would still pass while the other broke; this
    class catches that half-flip.
    """

    def test_samples_to_times_to_samples_is_identity(self):
        reader = _MinimalReader()
        original = np.array([0, 1, 100, N_SAMPLES - 1])
        times = reader.epochsamples2times("ai", 1, ["f.dat"], original)
        recovered = reader.epochtimes2samples("ai", 1, ["f.dat"], times)
        np.testing.assert_array_equal(recovered, original)

    def test_samples_to_times_to_samples_is_identity_ingested(self):
        reader = _reader()
        original = np.array([0, 1, 100, N_SAMPLES - 1])
        times = reader.epochsamples2times_ingested("ai", 1, ["epochid://x"], original, MagicMock())
        recovered = reader.epochtimes2samples_ingested("ai", 1, ["epochid://x"], times, MagicMock())
        np.testing.assert_array_equal(recovered, original)
