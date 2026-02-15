"""
ndi.fun.table - Table manipulation utilities.

MATLAB equivalents: +ndi/+fun/+table/identifyMatchingRows.m,
                    identifyValidRows.m, join.m, moveColumnsLeft.m, vstack.m

Provides pandas-DataFrame utilities for combining, filtering,
and reshaping tabular data produced by NDI document conversions.
"""

from __future__ import annotations

from typing import Any

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


def _require_pandas() -> None:
    if pd is None:
        raise ImportError(
            "pandas is required for ndi.fun.table utilities. " "Install it with: pip install pandas"
        )


def identify_matching_rows(
    df: pd.DataFrame,
    column: str | list[str],
    value: Any,
    mode: str = "identical",
    *,
    string_match: str | None = None,
    numeric_match: str | None = None,
) -> pd.Series:
    """Identify rows in a DataFrame matching the given criteria.

    MATLAB equivalent: ndi.fun.table.identifyMatchingRows

    Args:
        df: Input DataFrame.
        column: Column name(s) to match against.
        value: Value(s) to match.  When *column* is a list, *value*
            should be a list of the same length.
        mode: Legacy match mode — ``'identical'``, ``'ignoreCase'``,
            ``'contains'``, ``'eq'``, ``'ne'``, ``'lt'``,
            ``'le'``, ``'gt'``, ``'ge'``.
        string_match: String match mode (overrides *mode* for text):
            ``'identical'``, ``'ignoreCase'``, ``'contains'``.
        numeric_match: Numeric match mode (overrides *mode* for numbers):
            ``'eq'``, ``'ne'``, ``'lt'``, ``'le'``, ``'gt'``, ``'ge'``.

    Returns:
        Boolean Series indicating matching rows.
    """
    _require_pandas()

    # Normalize to lists for multi-column support
    if isinstance(column, str):
        columns = [column]
        values = [value]
    else:
        columns = list(column)
        values = list(value) if isinstance(value, (list, tuple)) else [value] * len(columns)

    mask = pd.Series(True, index=df.index)

    for col_name, val in zip(columns, values):
        col = df[col_name]

        # Determine effective mode
        if string_match is not None and col.dtype == object:
            effective_mode = string_match.lower()
        elif numeric_match is not None and col.dtype != object:
            effective_mode = numeric_match.lower()
        else:
            effective_mode = mode.lower()

        if effective_mode == "identical":
            col_match = col == val
        elif effective_mode == "ignorecase":
            col_match = col.astype(str).str.lower() == str(val).lower()
        elif effective_mode == "contains":
            col_match = col.astype(str).str.contains(str(val), case=True, na=False)
        elif effective_mode == "eq":
            col_match = col == val
        elif effective_mode == "ne":
            col_match = col != val
        elif effective_mode == "lt":
            col_match = col < val
        elif effective_mode == "le":
            col_match = col <= val
        elif effective_mode == "gt":
            col_match = col > val
        elif effective_mode == "ge":
            col_match = col >= val
        else:
            raise ValueError(f"Unknown match mode: '{effective_mode}'")

        mask = mask & col_match

    return mask


def identify_valid_rows(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    invalid_value: Any = None,
) -> pd.Series:
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


def join(
    tables: list[pd.DataFrame],
    unique_variables: list[str] | None = None,
) -> pd.DataFrame:
    """Combine multiple DataFrames using common columns as keys.

    MATLAB equivalent: ndi.fun.table.join

    Performs an inner merge on common key columns. When
    *unique_variables* is given, duplicates are collapsed and
    non-key columns are aggregated into comma-separated strings.

    Args:
        tables: List of DataFrames.
        unique_variables: Column names for which only unique values
            should be kept per aggregated row.

    Returns:
        Merged DataFrame.
    """
    _require_pandas()

    if not tables:
        return pd.DataFrame()

    result = tables[0].copy()

    for t in tables[1:]:
        common = sorted(set(result.columns) & set(t.columns))
        if common:
            result = result.merge(t, on=common, how="inner")
        else:
            result = pd.concat([result, t], ignore_index=True)

    if unique_variables:
        other_cols = [c for c in result.columns if c not in unique_variables]
        if other_cols:

            def _agg(series: pd.Series) -> Any:
                vals = series.dropna().unique()
                if len(vals) == 0:
                    return ""
                if len(vals) == 1:
                    return vals[0]
                return ",".join(str(v) for v in vals)

            result = (
                result.groupby(unique_variables, sort=False)
                .agg({c: _agg for c in other_cols})
                .reset_index()
            )

    return result


def join_tables(
    tables: list[pd.DataFrame],
    key_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Combine multiple DataFrames using common columns as keys.

    .. deprecated:: Use :func:`join` instead.

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
            result = result.merge(t, on=key_columns, how="outer")
        else:
            result = pd.concat([result, t], ignore_index=True)

    return result


def move_columns_left(
    df: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
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
    tables: list[pd.DataFrame],
) -> pd.DataFrame:
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
