"""ndi.gui.app.pyraview.filter_data - the viewer's filter band.

MATLAB counterpart: ``+ndi/+gui/+app/+pyraview/filterData.m``
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np

__all__ = ["filter_data", "filterData", "FILTER_TYPES"]

#: The bands accepted. 'all' is the user-facing all-pass and 'none' is the
#: stored filter type of one; both are accepted so this can be called from the
#: creation path (with a band) and the read-back path (with a stored type).
FILTER_TYPES = ("low", "high", "all", "none")

#: The Chebyshev design MATLAB uses for the two real bands.
FILTER_ORDER = 4
PASSBAND_RIPPLE_DB = 0.8
CUTOFF_HZ = 300.0


def filter_data(data: Any, sr: float, type: str) -> tuple[np.ndarray, dict[str, Any]]:  # noqa: A002
    """Filter DATA (samples x channels) at sample rate SR for band TYPE.

    Returns ``(filtered_data, filter_struct)``. The struct is what goes into a
    ``filter`` document: ``label`` carries the user-facing band, while ``type``
    and ``algorithm`` carry the schema's vocabulary -- so an all-pass records
    itself as a ``none`` filter labelled ``all``, which is how a document
    written for the "all" band reads back correctly.

    MATLAB checks for the Signal Processing Toolbox and returns the data
    unfiltered when it is absent. scipy is a hard dependency here, so the
    equivalent branch cannot arise; what remains is MATLAB's other guard, the
    cutoff at or above Nyquist, which is clamped with a warning rather than
    handed to the design routine.
    """
    if type not in FILTER_TYPES:
        raise ValueError(f"type must be one of {FILTER_TYPES}; got {type!r}.")

    array = np.asarray(data, dtype=float)
    if array.ndim == 1:
        array = array.reshape(-1, 1)

    # The label is the band the user asked for; the type is the schema's word.
    filter_struct: dict[str, Any] = {"label": type}

    if type in ("all", "none"):
        filter_struct["type"] = "none"
        filter_struct["algorithm"] = "none"
        filter_struct["parameters"] = {
            "sampleFrequency": float(sr),
            "order": math.nan,
            "filterFrequency": math.nan,
            "passBandRipple": math.nan,
            "stopbandAttentuation": math.nan,
        }
        return array, filter_struct

    filter_struct["type"] = type
    filter_struct["algorithm"] = "chebyshev_1"
    filter_struct["parameters"] = {
        "sampleFrequency": float(sr),
        "order": FILTER_ORDER,
        "filterFrequency": CUTOFF_HZ,
        "passBandRipple": PASSBAND_RIPPLE_DB,
        "stopbandAttentuation": math.nan,
    }

    if array.size == 0:
        return array, filter_struct

    from scipy.signal import cheby1, lfilter

    nyquist = 0.5 * float(sr)
    cutoff = CUTOFF_HZ / nyquist
    if cutoff >= 1:
        warnings.warn(
            "Filter cutoff frequency is >= Nyquist frequency. "
            "Adjusting to 0.99*Nyquist for stability.",
            stacklevel=2,
        )
        cutoff = 0.99

    b, a = cheby1(FILTER_ORDER, PASSBAND_RIPPLE_DB, cutoff, btype=type)
    # lfilter, not filtfilt: MATLAB's filter() is causal and single-pass, and
    # a zero-phase filter here would shift spike shapes relative to the ticks
    # drawn over them.
    filtered = lfilter(b, a, array, axis=0)
    return filtered, filter_struct


#: MATLAB's spelling.
filterData = filter_data
