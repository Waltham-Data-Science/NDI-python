"""
ndi.validators.mustBeID

MATLAB equivalent: +ndi/+validators/mustBeID.m

Validates that a string is a correctly formatted NDI ID (33 characters,
underscore at position 17, all other characters alphanumeric).
"""

from __future__ import annotations

import re

_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{16}_[A-Za-z0-9]{16}$")


def mustBeID(inputArg: str) -> None:
    """Validate that *inputArg* is a correctly formatted NDI ID.

    MATLAB equivalent: ``ndi.validators.mustBeID(inputArg)``

    Format: exactly 33 characters — 16 alphanumeric, an underscore, then
    16 more alphanumeric characters.

    Parameters
    ----------
    inputArg : str
        The string to validate.

    Raises
    ------
    TypeError
        If *inputArg* is not a string.
    ValueError
        If the format is incorrect.
    """
    if not isinstance(inputArg, str):
        raise TypeError("Input must be a string.")

    if len(inputArg) != 33:
        raise ValueError(
            f"Input must be exactly 33 characters long " f"(actual length was {len(inputArg)})."
        )

    if inputArg[16] != "_":
        raise ValueError(f"Character 17 must be an underscore (_), " f"but found {inputArg[16]!r}.")

    if not _ID_PATTERN.match(inputArg):
        # Find first invalid character for a helpful message.
        for i, ch in enumerate(inputArg):
            if i == 16:
                continue
            if not ch.isalnum():
                raise ValueError(
                    f"Characters 1-16 and 18-33 must be alphanumeric. "
                    f"Found invalid character {ch!r} at position {i + 1}."
                )
