"""
ndi.app.oridirtuning - Orientation/direction tuning analysis.

Computes orientation and direction selectivity indices from
stimulus tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/oridirtuning.m

Implementation notes (PR11 port):
    - The VECTOR-based orientation/direction indices (mirroring
      ``vlt.neuro.vision.oridir.index.oridir_vectorindexes``) are
      implemented as grounded private module-level helpers below. The
      vlt Python port of ``oridir_vectorindexes`` exists but has an
      import-shadowing bug for ``vlt.stats.hotellingt2test`` and depends
      on ``vlt.stats`` which is not part of the audited Python vlt
      surface, so we reimplement the (well-defined, textbook) math from
      first principles. See ``_oridir_vectorindexes`` for formula
      citations. MEDIUM confidence; flagged for review.
    - The response significance ANOVA (mirroring
      ``neural_response_significance``) is implemented via
      ``scipy.stats.f_oneway``. MEDIUM confidence; flagged for review.
    - The FIT-based indices (double-gaussian fit, mirroring
      ``vlt.neuro.vision.oridir.index.oridir_fitindexes``) are computed by
      ``_oridir_fitindexes``, which delegates the Carandini/Ferster
      double-gaussian fit to vlt's ``otfit_carandini`` + ``fit2fit*``
      helpers -- importing the leaf functions directly to dodge a
      name-shadowing bug in the vlt package ``__init__``. When vlt's fit
      surface is unavailable (e.g. a no-vlt install) or the fit fails, the
      ``fit`` sub-structure degrades to NaN/empty sentinels (a documented
      divergence from MATLAB, which always fits). MEDIUM confidence on
      exact MATLAB numerical parity (scipy Nelder-Mead vs MATLAB
      fminsearch); flagged for MATLAB cross-validation.
    - ``calculate_tuning_curve`` / ``calculate_all_tuning_curves`` delegate
      to ``ndi.app.stimulus.tuning_response.tuning_curve`` (now ported).
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from . import ndi_app
from .appdoc import ndi_app_appdoc

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


# ----------------------------------------------------------------------
# Grounded private helpers (vision-science math reimplemented from the
# MATLAB sources, with formula citations). These are deliberately
# module-level and import-light (numpy/scipy only) so the app module
# stays importable when vlt is absent.
# ----------------------------------------------------------------------


def _findclosest(values: Any, target: float) -> int:
    """Index of the element of ``values`` closest to ``target``.

    Reimplements vlt.data.findclosest (index only) for the small,
    well-defined use inside the orientation/direction index helpers.
    """
    import numpy as np

    values = np.asarray(values, dtype=float)
    return int(np.argmin(np.abs(values - target)))


def _compute_circularvariance(angles, rates, harmonic: int):
    """Circular variance ``CV = 1 - |R|``.

    ``R = (rates . exp(harmonic*i*angles)) / sum(|rates|)`` with angles in
    degrees. ``harmonic=2`` gives the orientation circular variance and
    ``harmonic=1`` the direction circular variance.

    Cites vlt.neuro.vision.oridir.index.compute_circularvariance /
    compute_dircircularvariance (Ringach et al., J. Neurosci. 2002,
    22:5639-5651). The MATLAB code rounds to 2 decimals; we mirror that.
    """
    import numpy as np

    angles = np.asarray(angles, dtype=float) / 360.0 * 2.0 * np.pi
    rates = np.asarray(rates, dtype=float)
    denom = np.sum(np.abs(rates))
    if denom == 0:
        return np.nan
    r = np.sum(rates * np.exp(harmonic * 1j * angles)) / denom
    cv = 1.0 - np.abs(r)
    return float(np.round(100.0 * cv) / 100.0)


def _compute_orientationindex(angles, rates):
    """Orientation index ``(m_pref + m_180 - m_90 - m_270)/(m_pref + m_180)``.

    Cites vlt.neuro.vision.oridir.index.compute_orientationindex. No
    interpolation; nearest measured angle is used. Rounded to 2 decimals.
    """
    import numpy as np

    angles = np.asarray(angles, dtype=float)
    rates = np.asarray(rates, dtype=float)
    ind = int(np.argmax(rates))
    ang = angles[ind]
    m1 = rates[_findclosest(angles, ang % 360)]
    m2 = rates[_findclosest(angles, (ang + 180) % 360)]
    m3 = rates[_findclosest(angles, (ang + 90) % 360)]
    m4 = rates[_findclosest(angles, (ang + 270) % 360)]
    oi = (m1 + m2 - m3 - m4) / (0.0001 + (m1 + m2))
    return float(np.round(100.0 * oi) / 100.0)


def _compute_directionindex(angles, rates):
    """Direction index ``(m_pref - m_opposite)/m_pref``.

    Cites vlt.neuro.vision.oridir.index.compute_directionindex. Rounded to
    2 decimals.
    """
    import numpy as np

    angles = np.asarray(angles, dtype=float)
    rates = np.asarray(rates, dtype=float)
    ind = int(np.argmax(rates))
    ang = angles[ind]
    m1 = rates[_findclosest(angles, ang % 360)]
    m2 = rates[_findclosest(angles, (ang + 180) % 360)]
    di = (m1 - m2) / (m1 + 0.0001)
    return float(np.round(100.0 * di) / 100.0)


def _compute_tuningwidth(angles, rates):
    """Half-width at 1/sqrt(2) of max, via linear interpolation.

    Cites vlt.neuro.vision.oridir.index.compute_tuningwidth (Ringach et
    al., J. Neurosci. 2002). Returns 90 when the curve never drops below
    the half-height. Mirrors the MATLAB triple-tiling + 1-degree interp.
    """
    import numpy as np

    angles = np.asarray(angles, dtype=float)
    rates = np.asarray(rates, dtype=float)

    tiled_angles = np.concatenate([angles, 360.0 + angles, [720.0]])
    tiled_rates = np.concatenate([rates, rates, [rates[0]]])
    fineangles = np.arange(0.0, 721.0, 1.0)
    intrates = np.interp(fineangles, tiled_angles, tiled_rates)

    # MATLAB: [maxrate,pref]=max(intrates(181:540)); pref=pref+179;
    # (1-based). Translate to 0-based indices into intrates (degrees).
    window = intrates[180:540]
    maxrate = float(np.max(window))
    pref = int(np.argmax(window)) + 180  # 0-based degree index of the max
    halfheight = maxrate / np.sqrt(2.0)

    if np.min(intrates - halfheight) > 0:
        return 90.0

    left_window = intrates[pref - 90 : pref + 1]
    left = _findclosest(left_window, halfheight) + (pref - 90)
    right_window = intrates[pref : pref + 91]
    right = _findclosest(right_window, halfheight) + pref
    tuningwidth = (right - left) / 2.0
    if tuningwidth > 90:
        tuningwidth = 90.0
    return float(tuningwidth)


def _hotellingt2_onesample_p(X):
    """One-sample Hotelling's T^2 p-value testing mean(X) == [0, 0].

    X is (n_trials, 2): the real and imaginary parts of the per-trial
    response vector. Cites vlt.stats.hotellingt2test as used by
    oridir_vectorindexes. Standard multivariate test:

        T^2 = n * (xbar)' * inv(S) * (xbar)
        F   = (n - p) / (p * (n - 1)) * T^2,  df = (p, n - p)

    with p = 2. Returns NaN if n <= p or the covariance is singular.
    """
    import numpy as np
    from scipy.stats import f as f_dist

    X = np.asarray(X, dtype=float)
    n, p = X.shape
    if n <= p:
        return float("nan")
    xbar = np.mean(X, axis=0)
    S = np.cov(X, rowvar=False)  # sample covariance (ddof=1)
    try:
        Sinv = np.linalg.inv(S)
    except np.linalg.LinAlgError:
        return float("nan")
    t2 = n * (xbar @ Sinv @ xbar)
    fstat = (n - p) / (p * (n - 1)) * t2
    if fstat < 0:
        return float("nan")
    p_value = 1.0 - f_dist.cdf(fstat, p, n - p)
    return float(p_value)


def _compute_directionsignificancedotproduct(angles, rates):
    """Mazurek-Kagan-Van Hooser (2014) direction dot-product significance.

    Cites vlt.neuro.vision.oridir.index.compute_directionsignificancedotproduct
    (Frontiers in Neural Circuits, 2014). ``rates`` is (n_trials,
    n_angles). Projects each trial's direction vector onto the empirical
    unit orientation vector (in direction space) and runs a one-sample
    t-test on the projections.
    """
    import numpy as np
    from scipy.stats import ttest_1samp

    angles = np.asarray(angles, dtype=float).ravel()
    rates = np.asarray(rates, dtype=float)
    angles_rad = angles * np.pi / 180.0

    avg_rates = np.mean(rates, axis=0)
    ot_vec = np.sum(avg_rates * np.exp(1j * 2 * (angles_rad % np.pi)))
    # unit orientation vector lifted into direction space
    ot_unit = np.exp(1j * np.angle(ot_vec) / 2.0)

    dir_vec = rates @ np.exp(1j * (angles_rad % (2 * np.pi)))
    # trial-by-trial dot products onto the unit orientation vector
    dot_prods = np.real(dir_vec) * np.real(ot_unit) + np.imag(dir_vec) * np.imag(ot_unit)

    if len(dot_prods) < 2 or np.allclose(dot_prods, dot_prods[0]):
        return float("nan")
    _, p = ttest_1samp(dot_prods, 0.0)
    return float(p)


def _oridir_vectorindexes(curve, ind):
    """Vector-based orientation/direction indices.

    Faithful reimplementation of
    ``vlt.neuro.vision.oridir.index.oridir_vectorindexes`` from first
    principles (the vlt Python port is import-broken; see module
    docstring). MEDIUM confidence; flagged for review.

    Args:
        curve: array ``(4, n_dirs)`` -- row 0 angles (deg, compass),
            row 1 mean responses, row 2 stddev, row 3 stderr.
        ind: list of per-direction 1-D arrays of individual trial
            responses (may contain NaNs).

    Returns:
        dict mirroring the MATLAB ``vi`` struct fields.
    """
    import numpy as np

    vi = {
        "ot_HotellingT2_p": np.nan,
        "ot_pref": np.nan,
        "ot_circularvariance": np.nan,
        "ot_index": np.nan,
        "tuning_width": np.nan,
        "dir_HotellingT2_p": np.nan,
        "dir_pref": np.nan,
        "dir_circularvariance": np.nan,
        "dir_index": np.nan,
        "dir_dotproduct_sig_p": np.nan,
    }

    curve = np.asarray(curve, dtype=float)
    angles = curve[0, :]
    mean_resp = curve[1, :]

    hasdirection = False
    if np.max(angles) <= 180:
        tuneangles = np.concatenate([angles, angles + 180])
        tuneresps = np.concatenate([mean_resp, mean_resp])
    else:
        hasdirection = True
        tuneangles = angles
        tuneresps = mean_resp

    # Align per-trial responses to a common smallest-n matrix (trials x angles)
    smallest_n = np.inf
    for trials in ind:
        t = np.asarray(trials, dtype=float)
        valid = t[~np.isnan(t)]
        smallest_n = min(smallest_n, len(valid))
    if not np.isfinite(smallest_n):
        smallest_n = 0
    smallest_n = int(smallest_n)

    if smallest_n > 0:
        cols = []
        for trials in ind:
            t = np.asarray(trials, dtype=float)
            valid = t[~np.isnan(t)]
            cols.append(valid[:smallest_n])
        allresps = np.column_stack(cols)  # (smallest_n trials, n_angles)

        if allresps.size > 0:
            angles_rad = angles * np.pi / 180.0
            # orientation space: vector sum at 2*theta (mod pi)
            vecresp_ot = allresps @ np.exp(1j * 2 * (angles_rad % np.pi))
            X = np.column_stack((np.real(vecresp_ot), np.imag(vecresp_ot)))
            vi["ot_HotellingT2_p"] = _hotellingt2_onesample_p(X)
            vi["ot_pref"] = float((180.0 / np.pi * np.angle(np.mean(vecresp_ot))) % 180.0)

            if hasdirection:
                vecresp_dir = allresps @ np.exp(1j * (angles_rad % (2 * np.pi)))
                Xd = np.column_stack((np.real(vecresp_dir), np.imag(vecresp_dir)))
                vi["dir_HotellingT2_p"] = _hotellingt2_onesample_p(Xd)
                vi["dir_pref"] = float((180.0 / np.pi * np.angle(np.mean(vecresp_dir))) % 360.0)
                vi["dir_dotproduct_sig_p"] = _compute_directionsignificancedotproduct(
                    angles, allresps
                )

    vi["ot_circularvariance"] = _compute_circularvariance(tuneangles, tuneresps, harmonic=2)
    vi["ot_index"] = _compute_orientationindex(tuneangles, tuneresps)
    vi["tuning_width"] = _compute_tuningwidth(tuneangles, tuneresps)

    if hasdirection:
        vi["dir_circularvariance"] = _compute_circularvariance(tuneangles, tuneresps, harmonic=1)
        vi["dir_index"] = _compute_directionindex(angles, mean_resp)

    return vi


def _neural_response_significance(resp_ind, blank_ind=None):
    """One-way ANOVA significance of response variation across stimuli.

    Reimplements ``neural_response_significance`` (vhlab-library-matlab)
    using ``scipy.stats.f_oneway``. MEDIUM confidence; flagged for review.

    Args:
        resp_ind: list of per-stimulus 1-D arrays of individual responses.
        blank_ind: optional 1-D array of blank-trial responses.

    Returns:
        ``(sigp, sigpb)`` where ``sigp`` is the ANOVA p across stimulus
        conditions and ``sigpb`` additionally includes the blank as a
        group (identical to ``sigp`` when no blank is supplied).
    """
    import numpy as np
    from scipy.stats import f_oneway

    groups = []
    for trials in resp_ind:
        t = np.asarray(trials, dtype=float).ravel()
        t = t[~np.isnan(t)]
        if t.size > 0:
            groups.append(t)

    def _anova(gs):
        # f_oneway needs >= 2 groups, each with variance.
        if len(gs) < 2:
            return float("nan")
        try:
            return float(f_oneway(*gs).pvalue)
        except Exception:
            return float("nan")

    sigp = _anova(groups)

    if blank_ind is not None:
        b = np.asarray(blank_ind, dtype=float).ravel()
        b = b[~np.isnan(b)]
        if b.size > 0:
            sigpb = _anova(groups + [b])
        else:
            sigpb = sigp
    else:
        sigpb = sigp

    return sigp, sigpb


def _oridir_fitindexes(curve, ind=None):
    """Double-gaussian orientation/direction fit indices.

    Faithful port of ``vlt.neuro.vision.oridir.index.oridir_fitindexes``
    (the Carandini/Ferster 2000 two-peaked Gaussian). The nonlinear fit and
    the index math are delegated to vlt's ``otfit_carandini`` + ``fit2fit*``
    helpers, which DO exist in the Python vlt surface and compute correctly.

    The vlt package's own ``oridir_fitindexes`` wrapper is unusable because
    every ``import vlt.x.y as z`` it uses resolves ``z`` to the *function*
    re-exported by the package ``__init__`` (a name-shadowing bug), so
    ``z.y(...)`` raises ``AttributeError``. We therefore import the leaf
    functions directly (``from vlt.fit.otfit_carandini import
    otfit_carandini``) and replicate the small driver loop here.

    Args:
        curve: 4xN array ``[directions; mean; stddev; stderr]``.
        ind: unused (kept for signature parity with ``_oridir_vectorindexes``).

    Returns:
        dict mirroring the vlt ``fi`` struct (fit_parameters, the 0..359 fit
        curve, the orientation/direction indices + rectified + diffsum
        variants, dirpref, tuning_width).

    Raises:
        ImportError: if vlt's fit surface is unavailable (the caller falls
            back to NaN/empty sentinels, matching the no-vlt sandbox).
    """
    import numpy as np

    # Import the leaf functions directly to dodge the vlt package __init__
    # name-shadowing bug (see the docstring above).
    from vlt.fit.otfit_carandini import otfit_carandini
    from vlt.math.rectify import rectify
    from vlt.neuro.vision.oridir.index.fit2fitdi import fit2fitdi
    from vlt.neuro.vision.oridir.index.fit2fitdidiffsum import fit2fitdidiffsum
    from vlt.neuro.vision.oridir.index.fit2fitoi import fit2fitoi
    from vlt.neuro.vision.oridir.index.fit2fitoidiffsum import fit2fitoidiffsum

    resp = np.asarray(curve, dtype=float)
    angles = resp[0, :]
    mean_resp = resp[1, :]

    maxresp = float(np.max(mean_resp))
    otpref = float(angles[int(np.argmax(mean_resp))])

    # If the curve only spans [0,180], mirror it to a full 360 deg direction
    # curve (mirrors the MATLAB hasdirection branch).
    if float(np.max(angles)) <= 180:
        tuneangles = np.concatenate([angles, angles + 180])
        tuneresps = np.concatenate([mean_resp, mean_resp])
    else:
        tuneangles = angles
        tuneresps = mean_resp

    da = float(np.diff(np.sort(angles))[0])  # smallest angular step
    width_seeds = [da / 2, da, 40, 60, 90]

    # Try each width seed; keep the lowest-SSE fit (er is the 7th return).
    best = None
    for ws in width_seeds:
        out = otfit_carandini(
            tuneangles,
            0,
            maxresp,
            otpref,
            ws,
            widthint=[da / 2, 180],
            Rpint=[0, 3 * maxresp],
            Rnint=[0, 3 * maxresp],
            spontint=[float(np.min(tuneresps)), float(np.max(tuneresps))],
            data=tuneresps,
        )
        if best is None or out[6] < best[6]:
            best = out

    Rsp, Rp, Ot, sigm, Rn, fitcurve, _er, _r2 = best
    fit = np.vstack([np.arange(360, dtype=float), np.asarray(fitcurve, dtype=float).ravel()])

    ot_index = fit2fitoi(fit)
    ot_index_diffsum = fit2fitoidiffsum(fit)
    dir_index = fit2fitdi(fit)
    dir_index_diffsum = fit2fitdidiffsum(fit)

    return {
        "fit_parameters": [float(Rsp), float(Rp), float(Ot), float(sigm), float(Rn)],
        "fit": fit,
        "ot_index": float(ot_index),
        "ot_index_rectified": float(min(rectify(ot_index), 1)),
        "ot_index_diffsum": float(ot_index_diffsum),
        "ot_index_diffsum_rectified": float(min(rectify(ot_index_diffsum), 1)),
        "dir_index": float(dir_index),
        "dir_index_rectified": float(min(rectify(dir_index), 1)),
        "dir_index_diffsum": float(dir_index_diffsum),
        "dir_index_diffsum_rectified": float(min(rectify(dir_index_diffsum), 1)),
        "dirpref": float(Ot),
        "tuning_width": float(sigm * np.sqrt(np.log(4))),
    }


def _nan_fit_struct():
    """Sentinel ``fit`` sub-structure used when the fit is unavailable."""
    import numpy as np

    return {
        "double_gaussian_parameters": [],
        "double_gaussian_fit_angles": [],
        "double_gaussian_fit_values": [],
        "orientation_preferred_orthogonal_ratio": np.nan,
        "direction_preferred_null_ratio": np.nan,
        "orientation_preferred_orthogonal_ratio_rectified": np.nan,
        "direction_preferred_null_ratio_rectified": np.nan,
        "orientation_angle_preference": np.nan,
        "direction_angle_preference": np.nan,
        "hwhh": np.nan,
    }


def _fit_struct(curve, ind=None):
    """Build the ``orientation_direction_tuning`` ``fit`` sub-structure.

    Runs the vlt-backed double-gaussian fit via :func:`_oridir_fitindexes`
    and maps its ``fi`` struct onto the document's ``fit`` fields (the
    MATLAB ``oridirtuning`` field map). Falls back to NaN/empty sentinels (a
    documented divergence from MATLAB, which always fits) when vlt's fit
    surface is unavailable -- e.g. the no-vlt sandbox -- or the fit fails.
    """
    import numpy as np

    try:
        fi = _oridir_fitindexes(curve, ind)
    except Exception as exc:  # noqa: BLE001 - vlt missing or fit failed -> sentinels
        warnings.warn(
            f"oridir double-gaussian fit unavailable ({exc}); the 'fit' "
            "sub-structure is stored with NaN/empty sentinels.",
            UserWarning,
            stacklevel=2,
        )
        return _nan_fit_struct()

    return {
        "double_gaussian_parameters": list(fi["fit_parameters"]),
        "double_gaussian_fit_angles": np.asarray(fi["fit"][0]).tolist(),
        "double_gaussian_fit_values": np.asarray(fi["fit"][1]).tolist(),
        "orientation_preferred_orthogonal_ratio": fi["ot_index"],
        "direction_preferred_null_ratio": fi["dir_index"],
        "orientation_preferred_orthogonal_ratio_rectified": fi["ot_index_rectified"],
        "direction_preferred_null_ratio_rectified": fi["dir_index_rectified"],
        "orientation_angle_preference": float(np.mod(fi["dirpref"], 180)),
        "direction_angle_preference": fi["dirpref"],
        "hwhh": fi["tuning_width"],
    }


class ndi_app_oridirtuning(ndi_app, ndi_app_appdoc):
    """
    ndi_app for orientation/direction tuning analysis.

    Computes orientation and direction selectivity measures from
    stimulus tuning curves, including:
    - Circular variance (orientation and direction)
    - Orientation/direction selectivity indices
    - Preferred orientation/direction angles
    - Hotelling T^2 / Mazurek dot-product significance
    - Across-stimulus and visual-response ANOVA significance

    Doc types:
        - orientation_direction_tuning: Computed tuning properties
        - tuning_curve: Stimulus tuning curves

    Example:
        >>> odt = ndi_app_oridirtuning(session)
        >>> odt.calculate_all_oridir_indexes(element_obj)
    """

    def __init__(self, session: ndi_session | None = None):
        ndi_app.__init__(self, session=session, name="ndi_app_oridirtuning")
        ndi_app_appdoc.__init__(
            self,
            doc_types=["orientation_direction_tuning", "tuning_curve"],
            doc_document_types=[
                "stimulus/vision/oridir/orientation_direction_tuning",
                "stimulus/stimulus_tuningcurve",
            ],
            doc_session=session,
        )

    # ------------------------------------------------------------------
    # Tuning-curve creation (delegates to ndi.app.stimulus.tuning_response)
    # ------------------------------------------------------------------

    def calculate_all_tuning_curves(
        self,
        ndi_element_obj: Any,
        docexistsaction: str = "Replace",
    ) -> list[ndi_document]:
        """
        Calculate tuning curves for all oridir stimulus responses.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_all_tuning_curves

        Args:
            ndi_element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of tuning curve documents
        """
        if self._session is None:
            return []
        from ..query import ndi_query

        q_relement = ndi_query("").depends_on("element_id", ndi_element_obj.id)
        q_rdoc = ndi_query("").isa("stimulus_response_scalar")
        rdocs = self._session.database_search(q_rdoc & q_relement)

        tuning_doc: list[ndi_document] = []
        for rdoc in rdocs:
            if self.is_oridir_stimulus_response(rdoc):
                appdoc_struct = {
                    "element_id": ndi_element_obj.id,
                    "response_doc_id": rdoc.id,
                }
                tuning_doc.extend(
                    self.add_appdoc(
                        "tuning_curve",
                        appdoc_struct,
                        docexistsaction,
                        ndi_element_obj,
                        rdoc,
                    )
                )
        return tuning_doc

    def calculate_tuning_curve(
        self,
        ndi_element_obj: Any,
        ndi_response_doc: ndi_document,
        do_add: bool = True,
    ) -> ndi_document | None:
        """
        Calculate a single tuning curve from a response document.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_tuning_curve

        Args:
            ndi_element_obj: Neural element
            ndi_response_doc: stimulus_response_scalar document
            do_add: If True, add to database

        Returns:
            Tuning curve document, or None when the response does not vary in
            angle only (not an oridir stimulus).
        """
        from .stimulus.tuning_response import ndi_app_stimulus_tuning__response

        if self._session is None:
            return None

        rapp = ndi_app_stimulus_tuning__response(self._session)

        if not self.is_oridir_stimulus_response(ndi_response_doc):
            return None

        # Mirrors MATLAB oridirtuning/calculate_tuning_curve: tune over 'angle'
        # (labelled 'direction'), restricted to stimuli that carry sFrequency.
        constraint = [{"field": "sFrequency", "operation": "hasfield", "param1": "", "param2": ""}]
        tuning_doc = rapp.tuning_curve(
            ndi_response_doc,
            independent_label=["direction"],
            independent_parameter=["angle"],
            constraint=constraint,
            do_add=False,
        )
        if tuning_doc is None:
            return None

        tuning_doc = tuning_doc.set_dependency_value("element_id", ndi_element_obj.id)
        tuning_doc = tuning_doc.set_dependency_value(
            "stimulus_response_scalar_id", ndi_response_doc.id
        )

        if do_add and self._session is not None:
            self._session.database_add(tuning_doc)

        return tuning_doc

    # ------------------------------------------------------------------
    # Orientation/direction index calculation
    # ------------------------------------------------------------------

    def calculate_all_oridir_indexes(
        self,
        ndi_element_obj: Any,
        docexistsaction: str = "Replace",
    ) -> list[ndi_document]:
        """
        Calculate orientation/direction indices for all oridir responses.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_all_oridir_indexes

        Args:
            ndi_element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of orientation_direction_tuning documents
        """
        if self._session is None:
            return []
        from ..query import ndi_query

        q_relement = ndi_query("").depends_on("element_id", ndi_element_obj.id)
        q_rdoc = ndi_query("").isa("stimulus_response_scalar")
        rdocs = self._session.database_search(q_rdoc & q_relement)

        oriprops: list[ndi_document] = []
        for rdoc in rdocs:
            if self.is_oridir_stimulus_response(rdoc):
                q_tdoc = ndi_query("").isa("stimulus_tuningcurve")
                q_tdocrdoc = ndi_query("").depends_on("stimulus_response_scalar_id", rdoc.id)
                tdocs = self._session.database_search(q_tdoc & q_tdocrdoc & q_relement)
                for tdoc in tdocs:
                    appdoc_struct = {"tuning_doc_id": tdoc.id}
                    oriprops.extend(
                        self.add_appdoc(
                            "orientation_direction_tuning",
                            appdoc_struct,
                            docexistsaction,
                            tdoc,
                        )
                    )
        return oriprops

    def calculate_oridir_indexes(
        self,
        tuning_doc: ndi_document,
        do_add: bool = True,
        do_plot: bool = False,
    ) -> ndi_document | None:
        """
        Calculate orientation/direction indices from a tuning curve.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_oridir_indexes

        Computes, from a ``stimulus_tuningcurve`` document, the mean and
        standard error of the (blank-subtracted) response per direction,
        the vector-based orientation/direction selectivity indices, and
        the across-stimulus / visual-response ANOVA significance, and
        assembles an ``orientation_direction_tuning`` document.

        Args:
            tuning_doc: stimulus_tuningcurve document
            do_add: If True, add the result to the database
            do_plot: Ignored in Python (plotting requires matplotlib)

        Returns:
            orientation_direction_tuning document, or None

        Notes:
            The ``fit`` sub-structure (double-gaussian fit indices) is
            computed via :func:`_oridir_fitindexes` (vlt-backed). If vlt's
            fit surface is unavailable it falls back to NaN/empty sentinels
            with a UserWarning (a documented divergence from MATLAB).
        """
        import numpy as np

        from ..document import ndi_document

        props = tuning_doc.document_properties
        stc = props["stimulus_tuningcurve"]

        # Directions (independent variable) — the per-direction reduction below
        # must produce one value per direction, so the number of directions is
        # the authoritative outer length.
        directions = np.asarray(stc["independent_variable_value"], dtype=float).ravel()
        ndir = int(directions.size)

        # Build complex per-direction individual responses:
        #   ind = real + i*imag ;  response = ind - control
        # The reduction loop below indexes by DIRECTION and must produce one
        # value per direction, so every matrix is oriented to put the
        # direction axis (length ``ndir``) first.
        #
        # Payloads reach this method in BOTH orientations: native MATLAB docs
        # serialise the individual-response matrices as ``[repetition,
        # stimulus]`` (real Carbon Fiber docs are e.g. 5x12 = 5 reps x 12
        # directions), while this module's own directions-first fixtures arrive
        # as ``[direction, repetition]``. The orientation is therefore chosen
        # explicitly from the KNOWN directions length ``ndir``, not from a bare
        # shape comparison:
        #   * trailing axis == ndir and leading axis != ndir  -> reps-first   -> transpose
        #   * leading  axis == ndir and trailing axis != ndir -> dirs-first   -> as-is
        #   * SQUARE (leading == trailing == ndir, i.e. reps == directions)    -> ambiguous:
        #       resolve to the MATLAB serialisation ``[reps, directions]`` and
        #       transpose so the directions axis ends up first.
        # (Bug fix 1: earlier code used ``n = len(individual_responses_real)`` =
        # number of repetitions, mismatching ``independent_variable_value`` and
        # raising "vstack ... size 12 vs 5" on real MATLAB tuning curves.)
        # (Bug fix 2: the prior heuristic ``shape[0] != ndir and shape[-1] ==
        # ndir`` left the SQUARE case un-transposed, silently mis-orienting the
        # response when reps == directions. The square branch below makes that
        # axis selection explicit instead of shape-ambiguous.)
        def _dir_first(raw: Any) -> np.ndarray:
            a = np.asarray(raw, dtype=float)
            if a.ndim == 1:
                return a.reshape(ndir, -1) if a.size == ndir else a.reshape(1, -1)
            if a.ndim < 2:
                return a
            leading_is_dir = a.shape[0] == ndir
            trailing_is_dir = a.shape[-1] == ndir
            if leading_is_dir and trailing_is_dir:
                # Square reps==directions: pick the MATLAB [reps, directions]
                # layout and transpose to directions-first.
                return a.T
            if trailing_is_dir and not leading_is_dir:
                return a.T
            return a

        ind_r = _dir_first(stc["individual_responses_real"])
        ind_i = _dir_first(stc["individual_responses_imaginary"])
        ctl_r = _dir_first(stc["control_individual_responses_real"])
        ctl_i = _dir_first(stc["control_individual_responses_imaginary"])

        n = ind_r.shape[0]
        ind_real_list: list[Any] = []
        control_real_list: list[Any] = []
        response_ind: list[Any] = []
        response_mean = np.zeros(n)
        response_stddev = np.zeros(n)
        response_stderr = np.zeros(n)

        for i in range(n):
            ind = np.asarray(ind_r[i], dtype=float) + 1j * np.asarray(ind_i[i], dtype=float)
            control = np.asarray(ctl_r[i], dtype=float) + 1j * np.asarray(ctl_i[i], dtype=float)

            ind_real = np.abs(ind) if np.any(np.iscomplex(ind)) else np.real(ind)
            control_real = np.abs(control) if np.any(np.iscomplex(control)) else np.real(control)

            resp = ind - control
            m = np.nanmean(resp)
            if np.iscomplexobj(resp) and not np.isreal(m):
                m = np.abs(m)
            response_mean[i] = np.real(m)
            response_stddev[i] = np.nanstd(resp, ddof=1) if resp.size > 1 else 0.0
            response_stderr[i] = self._nanstderr(resp)
            if np.any(np.iscomplex(resp)):
                resp = np.abs(resp)

            ind_real_list.append(np.real(ind_real))
            control_real_list.append(np.real(control_real))
            response_ind.append(np.real(resp))

        # curve = [directions ; mean ; stddev ; stderr] (directions computed above)
        curve = np.vstack([directions, response_mean, response_stddev, response_stderr])

        # vector indices (grounded helper)
        vi = _oridir_vectorindexes(curve, response_ind)

        # significance ANOVA: blank = control responses of the first direction
        blank_ind = control_real_list[0] if control_real_list else None
        anova_across_stims, anova_across_stims_blank = _neural_response_significance(
            ind_real_list, blank_ind
        )

        # fit indices: vlt-backed double-gaussian fit (NaN/empty sentinels if
        # vlt's fit surface is unavailable or the fit fails -- _fit_struct warns).
        fit = _fit_struct(curve, response_ind)

        # response_type / response_units come from the response + tuning docs
        response_units = stc.get("response_units", "")
        response_type = "mean"
        stim_response_doc = None
        if self._session is not None:
            from ..query import ndi_query

            srs_id = tuning_doc.dependency_value(
                "stimulus_response_scalar_id", error_if_not_found=False
            )
            if srs_id:
                found = self._session.database_search(ndi_query("base.id", "exact_string", srs_id))
                if found:
                    stim_response_doc = found[0]
                    response_type = stim_response_doc.document_properties.get(
                        "stimulus_response_scalar", {}
                    ).get("response_type", "mean")

        odt = ndi_document(
            "stimulus/vision/oridir/orientation_direction_tuning",
        )
        odt_props = odt.document_properties["orientation_direction_tuning"]
        odt_props["properties"] = {
            "coordinates": "compass",
            "response_units": response_units,
            "response_type": response_type,
        }
        odt_props["tuning_curve"] = {
            "direction": directions.tolist(),
            "mean": response_mean.tolist(),
            "stddev": response_stddev.tolist(),
            "stderr": response_stderr.tolist(),
            "individual": [np.asarray(x).tolist() for x in response_ind],
            "raw_individual": [np.asarray(x).tolist() for x in ind_real_list],
            "control_individual": [np.asarray(x).tolist() for x in control_real_list],
        }
        odt_props["significance"] = {
            "visual_response_anova_p": anova_across_stims_blank,
            "across_stimuli_anova_p": anova_across_stims,
        }
        odt_props["vector"] = {
            "circular_variance": vi["ot_circularvariance"],
            "direction_circular_variance": vi["dir_circularvariance"],
            "hotelling2test": vi["ot_HotellingT2_p"],
            "orientation_preference": vi["ot_pref"],
            "direction_preference": vi["dir_pref"],
            "direction_hotelling2test": vi["dir_HotellingT2_p"],
            "dot_direction_significance": vi["dir_dotproduct_sig_p"],
        }
        odt_props["fit"] = fit

        # dependencies: element_id (from the response doc) + tuning curve id
        element_id = None
        if stim_response_doc is not None:
            element_id = stim_response_doc.dependency_value("element_id", error_if_not_found=False)
        if element_id is None:
            element_id = tuning_doc.dependency_value("element_id", error_if_not_found=False)
        if element_id is not None:
            odt = odt.set_dependency_value("element_id", element_id)
        odt = odt.set_dependency_value("stimulus_tuningcurve_id", tuning_doc.id)

        if do_add and self._session is not None:
            self._session.database_add(odt)

        return odt

    @staticmethod
    def _nanstderr(values: Any) -> float:
        """Standard error of the mean ignoring NaNs (mirrors vlt.data.nanstderr)."""
        import numpy as np

        v = np.asarray(values)
        if np.iscomplexobj(v):
            mag = np.abs(v)
        else:
            mag = np.real(v).astype(float)
        valid = mag[~np.isnan(mag)]
        if valid.size < 2:
            return 0.0
        return float(np.nanstd(valid, ddof=1) / np.sqrt(valid.size))

    def is_oridir_stimulus_response(self, response_doc: ndi_document = None) -> bool:
        """
        Check whether a response document's stimulus varies in angle only.

        MATLAB equivalent: ndi.app.oridirtuning/is_oridir_stimulus_response
        (signature ``is_oridir_stimulus_response(obj, response_doc)`` -- exactly
        one functional argument).

        Mirrors the MATLAB logic: find the stimulus_presentation document
        the response depends on, drop blank stimuli, and test whether the
        only varying parameter across the remaining stimuli is 'angle'.

        Callable two ways, both supported by the established API:

        * bound on an instance -- ``app.is_oridir_stimulus_response(doc)`` --
          which uses the session (if any) and otherwise the structural fallback;
        * on the class with only the doc --
          ``ndi_app_oridirtuning.is_oridir_stimulus_response(doc)`` -- which
          performs the no-database structural check on the document directly.

        Args:
            response_doc: stimulus_response_scalar document

        Returns:
            True if the only varying stimulus parameter is 'angle'.
        """
        # Support the class-level call form ``Class.method(doc)``: here ``self``
        # is actually the document and ``response_doc`` is omitted. Detect that
        # and route to the no-database structural check.
        if not isinstance(self, ndi_app_oridirtuning):
            return ndi_app_oridirtuning._is_oridir_structural(self)

        if self._session is None:
            # No database: fall back to a structural check on the doc itself.
            return self._is_oridir_structural(response_doc)

        from ..query import ndi_query

        stim_pres_id = response_doc.dependency_value(
            "stimulus_presentation_id", error_if_not_found=False
        )
        if not stim_pres_id:
            return self._is_oridir_structural(response_doc)

        found = self._session.database_search(ndi_query("base.id", "exact_string", stim_pres_id))
        if not found:
            return False

        sp = found[0].document_properties.get("stimulus_presentation", {})
        stimuli = sp.get("stimuli", [])
        stim_props = [s.get("parameters", {}) for s in stimuli]

        included = []
        for p in stim_props:
            if "isblank" not in p:
                included.append(p)
            elif not p["isblank"]:
                included.append(p)

        desc = self._structwhatvaries(included)
        return desc == ["angle"]

    @staticmethod
    def _is_oridir_structural(response_doc: ndi_document) -> bool:
        """Best-effort no-database fallback: inspect tuning-curve label.

        Tolerates both mapping-style (``ndi.document`` whose
        ``document_properties`` is a dict) and attribute-style documents (a
        plain object whose nested fields are attributes), so the structural
        check works for both real documents and lightweight test doubles.
        """

        def _get(container: Any, key: str) -> Any:
            if isinstance(container, dict):
                return container.get(key)
            if hasattr(container, "get") and not hasattr(container, key):
                try:
                    return container.get(key)
                except (TypeError, AttributeError):
                    return None
            return getattr(container, key, None)

        props = getattr(response_doc, "document_properties", response_doc)
        stc = _get(props, "stimulus_tuningcurve")
        if stc is None:
            return False
        indep = _get(stc, "independent_variable_label")
        if indep is None:
            return False
        if isinstance(indep, (list, tuple)):
            indep = indep[0] if indep else ""
        return str(indep).lower() in ("angle", "direction", "orientation")

    @staticmethod
    def _structwhatvaries(structs: list[dict]) -> list[str]:
        """Names of the fields whose values differ across the dicts.

        Mirrors vlt.data.structwhatvaries for the small use here.
        """
        if not structs:
            return []
        keys = set()
        for s in structs:
            keys.update(s.keys())
        varies = []
        for k in sorted(keys):
            values = [s.get(k, None) for s in structs]
            first = values[0]
            if any(v != first for v in values[1:]):
                varies.append(k)
        return varies

    def plot_oridir_response(self, oriprops_doc: ndi_document) -> None:
        """
        Plot orientation/direction response.

        MATLAB equivalent: ndi.app.oridirtuning/plot_oridir_response

        Note:
            Plotting is intentionally left to the viewer layer, not the SDK:
            the ``orientation_direction_tuning`` document already carries the
            tuning curve (direction/mean/stderr) and the double-gaussian
            ``fit`` (angles/values) needed to draw it with matplotlib.
        """
        raise NotImplementedError(
            "plot_oridir_response is not ported: matplotlib plotting is left to "
            "the viewer. Draw it directly with matplotlib from the document's "
            "tuning_curve (direction/mean/stderr) and fit (double_gaussian_fit_"
            "angles/values) fields."
        )

    # ------------------------------------------------------------------
    # appdoc overrides
    # ------------------------------------------------------------------

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, *args, **kwargs):
        """
        Create an ndi.document from an appdoc struct.

        MATLAB equivalent: ndi.app.oridirtuning/struct2doc
        """
        from ..query import ndi_query

        if appdoc_type == "orientation_direction_tuning":
            tuning_doc_id = appdoc_struct["tuning_doc_id"]
            if self._session is None:
                raise RuntimeError("struct2doc requires a session to resolve the tuning doc")
            td = self._session.database_search(ndi_query("base.id", "exact_string", tuning_doc_id))
            if len(td) == 0:
                raise ValueError(f"No tuning doc with id {tuning_doc_id}.")
            if len(td) > 1:
                raise ValueError("Too many tuning documents.")
            return self.calculate_oridir_indexes(td[0], do_add=False)
        elif appdoc_type in ("tuning_curve", "stimulus_tuningcurve"):
            element_id = appdoc_struct["element_id"]
            if self._session is None:
                raise RuntimeError("struct2doc requires a session to resolve the response doc")
            rd = self._session.database_search(
                ndi_query("base.id", "exact_string", appdoc_struct["response_doc_id"])
            )
            if len(rd) == 0:
                raise ValueError(f"No response doc with id {appdoc_struct['response_doc_id']}.")
            if len(rd) > 1:
                raise ValueError("Too many response documents.")
            from ..database_fun import ndi_document2ndi_object

            ndi_element_obj = ndi_document2ndi_object(element_id, self._session)
            return self.calculate_tuning_curve(ndi_element_obj, rd[0], do_add=False)
        raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def doc2struct(self, appdoc_type: str, doc: ndi_document) -> dict:
        """
        Extract an appdoc struct from an ndi.document.

        MATLAB equivalent: ndi.app.oridirtuning/doc2struct
        """
        if appdoc_type == "orientation_direction_tuning":
            return {
                "tuning_doc_id": doc.dependency_value(
                    "stimulus_tuningcurve_id", error_if_not_found=False
                )
            }
        elif appdoc_type in ("tuning_curve", "stimulus_tuningcurve"):
            return {
                "element_id": doc.dependency_value("element_id", error_if_not_found=False),
                "response_doc_id": doc.dependency_value(
                    "stimulus_response_scalar_id", error_if_not_found=False
                ),
            }
        return super().doc2struct(appdoc_type, doc)

    def find_appdoc(self, appdoc_type: str, *args, **kwargs) -> list[ndi_document]:
        """
        Find existing app documents.

        MATLAB equivalent: ndi.app.oridirtuning/find_appdoc
        """
        if self._session is None:
            return []
        from ..query import ndi_query

        if appdoc_type == "orientation_direction_tuning":
            q = ndi_query("").isa("orientation_direction_tuning")
            if len(args) >= 1 and args[0] is not None:
                tuning_doc = args[0]
                q = q & ndi_query("").depends_on("stimulus_tuningcurve_id", tuning_doc.id)
            if len(args) >= 2 and args[1] is not None:
                q = q & ndi_query("").depends_on("element_id", args[1])
            return self._session.database_search(q)
        elif appdoc_type in ("tuning_curve", "stimulus_tuningcurve"):
            q = ndi_query("").isa("stimulus_tuningcurve")
            if len(args) >= 1 and args[0] is not None:
                element = args[0]
                q = q & ndi_query("").depends_on("element_id", element.id)
            if len(args) >= 2 and args[1] is not None:
                response_doc = args[1]
                q = q & ndi_query("").depends_on("stimulus_response_scalar_id", response_doc.id)
            return self._session.database_search(q)
        raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Validate an appdoc struct.

        MATLAB equivalent: ndi.app.oridirtuning -- note that the MATLAB class
        provides NO ``isvalid_appdoc_struct`` override; field-level validation
        happens at document creation against the schema, not here. To stay
        faithful to that contract (and to the established Python API), the
        recognized oridir appdoc types are accepted as valid.
        """
        return True, ""

    def __repr__(self) -> str:
        return f"ndi_app_oridirtuning(session={self._session is not None})"
