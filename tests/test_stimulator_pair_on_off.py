"""Stimulus on/off events are paired, and a clipped interval survives it.

MATLAB counterpart: ``+ndi/+probe/+timeseries/stimulator.m``, whose
``pairOnOff`` static method replaced three copies of::

    t.stimon  = timestamps{i}(find(edata{i}(:,1)>0),1);
    t.stimoff = timestamps{i}(find(edata{i}(:,1)==-1),1);

Selecting the ons and the offs separately is fine only while every
stimulus has both. A read window that starts mid-stimulus, or ends before
one finishes, yields arrays of different lengths -- and nothing then says
which on belongs to which off. Python's callers papered over this with
``len(...) == len(...)`` guards that silently dropped the pairing, so an
epoch read across a clipped boundary quietly returned offsets attributed
to the wrong onsets (NDI-matlab#248).

Pairing walks the events in time order instead: each on takes the next
off, an on with no following off gets ``nan``, and an off with no
preceding on gets ``nan`` -- equal lengths, and the orphan is visible
rather than inferred.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.probe.timeseries_stimulator import ndi_probe_timeseries_stimulator as stimulator

pair = stimulator.pair_on_off


class TestTheWellFormedCase:
    def test_alternating_events_pair_up(self):
        on, off = pair([1.0, 2.0, 3.0, 4.0], [1, -1, 1, -1])
        assert list(on) == [1.0, 3.0]
        assert list(off) == [2.0, 4.0]

    def test_no_events_is_empty(self):
        on, off = pair([], [])
        assert len(on) == 0
        assert len(off) == 0

    def test_events_are_sorted_before_pairing(self):
        """Channels are not guaranteed to arrive in time order."""
        on, off = pair([4.0, 1.0, 3.0, 2.0], [-1, 1, 1, -1])
        assert list(on) == [1.0, 3.0]
        assert list(off) == [2.0, 4.0]


class TestClippedIntervals:
    """The reason the pairing exists."""

    def test_a_stimulus_still_running_at_the_end_gets_a_nan_off(self):
        on, off = pair([1.0, 2.0, 3.0], [1, -1, 1])
        assert list(on) == [1.0, 3.0]
        assert off[0] == 2.0
        assert np.isnan(off[1])

    def test_a_stimulus_already_running_at_the_start_gets_a_nan_on(self):
        on, off = pair([1.0, 2.0, 3.0], [-1, 1, -1])
        assert np.isnan(on[0])
        assert off[0] == 1.0
        assert on[1] == 2.0
        assert off[1] == 3.0

    def test_clipped_at_both_ends(self):
        on, off = pair([1.0, 2.0, 3.0, 4.0], [-1, 1, -1, 1])
        assert np.isnan(on[0]) and off[0] == 1.0
        assert on[1] == 2.0 and off[1] == 3.0
        assert on[2] == 4.0 and np.isnan(off[2])

    @pytest.mark.parametrize(
        "signs",
        [
            [1, -1, 1],
            [-1, 1, -1],
            [1, 1, -1],
            [-1, -1, 1],
            [1, 1, 1],
            [-1, -1, -1],
        ],
    )
    def test_on_and_off_are_always_the_same_length(self, signs):
        """The invariant the length guards were standing in for."""
        times = [float(i) for i in range(len(signs))]
        on, off = pair(times, signs)
        assert len(on) == len(off)


class TestSignsAreReadAsSigns:
    def test_any_positive_value_is_an_on(self):
        """MATLAB applies ``sign()``, so the magnitude carries no meaning."""
        on, off = pair([1.0, 2.0], [7, -3])
        assert list(on) == [1.0]
        assert list(off) == [2.0]

    def test_a_negative_other_than_minus_one_is_an_off(self):
        """The old code tested ``== -1`` and dropped anything else."""
        on, off = pair([1.0, 2.0], [1, -2])
        assert list(on) == [1.0]
        assert list(off) == [2.0]
