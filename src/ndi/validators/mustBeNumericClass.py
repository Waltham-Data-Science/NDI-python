"""
ndi.validators.mustBeNumericClass

MATLAB equivalent: +ndi/+validators/mustBeNumericClass.m

Validates that a string names a valid numeric (or logical) dtype.
"""

from __future__ import annotations

_VALID_CLASSES = frozenset(
    {
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "int8",
        "int16",
        "int32",
        "int64",
        "single",
        "double",
        "logical",
        # Python/NumPy equivalents accepted as well:
        "float32",
        "float64",
        "bool",
    }
)


def mustBeNumericClass(className: str) -> None:
    """Validate that *className* is a recognised numeric or logical class.

    MATLAB equivalent: ``ndi.validators.mustBeNumericClass(className)``

    Accepts MATLAB names (``"double"``, ``"single"``, ``"logical"``, etc.)
    as well as NumPy equivalents (``"float64"``, ``"float32"``, ``"bool"``).

    Parameters
    ----------
    className : str
        The class name to validate.

    Raises
    ------
    TypeError
        If *className* is not a string.
    ValueError
        If *className* is not one of the recognised numeric/logical types.
    """
    if not isinstance(className, str):
        raise TypeError("Input must be a string.")

    if className not in _VALID_CLASSES:
        raise ValueError(
            f"Value must be a valid numeric or logical class name. "
            f"Must be one of: {', '.join(sorted(_VALID_CLASSES))}."
        )
