"""
ndi.validators.mustBeCellArrayOfNdiSessions

MATLAB equivalent: +ndi/+validators/mustBeCellArrayOfNdiSessions.m

Validates that the input is a list of ``ndi.session.ndi_session_dir`` objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def mustBeCellArrayOfNdiSessions(value: Sequence) -> None:
    """Validate that every element is an ``ndi.session.ndi_session_dir``.

    MATLAB equivalent: ``ndi.validators.mustBeCellArrayOfNdiSessions(value)``

    Parameters
    ----------
    value : list or tuple
        The collection to validate.

    Raises
    ------
    TypeError
        If *value* is not a list/tuple, or any element is not a
        ``ndi_session_dir``.
    """
    # Import lazily to avoid circular imports.
    from ndi.session import ndi_session_dir

    if not isinstance(value, (list, tuple)):
        raise TypeError("Input must be a list or tuple.")

    for i, item in enumerate(value):
        if not isinstance(item, ndi_session_dir):
            raise TypeError(
                f"All elements must be ndi.session.ndi_session_dir objects. "
                f"ndi_element {i} is of class {type(item).__name__!r}."
            )
