"""
ndi.validators - Custom validation functions for NDI.

MATLAB equivalent: +ndi/+validators/

Provides validation functions that mirror MATLAB's custom validators used
in ``arguments`` blocks.  In Python these are typically called explicitly
or via ``@pydantic.validate_call``.
"""

from .mustBeCellArrayOfClass import mustBeCellArrayOfClass
from .mustBeCellArrayOfNdiSessions import mustBeCellArrayOfNdiSessions
from .mustBeCellArrayOfNonEmptyCharacterArrays import (
    mustBeCellArrayOfNonEmptyCharacterArrays,
)
from .mustBeClassnameOfType import mustBeClassnameOfType
from .mustBeEpochInput import mustBeEpochInput
from .mustBeID import mustBeID
from .mustBeNumericClass import mustBeNumericClass
from .mustBeTextLike import mustBeTextLike
from .mustHaveFields import mustHaveFields
from .mustHaveRequiredColumns import mustHaveRequiredColumns
from .mustMatchRegex import mustMatchRegex

__all__ = [
    "mustBeCellArrayOfClass",
    "mustBeCellArrayOfNdiSessions",
    "mustBeCellArrayOfNonEmptyCharacterArrays",
    "mustBeClassnameOfType",
    "mustBeEpochInput",
    "mustBeID",
    "mustBeNumericClass",
    "mustBeTextLike",
    "mustHaveFields",
    "mustHaveRequiredColumns",
    "mustMatchRegex",
]
