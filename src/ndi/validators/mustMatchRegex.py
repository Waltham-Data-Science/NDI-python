"""
ndi.validators.mustMatchRegex

MATLAB equivalent: +ndi/+validators/mustMatchRegex.m

Validates that a string fully matches a regular expression pattern.
"""

from __future__ import annotations

import re


def mustMatchRegex(value: str, pattern: str) -> None:
    """Validate that *value* fully matches *pattern*.

    MATLAB equivalent: ``ndi.validators.mustMatchRegex(value, pattern)``

    The pattern is anchored (must match the entire string).

    Parameters
    ----------
    value : str
        The string to validate.
    pattern : str
        The regular expression pattern.

    Raises
    ------
    TypeError
        If *value* or *pattern* is not a string.
    ValueError
        If *value* does not match *pattern*.
    """
    if not isinstance(value, str):
        raise TypeError("Input value must be a string.")
    if not isinstance(pattern, str):
        raise TypeError("Pattern must be a string.")

    if not re.fullmatch(pattern, value):
        raise ValueError(f'Value "{value}" does not match the required pattern: "{pattern}".')
