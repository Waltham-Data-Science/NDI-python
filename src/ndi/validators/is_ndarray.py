"""
ndi.validators.is_ndarray

MATLAB equivalent: +ndi/+validators/ (custom; mirrors ``mustBeA(val, 'numeric')``)

Validates that an input is a numpy ndarray.
"""

from __future__ import annotations

import numpy as np


def is_ndarray(val: object) -> np.ndarray:
    """Validate that *val* is a :class:`numpy.ndarray`.

    MATLAB equivalent: type checking inside ``arguments`` blocks
    (e.g. ``mustBeA(val, 'numeric')``).

    Parameters
    ----------
    val : object
        The value to check.

    Returns
    -------
    numpy.ndarray
        The validated array (unchanged).

    Raises
    ------
    ValueError
        If *val* is not a ``numpy.ndarray``.
    """
    if not isinstance(val, np.ndarray):
        raise ValueError("Input must be a numpy.ndarray")
    return val
