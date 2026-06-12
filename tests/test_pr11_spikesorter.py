"""
PR11 tests for ndi.app.spikesorter.

These tests exercise the faithfully-ported, vlt-grounded pieces of
ndi.app.spikesorter. ``spike_sort`` (automatic path) and ``clusters2neurons`` are
now implemented; the end-to-end clustering behaviour is covered in
tests/test_spikesorter_clustering.py. Here we check that they bail out cleanly
when called without a session, and that the graphical path is still directed to
the separate PyQt editor.

The module must import even when vlt is absent (all vlt imports are deferred), so
the import + parameter tests run unconditionally. The math tests
``importorskip("vlt")`` so they SKIP cleanly when vlt is absent and run the real
vlt-backed code when vlt is present.

MATLAB equivalent: src/ndi/+ndi/+app/spikesorter.m
"""

import numpy as np
import pytest

from ndi.app.spikesorter import ndi_app_spikesorter

# ---------------------------------------------------------------------------
# Import + construction + blocker tests (no vlt required).
# ---------------------------------------------------------------------------


def test_construct_and_repr():
    app = ndi_app_spikesorter()
    assert app.name == "ndi_app_spikesorter"
    assert app.doc_types == ["sorting_parameters", "spike_clusters"]
    assert app.doc_document_types == [
        "apps/spikesorter/sorting_parameters",
        "apps/spikesorter/spike_clusters",
    ]
    assert "ndi_app_spikesorter" in repr(app)


def test_spike_sort_requires_session():
    """Without a session, the automatic sorter bails out with a clear error."""
    app = ndi_app_spikesorter()
    with pytest.raises(RuntimeError, match="session"):
        app.spike_sort(None, "default", "default")


def test_clusters2neurons_requires_session():
    app = ndi_app_spikesorter()
    with pytest.raises(RuntimeError, match="session"):
        app.clusters2neurons(None, "default", "default")


def test_check_sorting_parameters_clamps_and_rounds():
    """check_sorting_parameters is a faithful, vlt-free port: round + clamp [1,10]."""
    app = ndi_app_spikesorter()
    # round(3.6) -> 4
    assert app.check_sorting_parameters({"interpolation": 3.6})["interpolation"] == 4
    # clamp above 10
    assert app.check_sorting_parameters({"interpolation": 50})["interpolation"] == 10
    # clamp below 1
    assert app.check_sorting_parameters({"interpolation": 0})["interpolation"] == 1
    assert app.check_sorting_parameters({"interpolation": -3})["interpolation"] == 1


def test_check_sorting_parameters_missing_interpolation_raises():
    app = ndi_app_spikesorter()
    with pytest.raises(ValueError, match="interpolation"):
        app.check_sorting_parameters({})


def test_default_sorting_parameters_field_set():
    """Defaults mirror the field set documented in appdoc_description."""
    params = ndi_app_spikesorter.default_sorting_parameters()
    for field in (
        "graphical_mode",
        "num_pca_features",
        "interpolation",
        "min_clusters",
        "max_clusters",
        "num_start",
    ):
        assert field in params


def test_loadwaveforms_requires_session():
    app = ndi_app_spikesorter()  # no session
    with pytest.raises(RuntimeError, match="session"):
        app.loadwaveforms(object(), "default")


def test_find_appdoc_no_session_returns_empty():
    app = ndi_app_spikesorter()
    assert app.find_appdoc("sorting_parameters", "default") == []


def test_struct2doc_unknown_type_raises():
    app = ndi_app_spikesorter()
    with pytest.raises(ValueError, match="Unknown APPDOC_TYPE"):
        app.struct2doc("not_a_type", {})


def test_struct2doc_spike_clusters_is_internal():
    app = ndi_app_spikesorter()
    with pytest.raises(ValueError, match="internally"):
        app.struct2doc("spike_clusters", {})


def test_struct2doc_sorting_parameters_requires_name():
    app = ndi_app_spikesorter()
    with pytest.raises(ValueError, match="name"):
        app.struct2doc("sorting_parameters", {"interpolation": 3})


# ---------------------------------------------------------------------------
# vlt-backed math tests (skip cleanly when vlt absent).
# ---------------------------------------------------------------------------


def test_isvalid_appdoc_struct_sorting_parameters():
    pytest.importorskip("vlt")
    app = ndi_app_spikesorter()
    good = ndi_app_spikesorter.default_sorting_parameters()
    b, errmsg = app.isvalid_appdoc_struct("sorting_parameters", good)
    assert b is True
    assert errmsg == ""

    bad = {"graphical_mode": 1}  # missing the rest
    b, errmsg = app.isvalid_appdoc_struct("sorting_parameters", bad)
    assert b is False
    assert errmsg  # non-empty error message


def test_isvalid_appdoc_struct_spike_clusters():
    pytest.importorskip("vlt")
    app = ndi_app_spikesorter()
    b, _ = app.isvalid_appdoc_struct("spike_clusters", {"epoch_info": {}, "clusterinfo": []})
    assert b is True
    b, _ = app.isvalid_appdoc_struct("spike_clusters", {"epoch_info": {}})
    assert b is False


def test_prepare_waveforms_for_sorting_with_oversampling():
    """The available oversample/center/PCA scaffolding runs and has correct shapes.

    NumSamples x NumChannels x NumSpikes input, interpolation=3, 4 PCA features.
    Oversampling multiplies the sample axis by the interpolation factor; PCA
    returns an (N_features x NumSpikes) matrix.
    """
    pytest.importorskip("vlt")
    n_samples, n_channels, n_spikes = 32, 2, 12
    rng = np.random.default_rng(0)
    waves = rng.standard_normal((n_samples, n_channels, n_spikes))
    # Put a clear negative peak at the center sample of each spike.
    waves[15, :, :] = -8.0

    waveparams = {"S0": -15, "S1": 16}
    sort = {"interpolation": 3, "num_pca_features": 4}

    prepared, wavesamples, features = ndi_app_spikesorter._prepare_waveforms_for_sorting(
        waves, waveparams, sort, threshold_sign=-1
    )

    # Oversampled sample axis = n_samples * interpolation; chans/spikes unchanged.
    assert prepared.shape == (n_samples * 3, n_channels, n_spikes)
    assert wavesamples.shape == (n_samples * 3,)
    # spikewaves2pca returns N_features x NumSpikes.
    assert features.shape == (4, n_spikes)
    assert np.all(np.isfinite(features))


def test_prepare_waveforms_for_sorting_without_oversampling():
    """interpolation == 1 leaves the waveform geometry unchanged."""
    pytest.importorskip("vlt")
    n_samples, n_channels, n_spikes = 30, 1, 8
    rng = np.random.default_rng(1)
    waves = rng.standard_normal((n_samples, n_channels, n_spikes))

    waveparams = {"S0": -10, "S1": 19}
    sort = {"interpolation": 1, "num_pca_features": 3}

    prepared, wavesamples, features = ndi_app_spikesorter._prepare_waveforms_for_sorting(
        waves, waveparams, sort, threshold_sign=-1
    )
    assert prepared.shape == (n_samples, n_channels, n_spikes)
    assert wavesamples.shape == (n_samples,)
    assert features.shape == (3, n_spikes)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
