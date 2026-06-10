"""PR5 §3.4-7: ndi.time.fun trigger-train / random-trigger synchronization.

Ports of MATLAB syncTriggerTrains / syncRandomTriggers: quantized interval
fingerprints align two independent clocks recording a common pulse train, robust
to drift, a dropped pulse, and partial overlap. These replace the prior
hard-fail-on-unequal-counts and interval cross-correlation approaches.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.time.fun import sync_random_triggers, sync_trigger_trains


def _train(n=30, seed=0, start=0.0):
    rng = np.random.RandomState(seed)
    intervals = 0.5 + rng.rand(n - 1)  # varied 0.5-1.5s intervals
    return start + np.concatenate([[0.0], np.cumsum(intervals)])


class TestSyncTriggerTrains:
    def test_exact_recovery(self):
        t1 = _train(30, seed=1)
        t2 = 10.0 + 1.0 * t1  # shift 10, scale 1
        shift, scale = sync_trigger_trains(t1, t2)
        assert abs(scale - 1.0) < 1e-6
        assert abs(shift - 10.0) < 1e-3

    def test_recovers_drift(self):
        t1 = _train(40, seed=2)
        scale_true, shift_true = 1.0002, 5.0  # ~200 ppm drift
        t2 = shift_true + scale_true * t1
        shift, scale = sync_trigger_trains(t1, t2)
        assert abs(scale - scale_true) < 1e-4
        assert abs(shift - shift_true) < 1e-2

    def test_one_dropped_pulse(self):
        t1 = _train(30, seed=3)
        t2 = 2.0 + 1.0 * t1
        t2_dropped = np.delete(t2, 15)  # remove a middle pulse
        shift, scale = sync_trigger_trains(t1, t2_dropped)
        assert abs(scale - 1.0) < 1e-3
        assert abs(shift - 2.0) < 1e-1

    def test_partial_overlap(self):
        # the shorter train (prober) lies fully within the longer one's span,
        # so >= min_match_rate of its pulses align (partial overlap of the files)
        full = _train(50, seed=5)
        t1 = full[:40]
        t2 = 3.0 + full[5:35]  # 30 pulses, all within t1's time span
        shift, scale = sync_trigger_trains(t1, t2)
        assert abs(scale - 1.0) < 1e-3
        assert abs(shift - 3.0) < 1e-1

    def test_below_match_rate_returns_nan(self):
        # only ~half the prober overlaps the target -> below min_match_rate=0.8
        full = _train(50, seed=8)
        t1 = full[:35]
        t2 = 3.0 + full[15:]
        shift, scale = sync_trigger_trains(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)

    def test_unrelated_returns_nan(self):
        t1 = _train(30, seed=6)
        t2 = _train(30, seed=999)
        shift, scale = sync_trigger_trains(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)

    def test_too_short_returns_nan(self):
        shift, scale = sync_trigger_trains([0.0, 1.0], [0.0, 1.0])
        assert np.isnan(shift) and np.isnan(scale)

    def test_periodic_data_is_ambiguous(self):
        # perfectly uniform intervals -> many indistinguishable alignments
        t1 = np.arange(0, 30, 1.0)
        t2 = 4.0 + t1
        with pytest.raises(ValueError, match="ambiguous"):
            sync_trigger_trains(t1, t2)


class TestSyncRandomTriggers:
    def test_recovery_with_offset_and_scale(self):
        t2 = _train(40, seed=11)
        scale_true, shift_true = 1.0, 7.5  # t1 = shift + scale*t2
        t1 = shift_true + scale_true * t2
        shift, scale = sync_random_triggers(t1, t2)
        assert abs(scale - scale_true) < 1e-4
        assert abs(shift - shift_true) < 1e-2

    def test_partial_overlap(self):
        full = _train(60, seed=12)
        t2 = full[:40]
        t1 = 2.0 + full[10:]  # t1 = 2 + t2-region, overlapping
        shift, scale = sync_random_triggers(t1, t2)
        assert abs(scale - 1.0) < 1e-3
        assert abs(shift - 2.0) < 1e-1

    def test_unrelated_returns_nan(self):
        t1 = _train(30, seed=13)
        t2 = _train(30, seed=777)
        shift, scale = sync_random_triggers(t1, t2)
        assert np.isnan(shift) and np.isnan(scale)


class TestCommonTriggersFallback:
    def test_unequal_counts_falls_back(self):
        from ndi.time.syncrule.common_triggers_overlapping_epochs import _sync_triggers

        t1 = _train(30, seed=21)
        t2 = 6.0 + 1.0 * t1
        t2_dropped = np.delete(t2, 20)  # unequal length -> fingerprint fallback
        shift, scale = _sync_triggers(t1, t2_dropped)
        assert abs(scale - 1.0) < 1e-3
        assert abs(shift - 6.0) < 1e-1

    def test_equal_counts_direct_fit(self):
        from ndi.time.syncrule.common_triggers_overlapping_epochs import _sync_triggers

        t1 = _train(20, seed=22)
        t2 = 1.5 + 2.0 * t1
        shift, scale = _sync_triggers(t1, t2)
        assert abs(scale - 2.0) < 1e-9
        assert abs(shift - 1.5) < 1e-9
