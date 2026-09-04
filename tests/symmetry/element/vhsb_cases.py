"""Shared VHSB round-trip battery, defined identically in both languages.

MATLAB counterpart: tests/+ndi/+symmetry/+element/vhsbCases.m

WHY THIS BATTERY DOES NOT COMPARE A JSON ARTIFACT
Every other symmetry battery here writes each language's *results* to JSON and
compares the two files. VHSB is different: the binary IS the contract.
NDI-matlab and NDI-python both store an element's epoch as
``epoch_binary_data.vhsb``, and the thing that has to hold is that each
language can read what the other wrote.

So each side writes its cases as real ``.vhsb`` files, and the read side opens
**both** languages' files and checks them against values it computed locally
from the case list. Nothing but the binary crosses the language boundary --
no float is ever serialized to text and parsed back -- so an exact equality
assertion means what it says.

WHY EVERY VALUE IS AN EXACT BINARY FRACTION
The times are quarter-integers, halves, and powers of two. Each is exactly
representable in float64 in both languages, so ``==`` is the right comparison
and a mismatch is a real difference rather than a formatting artifact. A case
built from, say, ``(0:99)/1000`` would not have that property.

WHAT THE SHRINKING-INTERVAL CASE PINS
``shrinkingInterval`` is the one shape whose ``X_constantinterval`` the two
languages disagreed about. MATLAB tested ``max(diff(diff(x))) < 1e-7`` on the
SIGNED second difference, so an all-negative one passed and a series whose
interval shrinks was recorded as constant-interval; Python already took
``abs`` and was right. This battery deliberately left the shape out while that
was true, because an allow-listed entry would have gone red the moment the bug
was fixed -- the wrong reward for fixing it. It is fixed
(VH-Lab/vhlab-toolbox-matlab#145, PR #147; mirrored in
VH-Lab/vhlab-toolbox-python#23), so the case is in, and it is the only one
here that tells the two rules apart: remove the ``abs`` on either side and
this case alone goes red.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INDEX_FILE = "vhsbIndex.json"

#: name -> (times, data, note). Data is a list of rows; a single-column case
#: uses one value per row.
CASES: dict[str, tuple[list[float], list[Any], str]] = {
    "regularInterval": (
        [i * 0.25 for i in range(100)],
        [float(i) for i in range(100)],
        "100 evenly spaced samples: X_constantinterval is 1, and reading with "
        "+/-Inf bounds must return all 100. It returned 1 before "
        "VH-Lab/vhlab-toolbox-python#21.",
    ),
    "markedPointProcess": (
        [0.125, 0.25, 0.375, 0.5, 0.75, 1.0, 1.5],
        [1.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0],
        "The ensemble case: irregular times that ARE the data, with the neuron "
        "column index as the mark. Intervals widen, so both languages agree "
        "X_constantinterval is 0.",
    ),
    "singleSample": (
        [0.5],
        [42.0],
        "One sample. X_increment and X_constantinterval are both 0 in MATLAB "
        "because of its numel(x) guards.",
    ),
    "twoSamples": (
        [0.25, 0.75],
        [7.0, 9.0],
        "Two samples. This raised inside Python's vhsb_write until "
        "VH-Lab/vhlab-toolbox-python#21: diff(diff(x)) is empty and np.max of "
        "an empty array is a ValueError. MATLAB's numel(x)>3 guard never "
        "reaches it.",
    ),
    "threeSamples": (
        [0.0, 0.25, 0.5],
        [1.0, 2.0, 3.0],
        "The n=3 boundary. MATLAB computes X_increment (numel>2) but NOT "
        "X_constantinterval (numel>3), so the header is increment 0.25 with "
        "the flag still 0. Python wrote 1 here before #21.",
    ),
    "shrinkingInterval": (
        [0.0, 1.0, 1.5, 1.75],
        [1.0, 2.0, 3.0, 4.0],
        "Intervals 1, 0.5, 0.25 -- shrinking, so X_constantinterval must be 0 "
        "even though X_increment is a median of 0.5 that describes none of "
        "them. The reproduction from VH-Lab/vhlab-toolbox-matlab#145: MATLAB "
        "wrote 1 here until PR #147 took abs() of the second difference.",
    ),
    "negativeTimes": (
        [-1.5, -0.5, 0.0, 0.5, 1.5],
        [1.0, 2.0, 3.0, 4.0, 5.0],
        "Times spanning zero and negative, with widening intervals.",
    ),
    "multiChannel": (
        [0.0, 0.25, 0.5, 0.75],
        [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]],
        "Two data columns per sample, to pin Y_dim and the sample stride.",
    ),
    "largeMagnitude": (
        [1048576.0, 1048576.25, 1048576.5, 1048576.75, 1048577.0],
        [1.0, 2.0, 3.0, 4.0, 5.0],
        "Times near 2^20 with a quarter-unit step: exactly representable, but "
        "far enough from zero that a float32 store would lose the step.",
    ),
}


def case_names() -> list[str]:
    """Case names in a stable order."""
    return sorted(CASES)


def expected(name: str) -> tuple[Any, Any]:
    """(times, data) for a case, as float64 arrays shaped as vhsb returns them."""
    import numpy as np

    times, data, _ = CASES[name]
    x = np.asarray(times, dtype=float).reshape(-1, 1)
    y = np.asarray(data, dtype=float)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    return x, y


def write_cases(dest: Path) -> list[str]:
    """Write every case as ``<name>.vhsb`` into DEST, plus the index."""
    from vlt.file.custom_file_formats import vhsb_write

    dest.mkdir(parents=True, exist_ok=True)
    for name in case_names():
        x, y = expected(name)
        vhsb_write(str(dest / f"{name}.vhsb"), x, y, use_filelock=0)

    (dest / INDEX_FILE).write_text(
        json.dumps(
            {"schemaVersion": 1, "language": "python", "cases": case_names()},
            indent=2,
        ),
        encoding="utf-8",
    )
    return case_names()


def read_case(path: Path) -> tuple[Any, Any, dict]:
    """Read one ``.vhsb`` back as (times, data, header).

    ``vhsb_read`` returns ``(y, x)`` -- data first, times second, matching
    MATLAB's ``[data, t] = vhsb_read(...)``. The order is unpacked here once
    so no caller has to remember it.
    """
    import numpy as np
    from vlt.file.custom_file_formats import vhsb_read, vhsb_readheader

    header = vhsb_readheader(str(path))
    data, times = vhsb_read(str(path), -np.inf, np.inf)
    times = np.asarray(times, dtype=float).reshape(-1, 1)
    data = np.asarray(data, dtype=float)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    return times, data, header


def compare(name: str, path: Path) -> list[str]:
    """Check one written case against the locally computed expectation.

    Returns a list of human-readable problems; empty means it matched.
    """
    import numpy as np

    want_x, want_y = expected(name)
    got_x, got_y, header = read_case(path)

    problems: list[str] = []
    if got_x.shape != want_x.shape:
        problems.append(f"times shape {got_x.shape} != {want_x.shape}")
    elif not np.array_equal(got_x, want_x):
        problems.append(f"times differ: {got_x.ravel()} != {want_x.ravel()}")

    if got_y.shape != want_y.shape:
        problems.append(f"data shape {got_y.shape} != {want_y.shape}")
    elif not np.array_equal(got_y, want_y):
        problems.append(f"data differ: {got_y.ravel()} != {want_y.ravel()}")

    if int(header["num_samples"]) != want_x.shape[0]:
        problems.append(f"num_samples {header['num_samples']} != {want_x.shape[0]}")

    expected_flag = _expected_constant_interval(want_x.ravel())
    if int(header["X_constantinterval"]) != expected_flag:
        problems.append(f"X_constantinterval {header['X_constantinterval']} != {expected_flag}")
    return problems


def _expected_constant_interval(x) -> int:
    """MATLAB's rule: only computed when numel(x) > 3, else 0.

    Compared as well as the values because the flag decides how a windowed
    read selects samples, and the two languages wrote different flags for the
    same input until VH-Lab/vhlab-toolbox-python#21 (Python's guards) and
    VH-Lab/vhlab-toolbox-matlab#145 (MATLAB's missing ``abs``). Both now use
    the rule below; ``shrinkingInterval`` is the case that separates it from
    the signed one.
    """
    import numpy as np

    x = np.asarray(x, dtype=float)
    if len(x) <= 3:
        return 0
    return int(np.max(np.abs(np.diff(np.diff(x)))) < 1e-7)


def load_index(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
