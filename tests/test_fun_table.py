"""``ndi.fun.table`` against ``+ndi/+fun/+table/``.

These five functions decide WHICH ROWS a caller gets back, so a porting slip
here does not raise -- it returns a different set of rows and everything
downstream believes it. Three of them did exactly that.

* ``identifyValidRows(df, cols, NaN)`` returned every row as valid. ``NaN``
  never equals itself, so ``df[col] != nan`` is True even on the NaN rows --
  the exact opposite of what was asked, and ``{NaN}`` is MATLAB's DEFAULT
  ``invalidValues``, so it is the value a caller is most likely to pass.
* ``identifyMatchingRows`` chose string-vs-numeric matching from the COLUMN's
  dtype, where MATLAB chooses from the MATCH VALUE's type. Against an
  object-dtype column of numbers -- which pandas produces routinely from
  mixed data -- ``numericMatch='gt'`` returned the rows EQUAL to the
  threshold instead of those above it.
* ``identifyMatchingRows`` raised ``ValueError: Lengths must match`` on the
  multi-value form MATLAB's own help documents,
  ``identifyMatchingRows(T, 'col', {{'a','b','c'}})``.

TWO TESTS BELOW WERE RELOCATED, not written from scratch:
``test_identifyMatchingRows_string_contains`` and
``test_identifyMatchingRows_numeric`` come from
``tests/matlab_tests/test_jess_haley.py``, where a module-level
``pytestmark = pytest.mark.skipif(not JESS_HALEY_DOCS.exists(), ...)`` skipped
all 47 tests in the file. These two need no dataset -- they build their own
two-column DataFrame -- so the skip hid them for no reason, and they would
have FAILED if run: both pass ``string_match=`` / ``numeric_match=``, and the
function accepted only ``stringMatch`` / ``numericMatch``. A module-level
skip that covers tests which do not need what it is guarding is the same
shape as the bridge guard's own complaint about skips.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from ndi.fun.table import (  # noqa: E402
    identifyMatchingRows,
    identifyValidRows,
    join,
    moveColumnsLeft,
    vstack,
)


class TestIdentifyValidRows:
    """MATLAB counterpart: ``+ndi/+fun/+table/identifyValidRows.m``."""

    @staticmethod
    def _frame():
        return pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": ["x", "y", None]})

    def test_an_explicit_nan_sentinel_marks_the_nan_rows_invalid(self):
        """The regression. MATLAB gives NaN its own branch
        (``isnumeric(v) && isnan(v)``) precisely because ``==``/``~=`` cannot
        express it; comparing with ``!=`` returned every row valid."""
        assert list(identifyValidRows(self._frame(), ["a"], float("nan"))) == [
            True,
            False,
            True,
        ]

    def test_a_none_sentinel_falls_back_to_notna(self):
        assert list(identifyValidRows(self._frame(), ["a"])) == [True, False, True]

    def test_an_ordinary_sentinel_still_compares_by_equality(self):
        """MATLAB's final else: ``currentVariable == currentInvalidValue``."""
        assert list(identifyValidRows(self._frame(), ["a"], 1.0)) == [False, True, True]

    def test_a_missing_column_warns_rather_than_vanishing(self):
        """MATLAB raises identifyValidRows:InvalidVariableName and skips."""
        with pytest.warns(UserWarning, match="not found"):
            mask = identifyValidRows(self._frame(), ["nope"])
        assert list(mask) == [True, True, True]

    def test_several_columns_are_combined_with_and(self):
        assert list(identifyValidRows(self._frame(), ["a", "b"])) == [True, False, False]


