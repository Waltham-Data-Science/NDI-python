"""
ndi.validators.mustBeID

MATLAB equivalent: +ndi/+validators/mustBeID.m

Validates that a string is a correctly formatted NDI ID (33 characters,
underscore at position 17, all other characters alphanumeric).
"""

from __future__ import annotations

import re
import string

_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{16}_[A-Za-z0-9]{16}$")

#: The same ASCII rule :data:`_ID_PATTERN` enforces, per character.
#:
#: Reporting WHICH character is at fault must use this and not
#: ``str.isalnum()``. ``str.isalnum()`` is Unicode-aware -- it is true for
#: ``"e"``-acute, for Arabic-Indic digits, and even for ``"1/2"`` -- so a
#: string the pattern had just rejected could yield no character to blame,
#: the loop would end, and the function would return None. That silently
#: ACCEPTED the malformed ID.
_ASCII_ALNUM = frozenset(string.ascii_letters + string.digits)


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
        # Name the first offending character, the way MATLAB does. The test
        # is _ASCII_ALNUM rather than str.isalnum() so that this branch can
        # never fail to find one and fall through -- see _ASCII_ALNUM.
        for i, ch in enumerate(inputArg):
            if i == 16 or ch in _ASCII_ALNUM:
                continue
            raise ValueError(
                f"Characters 1-16 and 18-33 must be alphanumeric (A-Z, a-z, 0-9). "
                f"Found invalid character {ch!r} at position {i + 1}."
            )
        raise ValueError(  # pragma: no cover -- unreachable, see above
            f"Input {inputArg!r} is not a valid NDI ID."
        )
