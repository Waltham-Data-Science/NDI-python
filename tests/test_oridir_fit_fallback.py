"""Fallback coverage for the oridir double-gaussian fit.

Unlike ``test_pr11_oridirtuning.py`` this file is intentionally NOT gated on
``vlt``: it exercises the NaN/empty sentinel path that ``_fit_struct`` takes
when vlt's fit surface is unavailable (or the fit raises). CI must cover this
path even when vlt is not installed, and it guards against key drift between
``_nan_fit_struct`` and the success-path field mapping (both feed the same
``orientation_direction_tuning`` ``fit`` sub-structure).
"""

from __future__ import annotations

import numpy as np
import pytest

import ndi.app.oridirtuning as od

# The canonical ``fit`` sub-structure fields (the success mapping in
# ``_fit_struct`` and ``_nan_fit_struct`` must both produce exactly these).
_FIT_FIELDS = {
    "double_gaussian_parameters",
    "double_gaussian_fit_angles",
    "double_gaussian_fit_values",
    "orientation_preferred_orthogonal_ratio",
    "direction_preferred_null_ratio",
    "orientation_preferred_orthogonal_ratio_rectified",
    "direction_preferred_null_ratio_rectified",
    "orientation_angle_preference",
    "direction_angle_preference",
    "hwhh",
}


def _curve():
    angles = np.arange(0.0, 360.0, 45.0)
    return np.vstack([angles, np.ones(8), np.zeros(8), np.zeros(8)])


def test_nan_fit_struct_has_canonical_fields():
    assert set(od._nan_fit_struct()) == _FIT_FIELDS


def test_fit_struct_falls_back_to_sentinels_on_failure(monkeypatch):
    """When the fit raises (e.g. vlt absent -> ImportError), ``_fit_struct``
    warns and returns the NaN/empty sentinel struct."""

    def _boom(*args, **kwargs):
        raise ImportError("vlt fit surface unavailable")

    monkeypatch.setattr(od, "_oridir_fitindexes", _boom)

    with pytest.warns(UserWarning, match="fit unavailable"):
        fit = od._fit_struct(_curve())

    # Same fields as the documented sentinel; sentinel values.
    assert set(fit) == _FIT_FIELDS
    assert fit["double_gaussian_parameters"] == []
    assert fit["double_gaussian_fit_angles"] == []
    assert fit["double_gaussian_fit_values"] == []
    assert np.isnan(fit["hwhh"])
    assert np.isnan(fit["orientation_angle_preference"])
    assert np.isnan(fit["direction_preferred_null_ratio"])
