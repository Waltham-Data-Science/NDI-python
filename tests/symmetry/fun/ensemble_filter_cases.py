"""Shared, self-describing ndi.fun.ensemble.filter symmetry battery.

Python counterpart of:
    tests/+ndi/+symmetry/+fun/ensembleFilterCases.m

Both language ports run the SAME case list -- each case identified by an ASCII
case NAME -- through their own real ``ndi.fun.ensemble.filter``, then write the
recorded outputs to

    <tempdir>/NDI/symmetryTest/<matlabArtifacts|pythonArtifacts>/fun/
             ensembleFilter/testEnsembleFilterArtifacts/ensembleFilterCases.json

The on-disk schema is NDI-matlab's ``tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md``,
section 10. READ THAT FILE before changing anything here.

This is a separate module from :mod:`tests.symmetry.fun.cases` for the same
reason ``parse_text_cases`` is: only the case list is new; the canonical value
grammar (:func:`~tests.symmetry.fun.cases.render` /
:func:`~tests.symmetry.fun.cases.render_sequence`) is imported from it, so the
grammar stays single-sourced.

What the battery is for
-----------------------
``ndi.fun.ensemble.filter`` is the one function in the ``+ensemble`` package
that is pure and in-memory: no session, no database, no clocks. The rules
themselves are stated in the MATLAB help but each is easy to invert in a port:
includes are a UNION across names / ids / index / Keep, excludes always win
over includes, indices are 1-based on both sides (a deliberate choice — the
port keeps MATLAB's 1-based ``IncludeIndex`` so the same case list drives both
languages), and the activity matrix has its all-zero trailing columns trimmed
afterwards **except when nothing is kept**, where MATLAB's ``isempty`` guard
returns early and the ``0``-by-``Smax`` width survives.

Each case pins one of those rules. ``expectedShape`` is compared alongside
``expectedActivityRows`` so the isempty-guard asymmetry cannot drift from
either side while the (empty) values still happen to agree.

Why activity is encoded row by row
----------------------------------
The activity matrix is 2-D. Section 3 of the schema rules out a 2-D matrix from
the canonical grammar because MATLAB's column-major and Python's row-major
iteration render one the wrong way round. Rows are 1-D though, so the battery
encodes activity as a list of rendered row sequences -- exactly the pattern
``parseText`` uses for ``inputRendered``.

Sparse activity
---------------
``ndi.element.ensemble.spike_matrix`` returns sparse activity by default and
the round-trip format (``ndi.util.readSparse`` / ``writeSparse``) is
NDI-specific and exists precisely so ensembles move sparsely between the two
languages. Two sparse cases (``sparseInputBasic`` and
``sparseNothingKeptPreservesWidth``) run the same fixture through the sparse
code path -- the outputs are densified before rendering, so the signature is
identical to the dense case's, but ``input_signature`` records ``storage`` so
one language sparse and the other dense would fail as a real disagreement
rather than pass because the numbers happened to match.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tests.symmetry.fun import cases

# ---------------------------------------------------------------------------
# case builder
# ---------------------------------------------------------------------------


def _case(
    name: str,
    note: str,
    mirrors: str,
    neuron_ids: list[str],
    neuron_names: list[str],
    activity: list[list[float]],
    *,
    include_names: list[str] | None = None,
    exclude_names: list[str] | None = None,
    include_index: list[int] | None = None,
    exclude_index: list[int] | None = None,
    include_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
    keep_logical: list[bool] | None = None,
    keep_index: list[int] | None = None,
    storage: str = "dense",
    expected_ids: list[str] | None = None,
    expected_names: list[str] | None = None,
    expected_activity: list[list[float]] | None = None,
    expected_shape: tuple[int, int] | None = None,
    expected_status: str = "ok",
) -> dict:
    """One case definition.

    ``storage`` picks how the activity is handed to ``filter``: ``'dense'``
    (a plain 2-D array) or ``'sparse'`` (scipy CSR / MATLAB sparse). It is in
    ``input_signature`` so a green comparison cannot be one language dense and
    the other sparse.

    ``expected_activity`` and ``expected_shape`` are ignored when
    ``expected_status`` is ``'error'``: an error case pins the FACT of an error
    only, per section 4 of the schema.
    """
    if storage not in ("dense", "sparse"):
        raise ValueError(f"storage must be 'dense' or 'sparse'; got {storage!r}.")
    return {
        "name": name,
        "note": note,
        "mirrors": mirrors,
        "neuronIds": list(neuron_ids),
        "neuronNames": list(neuron_names),
        "activity": [list(row) for row in activity],
        "storage": storage,
        "includeNames": list(include_names or []),
        "excludeNames": list(exclude_names or []),
        "includeIndex": list(include_index or []),
        "excludeIndex": list(exclude_index or []),
        "includeIds": list(include_ids or []),
        "excludeIds": list(exclude_ids or []),
        "keepLogical": [bool(x) for x in (keep_logical or [])],
        "keepIndex": list(keep_index or []),
        "expectedStatus": expected_status,
        "expectedIds": list(expected_ids or []),
        "expectedNames": list(expected_names or []),
        "expectedActivity": (
            [list(row) for row in (expected_activity or [])] if expected_status == "ok" else []
        ),
        "expectedShape": list(expected_shape) if expected_shape is not None else [],
    }


# ---------------------------------------------------------------------------
# the battery
# ---------------------------------------------------------------------------

# The workhorse fixture: 4 neurons; row i has i spikes, so neuron 3 pins the
# widest column and trimming is observable when anyone else is kept alone.
_IDS = ["id1", "id2", "id3", "id4"]
_NAMES = ["A", "B", "C", "D"]
_ACTIVITY = [
    [11, 0, 0],
    [21, 22, 0],
    [31, 32, 33],
    [41, 0, 0],
]


def definitions() -> list[dict]:
    """The 17-case battery (15 dense + 2 sparse), in the fixed order.

    Cases are joined by NAME on the read side, so order here is for humans.
    """
    return [
        # --- no options at all ---------------------------------------------
        _case(
            "noCriteriaKeepsAll",
            "With no criteria the whole ensemble comes back unchanged and "
            "num_neurons is preserved.",
            "testNoOptionsKeepsAll",
            _IDS,
            _NAMES,
            _ACTIVITY,
            expected_ids=_IDS,
            expected_names=_NAMES,
            expected_activity=_ACTIVITY,
            expected_shape=(4, 3),
        ),
        # --- one selection method at a time --------------------------------
        _case(
            "includeNamesBasic",
            "IncludeNames keeps only the named neurons; trailing columns are "
            "trimmed to the widest surviving row.",
            "testIncludeNames",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_names=["B", "D"],
            expected_ids=["id2", "id4"],
            expected_names=["B", "D"],
            expected_activity=[[21, 22], [41, 0]],
            expected_shape=(2, 2),
        ),
        _case(
            "excludeNamesBasic",
            "ExcludeNames drops the named neurons; every other row survives.",
            "testExcludeNames",
            _IDS,
            _NAMES,
            _ACTIVITY,
            exclude_names=["A"],
            expected_ids=["id2", "id3", "id4"],
            expected_names=["B", "C", "D"],
            expected_activity=[[21, 22, 0], [31, 32, 33], [41, 0, 0]],
            expected_shape=(3, 3),
        ),
        _case(
            "includeIndexBasic",
            "IncludeIndex is 1-based on BOTH sides -- a deliberate choice so "
            "the same case list drives both languages.",
            "testIncludeIndex",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_index=[1, 3],
            expected_ids=["id1", "id3"],
            expected_names=["A", "C"],
            expected_activity=[[11, 0, 0], [31, 32, 33]],
            expected_shape=(2, 3),
        ),
        _case(
            "excludeIndexBasic",
            "ExcludeIndex takes 1-based positions too.",
            "testExcludeIndex",
            _IDS,
            _NAMES,
            _ACTIVITY,
            exclude_index=[2],
            expected_ids=["id1", "id3", "id4"],
            expected_names=["A", "C", "D"],
            expected_activity=[[11, 0, 0], [31, 32, 33], [41, 0, 0]],
            expected_shape=(3, 3),
        ),
        _case(
            "includeIdsBasic",
            "IncludeIds matches on the element document id, not the name.",
            "testIncludeIds",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_ids=["id2", "id4"],
            expected_ids=["id2", "id4"],
            expected_names=["B", "D"],
            expected_activity=[[21, 22], [41, 0]],
            expected_shape=(2, 2),
        ),
        _case(
            "excludeIdsBasic",
            "ExcludeIds drops by element id.",
            "testExcludeIds",
            _IDS,
            _NAMES,
            _ACTIVITY,
            exclude_ids=["id3"],
            expected_ids=["id1", "id2", "id4"],
            expected_names=["A", "B", "D"],
            expected_activity=[[11, 0], [21, 22], [41, 0]],
            expected_shape=(3, 2),
        ),
        _case(
            "keepLogicalMask",
            "Keep with a length-N boolean mask; equivalent to IncludeIndex on "
            "the true positions.",
            "testKeepLogicalMask",
            _IDS,
            _NAMES,
            _ACTIVITY,
            keep_logical=[True, False, True, False],
            expected_ids=["id1", "id3"],
            expected_names=["A", "C"],
            expected_activity=[[11, 0, 0], [31, 32, 33]],
            expected_shape=(2, 3),
        ),
        _case(
            "keepIndexVectorOrderFollowsEnsemble",
            "Keep as an INDEX VECTOR; the argument order [4, 2] does NOT set "
            "the output order -- the kept neurons come back in the ensemble's "
            "own order.",
            "testKeepIndexVector",
            _IDS,
            _NAMES,
            _ACTIVITY,
            keep_index=[4, 2],
            expected_ids=["id2", "id4"],
            expected_names=["B", "D"],
            expected_activity=[[21, 22], [41, 0]],
            expected_shape=(2, 2),
        ),
        # --- combinations that pin the include/exclude semantics -----------
        _case(
            "includesAreAUnion",
            "The kept set is the UNION of every include criterion; here a "
            "name, an id and an index reach three different neurons and all "
            "three survive.",
            "testIncludeUnionThenExclude",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_names=["A"],
            include_ids=["id4"],
            include_index=[2],
            expected_ids=["id1", "id2", "id4"],
            expected_names=["A", "B", "D"],
            expected_activity=[[11, 0], [21, 22], [41, 0]],
            expected_shape=(3, 2),
        ),
        _case(
            "excludeBeatsIncludeOnSameNeuron",
            "An exclude always removes from the kept set, INCLUDING a neuron "
            "an include criterion just put there. This is the one rule a "
            "reader is most likely to invert.",
            "testIncludeUnionThenExclude",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_names=["A", "B", "C"],
            exclude_names=["B"],
            expected_ids=["id1", "id3"],
            expected_names=["A", "C"],
            expected_activity=[[11, 0, 0], [31, 32, 33]],
            expected_shape=(2, 3),
        ),
        # --- trimming and the isempty asymmetry ----------------------------
        _case(
            "trailingColumnsTrimmedToOne",
            "Keeping only neuron 4 -- one spike, in column 1 -- leaves a "
            "1-by-1 activity. Trimming keeps at least one column, so a row of "
            "all zeros does not collapse to width 0.",
            "testIncludeNames",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_names=["D"],
            expected_ids=["id4"],
            expected_names=["D"],
            expected_activity=[[41]],
            expected_shape=(1, 1),
        ),
        _case(
            "nothingKeptPreservesWidth",
            "When nothing is kept, MATLAB's isempty guard returns EARLY and "
            "the 0-by-Smax width survives -- so activity is 0-by-3 rather "
            "than 0-by-1. Python's port reproduces the asymmetry deliberately: "
            "a filter that kept nothing must not silently redefine the "
            "ensemble's temporal width.",
            "-- pins isempty asymmetry",
            _IDS,
            _NAMES,
            _ACTIVITY,
            exclude_names=["A", "B", "C", "D"],
            expected_ids=[],
            expected_names=[],
            expected_activity=[],
            expected_shape=(0, 3),
        ),
        # --- errors --------------------------------------------------------
        _case(
            "errorBadIndex",
            "IncludeIndex outside 1..N is an error, not a silent drop.",
            "testBadIndexErrors",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_index=[5],
            expected_status="error",
        ),
        _case(
            "errorBadKeepMask",
            "A boolean Keep mask of the wrong length is an error, not a " "silent pad or truncate.",
            "testBadKeepMaskErrors",
            _IDS,
            _NAMES,
            _ACTIVITY,
            keep_logical=[True, False, True],
            expected_status="error",
        ),
        # --- sparse activity -----------------------------------------------
        # ndi.element.ensemble stores activity sparsely (ndi.util.readSparse /
        # writeSparse is the round-trip format), so the real caller of filter
        # passes sparse. Both cases mirror a dense case, so an accidental
        # sparse/dense divergence shows as a signature mismatch on the case
        # pair rather than a hidden code-path drift.
        _case(
            "sparseInputBasic",
            "Same input and options as includeNamesBasic but the activity is "
            "SPARSE (scipy CSR on the Python side, MATLAB sparse on the MATLAB "
            "side). The filter must produce the same result whichever storage "
            "the caller uses; ndi.element.ensemble.spike_matrix returns sparse "
            "and this is the code path production actually takes.",
            "testIncludeNames + sparse round trip",
            _IDS,
            _NAMES,
            _ACTIVITY,
            include_names=["B", "D"],
            storage="sparse",
            expected_ids=["id2", "id4"],
            expected_names=["B", "D"],
            expected_activity=[[21, 22], [41, 0]],
            expected_shape=(2, 2),
        ),
        _case(
            "sparseNothingKeptPreservesWidth",
            "Sparse-storage twin of nothingKeptPreservesWidth. The isempty "
            "guard in local_trim_columns must return early on a 0-row sparse "
            "slice too, so the 0-by-3 width survives -- if it did not, a "
            "sparse ensemble would silently redefine its temporal width on a "
            "no-neuron filter.",
            "-- pins isempty asymmetry, sparse path",
            _IDS,
            _NAMES,
            _ACTIVITY,
            exclude_names=["A", "B", "C", "D"],
            storage="sparse",
            expected_ids=[],
            expected_names=[],
            expected_activity=[],
            expected_shape=(0, 3),
        ),
    ]


# ---------------------------------------------------------------------------
# running the battery
# ---------------------------------------------------------------------------


def _activity_matrix(rows: list[list[float]], n_neurons: int) -> np.ndarray:
    """A dense ``n_neurons``-by-Smax activity matrix; empty is n-by-1.

    The n-by-1 shape when there are no rows keeps the empty case matching
    MATLAB's ``zeros(0, 1)``: an ensemble with zero recorded neurons still has
    a width, and the filter never sees this shape anyway.
    """
    if not rows:
        return np.zeros((n_neurons, 1), dtype=float)
    return np.asarray(rows, dtype=float)


def _densify(matrix: Any) -> np.ndarray:
    """A dense 2-D float array from either a dense array or a scipy sparse one.

    ``np.asarray`` on a scipy CSR yields an object array pointing at the CSR
    (nothing gets densified), which then breaks every row-wise op below;
    ``.toarray()`` is the sparse-side entry point that gives back a plain 2-D
    array of floats. Both ``filter``s return sparse output when handed sparse
    input, so this is exercised by every sparse case.
    """
    if hasattr(matrix, "toarray"):
        return matrix.toarray()
    return np.asarray(matrix, dtype=float)


def _rendered_rows(matrix: Any) -> list[str]:
    """One rendered sequence per row of ``matrix``. Empty rows are dropped.

    A 0-row matrix returns ``[]``, not one entry per column, so the empty case
    round-trips through JSON without becoming a list of empty strings.
    """
    arr = _densify(matrix)
    if arr.size == 0 or arr.shape[0] == 0:
        return []
    return [cases.render_sequence([float(x) for x in row]) for row in arr]


def _output_shape(matrix: Any) -> tuple[int, int]:
    if hasattr(matrix, "shape") and not isinstance(matrix, np.ndarray):
        rows, cols = matrix.shape
        return int(rows), int(cols)
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    return int(arr.shape[0]), int(arr.shape[1])


def _filter_kwargs(defn: dict) -> dict:
    """Kwargs for :func:`ndi.fun.ensemble.filter` from a case definition.

    Only one of ``keep_logical`` and ``keep_index`` is non-empty per case; both
    map onto the ``keep`` argument, so we pick whichever is populated.
    """
    kwargs: dict[str, Any] = {}
    if defn["includeNames"]:
        kwargs["include_names"] = list(defn["includeNames"])
    if defn["excludeNames"]:
        kwargs["exclude_names"] = list(defn["excludeNames"])
    if defn["includeIndex"]:
        kwargs["include_index"] = list(defn["includeIndex"])
    if defn["excludeIndex"]:
        kwargs["exclude_index"] = list(defn["excludeIndex"])
    if defn["includeIds"]:
        kwargs["include_ids"] = list(defn["includeIds"])
    if defn["excludeIds"]:
        kwargs["exclude_ids"] = list(defn["excludeIds"])
    if defn["keepLogical"]:
        kwargs["keep"] = np.asarray(defn["keepLogical"], dtype=bool)
    elif defn["keepIndex"]:
        kwargs["keep"] = list(defn["keepIndex"])
    return kwargs


def run_cases() -> list[dict]:
    """Run every case through ``ndi.fun.ensemble.filter`` and record it.

    Errors are CAUGHT and recorded as ``status: 'error'`` rather than raised,
    for the same reason ``parse_text_cases`` gives (FUN_CASES_SCHEMA.md
    section 6): a generator that dies on one case writes no artifact at all
    and costs the suite every other case's coverage. The error is asserted
    against MATLAB in the readArtifacts twin.
    """
    from scipy.sparse import csr_matrix

    from ndi.fun.ensemble import filter as ensemble_filter

    results: list[dict] = []
    for defn in definitions():
        activity = _activity_matrix(defn["activity"], len(defn["neuronIds"]))
        if defn["storage"] == "sparse":
            activity = csr_matrix(activity)
        record = {
            "name": defn["name"],
            "note": defn["note"],
            "mirrors": defn["mirrors"],
            "neuronIds": list(defn["neuronIds"]),
            "neuronNames": list(defn["neuronNames"]),
            "activity": _rendered_rows(defn["activity"]) if defn["activity"] else [],
            "storage": defn["storage"],
            "includeNames": list(defn["includeNames"]),
            "excludeNames": list(defn["excludeNames"]),
            "includeIndex": list(defn["includeIndex"]),
            "excludeIndex": list(defn["excludeIndex"]),
            "includeIds": list(defn["includeIds"]),
            "excludeIds": list(defn["excludeIds"]),
            "keepLogical": list(defn["keepLogical"]),
            "keepIndex": list(defn["keepIndex"]),
            "status": "ok",
            "identifier": "",
            "message": "",
            "neuronIdsOut": [],
            "neuronNamesOut": [],
            "activityOut": [],
            "shapeOut": [],
            "numNeuronsOut": 0,
        }

        ensemble = {
            "activity": activity,
            "neuron_ids": list(defn["neuronIds"]),
            "neuron_names": list(defn["neuronNames"]),
            "epoch": "epoch_1",
            "info": {"num_neurons": len(defn["neuronIds"])},
        }

        try:
            out = ensemble_filter(ensemble, **_filter_kwargs(defn))
            record["neuronIdsOut"] = list(out["neuron_ids"])
            record["neuronNamesOut"] = list(out["neuron_names"])
            record["activityOut"] = _rendered_rows(out["activity"])
            record["shapeOut"] = list(_output_shape(out["activity"]))
            record["numNeuronsOut"] = int(out.get("info", {}).get("num_neurons", 0))
        except Exception as exc:  # noqa: BLE001 - recorded, then compared
            record["status"] = "error"
            record["identifier"] = type(exc).__name__
            record["message"] = str(exc)

        results.append(record)
    return results


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def _as_list(v: Any) -> list[str]:
    """Normalize a decoded-JSON string list. MATLAB collapses length-1 arrays."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


