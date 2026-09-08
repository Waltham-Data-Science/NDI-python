"""
ndi.fun.table - Table manipulation utilities.

MATLAB equivalents: +ndi/+fun/+table/identifyMatchingRows.m,
                    identifyValidRows.m, join.m, moveColumnsLeft.m, vstack.m

Provides pandas-DataFrame utilities for combining, filtering,
and reshaping tabular data produced by NDI document conversions.
"""

from __future__ import annotations

import warnings
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


def identifyMatchingRows(
    df: pd.DataFrame,
    column: str | list[str],
    value: Any,
    match_mode: str | None = None,
    *,
    stringMatch: str = "identical",
    numericMatch: str = "eq",
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
        stringMatch: String match mode:
            ``'identical'``, ``'ignoreCase'``, ``'contains'``.
        numericMatch: Numeric match mode:
            ``'eq'``, ``'ne'``, ``'lt'``, ``'le'``, ``'gt'``, ``'ge'``.

    Returns:
        Boolean Series indicating matching rows.
    """
    _require_pandas()

    # Snake-case spellings of the two options, per this project's
    # cross-language naming convention. tests/matlab_tests/test_jess_haley.py
    # already calls them this way.
    if string_match is not None:
        stringMatch = string_match
    if numeric_match is not None:
        numericMatch = numeric_match

    # Allow passing match mode as positional argument
    if match_mode is not None:
        _string_modes = {"identical", "ignorecase", "contains"}
        _numeric_modes = {"eq", "ne", "lt", "le", "gt", "ge"}
        if match_mode.lower() in _string_modes:
            stringMatch = match_mode
        elif match_mode.lower() in _numeric_modes:
            numericMatch = match_mode

    # Normalize to lists for multi-column support
    if isinstance(column, str):
        columns = [column]
        values = [value]
    else:
        columns = list(column)
        values = list(value) if isinstance(value, (list, tuple)) else [value] * len(columns)

    mask = pd.Series(True, index=df.index)

    for col_name, val in zip(columns, values):
        if col_name not in df.columns:
            # MATLAB warns identifyMatchingRows:ColumnNotFound and sets the
            # whole index false -- "no rows can match based on this
            # criterion". Indexing df here raised KeyError instead.
            warnings.warn(
                f'Column "{col_name}" not found in the table. Skipping this '
                "column for matching.",
                stacklevel=2,
            )
            return pd.Series(False, index=df.index)

        col = df[col_name]

        # MATLAB ORs the alternatives for one column, which is how its own
        # help spells a multi-value match:
        #     identifyMatchingRows(dataTable, 'column1', {{'a','b','c'}})
        # Comparing a Series against the list raised "Lengths must match".
        alternatives = list(val) if isinstance(val, (list, tuple, set)) else [val]

        col_match = pd.Series(False, index=df.index)
        for one in alternatives:
            col_match = col_match | _match_one(col, one, stringMatch, numericMatch)

        mask = mask & col_match

    return mask


def _match_one(col: pd.Series, val: Any, stringMatch: str, numericMatch: str) -> pd.Series:
    """One column against one match value.

    THE MODE IS CHOSEN BY THE MATCH VALUE'S TYPE, not the column's dtype.
    That is what MATLAB does -- it branches on ``ischar(matchVal) ||
    isstring(matchVal)`` and ``isnumeric(matchVal) || isdatetime(matchVal)``,
    never on the column. Choosing by dtype instead silently used the STRING
    mode for a numeric match against an object-dtype column, which pandas
    produces routinely from mixed data: asking for ``numericMatch='gt'``
    against 2 returned the rows equal to 2 rather than those above it. No
    error, just the wrong rows.
    """
    if isinstance(val, str):
        mode = stringMatch.lower()
        if mode == "ignorecase":
            return col.astype(str).str.lower() == val.lower()
        if mode == "contains":
            return col.astype(str).str.contains(val, case=True, na=False, regex=False)
        return col.astype(str) == val

    if isinstance(val, bool) or not isinstance(val, (int, float, complex, pd.Timestamp)):
        # MATLAB's final else: exact equality for logicals, categoricals and
        # anything else it does not recognise.
        return col == val

    mode = numericMatch.lower()
    numeric = pd.to_numeric(col, errors="coerce") if col.dtype == object else col
    if mode == "ne":
        return numeric != val
    if mode == "lt":
        return numeric < val
    if mode == "le":
        return numeric <= val
    if mode == "gt":
        return numeric > val
    if mode == "ge":
        return numeric >= val
    if mode == "eq":
        return numeric == val
    raise ValueError(f"Unknown numeric match mode: '{mode}'")


def _is_nan_sentinel(value: Any) -> bool:
    """Is *value* the NaN/NaT sentinel, which cannot be compared with ``!=``?

    MATLAB tests ``isnumeric(v) && isnan(v)`` and ``isdatetime(v) && isnat(v)``
    in two dedicated branches for the same reason.
    """
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def identifyValidRows(
    df: pd.DataFrame,
    checkVariables: list[str] | None = None,
    invalidValues: Any = None,
    *,
    columns: list[str] | None = None,
) -> pd.Series:
    """Identify rows where specified columns have valid (non-NaN) values.

    MATLAB equivalent: ndi.fun.table.identifyValidRows

    Args:
        df: Input DataFrame.
        checkVariables: Columns to check.  If *None*, check all columns.
        invalidValues: Custom invalid sentinel (default: NaN/NaT/None).

    Returns:
        Boolean Series — True for valid rows.
    """
    _require_pandas()

    # Support 'columns' as alias for 'checkVariables'
    if columns is not None and checkVariables is None:
        checkVariables = columns
    cols = checkVariables if checkVariables is not None else list(df.columns)

    mask = pd.Series(True, index=df.index)
    for col in cols:
        if col not in df.columns:
            # MATLAB warns identifyValidRows:InvalidVariableName here and
            # skips; say so rather than dropping the name in silence.
            warnings.warn(
                f'Variable "{col}" provided in checkVariables not found in the '
                "table. Skipping check.",
                stacklevel=2,
            )
            continue
        if invalidValues is None:
            mask = mask & df[col].notna()
        elif _is_nan_sentinel(invalidValues):
            # NaN never equals itself, so `df[col] != nan` is True even on the
            # NaN rows and every row came back valid -- the exact opposite of
            # what was asked. MATLAB special-cases this branch for the same
            # reason, and {NaN} is its DEFAULT invalidValues, so it is the
            # value a caller is most likely to pass explicitly.
            mask = mask & df[col].notna()
        else:
            mask = mask & (df[col] != invalidValues)

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
                .agg(dict.fromkeys(other_cols, _agg))
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


def moveColumnsLeft(
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


# Backward-compatible aliases
identify_matching_rows = identifyMatchingRows
identify_valid_rows = identifyValidRows
move_columns_left = moveColumnsLeft
