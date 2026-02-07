"""
ndi.fun.table - Table manipulation utilities.

MATLAB equivalents: +ndi/+fun/+table/identifyMatchingRows.m,
                    identifyValidRows.m, join.m, moveColumnsLeft.m, vstack.m

Provides pandas-DataFrame utilities for combining, filtering,
and reshaping tabular data produced by NDI document conversions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


def _require_pandas() -> None:
    if pd is None:
        raise ImportError(
            'pandas is required for ndi.fun.table utilities. '
            'Install it with: pip install pandas'
        )


def identify_matching_rows(
    df: 'pd.DataFrame',
    column: str,
    value: Any,
    mode: str = 'identical',
) -> 'pd.Series':
    """Identify rows in a DataFrame matching the given criteria.

    MATLAB equivalent: ndi.fun.table.identifyMatchingRows

    Args:
        df: Input DataFrame.
        column: Column name to match against.
        value: Value to match.
        mode: Match mode — ``'identical'``, ``'ignoreCase'``,
            ``'contains'``, ``'eq'``, ``'ne'``, ``'lt'``,
            ``'le'``, ``'gt'``, ``'ge'``.

    Returns:
        Boolean Series indicating matching rows.
    """
    _require_pandas()

    col = df[column]
    mode_lower = mode.lower()

    if mode_lower == 'identical':
        return col == value
    elif mode_lower == 'ignorecase':
        return col.astype(str).str.lower() == str(value).lower()
    elif mode_lower == 'contains':
        return col.astype(str).str.contains(str(value), case=False, na=False)
    elif mode_lower == 'eq':
        return col == value
    elif mode_lower == 'ne':
        return col != value
    elif mode_lower == 'lt':
        return col < value
    elif mode_lower == 'le':
        return col <= value
    elif mode_lower == 'gt':
        return col > value
    elif mode_lower == 'ge':
        return col >= value
    else:
        raise ValueError(f"Unknown match mode: '{mode}'")


def identify_valid_rows(
    df: 'pd.DataFrame',
    columns: Optional[List[str]] = None,
    invalid_value: Any = None,
) -> 'pd.Series':
    """Identify rows where specified columns have valid (non-NaN) values.

    MATLAB equivalent: ndi.fun.table.identifyValidRows

    Args:
        df: Input DataFrame.
        columns: Columns to check.  If *None*, check all columns.
        invalid_value: Custom invalid sentinel (default: NaN/NaT/None).

    Returns:
        Boolean Series — True for valid rows.
    """
    _require_pandas()

    if columns is None:
        columns = list(df.columns)

    mask = pd.Series(True, index=df.index)
    for col in columns:
        if col not in df.columns:
            continue
        if invalid_value is not None:
            mask = mask & (df[col] != invalid_value)
        else:
            mask = mask & df[col].notna()

    return mask


def join_tables(
    tables: List['pd.DataFrame'],
    key_columns: Optional[List[str]] = None,
) -> 'pd.DataFrame':
    """Combine multiple DataFrames using common columns as keys.

    MATLAB equivalent: ndi.fun.table.join

    Performs an outer merge on common key columns.

    Args:
        tables: List of DataFrames.
        key_columns: Columns to join on.  If *None*, uses the
            intersection of all column names.

    Returns:
        Merged DataFrame.
    """
    _require_pandas()

    if not tables:
        return pd.DataFrame()

    result = tables[0]
    if key_columns is None:
        common = set(result.columns)
        for t in tables[1:]:
            common &= set(t.columns)
        key_columns = sorted(common) if common else None

    for t in tables[1:]:
        if key_columns:
            result = result.merge(t, on=key_columns, how='outer')
        else:
            result = pd.concat([result, t], ignore_index=True)

    return result


def move_columns_left(
    df: 'pd.DataFrame',
    columns: List[str],
) -> 'pd.DataFrame':
    """Move specified columns to the left of the DataFrame.

    MATLAB equivalent: ndi.fun.table.moveColumnsLeft

    Args:
        df: Input DataFrame.
        columns: Column names to move to the front.

    Returns:
        DataFrame with reordered columns.
    """
    _require_pandas()

    existing = [c for c in columns if c in df.columns]
    rest = [c for c in df.columns if c not in existing]
    return df[existing + rest]


def vstack(
    tables: List['pd.DataFrame'],
) -> 'pd.DataFrame':
    """Vertically stack DataFrames with dissimilar columns.

    MATLAB equivalent: ndi.fun.table.vstack

    Discovers the union of all column names and fills missing
    columns with NaN/None as appropriate before concatenating.

    Args:
        tables: List of DataFrames.

    Returns:
        Vertically stacked DataFrame.
    """
    _require_pandas()

    if not tables:
        return pd.DataFrame()

    return pd.concat(tables, ignore_index=True, sort=False)
