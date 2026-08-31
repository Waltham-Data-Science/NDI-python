"""Unit tests for ndi.fun.ensemble.filter.

MATLAB equivalent: ndi.fun.ensemble.filter

The selection rules are stated in the MATLAB help but are easy to get subtly
wrong in a port: includes are a UNION, excludes always win, indices are
1-based, and the activity matrix has its all-zero trailing columns trimmed
afterwards -- except when nothing is kept.
"""

import numpy as np
import pytest

from ndi.fun.ensemble import filter as ensemble_filter


def make_ensemble():
    """4 neurons; neuron 3 is the widest, so trimming is observable."""
    activity = np.zeros((4, 3))
    activity[0, 0] = 11
    activity[1, :2] = [21, 22]
    activity[2, :] = [31, 32, 33]
    activity[3, 0] = 41
    return {
        "activity": activity,
        "neuron_ids": ["id1", "id2", "id3", "id4"],
        "neuron_names": ["A", "B", "C", "D"],
        "epoch": "epoch_1",
        "info": {"num_neurons": 4},
    }


class TestSelection:
    def test_no_criteria_keeps_everything(self):
        out = ensemble_filter(make_ensemble())
        assert out["neuron_names"] == ["A", "B", "C", "D"]
        assert out["activity"].shape == (4, 3)

    def test_includes_are_a_union(self):
        out = ensemble_filter(
            make_ensemble(), include_names=["A"], include_ids=["id4"], include_index=[2]
        )
        assert out["neuron_names"] == ["A", "B", "D"]

    def test_exclude_beats_include_on_the_same_neuron(self):
        """Stated in the MATLAB help; the one rule a port is likely to invert."""
        out = ensemble_filter(make_ensemble(), include_names=["A", "B"], exclude_names=["B"])
        assert out["neuron_names"] == ["A"]

    def test_exclude_alone_keeps_the_rest(self):
        out = ensemble_filter(make_ensemble(), exclude_index=[1, 3])
        assert out["neuron_names"] == ["B", "D"]

    def test_kept_neurons_are_reindexed_in_order(self):
        out = ensemble_filter(make_ensemble(), include_names=["D", "B"])
        assert out["neuron_names"] == ["B", "D"], "Order follows the ensemble, not the argument."
        assert out["neuron_ids"] == ["id2", "id4"]

    def test_num_neurons_is_updated(self):
        assert ensemble_filter(make_ensemble(), include_index=[1])["info"]["num_neurons"] == 1

    def test_a_structure_without_info_is_tolerated(self):
        E = make_ensemble()
        del E["info"]
        assert ensemble_filter(E, include_index=[1])["neuron_names"] == ["A"]

    def test_the_input_is_not_modified(self):
        E = make_ensemble()
        ensemble_filter(E, include_index=[1])
        assert E["neuron_names"] == ["A", "B", "C", "D"]
        assert E["info"]["num_neurons"] == 4
        assert E["activity"].shape == (4, 3)


class TestIndicesAreOneBased:
    """MATLAB's IncludeIndex is 1-based, and the shared symmetry battery feeds
    both languages the same case list -- so a 0-based Python variant would make
    identical inputs mean different things."""

    def test_index_one_is_the_first_neuron(self):
        assert ensemble_filter(make_ensemble(), include_index=[1])["neuron_names"] == ["A"]

    def test_index_n_is_the_last_neuron(self):
        assert ensemble_filter(make_ensemble(), include_index=[4])["neuron_names"] == ["D"]

    @pytest.mark.parametrize("bad", [[0], [5], [1.5], [-1]])
    def test_out_of_range_or_fractional_indices_raise(self, bad):
        with pytest.raises(ValueError, match="integers between 1 and 4"):
            ensemble_filter(make_ensemble(), include_index=bad)


class TestKeep:
    def test_boolean_mask(self):
        out = ensemble_filter(make_ensemble(), keep=np.array([True, False, True, False]))
        assert out["neuron_names"] == ["A", "C"]

    def test_index_vector(self):
        out = ensemble_filter(make_ensemble(), keep=[2, 4])
        assert out["neuron_names"] == ["B", "D"]

    def test_a_wrong_length_mask_raises(self):
        with pytest.raises(ValueError, match="must have 4 elements"):
            ensemble_filter(make_ensemble(), keep=np.array([True, False]))

    def test_keep_counts_as_an_include_so_excludes_still_apply(self):
        out = ensemble_filter(
            make_ensemble(), keep=np.array([True, True, False, False]), exclude_names=["A"]
        )
        assert out["neuron_names"] == ["B"]


class TestActivityTrimming:
    def test_trailing_all_zero_columns_are_dropped(self):
        """Neuron 3 is the only one reaching column 3, so dropping it narrows
        the matrix from 3 columns to 2."""
        out = ensemble_filter(make_ensemble(), exclude_names=["C"])
        assert out["activity"].shape == (3, 2)
        assert np.array_equal(out["activity"], np.array([[11, 0], [21, 22], [41, 0]]))

    def test_keeping_the_widest_neuron_keeps_the_width(self):
        out = ensemble_filter(make_ensemble(), include_names=["C"])
        assert out["activity"].shape == (1, 3)

    def test_a_silent_selection_keeps_one_column(self):
        """A kept neuron with no spikes leaves an all-zero matrix; MATLAB's
        trim keeps at least one column rather than producing a 1-by-0."""
        E = make_ensemble()
        E["activity"] = np.zeros((4, 3))
        out = ensemble_filter(E, include_index=[1])
        assert out["activity"].shape == (1, 1)

    def test_an_empty_selection_keeps_the_original_width(self):
        """MATLAB's isempty guard returns early on a 0-by-Smax matrix, so a
        filter that keeps nothing does not also collapse the width."""
        out = ensemble_filter(make_ensemble(), include_names=["nobody"])
        assert out["neuron_names"] == []
        assert out["activity"].shape == (0, 3)


def test_scipy_sparse_activity_is_supported():
    """MATLAB stores activity as a sparse matrix, so the port must accept one."""
    sparse = pytest.importorskip("scipy.sparse")
    E = make_ensemble()
    E["activity"] = sparse.csr_matrix(E["activity"])
    out = ensemble_filter(E, include_names=["B", "D"])
    assert out["activity"].shape == (2, 2)
    assert np.array_equal(out["activity"].toarray(), np.array([[21, 22], [41, 0]]))