def _as_int_list(v: Any) -> list[int]:
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [int(v)]
    return [int(x) for x in v]


def _as_bool_list(v: Any) -> list[bool]:
    if v is None:
        return []
    if isinstance(v, bool):
        return [v]
    if isinstance(v, (int, float)):
        return [bool(v)]
    return [bool(x) for x in v]


def signature(c: dict) -> str:
    """The compared part of one recorded case.

    ``identifier`` and ``message`` are deliberately absent: MATLAB identifiers
    and Python exception names can never match, and pinning them would make
    this a translation table instead of a behaviour check. Only the FACT of an
    error is symmetric.
    """
    return "; ".join(
        [
            f"status={c['status']}",
            f"num={int(c['numNeuronsOut'])}",
            f"ids={'|'.join(_as_list(c['neuronIdsOut']))}",
            f"names={'|'.join(_as_list(c['neuronNamesOut']))}",
            f"activity={'|'.join(_as_list(c['activityOut']))}",
            f"shape={'x'.join(str(x) for x in _as_int_list(c['shapeOut']))}",
        ]
    )


def input_signature(c: dict) -> str:
    """The inputs, so a green run cannot be two different batteries agreeing.

    Every input field is compared: without this the output comparison could
    pass while the two languages started from different ensembles or ran
    different filter options.
    """
    return "; ".join(
        [
            f"ids={'|'.join(_as_list(c['neuronIds']))}",
            f"names={'|'.join(_as_list(c['neuronNames']))}",
            f"activity={'|'.join(_as_list(c['activity']))}",
            # storage defaults to 'dense' for records written before the field
            # existed, so the pre-sparse artifacts do not falsely disagree with
            # this reader.
            f"storage={c.get('storage') or 'dense'}",
            f"includeNames={'|'.join(_as_list(c['includeNames']))}",
            f"excludeNames={'|'.join(_as_list(c['excludeNames']))}",
            f"includeIndex={'|'.join(str(x) for x in _as_int_list(c['includeIndex']))}",
            f"excludeIndex={'|'.join(str(x) for x in _as_int_list(c['excludeIndex']))}",
            f"includeIds={'|'.join(_as_list(c['includeIds']))}",
            f"excludeIds={'|'.join(_as_list(c['excludeIds']))}",
            f"keepLogical={'|'.join(cases.render(b) for b in _as_bool_list(c['keepLogical']))}",
            f"keepIndex={'|'.join(str(x) for x in _as_int_list(c['keepIndex']))}",
        ]
    )


