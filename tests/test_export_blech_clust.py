"""Unit tests for ndi.fun.export.blech_clust_write.

MATLAB equivalent: ndi.fun.export.blech_clust_write

The file format is an interop contract with blech_clust, and it has already
been got wrong once: VH-Lab/NDI-matlab#855 reported the spike_array axes as
(time, units, trials) where blech needs (trials, units, time). These tests pin
the contract from the reader's side -- what h5py actually sees when the file is
opened -- rather than from the writer's intent.
"""

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from ndi.fun.export import blech_clust_write  # noqa: E402

PRE, POST = 10.0, 20.0
DUR = int(PRE + POST)


def _unit_info(n):
    return [
        {
            "name": f"unit_{i}",
            "single_unit": i % 2,
            "regular_spiking": 1,
            "fast_spiking": 0,
        }
        for i in range(n)
    ]


def _write(tmp_path, **kw):
    path = tmp_path / "out.h5"
    defaults = {
        "unit_spiketimes": [np.array([1.0]), np.array([2.0])],
        "unit_info": _unit_info(2),
        "onset_times": np.array([1.0, 2.0]),
        "trial_stimid": np.array([7.0, 8.0]),
        "stimid_tastant": {7: "sucrose", 8: "quinine"},
        "pre_stim": PRE,
        "post_stim": POST,
        "sample_rate": 1000.0,
        "verbose": False,
    }
    defaults.update(kw)
    blech_clust_write(str(path), **defaults)
    return path


class TestSpikeArrayAxisOrder:
    """Issue #855. The shape a Python reader sees is the whole contract."""

    def test_shape_is_trials_units_time(self, tmp_path):
        path = _write(
            tmp_path,
            onset_times=np.array([1.0, 2.0, 3.0]),
            trial_stimid=np.array([7.0, 7.0, 7.0]),
        )
        with h5py.File(path, "r") as f:
            arr = f["/spike_trains/dig_in_0/spike_array"]
            assert arr.shape == (3, 2, DUR), (
                "blech_clust requires (n_trials, n_units, trial_dur_ms); a "
                "compensating transpose would show up here."
            )
            assert arr.dtype == np.uint8

    def test_the_three_axis_lengths_are_distinguishable(self, tmp_path):
        """With 3 trials, 2 units and 30 ms, no two axes could be confused.

        A test with equal axis lengths would pass under any permutation.
        """
        path = _write(
            tmp_path,
            onset_times=np.array([1.0, 2.0, 3.0]),
            trial_stimid=np.array([7.0, 7.0, 7.0]),
        )
        with h5py.File(path, "r") as f:
            assert len(set(f["/spike_trains/dig_in_0/spike_array"].shape)) == 3


