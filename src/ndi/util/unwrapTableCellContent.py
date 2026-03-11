"""
ndi.util.unwrapTableCellContent

MATLAB equivalent: +ndi/+util/unwrapTableCellContent.m

Recursively unwraps nested lists (MATLAB cell arrays) to retrieve the
core value.
"""

from __future__ import annotations

from typing import Any

import pydantic
from pydantic import ConfigDict


@pydantic.validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def unwrapTableCellContent(cellValue: Any) -> Any:
    """Recursively unwrap nested lists to retrieve the innermost value.

    MATLAB equivalent:
    ``unwrappedValue = ndi.util.unwrapTableCellContent(cellValue)``

    If the innermost value is ``None`` or an empty list, ``float('nan')``
    is returned (matching MATLAB's ``NaN`` for empty cells).

    Parameters
    ----------
    cellValue : any
        The value to unwrap.  In practice this is often a list (from
        MATLAB cell arrays) that may be nested.

    Returns
    -------
    any
        The unwrapped value, or ``float('nan')`` if the value is empty.
    """
    current = cellValue
    max_unwrap = 10

    for _ in range(max_unwrap):
        if not isinstance(current, list):
            break
        if len(current) == 0:
            return float("nan")
        current = current[0]

    if isinstance(current, list) and len(current) == 0:
        return float("nan")

    if current is None:
        return float("nan")

    return current
