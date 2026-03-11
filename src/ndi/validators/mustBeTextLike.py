"""
ndi.validators.mustBeTextLike

MATLAB equivalent: +ndi/+validators/mustBeTextLike.m

Validates that input is a string, or a list of strings.
"""

from __future__ import annotations


def mustBeTextLike(value: str | list | tuple) -> None:
    """Validate that *value* is text-like.

    MATLAB equivalent: ``ndi.validators.mustBeTextLike(value)``

    Accepted forms:

    * A ``str``
    * A ``list`` or ``tuple`` where every element is a ``str``

    Parameters
    ----------
    value : str, list, or tuple
        The value to validate.

    Raises
    ------
    TypeError
        If *value* is not a string, or a list/tuple of strings.
    """
    if isinstance(value, str):
        return

    if isinstance(value, (list, tuple)):
        if all(isinstance(item, str) for item in value):
            return

    raise TypeError("Input must be a string, or a list/tuple of strings.")
