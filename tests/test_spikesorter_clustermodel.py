"""
Headless tests for ndi.app.spikesorter_clustermodel.ClusterModel.

The model is the pure-numpy curation core behind the spike-sorter GUI (a port of
the data operations in vlt.neuro.spikesorting.cluster_spikewaves_gui). These
tests need no Qt/display -- they pin the merge/split/relabel/reorder/feature/
finalize semantics so the GUI (and clusters2neurons downstream) can rely on
them. The KlustaKwik clustering path is exercised separately, skip-gated on the
optional klustakwik2 dependency.

MATLAB equivalent: the command dispatch in cluster_spikewaves_gui.m.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.app.spikesorter_clustermodel import (
    QUALITY_LABELS,
    ClusterModel,
    points_in_polygon,
    spikewaves2Npointfeature,
    spikewaves2pca,
)


def test_points_in_polygon_square():
    poly = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]])
    pts = np.array([[1.0, 1.0], [-1.0, 1.0], [3.0, 1.0], [1.0, 3.0]])
    mask = points_in_polygon(pts, poly)
    assert list(mask) == [True, False, False, False]


def test_points_in_polygon_degenerate():
    # fewer than 3 vertices, or no points -> all False / empty, no error.
    assert list(points_in_polygon(np.array([[0.0, 0.0]]), np.array([[0.0, 0.0]]))) == [False]
    assert points_in_polygon(np.empty((0, 2)), np.zeros((4, 2))).shape == (0,)


# ---------------------------------------------------------------------------
# fixtures: simple, separable synthetic waveforms
# ---------------------------------------------------------------------------

S0, S1 = -10, 10  # 21 samples
NCHAN = 2


def _archetype(label: int) -> np.ndarray:
    s = np.arange(S0, S1 + 1)
    bump = np.exp(-(s**2) / 8.0)
    return {
        1: np.stack([-8.0 * bump, -1.0 * bump], axis=1),
        2: np.stack([-1.0 * bump, -8.0 * bump], axis=1),
        3: np.stack([-8.0 * bump, 8.0 * bump], axis=1),
    }[label]


def _waves_for_labels(labels, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(labels)
    w = np.zeros((S1 - S0 + 1, NCHAN, n))
    for i, lab in enumerate(labels):
        w[:, :, i] = _archetype(lab) + 0.1 * rng.standard_normal((S1 - S0 + 1, NCHAN))
    return w


# ---------------------------------------------------------------------------
# feature functions
# ---------------------------------------------------------------------------


def test_npoint_feature_shape_and_values():
    # 3 samples x 2 channels x 2 spikes; sample at 1-based indices [1, 3].
    waves = np.arange(3 * 2 * 2, dtype=float).reshape(3, 2, 2)
    feats = spikewaves2Npointfeature(waves, [1, 3])
    # (len(samplelist)*nchan) x nspikes = 4 x 2; column-major (sample-fastest).
    assert feats.shape == (4, 2)
    # spike 0: ch0 samples (s1,s3)=waves[0,0,0],waves[2,0,0]; ch1 (s1,s3).
    np.testing.assert_array_equal(
        feats[:, 0], [waves[0, 0, 0], waves[2, 0, 0], waves[0, 1, 0], waves[2, 1, 0]]
    )


def test_pca_feature_orientation():
    waves = _waves_for_labels([1, 2, 3] * 5)
    f = spikewaves2pca(waves, 3)
    assert f.shape == (3, 15)  # n_features x n_spikes
    # PCA scores are mean-centred.
    np.testing.assert_allclose(f.mean(axis=1), np.zeros(3), atol=1e-9)


def test_compute_features_stores_nspikes_by_nfeatures():
    waves = _waves_for_labels([1, 2, 3] * 4)
    m = ClusterModel(waves)
    f = m.compute_features("pca3")
    assert f.shape == (12, 3)  # n_spikes x n_features
    f2 = m.compute_features("2points")
    assert f2.shape == (12, len(m.npoint_samplelist) * NCHAN)


# ---------------------------------------------------------------------------
# construction + defaults
# ---------------------------------------------------------------------------


def test_default_all_unclassified_makes_single_nan_info():
    waves = _waves_for_labels([1, 2, 3])
    m = ClusterModel(waves)
    assert np.isnan(m.clusterids).all()
    assert len(m.clusterinfo) == 1
    assert m.clusterinfo[0]["number"] == "NaN"
    assert m.clusterinfo[0]["qualitylabel"] == "Unselected"


def test_feature_param_defaults_and_clamp():
    waves = _waves_for_labels([1])  # 21 samples
    m = ClusterModel(waves)
    # pca_range default round([8 22]/24*21) = [7, 19], within [1,21].
    assert m.pca_range == [7, 19]
    assert all(1 <= x <= 21 for x in m.npoint_samplelist)


def test_clusterids_padded_with_nan():
    waves = _waves_for_labels([1, 2, 3, 1])
    m = ClusterModel(waves, clusterids=np.array([1, 2]))
    assert m.clusterids.shape == (4,)
    assert np.isnan(m.clusterids[2]) and np.isnan(m.clusterids[3])


# ---------------------------------------------------------------------------
# init_cluster_info / reorder / make_1_to_n
# ---------------------------------------------------------------------------


def test_init_cluster_info_rebuild_meanshapes():
    waves = np.zeros((3, 2, 4))
    waves[:, :, 0] = 1.0
    waves[:, :, 1] = 3.0  # cluster 1 mean 2.0
    waves[:, :, 2] = 10.0
    waves[:, :, 3] = 20.0  # cluster 2 mean 15.0
    m = ClusterModel(waves, clusterids=np.array([1, 1, 2, 2]))
    m.init_cluster_info(rebuild=True)
    assert [c["number"] for c in m.clusterinfo] == ["1", "2"]
    np.testing.assert_allclose(np.asarray(m.clusterinfo[0]["meanshape"]), np.full((3, 2), 2.0))
    np.testing.assert_allclose(np.asarray(m.clusterinfo[1]["meanshape"]), np.full((3, 2), 15.0))


def test_reorder_min_to_max():
    # cluster 1 is the shallow one, cluster 2 the deep one -> after reorder the
    # deeper (more negative) cluster becomes cluster 1.
    waves = np.zeros((3, 1, 4))
    waves[:, :, 0] = -1.0
    waves[:, :, 1] = -1.0  # cluster 1 min = -1
    waves[:, :, 2] = -9.0
    waves[:, :, 3] = -9.0  # cluster 2 min = -9
    m = ClusterModel(waves, clusterids=np.array([1, 1, 2, 2]))
    m.reorder_min_to_max()
    # spikes 2,3 (the deepest) become cluster 1.
    assert list(m.clusterids) == [2, 2, 1, 1]


def test_make_clusters_1_to_n_contiguous():
    waves = _waves_for_labels([1, 1, 1, 1])
    m = ClusterModel(waves, clusterids=np.array([2, 5, 2, 9]))
    m.init_cluster_info(rebuild=True)
    m.make_clusters_1_to_n()
    assert sorted(set(m.clusterids)) == [1.0, 2.0, 3.0]
    assert [c["number"] for c in m.clusterinfo] == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# merge / split / move / quality / epochs
# ---------------------------------------------------------------------------


def _three_cluster_model():
    labels = [1, 2, 3] * 6
    waves = _waves_for_labels(labels)
    m = ClusterModel(waves, clusterids=np.array(labels, dtype=float))
    m.init_cluster_info(rebuild=True)
    m.make_clusters_1_to_n()
    return m, labels


def test_merge_absorbs_higher_into_lower():
    m, labels = _three_cluster_model()
    n1 = (np.asarray(labels) == 1).sum()
    n2 = (np.asarray(labels) == 2).sum()
    m.merge(1, 2)  # cluster 2 -> cluster 1
    assert len(m.clusterinfo) == 2
    # the merged cluster holds n1+n2 spikes; clusters renumbered 1..2.
    counts = {c["number"]: c["number_of_spikes"] for c in m.clusterinfo}
    assert counts["1"] == n1 + n2
    assert sorted(set(m.clusterids)) == [1.0, 2.0]


def test_merge_preserves_survivor_label():
    m, _ = _three_cluster_model()
    m.set_quality(1, "Good")
    m.set_quality(2, "Excellent")
    m.merge(1, 2)
    # survivor (lower number, cluster 1) keeps its label.
    assert m.clusterinfo[0]["qualitylabel"] == "Good"


def test_split_creates_new_cluster():
    m, labels = _three_cluster_model()
    # split off the spikes currently in cluster 1.
    parent_idx = np.flatnonzero(m.clusterids == 1)
    take = parent_idx[: parent_idx.size // 2]
    m.split_cluster(1, take)
    # one more cluster now; the new cluster has len(take) spikes, Unselected.
    assert len(m.clusterinfo) == 4
    assert sorted(set(m.clusterids)) == [1.0, 2.0, 3.0, 4.0]
    new = m.clusterinfo[-1]
    assert new["qualitylabel"] == "Unselected"
    assert new["number_of_spikes"] == take.size


def test_split_all_of_parent_drops_parent_entry():
    m, _ = _three_cluster_model()
    parent_idx = np.flatnonzero(m.clusterids == 2)
    m.split_cluster(2, parent_idx)  # move ALL of cluster 2 out
    # still 3 clusters (parent emptied -> dropped, new one added), renumbered.
    assert len(m.clusterinfo) == 3
    assert sorted(set(m.clusterids)) == [1.0, 2.0, 3.0]


def test_move_to_front():
    m, _ = _three_cluster_model()
    m.set_quality(3, "Excellent")
    m.move_to_front(3)
    # cluster previously numbered 3 is now cluster 1 and keeps its label.
    assert m.clusterinfo[0]["number"] == "1"
    assert m.clusterinfo[0]["qualitylabel"] == "Excellent"


def test_set_quality_validates_label():
    m, _ = _three_cluster_model()
    for lab in QUALITY_LABELS:
        m.set_quality(1, lab)
        assert m.clusterinfo[0]["qualitylabel"] == lab
    with pytest.raises(ValueError):
        m.set_quality(1, "Bogus")


def test_set_epochs_validates_membership():
    labels = [1, 2, 3, 1, 2, 3]
    waves = _waves_for_labels(labels)
    m = ClusterModel(
        waves,
        clusterids=np.array(labels, dtype=float),
        epoch_start_samples=[1, 4],
        epoch_names=["epA", "epB"],
    )
    m.init_cluster_info(rebuild=True)
    m.make_clusters_1_to_n()
    m.set_epochs(1, "epA", "epA")
    loc = m._info_index_for_number(1)
    assert m.clusterinfo[loc]["EpochStart"] == "epA"
    assert m.clusterinfo[loc]["EpochStop"] == "epA"
    with pytest.raises(ValueError):
        m.set_epochs(1, "epA", "nope")


# ---------------------------------------------------------------------------
# epoch visibility + finalize (DoneBt)
# ---------------------------------------------------------------------------


def test_finalize_marks_not_present_spikes_nan():
    # 2 epochs of 3 spikes each; cluster 1 spans only epoch A.
    labels = [1, 1, 1, 1, 1, 1]
    waves = _waves_for_labels(labels)
    m = ClusterModel(
        waves,
        clusterids=np.array(labels, dtype=float),
        epoch_start_samples=[1, 4],
        epoch_names=["epA", "epB"],
    )
    m.init_cluster_info(rebuild=True)
    m.make_clusters_1_to_n()
    m.set_epochs(1, "epA", "epA")  # present only in epoch A (spikes 0,1,2)
    m.finalize()
    # spikes in epoch B (indices 3,4,5) become NaN; cluster 1 keeps 3 spikes.
    assert np.isnan(m.clusterids[3:]).all()
    assert not np.isnan(m.clusterids[:3]).any()
    loc = m._info_index_for_number(1)
    assert m.clusterinfo[loc]["number_of_spikes"] == 3
    # a NaN clusterinfo entry now exists for the not-present spikes.
    assert m._info_index_for_number("NaN") is not None


def test_export_uint16_maps_nan_to_zero():
    waves = _waves_for_labels([1, 2, 3])
    m = ClusterModel(waves, clusterids=np.array([1.0, np.nan, 2.0]))
    out = m.clusterids_for_export()
    assert out.dtype == np.dtype("<u2")
    assert list(out) == [1, 0, 2]


def test_all_quality_assigned_gate():
    m, _ = _three_cluster_model()
    assert not m.all_quality_assigned()  # all Unselected
    for n in (1, 2, 3):
        m.set_quality(n, "Good")
    assert m.all_quality_assigned()


# ---------------------------------------------------------------------------
# clustering algorithms (optional backends)
# ---------------------------------------------------------------------------


def test_cluster_all_klustakwik_wiring():
    # cluster_all is responsible for the *tidy-up* around the clustering call:
    # features -> klustakwik -> reorder_min_to_max -> rebuild info -> 1..N. We
    # assert those post-conditions (contiguous 1-based ids, aligned + Unselected
    # info), NOT the separation quality, which is stochastic for KlustaKwik's
    # penalty-free CEM on small waveform-PCA sets and is covered against clean
    # Gaussian blobs in tests/test_spikesorter_clustering.py.
    pytest.importorskip("klustakwik2")
    labels = [1, 2, 3] * 8
    waves = _waves_for_labels(labels, seed=1)
    m = ClusterModel(waves)
    m.compute_features("pca3")
    m.cluster_all("KlustaKwik", (3, 8), seed=1)
    k = len(set(m.clusterids))
    assert 1 <= k <= 8
    assert sorted(set(m.clusterids)) == [float(i) for i in range(1, k + 1)]  # contiguous 1..K
    assert [c["number"] for c in m.clusterinfo] == [str(i) for i in range(1, k + 1)]
    assert all(c["qualitylabel"] == "Unselected" for c in m.clusterinfo)
    assert sum(c["number_of_spikes"] for c in m.clusterinfo) == len(labels)


def test_cluster_all_kmeans_separates():
    pytest.importorskip("sklearn")
    labels = [1, 2, 3] * 8
    waves = _waves_for_labels(labels, seed=2)
    m = ClusterModel(waves)
    m.compute_features("pca3")
    m.cluster_all("KMeans", 3, seed=0)
    assert sorted(set(m.clusterids)) == [1.0, 2.0, 3.0]
    true = np.asarray(labels)
    purity = sum(np.bincount(true[m.clusterids == u]).max() for u in np.unique(m.clusterids))
    assert purity / true.size > 0.95


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
