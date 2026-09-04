"""ndi.app.spikeextractor: helpers, parameter defaults, in-memory extraction.

The session-backed persistence layer needs a full ndi_session and vlt on
the machine; those paths are exercised by the integration jobs. Here we
pin down the pieces the port is most likely to regress:

* ``_dotdisc`` — the negative-threshold branch the vlt Python port gets
  wrong. The whole extractor is silently broken if this ever collapses
  back to ``(y*sign) > thresh`` over the baseline.
* ``_refractory`` — MATLAB's round-based collapse; a single-pass keep
  would leak spikes through.
* Parameter defaults + ``isvalid_appdoc_struct`` — the appdoc contract.
* ``extract_epoch_inmemory`` end-to-end on a fake timeseries with three
  injected spikes: shape / count / times must all land.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.app.spikeextractor import _dotdisc, _refractory, ndi_app_spikeextractor


def test_dotdisc_negative_threshold_detects_isolated_dips():
    y = np.zeros(200)
    y[20] = -5.0
    y[100] = -5.0
    y[150] = -5.0
    # threshold below y=0 baseline (-4.0), sign=-1 => y < thresh
    locs = _dotdisc(y, [[-4.0, -1.0, 0.0]])
    # dotdisc emits ceil(i - ptsgood/2) with ptsgood=1: 20 -> ceil(21 - 0.5) = 21
    np.testing.assert_array_equal(locs, np.array([21.0, 101.0, 151.0]))


def test_dotdisc_positive_threshold_detects_isolated_peaks():
    y = np.zeros(50)
    y[10] = 5.0
    y[30] = 5.0
    locs = _dotdisc(y, [[4.0, 1.0, 0.0]])
    np.testing.assert_array_equal(locs, np.array([11.0, 31.0]))


def test_dotdisc_no_events_on_flat_baseline():
    y = np.zeros(100)
    locs = _dotdisc(y, [[-4.0, -1.0, 0.0]])
    assert locs.size == 0


def test_refractory_round_based_collapse():
    # Two triangles inside the refractory window: MATLAB drops the middles
    # AFTER the first survivor at 0 clears (0.9, 1.8), then keeps 5, drops 5.4.
    r = _refractory(np.array([0.0, 0.9, 1.8, 5.0, 5.4, 9.0]), 1.0)
    np.testing.assert_array_equal(r, np.array([0.0, 5.0, 9.0]))


def test_refractory_zero_period_is_noop():
    x = np.array([1.0, 1.0, 2.0, 3.0])
    np.testing.assert_array_equal(_refractory(x, 0.0), np.sort(x))


def test_refractory_empty_input():
    r = _refractory(np.array([], dtype=float), 1.0)
    assert r.size == 0


def test_default_extraction_parameters_pass_validation():
    ex = ndi_app_spikeextractor()
    p = ex.default_extraction_parameters()
    valid, msg = ex.isvalid_appdoc_struct("extraction_parameters", p)
    assert valid, msg
    # Sanity: the fields the extraction pipeline actually uses.
    assert p["threshold_sign"] == -1
    assert p["filter_type"] == "cheby1high"
    assert p["threshold_method"] == "standard_deviation"


def test_isvalid_appdoc_struct_reports_missing_fields():
    ex = ndi_app_spikeextractor()
    valid, msg = ex.isvalid_appdoc_struct("extraction_parameters", {"filter_type": "none"})
    assert not valid
    assert "missing fields" in msg


def test_isvalid_appdoc_struct_unknown_type_raises():
    ex = ndi_app_spikeextractor()
    with pytest.raises(ValueError):
        ex.isvalid_appdoc_struct("nope", {})


class FakeTimeseries:
    """A minimal timeseries object with the accessors the extractor needs."""

    id = "ts-1"
    name = "ts-1"
    reference = 1

    def __init__(self, data: np.ndarray, sample_rate: float):
        self._data = data
        self._sr = sample_rate

    def samplerate(self, _epoch):
        return self._sr

    def readtimeseries(self, _epoch, _t0, _t1):
        n = self._data.shape[0]
        t = np.arange(n) / self._sr
        return self._data, t, 0


def _inject_spike(data: np.ndarray, center: int, amplitude: float = -0.6):
    for s in range(-10, 22):
        data[center + s, 0] += amplitude * float(np.exp(-(s**2) / 8.0))


def test_extract_epoch_inmemory_recovers_injected_spikes():
    sr = 30000.0
    n = int(0.5 * sr)
    rng = np.random.default_rng(0)
    data = 0.05 * rng.standard_normal((n, 1))
    spike_centers = [3000, 8000, 12000]
    for c in spike_centers:
        _inject_spike(data, c)

    ex = ndi_app_spikeextractor()
    params = ex.default_extraction_parameters()
    waves, spiketimes, waveparams = ex.extract_epoch_inmemory(
        FakeTimeseries(data, sr), 1, params, -np.inf, np.inf
    )

    # Three spikes, S x D x N layout, no channel doubling.
    assert waves.ndim == 3
    assert waves.shape[1] == 1
    assert waves.shape[2] == 3
    assert spiketimes.shape == (3,)
    assert waveparams["numchannels"] == 1
    assert waveparams["samplerate"] == sr

    # Injected times were at c/sr; centering may nudge by up to ~1 sample.
    expected = np.array([c / sr for c in spike_centers])
    np.testing.assert_allclose(spiketimes, expected, atol=2 / sr)


def test_extract_epoch_inmemory_derives_sample_rate_from_times_when_accessor_returns_none():
    sr = 20000.0
    n = 4000
    rng = np.random.default_rng(1)
    data = 0.03 * rng.standard_normal((n, 1))
    _inject_spike(data, 2000)

    class NoRateTS(FakeTimeseries):
        def samplerate(self, _epoch):  # cloud-materialized case
            return None

    ex = ndi_app_spikeextractor()
    waves, spiketimes, waveparams = ex.extract_epoch_inmemory(
        NoRateTS(data, sr), 1, ex.default_extraction_parameters(), -np.inf, np.inf
    )
    # (n-1)/(t_last - t_first) recovers sr exactly for the uniform grid used.
    assert waveparams["samplerate"] == pytest.approx(sr)
    assert waves.shape[2] == 1
    assert spiketimes.size == 1


def test_extract_epoch_inmemory_zero_spikes_returns_empty_but_shaped():
    sr = 30000.0
    data = 0.01 * np.random.default_rng(2).standard_normal((3000, 2))
    ex = ndi_app_spikeextractor()
    waves, spiketimes, waveparams = ex.extract_epoch_inmemory(
        FakeTimeseries(data, sr), 1, ex.default_extraction_parameters()
    )
    assert waves.shape[2] == 0
    assert spiketimes.size == 0
    assert waves.shape[1] == 2


def test_extraction_params_accepts_plain_dict_and_document_properties_style():
    ex = ndi_app_spikeextractor()
    p = ex.default_extraction_parameters()
    # Plain params dict.
    assert ex._extraction_params(p) is p
    # A dict shaped like document_properties, keyed under the field name.
    wrapped = {"spike_extraction_parameters": p}
    assert ex._extraction_params(wrapped) is p


def test_normalize_epochs_handles_none_list_and_scalar():
    ex = ndi_app_spikeextractor()

    class EpochlessTS:
        def numepochs(self):
            return 3

    assert ex._normalize_epochs(EpochlessTS(), None) == [1, 2, 3]
    assert ex._normalize_epochs(EpochlessTS(), 2) == [2]
    assert ex._normalize_epochs(EpochlessTS(), [1, 3]) == [1, 3]
