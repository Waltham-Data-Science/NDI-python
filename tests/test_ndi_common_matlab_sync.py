"""
Pin the state of the NDI-python ``ndi_common/`` tree against NDI-matlab.

``ndi_common/`` is vendored from NDI-matlab. When it drifts silently, downstream
readers on either side stop agreeing on what a document means. This test pins
the current sync state so any drift shows up here rather than as an obscure
downstream failure.

The test needs a local checkout of NDI-matlab to compare against; it locates
one via the ``NDI_MATLAB_PATH`` environment variable, or by walking up a small
set of well-known sibling paths. When no checkout is found (the common CI
case), the whole module skips loudly rather than passing silently.

Three checks:
  1. **Missing from Python.** Files present in NDI-matlab under
     ``src/ndi/ndi_common/`` but not in NDI-python. A short exclusion list
     covers MATLAB-only trees (test fixtures, sync rules, examples).
  2. **Python-only.** Files present here but not in NDI-matlab. Also short
     exclusion list (the Python ontology working tree).
  3. **Byte-divergent.** Files present on both sides that don't match
     byte-for-byte. The set of allowed divergences is spelled out below --
     new divergences fail the test, and a divergence that unexpectedly
     converges also fails so the caller can retire it from the list.

See ndi-python issue #96.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

NDI_COMMON_REL = Path("src/ndi/ndi_common")


def _find_matlab_repo() -> Path | None:
    """Best-effort discovery of a local NDI-matlab checkout.

    Order:
      1. $NDI_MATLAB_PATH.
      2. A sibling directory named ``NDI-matlab`` next to this repo.
      3. ``~/NDI-matlab``.
    """
    env = os.environ.get("NDI_MATLAB_PATH")
    if env:
        p = Path(env).expanduser()
        if (p / NDI_COMMON_REL).is_dir():
            return p

    here = Path(__file__).resolve().parent.parent
    sibling = here.parent / "NDI-matlab"
    if (sibling / NDI_COMMON_REL).is_dir():
        return sibling

    home = Path.home() / "NDI-matlab"
    if (home / NDI_COMMON_REL).is_dir():
        return home

    return None


_MATLAB_REPO = _find_matlab_repo()
pytestmark = pytest.mark.skipif(
    _MATLAB_REPO is None,
    reason=(
        "NDI-matlab checkout not found. Set NDI_MATLAB_PATH, or clone "
        "NDI-matlab next to NDI-python, to run the ndi_common sync tests."
    ),
)


# ---------------------------------------------------------------------------
# Exclusion lists: everything below is a *declared* divergence. Anything not
# on these lists is checked strictly.
# ---------------------------------------------------------------------------


# Present in NDI-matlab, deliberately not vendored into Python.
MATLAB_ONLY_EXPECTED: frozenset[str] = frozenset(
    {
        ".matlab2markdown-ignore",
        # MATLAB-only sync rules (no Python callers yet).
        "sync_rules/vhlab/vhintan_intan2spike2.json",
        "sync_rules/vhlab/vhtaste_sync2bpod.json",
    }
)


# Present in NDI-matlab, allowed to be missing because they belong to
# subtrees Python does not (yet) ship at all.
MATLAB_ONLY_PREFIXES: tuple[str, ...] = (
    "example_app_sessions/",
    "example_datasets/oldDataset/",
    "schema_documents/apps/calculations/",
)


# Present in Python, deliberately not in NDI-matlab. Python's ontology
# working tree lives here.
PYTHON_ONLY_EXPECTED: frozenset[str] = frozenset(
    {
        "controlled_vocabulary/empty.obo",
        "controlled_vocabulary/working/EMPTY.json",
        "controlled_vocabulary/working/empty_ontology_v0.1.0.obo",
        "controlled_vocabulary/working/empty_ontology_v0.1.0.ttl",
    }
)


# Files present on both sides that intentionally do not match byte-for-byte.
# Each entry pairs the relative path with a one-line reason so the exclusion
# is not silent. When one of these converges, the test asks the caller to
# remove it from this map -- so the map itself never grows stale.
EXPECTED_DIVERGENCES: dict[str, str] = {
    # EMPTY ontology ids: Python uses 8-digit ids (EMPTY:00000090); MATLAB
    # switched to 7-digit ids (EMPTY:0000002). These are documentation
    # strings inside schema files and must match the id format the Python
    # ontology package actually resolves.
    "schema_documents/element/distance_metadata_schema.json": "EMPTY id format",
    "schema_documents/data/ontologyLabel_schema.json": "EMPTY id format",
    "schema_documents/data/ontologyImage_schema.json": "EMPTY id format",
    "schema_documents/data/ontologyTableRow_schema.json": "EMPTY id format + depends_on",
    "schema_documents/data/generic_file_schema.json": "EMPTY id format",
    "schema_documents/data/imageStack_schema.json": "EMPTY id format",
    # MATLAB refactored the calculator base class and bumped simple_calc/
    # tuningcurve_calc to v2 schemas that live under a different path
    # (apps/calculations/) than the docs (apps/calculators/). Adopting that
    # refactor is a separate coordination item; keep Python on v1 for now.
    "database_documents/data/ontologyTableRow.json": "depends_on not yet added",
    "database_documents/apps/calculators/tuningcurve_calc.json": "v1 vs v2 refactor",
    "database_documents/apps/calculators/simple_calc.json": "v1 vs v2 refactor",
    # probe/probetype2object.json: MATLAB renamed classname 'ndi_probe.timage'
    # to 'ndi.probe.image', renamed '2-photon-imaging' to 'two-photon-imaging'
    # etc., and added an 'event' stimulator entry. Adopting these renames is
    # a coordinated change (existing Python datasets reference the current
    # names); the extra 'event' entry is safe to add on its own but is left
    # with the rename cluster so the whole file lands together.
    "probe/probetype2object.json": "classname/type renames + extra entry",
    # daq_systems/rayolab/rayo_stim.json: MATLAB widened the
    # MetadataReaderFileParameters regex from `#_\d{6}_...` (matches only a
    # literal '#') to `.*_\d{6}_...` (matches any prefix). Likely a bug fix
    # on the MATLAB side, but changing what files the reader picks up needs
    # verification against the actual rayo_stim data corpus before we sync.
    "daq_systems/rayolab/rayo_stim.json": "MetadataReaderFileParameters regex",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_files(root: Path) -> set[str]:
    """Return every file under ``root``, as POSIX relative paths."""
    return {
        str(p.relative_to(root).as_posix())
        for p in root.rglob("*")
        if p.is_file()
    }


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(pref) for pref in prefixes)


@pytest.fixture(scope="module")
def python_common() -> Path:
    return Path(__file__).resolve().parent.parent / NDI_COMMON_REL


@pytest.fixture(scope="module")
def matlab_common() -> Path:
    assert _MATLAB_REPO is not None  # skip guard above
    return _MATLAB_REPO / NDI_COMMON_REL


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_undeclared_files_missing_in_python(python_common, matlab_common):
    """MATLAB files not present in Python must be on the exclusion list."""
    py = _list_files(python_common)
    ml = _list_files(matlab_common)
    missing = ml - py
    unexpected = {
        f
        for f in missing
        if f not in MATLAB_ONLY_EXPECTED and not _matches_prefix(f, MATLAB_ONLY_PREFIXES)
    }
    assert not unexpected, (
        "The following files exist in NDI-matlab/ndi_common but not in "
        "NDI-python. Either vendor them, or add them to MATLAB_ONLY_EXPECTED "
        "/ MATLAB_ONLY_PREFIXES with a reason:\n  "
        + "\n  ".join(sorted(unexpected))
    )


def test_no_undeclared_python_only_files(python_common, matlab_common):
    """Python files not present in MATLAB must be on the exclusion list."""
    py = _list_files(python_common)
    ml = _list_files(matlab_common)
    extra = py - ml
    unexpected = extra - PYTHON_ONLY_EXPECTED
    assert not unexpected, (
        "The following files exist in NDI-python/ndi_common but not in "
        "NDI-matlab. Either remove them, or add them to PYTHON_ONLY_EXPECTED "
        "with a reason:\n  " + "\n  ".join(sorted(unexpected))
    )


def test_no_undeclared_byte_divergences(python_common, matlab_common):
    """Files present on both sides must match byte-for-byte or be declared."""
    py = _list_files(python_common)
    ml = _list_files(matlab_common)
    shared = py & ml
    diverged: set[str] = set()
    for rel in sorted(shared):
        if (python_common / rel).read_bytes() != (matlab_common / rel).read_bytes():
            diverged.add(rel)
    unexpected = diverged - EXPECTED_DIVERGENCES.keys()
    assert not unexpected, (
        "The following files differ between NDI-python and NDI-matlab and "
        "are NOT on the EXPECTED_DIVERGENCES list. Re-sync them, or add "
        "each to EXPECTED_DIVERGENCES with a reason:\n  "
        + "\n  ".join(sorted(unexpected))
    )


def test_declared_divergences_still_diverge(python_common, matlab_common):
    """Retire an EXPECTED_DIVERGENCES entry once its file converges.

    Keeping stale entries makes the exclusion list untrustworthy. If a
    declared-divergent file now matches, remove it from the map (and consider
    whether the Python-side reason still applies elsewhere).
    """
    stale: list[str] = []
    for rel in EXPECTED_DIVERGENCES:
        py_file = python_common / rel
        ml_file = matlab_common / rel
        if not py_file.is_file() or not ml_file.is_file():
            continue  # missing-file cases are covered by the other tests
        if py_file.read_bytes() == ml_file.read_bytes():
            stale.append(rel)
    assert not stale, (
        "The following files are on EXPECTED_DIVERGENCES but now match "
        "byte-for-byte. Remove them from the list:\n  "
        + "\n  ".join(sorted(stale))
    )