class TestBinning:
    def test_a_spike_at_delivery_lands_in_the_pre_stim_column(self, tmp_path):
        # pre_stim 2000 ms makes win_start = onset - 2.0, exact in binary, so
        # the bin index is exactly pre_stim_ms. See the test below for what
        # happens when the window is not exactly representable.
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([5.0])],
            unit_info=_unit_info(1),
            onset_times=np.array([5.0]),
            trial_stimid=np.array([7.0]),
            pre_stim=2000.0,
            post_stim=1000.0,
        )
        with h5py.File(path, "r") as f:
            arr = f["/spike_trains/dig_in_0/spike_array"][...]
        assert arr[0, 0, 2000] == 1
        assert arr.sum() == 1, "Exactly one bin should be set."

    def test_delivery_bin_can_be_one_early_when_the_window_is_not_exact(self, tmp_path):
        """A spike exactly at delivery is binned one millisecond EARLY when
        ``onset - pre_stim/1000`` is not exactly representable.

        With onset 5.0 s and a 10 ms pre-window, win_start is 4.99, and
        ``(5.0 - 4.99) * 1000`` evaluates to 9.999999999999787, so floor gives
        bin 9 rather than 10.

        This is not a Python artifact: MATLAB performs the identical IEEE-754
        operations in the same order and reaches the same bin. It is pinned
        rather than corrected because rounding here instead of flooring would
        silently move every spike relative to the MATLAB exporter, and the two
        must agree. Worth a look on its own, though -- with the default
        pre_stim of 2000 ms the window is exact and this does not arise.
        """
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([5.0])],
            unit_info=_unit_info(1),
            onset_times=np.array([5.0]),
            trial_stimid=np.array([7.0]),
        )
        with h5py.File(path, "r") as f:
            arr = f["/spike_trains/dig_in_0/spike_array"][...]
        assert arr[0, 0, 9] == 1
        assert arr[0, 0, int(PRE)] == 0

    def test_spikes_outside_the_window_are_dropped(self, tmp_path):
        # Window is [onset-10ms, onset+20ms). 4.98 s and 5.03 s are outside.
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([4.98, 5.0, 5.03])],
            unit_info=_unit_info(1),
            onset_times=np.array([5.0]),
            trial_stimid=np.array([7.0]),
        )
        with h5py.File(path, "r") as f:
            arr = f["/spike_trains/dig_in_0/spike_array"][...]
        assert arr.sum() == 1

    def test_each_trial_is_binned_against_its_own_onset(self, tmp_path):
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([1.0, 50.0])],
            unit_info=_unit_info(1),
            onset_times=np.array([1.0, 50.0]),
            trial_stimid=np.array([7.0, 7.0]),
            pre_stim=2000.0,
            post_stim=1000.0,
        )
        with h5py.File(path, "r") as f:
            arr = f["/spike_trains/dig_in_0/spike_array"][...]
        assert arr[0, 0, 2000] == 1
        assert arr[1, 0, 2000] == 1
        assert arr.sum() == 2


class TestDigInNumbering:
    def test_an_empty_tastant_is_skipped_with_a_warning(self, tmp_path):
        with pytest.warns(UserWarning, match="no trials"):
            path = _write(
                tmp_path,
                onset_times=np.array([1.0]),
                trial_stimid=np.array([7.0]),
                stimulus_order=[7, 9],
                stimid_tastant={7: "sucrose", 9: "empty"},
            )
        with h5py.File(path, "r") as f:
            assert "dig_in_1" not in f["/spike_trains"]

    def test_a_skipped_tastant_still_consumes_its_index(self, tmp_path):
        """MATLAB names the group from the loop counter before the skip, so
        the numbering has a GAP. Closing the gap would be a silent format
        change for anything reading dig_in_<N> positionally."""
        with pytest.warns(UserWarning):
            path = _write(
                tmp_path,
                onset_times=np.array([1.0]),
                trial_stimid=np.array([8.0]),
                stimulus_order=[7, 8],
                stimid_tastant={7: "empty", 8: "quinine"},
            )
        with h5py.File(path, "r") as f:
            names = sorted(f["/spike_trains"].keys())
        assert names == ["dig_in_1"], "The present tastant keeps index 1, not 0."

    def test_stimulus_order_sets_the_dig_in_mapping(self, tmp_path):
        path = _write(tmp_path, stimulus_order=[8, 7])
        with h5py.File(path, "r") as f:
            assert f["/spike_trains/dig_in_0"].attrs["stimid"] == 8
            assert f["/spike_trains/dig_in_1"].attrs["stimid"] == 7

    def test_include_stimids_restricts_the_export(self, tmp_path):
        path = _write(tmp_path, include_stimids=[8])
        with h5py.File(path, "r") as f:
            assert sorted(f["/spike_trains"].keys()) == ["dig_in_0"]
            assert f["/spike_trains/dig_in_0"].attrs["stimid"] == 8

    def test_no_stimuli_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match="No tastant stimuli"):
            _write(tmp_path, include_stimids=[999])


