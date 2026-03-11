"""
ndi.util.downsampleTimeseries

MATLAB equivalent: +ndi/+util/downsampleTimeseries.m

Downsamples a timeseries after applying a low-pass anti-aliasing filter.
"""

from __future__ import annotations

import warnings

import numpy as np


def downsampleTimeseries(
    t_in: np.ndarray,
    d_in: np.ndarray,
    LP: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample a timeseries with anti-aliasing.

    MATLAB equivalent:
    ``[t_out, d_out] = ndi.util.downsampleTimeseries(t_in, d_in, LP)``

    If the sampling frequency is greater than ``2 * LP``, a 4th-order
    Chebyshev Type I low-pass filter is applied before downsampling.
    Otherwise the data is returned unchanged.

    Parameters
    ----------
    t_in : numpy.ndarray
        1-D array of time values (seconds).  Samples are assumed to be
        equally spaced.
    d_in : numpy.ndarray
        Data matrix.  Each column is a channel; rows correspond to samples
        in *t_in*.
    LP : float
        Low-pass cutoff frequency in Hz.

    Returns
    -------
    t_out : numpy.ndarray
        Downsampled time vector.
    d_out : numpy.ndarray
        Downsampled (and filtered) data matrix.

    Raises
    ------
    ValueError
        If *t_in* and *d_in* have incompatible shapes, or *LP* is not
        positive.
    """
    from scipy.signal import cheby1, filtfilt

    t_in = np.asarray(t_in, dtype=float)
    d_in = np.asarray(d_in, dtype=float)

    if t_in.ndim != 1:
        raise ValueError("t_in must be a 1-D array.")
    if d_in.ndim == 1:
        d_in = d_in[:, np.newaxis]
    if d_in.shape[0] != t_in.shape[0]:
        raise ValueError(
            "The number of rows in d_in must equal the length of t_in."
        )
    if LP <= 0:
        raise ValueError("LP must be positive.")

    dt = np.median(np.diff(t_in))
    fs = 1.0 / dt

    if fs > 2 * LP:
        b, a = cheby1(4, 0.8, LP / (fs / 2), btype="low")
        d_filtered = filtfilt(b, a, d_in, axis=0)

        t_out = np.arange(t_in[0], t_in[-1] + 1e-12, 1.0 / (2 * LP))
        d_out = np.empty((len(t_out), d_filtered.shape[1]))
        for ch in range(d_filtered.shape[1]):
            d_out[:, ch] = np.interp(t_out, t_in, d_filtered[:, ch])
    else:
        warnings.warn(
            "Sampling frequency is not greater than twice the low-pass "
            "frequency. No downsampling or filtering performed.",
            stacklevel=2,
        )
        t_out = t_in.copy()
        d_out = d_in.copy()

    return t_out, d_out
