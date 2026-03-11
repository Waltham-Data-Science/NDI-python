"""
ndi.validators.mustBeCellArrayOfNonEmptyCharacterArrays

MATLAB equivalent: +ndi/+validators/mustBeCellArrayOfNonEmptyCharacterArrays.m

Validates that the input is a list of non-empty strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def mustBeCellArrayOfNonEmptyCharacterArrays(value: Sequence) -> None:
    """Validate that every element is a non-empty string.

    MATLAB equivalent:
    ``ndi.validators.mustBeCellArrayOfNonEmptyCharacterArrays(value)``

    Parameters
    ----------
    value : list or tuple
        The collection to validate.

    Raises
    ------
    TypeError
        If *value* is not a list/tuple or any element is not a string.
    ValueError
        If any element is an empty string.
    """
    if not isinstance(value, (list, tuple)):
        raise TypeError("Input must be a list or tuple.")

    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(
                f"All elements must be non-empty strings. "
                f"Element {i} is of type {type(item).__name__!r}."
            )
        if not item:
            raise ValueError(
                f"All elements must be non-empty strings. Element {i} is empty."
            )
