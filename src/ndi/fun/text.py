"""
ndi.fun.text - Parse text against a JSON file of regular-expression rules.

MATLAB equivalent: +ndi/+fun/parseText.m

MATLAB keeps ``parseText`` at the top of ``+ndi/+fun``. It is defined here in
a ``text`` module and re-exported from :mod:`ndi.fun`, the same arrangement
``plot_extracellular_spikeshapes`` uses.

Why this module depends on ``regex`` rather than the standard library
---------------------------------------------------------------------
The rules are MATLAB regular expressions, written by hand in files like
``+ndi/+setup/+conv/+babu/textParser.json``. MATLAB's engine accepts two
constructs Python's :mod:`re` rejects outright:

* **variable-width lookbehind** — ``(?<!To.*)``, ``(?<!\\s+to\\s+.*|\\+)``
* **an inline flag anywhere in the pattern** — ``(?<!To.*)(?i)WT``,
  ``neurons/((?i)[a-z]{3} \\d{1,2} \\d{4})``

These are not exotic. Of the 72 rules shipped in NDI-matlab's three parser
files, **33 fail to compile under** :mod:`re` (24 for the inline flag, 8 for
the lookbehind, and one — ``PT3602`` — because it has an unbalanced ``)``
and is malformed under any engine). ``regex`` compiles all but that last one.

On Python 3.10 the count is lower and the situation is *worse*, not better: a
mid-pattern global flag was only deprecated there, not an error, so those 24
compile and the flag silently applies to the **whole** pattern. The stdlib
does not refuse them on 3.10, it answers them differently.

Hoisting a mid-pattern ``(?i)`` to the front to satisfy :mod:`re` is not a
workaround, it is a **behaviour change**: MATLAB applies the flag from that
point onward, so in ``(?<!To.*)(?i)WT`` the lookbehind stays case-sensitive
and ``toWT`` matches. Hoisted, the lookbehind becomes case-insensitive too
and ``toWT`` stops matching. A silently different answer is worse than a
compile error, which is why the engine is swapped instead of the patterns.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

import regex

try:
    import pandas as pd
except ImportError:  # pragma: no cover - exercised only without pandas
    pd = None  # type: ignore[assignment]

from ..util.matlab_regex import matlab_to_python_regex

__all__ = ["parse_text", "parseText", "matlab_column_class"]

# MATLAB's isstrprop(...,'digit') over the characters these rules produce.
# Spelled out rather than using str.isdigit(), which is also true for
# superscripts and other Unicode digit forms that str2double would reject.
_ASCII_DIGITS = frozenset("0123456789")

# The scan parseText.m performs on the PATTERN TEXT to decide whether a rule
# captures a token or is a plain true/false test: a '(' not followed by '?'.
# It cannot tell an ESCAPED paren from a capture group -- see the
# escapedParenTreatedAsToken case in the symmetry battery.
_TOKEN_SCAN = regex.compile(r"\((?!\?)")


def _require_pandas() -> None:
    if pd is None:
        raise ImportError(
            "pandas is required for ndi.fun.parse_text. " "Install it with: pip install pandas"
        )


def _str2double(text: str) -> float:
    """MATLAB ``str2double`` for the forms these rules produce.

    Returns NaN for anything unparseable, which is what the caller branches on.
    """
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return math.nan


def _normalize_rows(input_text: Any) -> list[list[str]]:
    """Normalize the input to a list of rows, each a list of text columns.

    MATLAB takes ``size(inputText)`` and slices ``inputText(f,:)``, so an Nx1
    cellstr is N rows of one column. A flat sequence of strings is accepted
    here for the same reason.
    """
    if isinstance(input_text, str):
        return [[input_text]]

    rows: list[list[str]] = []
    for row in input_text:
        if isinstance(row, str):
            cells: Sequence[Any] = [row]
        else:
            cells = list(row)
        out: list[str] = []
        for cell in cells:
            if not isinstance(cell, str):
                # Mirrors cellstr(), which requires character vectors and
                # errors on a cell holding anything else.
                raise TypeError(
                    "input_text must contain only strings; got "
                    f"{type(cell).__name__}. MATLAB's cellstr() has the same "
                    "requirement."
                )
            out.append(cell)
        rows.append(out)
    return rows


def _load_rules(text_parser: Any) -> list[dict]:
    """Read the parser file. A bare object is accepted as a one-rule list.

    MATLAB's ``jsondecode`` returns a scalar struct for a bare JSON object and
    a struct array for an array, and ``numel`` makes both work, so both forms
    are accepted here too.
    """
    with open(text_parser, encoding="utf-8") as handle:
        rules = json.load(handle)
    if isinstance(rules, dict):
        return [rules]
    return list(rules)


def parse_text(
    input_text: Any,
    text_parser: Any,
    *,
    clean: bool = True,
) -> Any:
    """Extract variables from text using a JSON file of regex rules.

    MATLAB equivalent: ``ndi.fun.parseText``

    Each rule in *text_parser* has a ``VariableName`` and a ``StringFormat``
    (a MATLAB regular expression) and produces one column. Each row of
    *input_text* has its columns joined with a single space before matching.

    A rule whose pattern contains a capture group produces a **token** column:
    the first group of the first match, converted to a number when it contains
    a digit and :func:`str2double` accepts it, and kept as text otherwise. A
    rule with no capture group produces a **logical** column of match/no-match.

    Args:
        input_text: Rows of text. Either a sequence of rows (each a sequence
            of string columns), a flat sequence of strings (one column), or a
            single string.
        text_parser: Path to the JSON rules file.
        clean: Drop columns that carry no information -- all ``False``, all
            NaN, or all empty text. Defaults to True, as in MATLAB.

    Returns:
        A :class:`pandas.DataFrame` with one column per surviving rule, in
        rule order. Column dtypes are set explicitly to ``bool``, ``float`` or
        ``object``, mirroring MATLAB's ``logical`` / ``double`` / ``cell``.

    Raises:
        ImportError: If pandas is not installed.
        TypeError: If *input_text* contains a non-string cell.

    Three behaviours worth knowing, each pinned by the symmetry battery:

    * **A miss records NaN or the empty string** depending on whether the
      literal text ``\\d`` appears in the pattern -- a substring test on the
      pattern, not on the match.
    * **A column of nothing but empty strings becomes a logical column of
      False**, because MATLAB's flattening pass treats ``''`` as empty; with
      *clean* set it is then dropped entirely.
    * **Only the first PARTICIPATING capture group is read.** With alternating
      groups such as ``(\\d+)MM|(\\d+)\\s+mM``, a row matching the second
      alternative leaves group 1 out of the match. MATLAB's ``regexp(...,
      'tokens', 'once')`` returns tokens for the matched alternative alone,
      so it reads ``7``; Python returns one entry per group in the whole
      pattern, with ``None`` for the ones that did not take part. The
      non-participating entries are dropped so the two languages agree.
      (Measured, not assumed: this case was recorded as a deferred trap and
      the first real MATLAB run settled it, refuting the opposite reading.)

    Example::

        >>> parse_text([['experiment12'], ['experiment7']], 'rules.json')
           Trial
        0   12.0
        1    7.0
    """
    _require_pandas()

    rules = _load_rules(text_parser)
    rows = _normalize_rows(input_text)
    var_names = [rule["VariableName"] for rule in rules]

    # data[row][var], laid out exactly as parseText.m's preallocated cell.
    data: list[list[Any]] = [[None] * len(rules) for _ in rows]

    for v, rule in enumerate(rules):
        pattern = rule["StringFormat"]
        has_token = _TOKEN_SCAN.search(pattern) is not None
        compiled = regex.compile(matlab_to_python_regex(pattern))
        # A substring test on the PATTERN, matching MATLAB's contains(pattern, '\d').
        misses_are_nan = "\\d" in pattern

        for f, row in enumerate(rows):
            row_text = " ".join(row)

            if not has_token:
                data[f][v] = compiled.search(row_text) is not None
                continue

            match = compiled.search(row_text)
            # Only the groups that PARTICIPATED, in pattern order. MATLAB's
            # regexp(..., 'tokens', 'once') returns tokens for the matched
            # alternative alone, where Python returns one entry per group in
            # the whole pattern with None for the ones that did not take part.
            # Dropping the Nones is what makes the two agree -- see the
            # multipleGroupsFirstParticipatingGroupWins case.
            groups = tuple(g for g in match.groups() if g is not None) if match is not None else ()
            if not groups:
                # No match at all, or a match by a pattern with no groups.
                data[f][v] = math.nan if misses_are_nan else ""
                continue

            token = groups[0]
            if any(ch in _ASCII_DIGITS for ch in token):
                # '_' is rewritten to '.' first, so '3_5' parses as 3.5.
                value = _str2double(token.replace("_", "."))
                data[f][v] = token if math.isnan(value) else value
            else:
                data[f][v] = token

    columns: list[tuple[str, str, list[Any]]] = []
    for v, name in enumerate(var_names):
        column = [data[f][v] for f in range(len(rows))]
        columns.append((name, _column_class(column), column))

    if clean:
        columns = [c for c in columns if not _is_removable(c[1], c[2])]

    frame = {}
    for name, kind, column in columns:
        if kind == "logical":
            frame[name] = pd.Series([bool(x) for x in column], dtype=bool)
        elif kind == "double":
            frame[name] = pd.Series([float(x) for x in column], dtype=float)
        else:
            frame[name] = pd.Series(column, dtype=object)
    return pd.DataFrame(frame, index=range(len(rows)))


def _column_class(column: list[Any]) -> str:
    """The MATLAB class parseText's flattening pass would give this column.

    The order of the two tests is MATLAB's and it matters. ``isempty('')`` is
    true, so a column of nothing but empty strings satisfies the
    logical-or-empty test **first**, its entries are replaced by ``False``,
    and a text rule ends up as a *logical* column. Testing numeric first would
    not change that case but would misclassify an all-NaN column.
    """
    if all(isinstance(x, bool) or x == "" for x in column):
        return "logical"
    if all(not isinstance(x, bool) and isinstance(x, (int, float)) for x in column):
        return "double"
    return "cell"


def _is_removable(kind: str, column: list[Any]) -> bool:
    """Whether the ``Clean`` pass drops this column: no information in it."""
    if kind == "logical":
        return not any(bool(x) for x in column)
    if kind == "double":
        return all(isinstance(x, float) and math.isnan(x) for x in column)
    return all(x == "" for x in column)


def matlab_column_class(series: Any) -> str:
    """The MATLAB class name of a column of a :func:`parse_text` result.

    ``logical``, ``double`` or ``cell``. :func:`parse_text` sets each column's
    dtype explicitly, so this reads back what it decided rather than depending
    on whichever dtype a given pandas version would have inferred.
    """
    _require_pandas()
    if pd.api.types.is_bool_dtype(series.dtype):
        return "logical"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "double"
    return "cell"


# MATLAB spelling, for callers mirroring MATLAB code directly.
parseText = parse_text
