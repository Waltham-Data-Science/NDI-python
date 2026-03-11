"""
ndi.validators.mustHaveRequiredColumns

MATLAB equivalent: +ndi/+validators/mustHaveRequiredColumns.m

Validates that a pandas DataFrame contains the specified columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def mustHaveRequiredColumns(
    t: pd.DataFrame,
    requiredCols: str | list[str],
) -> None:
    """Validate that DataFrame *t* has all *requiredCols*.

    MATLAB equivalent:
    ``ndi.validators.mustHaveRequiredColumns(t, requiredCols)``

    Parameters
    ----------
    t : pandas.DataFrame
        The table to check.
    requiredCols : str or list of str
        Required column name(s).

    Raises
    ------
    TypeError
        If *t* is not a DataFrame.
    ValueError
        If any required columns are missing.
    """
    import pandas as pd

    if not isinstance(t, pd.DataFrame):
        raise TypeError("First argument must be a pandas DataFrame.")

    if isinstance(requiredCols, str):
        requiredCols = [requiredCols]

    actual = set(t.columns)
    missing = [c for c in requiredCols if c not in actual]
    if missing:
        raise ValueError(
            f"Input table is missing required column(s): {', '.join(missing)}"
        )
