"""
ndi.validators.is_iso8601

MATLAB equivalent: +ndi/+validators/ (custom; mirrors the ``arguments``
block format check in ``datestamp2datetime.m``)

Validates that a string is a parseable ISO 8601 datestamp.
"""

from __future__ import annotations

from datetime import datetime


def is_iso8601(val: object) -> str:
    """Validate that *val* is a parseable ISO 8601 datestamp string.

    MATLAB equivalent: format validation in the ``arguments`` block of
    ``ndi.util.datestamp2datetime`` (input format
    ``'yyyy-MM-dd''T''HH:mm:ss.SSSXXX'``).

    Parameters
    ----------
    val : object
        The value to check.

    Returns
    -------
    str
        The validated string (unchanged).

    Raises
    ------
    ValueError
        If *val* is not a string or cannot be parsed as ISO 8601.
    """
    if not isinstance(val, str):
        raise ValueError("Input must be a string.")
    try:
        datetime.fromisoformat(val)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"String is not valid ISO 8601: {val!r}") from exc
    return val
