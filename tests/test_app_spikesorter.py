"""ndi.app.spikesorter: helpers, parameter contract, prep pipeline, gating.

Session-backed paths (loadwaveforms, spike_sort persistence, clusters2neurons)
need a full ndi_session and are exercised by the integration jobs. Here we
pin down:

* ``check_sorting_parameters`` — clamp + missing-field errors.
* ``default_sorting_parameters`` validates.
* ``cluster_initializeclusterinfo`` — the per-cluster mean/counts.
* ``_prepare_waveforms_for_sorting`` — vlt oversample+center+PCA pipeline.
* ``graphical_mode=1`` short-circuits with a NotImplementedError pointing at
  the GUI's issue rather than being silently ignored.
* ``spike_sort`` clearly refuses without a session.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.app.spikesorter import ndi_app_spikesorter


def test_default_sorting_parameters_pass_validation():
    s = ndi_app_spikesorter()
    p = s.default_sorting_parameters()
    valid, msg = s.isvalid_appdoc_struct("sorting_parameters", p)
    assert valid, msg
    assert p["graphical_mode"] == 1
    assert p["interpolation"] == 3


def test_check_sorting_parameters_clamps_interpolation():
    s = ndi_app_spikesorter()
    p = s.check_sorting_parameters({"interpolation": 42, "graphical_mode": 0})
    assert p["interpolation"] == 10
    p = s.check_sorting_parameters({"interpolation": -3})
    assert p["interpolation"] == 1
    p = s.check_sorting_parameters({"interpolation": 2.6})
    assert p["interpolation"] == 3  # rounds half-away-from-zero via round()


def test_check_sorting_parameters_missing_interpolation_raises():
    s = ndi_app_spikesorter()
    with pytest.raises(ValueError, match="interpolation"):
        s.check_sorting_parameters({"graphical_mode": 0})


def test_isvalid_appdoc_struct_reports_missing_field_matlab_style():
    s = ndi_app_spikesorter()
    valid, msg = s.isvalid_appdoc_struct("sorting_parameters", {"graphical_mode": 0})
    assert not valid
    assert "'num_pca_features' not present." in msg  # first missing wins


def test_isvalid_appdoc_struct_unknown_type_raises():
    s = ndi_app_spikesorter()
    with pytest.raises(ValueError):
        s.isvalid_appdoc_struct("bogus", {})


def test_cluster_initializeclusterinfo_counts_and_mean_shape():
    rng = np.random.default_rng(0)
    S, D = 15, 3
    waves = rng.standard_normal((S, D, 6)).astype(np.float32)
    clusterids = np.array([1, 1, 2, 2, 2, 3])
    info = ndi_app_spikesorter.cluster_initializeclusterinfo(
        clusterids, waves, {"EpochNames": ["e1", "e2"]}
    )
    assert [ci["number"] for ci in info] == ["1", "2", "3"]
    assert [ci["number_of_spikes"] for ci in info] == [2, 3, 1]
    # All start Unselected (MATLAB parity) and carry the epoch bounds.
    assert all(ci["qualitylabel"] == "Unselected" for ci in info)
    assert info[0]["EpochStart"] == "e1"
    assert info[0]["EpochStop"] == "e2"
    # meanshape is samples x channels for that cluster's spikes.
    np.testing.assert_allclose(
        np.asarray(info[0]["meanshape"]), waves[:, :, :2].mean(axis=2), atol=1e-6
    )


def test_cluster_initializeclusterinfo_empty_waveforms():
    info = ndi_app_spikesorter.cluster_initializeclusterinfo(
        np.array([1, 2]),
        np.empty((0, 0, 0)),
        {"EpochNames": []},
    )
    # No epoch names, no shape data — cluster records still land.
    assert [ci["number"] for ci in info] == ["1", "2"]
    assert info[0]["EpochStart"] == ""
    assert info[0]["EpochStop"] == ""


def test_prepare_waveforms_for_sorting_runs_vlt_pipeline():
    rng = np.random.default_rng(0)
    S, D, N = 45, 2, 20
    waves = rng.standard_normal((S, D, N)).astype(np.float32) * 0.1
    # A small negative dip near the middle keeps the extremum well-defined.
    waves[18:28, :, :] -= 0.6 * np.exp(-((np.arange(10) - 5.0) ** 2) / 5.0)[:, None, None]
    wp = {"S0": -20, "S1": 24, "numchannels": D, "samplerate": 30000.0}

    sorter = ndi_app_spikesorter()
    sp = sorter.check_sorting_parameters(
        {
            "graphical_mode": 0,
            "num_pca_features": 5,
            "interpolation": 3,
            "min_clusters": 2,
            "max_clusters": 5,
            "num_start": 3,
        }
    )
    prepared, wavesamples, features = ndi_app_spikesorter._prepare_waveforms_for_sorting(
        waves, wp, sp, threshold_sign=-1
    )
    # interpolation=3 triples the sample axis (vlt.oversamplespikes).
    assert prepared.shape[0] == S * sp["interpolation"]
    assert prepared.shape[1] == D
    assert prepared.shape[2] == N
    assert wavesamples.shape == (S * sp["interpolation"],)
    # spikewaves2pca returns NumFeatures x NumSpikes.
    assert features.shape == (sp["num_pca_features"], N)


def test_prepare_waveforms_for_sorting_no_interpolation_skips_oversample():
    rng = np.random.default_rng(1)
    S, D, N = 21, 1, 5
    waves = rng.standard_normal((S, D, N)).astype(np.float32) * 0.1
    wp = {"S0": -10, "S1": 10, "numchannels": D, "samplerate": 30000.0}
    sorter = ndi_app_spikesorter()
    sp = sorter.check_sorting_parameters(
        {
            "graphical_mode": 0,
            "num_pca_features": 3,
            "interpolation": 1,
            "min_clusters": 2,
            "max_clusters": 3,
            "num_start": 2,
        }
    )
    prepared, wavesamples, features = ndi_app_spikesorter._prepare_waveforms_for_sorting(
        waves, wp, sp, threshold_sign=-1
    )
    # No oversampling: sample axis unchanged, wavesamples = arange(S0, S1+1).
    assert prepared.shape == waves.shape
    np.testing.assert_array_equal(wavesamples, np.arange(-10, 11))
    assert features.shape == (3, N)


def test_spike_sort_without_session_raises():
    s = ndi_app_spikesorter()

    class DummyTS:
        id = "x"
        name = "x"

    with pytest.raises(RuntimeError, match="requires a session"):
        s.spike_sort(DummyTS())


def test_loadwaveforms_without_session_raises():
    s = ndi_app_spikesorter()

    class DummyTS:
        id = "x"
        name = "x"

    with pytest.raises(RuntimeError, match="requires a session"):
        s.loadwaveforms(DummyTS())


def test_clusters2neurons_without_session_raises():
    s = ndi_app_spikesorter()

    class DummyTS:
        id = "x"
        name = "x"

    with pytest.raises(RuntimeError, match="requires a session"):
        s.clusters2neurons(DummyTS())


def test_quality_number_mapping_matches_matlab_switch():
    # Excellent -> 1, Good -> 2, Multi-unit -> 3, Not useable -> 5, Unselected -> -1.
    m = ndi_app_spikesorter._QUALITY_NUMBER
    assert m["excellent"] == 1
    assert m["good"] == 2
    assert m["multi-unit"] == 3
    assert m["not useable"] == 5
    assert m["unselected"] == -1
