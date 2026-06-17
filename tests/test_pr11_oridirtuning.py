"""PR11: ndi.app.oridirtuning -- vector-based orientation/direction indices.

Ports the science core of ``ndi.app.oridirtuning`` (MATLAB
src/ndi/+ndi/+app/oridirtuning.m):

- the tuning curve (mean + standard error of blank-subtracted response per
  direction), assembled in ``calculate_oridir_indexes``;
- the VECTOR-based orientation/direction selectivity indices
  (``_oridir_vectorindexes``, mirroring
  ``vlt.neuro.vision.oridir.index.oridir_vectorindexes``);
- the across-stimulus / visual-response ANOVA significance
  (``_neural_response_significance``).

The math is grounded (numpy/scipy only) and is tested against hand-computed
expected OSI/DSI on cosine tuning curves. Per the audit convention this test
skips cleanly when vlt is absent (the standard CI/sandbox env); when vlt IS
present it additionally cross-checks the grounded helpers against vlt's own
``compute_*`` functions to prove numerical equivalence.

Now exercised (previously blockers):
- ``_oridir_fitindexes`` (double-gaussian fit) -- delegates to vlt's
  ``otfit_carandini`` + ``fit2fit*`` helpers (present in the Python vlt
  surface; the leaf functions are imported directly to dodge a vlt package
  ``__init__`` name-shadowing bug).
- ``calculate_tuning_curve`` / ``calculate_all_tuning_curves`` -- delegate to
  the now-ported ``ndi.app.stimulus.tuning_response.tuning_curve``.

Still a documented stub:
- ``plot_oridir_response`` -- matplotlib plotting is intentionally left to the
  viewer; it raises NotImplementedError pointing callers at the document's
  tuning_curve / fit fields.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

pytest.importorskip("vlt")  # skip cleanly when vlt is absent (sandbox/CI)

from ndi.app.oridirtuning import (  # noqa: E402
    _compute_circularvariance,
    _compute_directionindex,
    _compute_orientationindex,
    _compute_tuningwidth,
    _hotellingt2_onesample_p,
    _neural_response_significance,
    _oridir_fitindexes,
    _oridir_vectorindexes,
    ndi_app_oridirtuning,
)
from ndi.document import ndi_document  # noqa: E402

ANGLES = np.arange(0.0, 360.0, 45.0)  # 0..315, eight directions


def _curve(mean):
    mean = np.asarray(mean, dtype=float)
    return np.vstack([ANGLES, mean, np.zeros_like(mean), np.zeros_like(mean)])


def _reps(mean, reps=6):
    """Noiseless per-direction individual responses."""
    return [np.full(reps, mean[i], dtype=float) for i in range(len(mean))]


# ---------------------------------------------------------------------------
# Vector indices on hand-built cosine tuning curves with known OSI/DSI
# ---------------------------------------------------------------------------
class TestVectorIndexes:
    def test_orientation_only_cosine(self):
        # r = 1 + cos(2*theta): peaks equally at 0 and 180 -> pure orientation,
        # no direction preference.
        mean = 1.0 + np.cos(np.deg2rad(2 * ANGLES))
        vi = _oridir_vectorindexes(_curve(mean), _reps(mean))

        # Orientation preference at 0 deg.
        assert vi["ot_pref"] == pytest.approx(0.0, abs=1e-6)
        # OSI = (m0+m180 - m90-m270)/(m0+m180) = (2+2 - 0-0)/4 = 1.0
        assert vi["ot_index"] == pytest.approx(1.0, abs=1e-9)
        # Direction-symmetric -> no net direction vector -> DSI 0, dir CV 1.
        assert vi["dir_index"] == pytest.approx(0.0, abs=1e-9)
        assert vi["dir_circularvariance"] == pytest.approx(1.0, abs=1e-9)

    def test_direction_selective_cosine(self):
        # r = 1 + cos(theta-90): peak 2 at 90, min 0 at 270.
        mean = np.clip(1.0 + np.cos(np.deg2rad(ANGLES - 90.0)), 0.0, None)
        vi = _oridir_vectorindexes(_curve(mean), _reps(mean))

        assert vi["dir_pref"] == pytest.approx(90.0, abs=1e-6)
        # DSI = (m90 - m270)/m90 = (2-0)/(2+1e-4) ~ 1.0 (rounded to 2 dp -> 1.0)
        assert vi["dir_index"] == pytest.approx(1.0, abs=1e-9)
        # m90+m270 == m0+m180 == 2 -> OSI 0.
        assert vi["ot_index"] == pytest.approx(0.0, abs=1e-9)

    def test_hotelling_significance_present_with_noise(self):
        rng = np.random.default_rng(0)
        mean = np.clip(1.0 + np.cos(np.deg2rad(ANGLES - 90.0)), 0.0, None)
        ind = [mean[i] + 0.05 * rng.standard_normal(8) for i in range(len(mean))]
        vi = _oridir_vectorindexes(_curve(mean), ind)
        # Strongly direction-tuned, low noise -> direction vector clearly != 0.
        assert 0.0 <= vi["dir_HotellingT2_p"] < 0.01
        assert not np.isnan(vi["dir_dotproduct_sig_p"])

    def test_hotelling_onesample_endpoints(self):
        rng = np.random.default_rng(1)
        far = np.column_stack(
            [5.0 + 0.1 * rng.standard_normal(12), 5.0 + 0.1 * rng.standard_normal(12)]
        )
        near = 0.1 * rng.standard_normal((12, 2))
        # Cluster far from origin -> tiny p; cluster at origin -> not tiny.
        assert _hotellingt2_onesample_p(far) < 1e-6
        assert _hotellingt2_onesample_p(near) > 0.001
        # Degenerate (n <= p) -> NaN.
        assert np.isnan(_hotellingt2_onesample_p(np.zeros((2, 2))))


# ---------------------------------------------------------------------------
# Cross-validation against vlt's own compute_* (proves the port is faithful)
# ---------------------------------------------------------------------------
class TestAgainstVlt:
    def test_compute_helpers_match_vlt(self):
        idx = pytest.importorskip("vlt.neuro.vision.oridir.index")

        mean = np.clip(1.0 + np.cos(np.deg2rad(ANGLES - 90.0)), 0.0, None)

        assert _compute_circularvariance(ANGLES, mean, 2) == pytest.approx(
            idx.compute_circularvariance(ANGLES, mean)
        )
        assert _compute_circularvariance(ANGLES, mean, 1) == pytest.approx(
            idx.compute_dircircularvariance(ANGLES, mean)
        )
        assert _compute_orientationindex(ANGLES, mean) == pytest.approx(
            idx.compute_orientationindex(ANGLES, mean)
        )
        assert _compute_directionindex(ANGLES, mean) == pytest.approx(
            idx.compute_directionindex(ANGLES, mean)
        )
        assert _compute_tuningwidth(ANGLES, mean) == pytest.approx(
            idx.compute_tuningwidth(ANGLES, mean)
        )

        mean_ori = 1.0 + np.cos(np.deg2rad(2 * ANGLES))
        assert _compute_orientationindex(ANGLES, mean_ori) == pytest.approx(
            idx.compute_orientationindex(ANGLES, mean_ori)
        )
        assert _compute_circularvariance(ANGLES, mean_ori, 2) == pytest.approx(
            idx.compute_circularvariance(ANGLES, mean_ori)
        )


# ---------------------------------------------------------------------------
# ANOVA significance (neural_response_significance)
# ---------------------------------------------------------------------------
class TestSignificance:
    def test_significant_variation(self):
        rng = np.random.default_rng(2)
        # Five conditions with clearly different means, low within-group noise.
        groups = [m + 0.01 * rng.standard_normal(8) for m in (0.0, 1.0, 2.0, 3.0, 4.0)]
        sigp, sigpb = _neural_response_significance(groups)
        assert sigp < 1e-6
        # No blank supplied -> sigpb identical to sigp.
        assert sigpb == sigp

    def test_no_variation_not_significant(self):
        rng = np.random.default_rng(3)
        groups = [1.0 + 0.5 * rng.standard_normal(20) for _ in range(5)]
        sigp, _ = _neural_response_significance(groups)
        assert sigp > 0.05

    def test_blank_group_changes_sigpb(self):
        rng = np.random.default_rng(4)
        groups = [1.0 + 0.01 * rng.standard_normal(8) for _ in range(4)]  # all equal
        blank = 10.0 + 0.01 * rng.standard_normal(8)  # very different blank
        sigp, sigpb = _neural_response_significance(groups, blank)
        assert sigp > 0.05  # stimuli alone: no variation
        assert sigpb < 1e-6  # adding the distinct blank: significant


# ---------------------------------------------------------------------------
# Full calculate_oridir_indexes on a synthetic stimulus_tuningcurve document
# ---------------------------------------------------------------------------
class TestCalculateOridirIndexes:
    @staticmethod
    def _tuning_doc(mean, reps=6, blank=0.0):
        td = ndi_document("stimulus/stimulus_tuningcurve")
        stc = td.document_properties["stimulus_tuningcurve"]
        n = len(mean)
        stc["independent_variable_value"] = list(ANGLES)
        stc["individual_responses_real"] = [[float(mean[i])] * reps for i in range(n)]
        stc["individual_responses_imaginary"] = [[0.0] * reps for _ in range(n)]
        stc["control_individual_responses_real"] = [[float(blank)] * reps for _ in range(n)]
        stc["control_individual_responses_imaginary"] = [[0.0] * reps for _ in range(n)]
        stc["response_units"] = "spikes/s"
        return td

    def test_end_to_end_direction_curve(self):
        mean = np.clip(1.0 + np.cos(np.deg2rad(ANGLES - 90.0)), 0.0, None)
        td = self._tuning_doc(mean)
        app = ndi_app_oridirtuning()  # no session

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # fit falls back to sentinels if vlt absent
            odt = app.calculate_oridir_indexes(td, do_add=False)

        props = odt.document_properties["orientation_direction_tuning"]

        # class + dependency wiring
        assert odt.document_properties["document_class"]["class_name"] == (
            "orientation_direction_tuning"
        )
        assert odt.dependency_value("stimulus_tuningcurve_id", error_if_not_found=False) == td.id

        # reconstructed tuning curve: blank (0) subtracted -> mean == input mean.
        np.testing.assert_allclose(props["tuning_curve"]["mean"], mean, atol=1e-9)
        # noiseless -> zero standard error everywhere.
        np.testing.assert_allclose(props["tuning_curve"]["stderr"], 0.0, atol=1e-12)
        assert props["tuning_curve"]["direction"] == list(ANGLES)

        # vector indices land in the doc.
        assert props["vector"]["direction_preference"] == pytest.approx(90.0, abs=1e-6)
        assert props["properties"]["response_units"] == "spikes/s"

        # fit sub-structure is now populated by the vlt-backed double-gaussian
        # fit (vlt is present -- the module is importorskip-gated on it).
        assert not np.isnan(props["fit"]["hwhh"])
        assert props["fit"]["hwhh"] > 0
        assert len(props["fit"]["double_gaussian_parameters"]) == 5
        assert len(props["fit"]["double_gaussian_fit_angles"]) == 360
        assert len(props["fit"]["double_gaussian_fit_values"]) == 360
        # direction-selective cosine peaks at 90 deg -> fit direction preference near 90.
        assert abs(((props["fit"]["direction_angle_preference"] - 90 + 180) % 360) - 180) < 12
        assert 0.0 <= props["fit"]["direction_preferred_null_ratio_rectified"] <= 1.0

    def test_fit_indexes_returns_fit(self):
        # vlt is present (module-gated): the double-gaussian fit computes.
        mean = np.clip(1.0 + np.cos(np.deg2rad(ANGLES - 90.0)), 0.0, None)
        fi = _oridir_fitindexes(_curve(mean), _reps(mean))
        assert len(fi["fit_parameters"]) == 5
        assert len(fi["fit"][0]) == 360 and len(fi["fit"][1]) == 360
        assert 0.0 <= fi["ot_index_rectified"] <= 1.0
        assert 0.0 <= fi["dir_index_rectified"] <= 1.0
        assert fi["tuning_width"] > 0
        # direction-selective curve -> direction preference near the 90 deg peak.
        assert abs(((fi["dirpref"] - 90 + 180) % 360) - 180) < 12

    def test_calculate_tuning_curve_without_session_returns_none(self):
        # No session -> returns None (no longer raises NotImplementedError).
        app = ndi_app_oridirtuning()
        assert app.calculate_tuning_curve(object(), ndi_document("base"), do_add=False) is None

    def test_plot_is_blocker(self):
        app = ndi_app_oridirtuning()
        with pytest.raises(NotImplementedError, match="matplotlib"):
            app.plot_oridir_response(ndi_document("base"))


# ---------------------------------------------------------------------------
# is_oridir_stimulus_response structural fallback (no database)
# ---------------------------------------------------------------------------
class TestIsOridir:
    def test_structural_fallback_true(self):
        app = ndi_app_oridirtuning()
        doc = ndi_document("stimulus/stimulus_tuningcurve")
        doc.document_properties["stimulus_tuningcurve"]["independent_variable_label"] = "angle"
        assert app.is_oridir_stimulus_response(doc) is True

    def test_structural_fallback_false(self):
        app = ndi_app_oridirtuning()
        doc = ndi_document("stimulus/stimulus_tuningcurve")
        doc.document_properties["stimulus_tuningcurve"]["independent_variable_label"] = "sFrequency"
        assert app.is_oridir_stimulus_response(doc) is False

    def test_structwhatvaries(self):
        app = ndi_app_oridirtuning()
        varies = app._structwhatvaries(
            [{"angle": 0, "sf": 1}, {"angle": 90, "sf": 1}, {"angle": 180, "sf": 1}]
        )
        assert varies == ["angle"]
