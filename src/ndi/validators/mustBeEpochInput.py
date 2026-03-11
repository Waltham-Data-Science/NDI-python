"""
ndi.validators.mustBeEpochInput

MATLAB equivalent: +ndi/+validators/mustBeEpochInput.m

Determines whether an input can describe an epoch (string or positive
integer scalar).
"""

from __future__ import annotations


def mustBeEpochInput(v: str | int) -> None:
    """Validate that *v* is a valid epoch identifier.

    MATLAB equivalent: ``ndi.validators.mustBeEpochInput(v)``

    A valid epoch input is either a non-empty string or a positive integer.

    Parameters
    ----------
    v : str or int
        The value to validate.

    Raises
    ------
    TypeError
        If *v* is not a string or integer.
    ValueError
        If *v* is an integer that is not positive, or an empty string.
    """
    if isinstance(v, str):
        if not v:
            raise ValueError("Epoch input string must not be empty.")
        return

    if isinstance(v, (int,)) and not isinstance(v, bool):
        if v < 1:
            raise ValueError("Epoch input integer must be positive.")
        return

    raise TypeError(
        "Value must be a string or positive integer scalar."
    )
