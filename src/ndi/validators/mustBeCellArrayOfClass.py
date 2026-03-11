"""
ndi.validators.mustBeCellArrayOfClass

MATLAB equivalent: +ndi/+validators/mustBeCellArrayOfClass.m

Validation function that checks if all elements of a list are of a certain class.
"""

from __future__ import annotations


def mustBeCellArrayOfClass(c: list | tuple, className: type) -> None:
    """Validate that all elements of a list are instances of *className*.

    MATLAB equivalent: ``ndi.validators.mustBeCellArrayOfClass(c, className)``

    In MATLAB, *className* is a string naming a class.  In Python it is
    the class object itself (e.g. ``ndi.session.DirSession``).

    Parameters
    ----------
    c : list or tuple
        The collection to validate.
    className : type
        The required type for every element.

    Raises
    ------
    TypeError
        If *c* is not a list/tuple or any element is not an instance of
        *className*.
    """
    if not isinstance(c, (list, tuple)):
        raise TypeError("Input must be a list or tuple.")
    for i, item in enumerate(c):
        if not isinstance(item, className):
            raise TypeError(
                f"All elements must be of class {className.__name__}. "
                f"Element {i} is of class {type(item).__name__}."
            )