class TestSortedUnits:
    def test_times_are_acquisition_samples_as_uint64(self, tmp_path):
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([1.0, 2.0])],
            unit_info=_unit_info(1),
            sample_rate=1000.0,
        )
        with h5py.File(path, "r") as f:
            times = f["/sorted_units/unit000/times"]
            assert times.dtype == np.uint64
            assert list(times[...]) == [1000, 2000]

    def test_half_samples_round_away_from_zero_like_matlab(self, tmp_path):
        """numpy rounds half to even, MATLAB rounds half away from zero.

        At sample_rate 1 Hz a spike at 0.5 s is exactly half a sample:
        MATLAB records 1, an unadjusted numpy port would record 0.
        """
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([0.5, 1.5, 2.5])],
            unit_info=_unit_info(1),
            sample_rate=1.0,
            onset_times=np.array([1.0]),
            trial_stimid=np.array([7.0]),
        )
        with h5py.File(path, "r") as f:
            assert list(f["/sorted_units/unit000/times"][...]) == [1, 2, 3]

    def test_negative_times_are_dropped(self, tmp_path):
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([-1.0, 1.0])],
            unit_info=_unit_info(1),
            sample_rate=1000.0,
        )
        with h5py.File(path, "r") as f:
            assert list(f["/sorted_units/unit000/times"][...]) == [1000]

    def test_a_silent_unit_gets_a_single_zero(self, tmp_path):
        """HDF5 forbids a zero-length dimension, so MATLAB writes one 0."""
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([])],
            unit_info=_unit_info(1),
        )
        with h5py.File(path, "r") as f:
            assert list(f["/sorted_units/unit000/times"][...]) == [0]


class TestUnitDescriptor:
    def test_compound_table_of_three_int32_columns(self, tmp_path):
        path = _write(tmp_path)
        with h5py.File(path, "r") as f:
            table = f["unit_descriptor"][...]
        assert table.dtype.names == ("single_unit", "regular_spiking", "fast_spiking")
        assert all(table.dtype[name] == np.int32 for name in table.dtype.names)
        assert list(table["single_unit"]) == [0, 1]
        assert list(table["regular_spiking"]) == [1, 1]
        assert list(table["fast_spiking"]) == [0, 0]

    def test_one_row_per_unit(self, tmp_path):
        path = _write(
            tmp_path,
            unit_spiketimes=[np.array([1.0])] * 3,
            unit_info=_unit_info(3),
        )
        with h5py.File(path, "r") as f:
            assert f["unit_descriptor"].shape == (3,)


class TestAttributes:
    def test_numeric_attributes_are_doubles(self, tmp_path):
        """MATLAB's h5writeatt stores a numeric scalar as a double; writing
        ints here would change the type a MATLAB reader sees."""
        path = _write(tmp_path)
        with h5py.File(path, "r") as f:
            group = f["/spike_trains/dig_in_0"]
            for name in ("stimid", "n_trials", "pre_stim_ms", "post_stim_ms"):
                assert np.asarray(group.attrs[name]).dtype == np.float64, name
            assert np.asarray(f.attrs["sample_rate_hz"]).dtype == np.float64

    def test_tastant_and_epoch_are_recorded(self, tmp_path):
        path = _write(tmp_path, epoch_id="t00001")
        with h5py.File(path, "r") as f:
            assert f["/spike_trains/dig_in_0"].attrs["tastant"] == "sucrose"
            assert f.attrs["ndi_epochid"] == "t00001"

    def test_an_unmapped_stimid_is_labelled_unknown(self, tmp_path):
        path = _write(tmp_path, stimid_tastant={})
        with h5py.File(path, "r") as f:
            assert f["/spike_trains/dig_in_0"].attrs["tastant"] == "unknown"

    def test_window_attributes_match_the_array(self, tmp_path):
        path = _write(tmp_path)
        with h5py.File(path, "r") as f:
            group = f["/spike_trains/dig_in_0"]
            span = group.attrs["pre_stim_ms"] + group.attrs["post_stim_ms"]
            assert group["spike_array"].shape[2] == span


def test_an_existing_file_is_overwritten(tmp_path):
    path = tmp_path / "out.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("leftover", data=[1, 2, 3])
    _write(tmp_path)
    with h5py.File(path, "r") as f:
        assert "leftover" not in f
