"""
ndi.validators.mustHaveFields

MATLAB equivalent: +ndi/+validators/mustHaveFields.m

Validates that a dict (MATLAB struct) has all required keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def mustHaveFields(s: dict, fields: Sequence[str]) -> None:
    """Validate that dict *s* contains all *fields*.

    MATLAB equivalent: ``ndi.validators.mustHaveFields(s, fields)``

    Parameters
    ----------
    s : dict
        The dictionary to check.
    fields : list of str
        Required key names.

    Raises
    ------
    TypeError
        If *s* is not a dict.
    ValueError
        If any required keys are missing.
    """
    if not isinstance(s, dict):
        raise TypeError("First argument must be a dict.")
    missing = [f for f in fields if f not in s]
    if missing:
        raise ValueError(f"Dict is missing fields: {', '.join(missing)}")