class TestIdentifyMatchingRows:
    """MATLAB counterpart: ``+ndi/+fun/+table/identifyMatchingRows.m``."""

    @staticmethod
    def _frame():
        return pd.DataFrame({"c": ["a", "b", "c"], "n": [1, 2, 3]})

    def test_the_mode_follows_the_match_value_not_the_column_dtype(self):
        """The silent one. MATLAB branches on ``isnumeric(matchVal)``; this
        had branched on the column's dtype, so an object-dtype column of
        numbers took the STRING path and ``gt`` behaved like equality."""
        frame = pd.DataFrame({"v": pd.Series([1, 2, 3], dtype=object)})
        assert list(identifyMatchingRows(frame, "v", 2, numericMatch="gt")) == [
            False,
            False,
            True,
        ]

    def test_a_numeric_column_is_unaffected(self):
        assert list(identifyMatchingRows(self._frame(), "n", 2, numericMatch="gt")) == [
            False,
            False,
            True,
        ]

    def test_several_match_values_for_one_column_are_ored(self):
        """MATLAB's help spells this
        ``identifyMatchingRows(dataTable, 'column1', {{'a','b','c'}})``;
        it raised "Lengths must match to compare"."""
        assert list(identifyMatchingRows(self._frame(), "c", ["a", "b"])) == [
            True,
            True,
            False,
        ]

    def test_a_missing_column_warns_and_matches_nothing(self):
        """MATLAB warns identifyMatchingRows:ColumnNotFound and sets the whole
        index false -- "no rows can match based on this criterion". Indexing
        the frame raised KeyError instead."""
        with pytest.warns(UserWarning, match="not found"):
            mask = identifyMatchingRows(self._frame(), "nope", "x")
        assert list(mask) == [False, False, False]

    def test_several_columns_are_combined_with_and(self):
        mask = identifyMatchingRows(self._frame(), ["c", "n"], ["a", 1])
        assert list(mask) == [True, False, False]

    @pytest.mark.parametrize(
        "mode, expected",
        [
            ("eq", [False, True, False]),
            ("ne", [True, False, True]),
            ("lt", [True, False, False]),
            ("le", [True, True, False]),
            ("gt", [False, False, True]),
            ("ge", [False, True, True]),
        ],
    )
    def test_every_numeric_mode_matlab_allows(self, mode, expected):
        assert list(identifyMatchingRows(self._frame(), "n", 2, numericMatch=mode)) == expected

    def test_ignorecase_and_contains(self):
        frame = pd.DataFrame({"name": ["apple", "banana", "APPLE pie"]})
        assert identifyMatchingRows(frame, "name", "APPLE", stringMatch="ignoreCase").sum() == 1
        assert identifyMatchingRows(frame, "name", "apple", stringMatch="contains").sum() == 1

    def test_contains_is_case_sensitive(self):
        """MATLAB passes ``'IgnoreCase', false`` explicitly."""
        frame = pd.DataFrame({"name": ["apple", "APPLE pie"]})
        assert identifyMatchingRows(frame, "name", "apple", stringMatch="contains").sum() == 1


class TestRelocatedFromJessHaley:
    """Moved out from under a module-level dataset skip; see this module's
    docstring. Neither needs the dataset, and both used the snake_case
    option names the function did not accept."""

    def test_identifyMatchingRows_string_contains(self):
        """String 'contains' matching works on DataFrame."""
        df = pd.DataFrame({"name": ["apple", "banana", "cherry", "APPLE pie"]})
        mask = identifyMatchingRows(df, "name", "apple", string_match="contains")
        assert mask.sum() == 1  # case-sensitive: only 'apple'

    def test_identifyMatchingRows_numeric(self):
        """Numeric comparison matching."""
        df = pd.DataFrame({"value": [10, 20, 30, 40]})
        mask = identifyMatchingRows(df, "value", 25, numeric_match="gt")
        assert mask.sum() == 2  # 30 and 40


class TestMoveColumnsLeft:
    """MATLAB counterpart: ``+ndi/+fun/+table/moveColumnsLeft.m``."""

    def test_named_columns_move_to_the_front_in_order(self):
        frame = pd.DataFrame({"a": [1], "b": [2], "c": [3], "d": [4]})
        assert list(moveColumnsLeft(frame, ["c", "a"]).columns) == ["c", "a", "b", "d"]

    def test_the_relative_order_of_the_rest_is_kept(self):
        frame = pd.DataFrame({"a": [1], "b": [2], "c": [3], "d": [4]})
        assert list(moveColumnsLeft(frame, ["d"]).columns) == ["d", "a", "b", "c"]

    def test_an_unknown_column_is_ignored(self):
        """MATLAB's movevars would error; this filters it out. Recorded on
        the bridge entry rather than changed."""
        frame = pd.DataFrame({"a": [1], "b": [2]})
        assert list(moveColumnsLeft(frame, ["b", "nope"]).columns) == ["b", "a"]


class TestJoinAndVstack:
    """MATLAB counterparts: ``join.m``, ``vstack.m``."""

    def test_common_columns_are_the_join_keys(self):
        left = pd.DataFrame({"id": [1, 2], "x": ["a", "b"]})
        right = pd.DataFrame({"id": [2, 3], "y": ["p", "q"]})
        out = join([left, right])
        assert list(out["id"]) == [2]
        assert list(out["y"]) == ["p"]

    def test_a_single_table_comes_back_unchanged(self):
        frame = pd.DataFrame({"id": [1, 2]})
        assert list(join([frame])["id"]) == [1, 2]

    def test_vstack_takes_the_union_of_columns(self):
        t1 = pd.DataFrame({"ID": [1, 2], "Data": ["a", "b"]})
        t2 = pd.DataFrame({"ID": [3, 4], "Value": [10.5, 20.6]})
        out = vstack([t1, t2])
        assert list(out.columns) == ["ID", "Data", "Value"]
        assert len(out) == 4

    def test_vstack_fills_missing_columns(self):
        t1 = pd.DataFrame({"a": [1]})
        t2 = pd.DataFrame({"b": [2]})
        out = vstack([t1, t2])
        assert pd.isna(out.loc[0, "b"])
        assert pd.isna(out.loc[1, "a"])


def test_no_stray_warnings_on_the_ordinary_paths():
    """The two new warnings must fire only on a genuinely missing column."""
    frame = pd.DataFrame({"a": [1.0, 2.0]})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        identifyValidRows(frame, ["a"])
        identifyMatchingRows(frame, "a", 1.0)