def check_expected(defn: dict, record: dict) -> tuple[bool, str]:
    """Compare one recorded case against its expected output.

    An error case pins only the FACT of the error; a success case pins the
    kept ids, names, activity (row by row) and the resulting shape.
    """
    want_status = defn["expectedStatus"]
    if record["status"] != want_status:
        return False, (
            f"expected status={want_status}, got status={record['status']} "
            f"({record.get('identifier', '')}: {record.get('message', '')})"
        )
    if want_status == "error":
        return True, "error expected and observed"

    want_activity = [
        cases.render_sequence([float(x) for x in row]) for row in defn["expectedActivity"]
    ]
    want = "; ".join(
        [
            f"ids={'|'.join(defn['expectedIds'])}",
            f"names={'|'.join(defn['expectedNames'])}",
            f"activity={'|'.join(want_activity)}",
            f"shape={'x'.join(str(x) for x in defn['expectedShape'])}",
        ]
    )
    got = "; ".join(
        [
            f"ids={'|'.join(_as_list(record['neuronIdsOut']))}",
            f"names={'|'.join(_as_list(record['neuronNamesOut']))}",
            f"activity={'|'.join(_as_list(record['activityOut']))}",
            f"shape={'x'.join(str(x) for x in _as_int_list(record['shapeOut']))}",
        ]
    )
    return want == got, f"expected [{want}], got [{got}]"


def index_by_name(recorded: list[dict]) -> dict[str, dict]:
    """Case name -> case record. Cases are joined by name, never by position."""
    return {c["name"]: c for c in recorded}


__all__ = [
    "check_expected",
    "definitions",
    "index_by_name",
    "input_signature",
    "run_cases",
    "signature",
]
