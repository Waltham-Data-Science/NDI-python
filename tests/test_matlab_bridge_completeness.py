"""Every MATLAB function in a bridged package is recorded in a bridge file.

MATLAB counterpart: ``src/ndi/+ndi/+cloud/**`` against
``src/ndi/cloud/**/ndi_matlab_python_bridge.yaml``

The bridge YAMLs are the port's contract: for each MATLAB function they say
what the Python name is, or -- with ``status: not_yet_ported`` /
``not_applicable`` and a reason -- why there isn't one. They are maintained
by hand, and until now nothing compared them against MATLAB. So a function
could be ported without its entry ever being written (``documentDifference``,
landed in #112, recorded in #131) or skipped without anyone recording the
decision (``helloMatlab``, which nobody had decided to skip -- it was simply
missed). Five such gaps in ``+ndi/+cloud`` alone, found by hand in #131.

This is the guard. It walks the MATLAB package and asserts every function is
either recorded, or on an explicit exclusion list carrying a reason. The
value is not the one-time cleanup; it is that the next omission fails here.

TWO THINGS THIS HAS TO GET RIGHT, both learned by getting them wrong while
scoping #131:

**Nested entries count.** MATLAB has ``readSyncIndex.m`` / ``writeSyncIndex.m``
/ ``updateSyncIndex.m`` as free functions; Python has a ``SyncIndex`` class
whose ``read`` / ``write`` / ``update`` methods each carry a
``matlab_equivalent:``. A first pass that read only top-level ``name:`` keys
called the sync index missing when it is fully recorded. A checker that
raises false alarms gets ignored, which is worse than no checker.

**``+api/+implementation/`` is excluded as a LAYER, not file by file.** Its
62 files are MATLAB's internal implementation classes behind the public
``+api`` wrappers, and every wrapper is recorded. Listing them individually
would bury the five real gaps under 62 lines of noise.

WHERE THE MATLAB TREE COMES FROM
This needs NDI-matlab checked out; see :func:`matlab_root`. Absent, the
check skips -- unless ``NDI_BRIDGE_CHECK_STRICT`` is set, which CI does
after checking the repo out, so a workflow that stops providing the tree
fails instead of quietly passing. Same reasoning as
``tests/symmetry/conftest.py``: a check that could not run must not report
the same result as a check that ran and passed (issue #77).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

#: Set by CI once NDI-matlab is checked out. See the module docstring.
STRICT_ENV_VAR = "NDI_BRIDGE_CHECK_STRICT"

#: Explicit override for the NDI-matlab checkout location.
MATLAB_PATH_ENV_VAR = "NDI_MATLAB_PATH"

BRIDGE_FILENAME = "ndi_matlab_python_bridge.yaml"

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Extensions that are functions or apps. Everything else under a MATLAB
#: package (icons, README.md, the .png/.gif resources beside the .mlapp
#: files) is not something a bridge file could record.
FUNCTION_SUFFIXES = (".m", ".mlapp")


@dataclass(frozen=True)
class BridgedPackage:
    """A Python package and the MATLAB package it mirrors.

    Attributes:
        python_dir: Relative to the repo root. Every bridge YAML at or
            below it is read, so a package's own file and its
            sub-packages' files all count as places an entry may live --
            which is what makes ``ndi/cloud`` one unit rather than four.
        matlab_dir: Relative to NDI-matlab's ``src/ndi``.
        excluded_layers: ``(path prefix, reason)`` for whole subtrees that
            are deliberately not bridged. A prefix, not a file list.
    """

    python_dir: str
    matlab_dir: str
    excluded_layers: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:
        return self.python_dir


#: The packages this guard covers. Adding one is a single entry -- the
#: checker itself knows nothing about ``cloud``.
#:
#: ``cloud`` is first because that is where the gaps surfaced. The six that
#: follow were added because they ALREADY pass: every MATLAB function in
#: them is recorded, by an explicit ``matlab_path``, so registering them
#: costs nothing today and locks that in. A package is worth listing the
#: moment it is clean, not once someone finds time for it -- an unguarded
#: package that happens to be complete is one commit away from not being.
#:
#: Still unlisted, with what each would need first (measured against
#: NDI-matlab main at the time of writing):
#:
#:     fun      38 unrecorded      util      10 unrecorded
#:     gui      35 unrecorded      daq        5 unrecorded
#:     time      5 unrecorded      element    3 unrecorded
#:     epoch     2 unrecorded      file       2 unrecorded
#:     probe     2 unrecorded      common     1 unrecorded
#:
#: Each needs its own pass to decide port-or-defer and write the reason;
#: adding one here before that pass would land a red test.
PACKAGES = [
    BridgedPackage(
        python_dir="src/ndi/cloud",
        matlab_dir="+ndi/+cloud",
        excluded_layers=(
            (
                "+ndi/+cloud/+api/+implementation/",
                "MATLAB's internal implementation classes behind the public +api "
                "wrappers. Every wrapper (createDataset, listDatasets, getDocument, "
                "addDocument, ...) is recorded, and Python has no equivalent layer -- "
                "CloudClient is the one implementation. Excluded as a layer so 62 "
                "entries of noise do not bury the entries that carry a decision.",
            ),
        ),
    ),
    BridgedPackage(python_dir="src/ndi/app", matlab_dir="+ndi/+app"),
    BridgedPackage(python_dir="src/ndi/calc", matlab_dir="+ndi/+calc"),
    BridgedPackage(python_dir="src/ndi/dataset", matlab_dir="+ndi/+dataset"),
    BridgedPackage(python_dir="src/ndi/mock", matlab_dir="+ndi/+mock"),
    BridgedPackage(python_dir="src/ndi/session", matlab_dir="+ndi/+session"),
    BridgedPackage(python_dir="src/ndi/validators", matlab_dir="+ndi/+validators"),
]


def matlab_root() -> Path | None:
    """The NDI-matlab ``src/ndi`` directory, or None if not checked out.

    ``$NDI_MATLAB_PATH`` (the repo root, not ``src/ndi``) when set, and
    otherwise ``../NDI-matlab`` beside this checkout -- which is both the
    usual local layout and the one the CI workflows create.

    An override that points at nothing does NOT fall back to the sibling.
    Falling back would run the check against a different tree than the one
    the caller named and report the result as if it were that tree's.
    """
    override = os.environ.get(MATLAB_PATH_ENV_VAR, "").strip()
    candidate = Path(override) if override else REPO_ROOT.parent / "NDI-matlab"
    src = candidate / "src" / "ndi"
    return src if src.is_dir() else None


def require_matlab_root() -> Path:
    """:func:`matlab_root`, skipping the test when absent -- unless strict."""
    root = matlab_root()
    if root is not None:
        return root
    message = (
        "NDI-matlab is not checked out, so bridge completeness cannot be "
        f"checked. Clone it beside this repo or set {MATLAB_PATH_ENV_VAR}."
    )
    if os.environ.get(STRICT_ENV_VAR, "").strip():
        pytest.fail(
            f"{message} ({STRICT_ENV_VAR} is set, so the tree was supposed to "
            "be there -- a missing one means the workflow stopped providing it, "
            "and skipping would report that as a pass.)"
        )
    pytest.skip(message)


# ---------------------------------------------------------------------------
# Reading a bridge file
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeIndex:
    """What a package's bridge YAMLs record, flattened for lookup.

    Attributes:
        names: Every ``name:`` and ``matlab_equivalent:`` value found at
            any depth -- so a method recording its MATLAB counterpart
            counts exactly as much as a top-level function entry.
        paths: Every ``matlab_path:`` value, normalized by
            :func:`normalize_matlab_path`. ``"N/A"`` is dropped: it means
            "no MATLAB file", which is the opposite of a reference to one.
        sources: The YAML files read, for failure messages.
    """

    names: frozenset[str]
    paths: frozenset[str]
    sources: tuple[Path, ...]

    def records(self, matlab_path: str) -> bool:
        """True if this MATLAB file is recorded, by path or by name."""
        if matlab_path in self.paths:
            return True
        # A directory-shaped matlab_path covers the package under it. The
        # SyncIndex class records "+ndi/+cloud/+sync/+internal/+index/" for
        # the three free functions its methods replace.
        if any(matlab_path.startswith(p) for p in self.paths if p.endswith("/")):
            return True
        return Path(matlab_path).stem in self.names


#: The bridge files spell matlab_path two ways. Most write it relative to
#: NDI-matlab's ``src/ndi`` ("+ndi/+cloud/authenticate.m"); a minority --
#: concentrated in app, calc and mock -- include that prefix
#: ("src/ndi/+ndi/+app/appdoc.m"). Both name the same file, so both are
#: accepted and reduced to the first form.
_MATLAB_PATH_PREFIX = "src/ndi/"


def normalize_matlab_path(value: str) -> str:
    """A ``matlab_path:`` value as a path relative to NDI-matlab/src/ndi.

    Returns ``""`` for a value that names no file (``""``, ``"N/A"``).

    Without this, an entry written in the ``src/ndi/`` style matches
    nothing by path: it silently degrades to the weaker bare-name match,
    and :meth:`TestTheBridgeFilesAreComplete.
    test_every_recorded_matlab_path_points_at_a_real_file` skips it
    entirely, so a stale path in those packages would never be caught.
    """
    normalized = value.replace("\\", "/").strip().lstrip("/")
    if not normalized or normalized == "N/A":
        return ""
    if normalized.startswith(_MATLAB_PATH_PREFIX):
        normalized = normalized[len(_MATLAB_PATH_PREFIX) :]
    return normalized


def _collect(node: Any, names: set[str], paths: set[str]) -> None:
    """Walk a parsed YAML tree, gathering names and matlab paths.

    Recursive on purpose: see the module docstring on nested entries.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("name", "matlab_equivalent") and isinstance(value, str):
                names.add(value)
            elif key == "matlab_path" and isinstance(value, str):
                normalized = normalize_matlab_path(value)
                if normalized:
                    paths.add(normalized)
            _collect(value, names, paths)
    elif isinstance(node, list):
        for item in node:
            _collect(item, names, paths)


def read_bridge_index(package: BridgedPackage) -> BridgeIndex:
    """Read every bridge YAML at or below the package's Python directory."""
    sources = sorted((REPO_ROOT / package.python_dir).rglob(BRIDGE_FILENAME))
    assert sources, f"{package.python_dir} has no {BRIDGE_FILENAME}"
    names: set[str] = set()
    paths: set[str] = set()
    for source in sources:
        _collect(yaml.safe_load(source.read_text(encoding="utf-8")), names, paths)
    return BridgeIndex(frozenset(names), frozenset(paths), tuple(sources))


def matlab_functions(package: BridgedPackage, root: Path) -> list[str]:
    """Every function and app in the MATLAB package, as bridge-style paths."""
    base = root / package.matlab_dir
    assert base.is_dir(), f"{base} is not a directory"
    return sorted(
        f"{package.matlab_dir}/{path.relative_to(base).as_posix()}"
        for path in base.rglob("*")
        if path.suffix in FUNCTION_SUFFIXES
    )


def unrecorded(package: BridgedPackage, root: Path) -> list[str]:
    """MATLAB functions with no bridge entry and no layer exclusion."""
    index = read_bridge_index(package)
    excluded = tuple(prefix for prefix, _ in package.excluded_layers)
    return [
        path
        for path in matlab_functions(package, root)
        if not path.startswith(excluded) and not index.records(path)
    ]


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


class TestTheBridgeFilesAreComplete:
    @pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.id)
    def test_every_matlab_function_is_recorded(self, package: BridgedPackage):
        """The regression guard.

        A MATLAB function that is neither recorded nor excluded fails here.
        Two ways to fix it, and both are fine: port it and add a
        ``functions:`` entry, or add a ``not_yet_ported`` /
        ``not_applicable`` entry saying why not. What is not fine is
        silence, which is what let five of these accumulate.
        """
        missing = unrecorded(package, require_matlab_root())
        assert not missing, (
            f"{len(missing)} MATLAB function(s) under {package.matlab_dir} have no "
            f"entry in any {BRIDGE_FILENAME} below {package.python_dir}:\n  "
            + "\n  ".join(missing)
            + "\n\nAdd an entry recording the port, or one with "
            "status: not_yet_ported / not_applicable and a decision_log "
            "saying why there is none."
        )

    @pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.id)
    def test_every_recorded_matlab_path_points_at_a_real_file(self, package: BridgedPackage):
        """The other direction: an entry naming a file MATLAB no longer has.

        A renamed or removed MATLAB function leaves its entry pointing at
        nothing, and the entry then looks maintained while describing a
        file that does not exist. This found three when it was written: a
        function that moved package (+api/+files -> +api/+documents) and
        two that MATLAB deleted, whose entries are deliberate but should
        say ``matlab_path: "N/A"``.
        """
        root = require_matlab_root()
        index = read_bridge_index(package)
        prefix = f"{package.matlab_dir}/"
        stale = sorted(
            path for path in index.paths if path.startswith(prefix) and not (root / path).exists()
        )
        assert not stale, (
            f"{BRIDGE_FILENAME} entries under {package.python_dir} name MATLAB "
            "files that do not exist:\n  "
            + "\n  ".join(stale)
            + '\n\nPoint each at its new path, or set matlab_path: "N/A" and say '
            "in the decision_log that MATLAB removed it."
        )

    @pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.id)
    def test_every_excluded_layer_still_exists(self, package: BridgedPackage):
        """An exclusion for a directory MATLAB no longer has is stale.

        Left in place it would silently keep excluding whatever later takes
        that path -- an exclusion nobody decided on.
        """
        root = require_matlab_root()
        for prefix, reason in package.excluded_layers:
            assert (root / prefix).is_dir(), (
                f"excluded layer {prefix!r} is not a directory in NDI-matlab. "
                f"The exclusion's reason was: {reason}"
            )

    @pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.id)
    def test_every_excluded_layer_carries_a_reason(self, package: BridgedPackage):
        """An exclusion without a reason is indistinguishable from an omission."""
        for prefix, reason in package.excluded_layers:
            assert len(reason.split()) >= 10, f"exclusion {prefix!r} needs a real reason"


class TestTheDeferralsSayWhy:
    """``not_yet_ported`` and ``not_applicable`` are decisions, not labels.

    An entry that records a status but no reason passes the completeness
    check above while telling the next reader nothing -- so the gap is
    "recorded" and still gets re-investigated, which is exactly what #131
    set out to stop.
    """

    @pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.id)
    def test_every_status_entry_has_a_decision_log(self, package: BridgedPackage):
        undocumented = []
        for source in sorted((REPO_ROOT / package.python_dir).rglob(BRIDGE_FILENAME)):
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in _entries_with_status(data):
                if len((entry.get("decision_log") or "").split()) < 5:
                    name = entry.get("name", "<unnamed>")
                    undocumented.append(f"{source.relative_to(REPO_ROOT)}: {name}")
        assert (
            not undocumented
        ), "bridge entries with a status but no decision_log explaining it:\n  " + "\n  ".join(
            undocumented
        )


def _entries_with_status(node: Any) -> list[dict[str, Any]]:
    """Every mapping in the tree that carries a ``status:`` key."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("status"), str):
            found.append(node)
        for value in node.values():
            found.extend(_entries_with_status(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_entries_with_status(item))
    return found


class TestTheGuardWouldActuallyCatchOne:
    """A guard that cannot fail is worse than none. These prove it can."""

    def test_an_unrecorded_function_is_reported(self, tmp_path):
        index = BridgeIndex(frozenset({"uploadDataset"}), frozenset(), ())
        assert index.records("+ndi/+cloud/uploadDataset.m")
        assert not index.records("+ndi/+cloud/helloMatlab.m")

    def test_a_matlab_path_entry_counts(self):
        index = BridgeIndex(frozenset(), frozenset({"+ndi/+cloud/helloMatlab.m"}), ())
        assert index.records("+ndi/+cloud/helloMatlab.m")

    def test_na_is_not_a_reference_to_anything(self):
        """``matlab_path: "N/A"`` marks a Python-only entry. Treating it as a
        path would make every such entry vouch for a MATLAB file named N/A."""
        names: set[str] = set()
        paths: set[str] = set()
        _collect({"matlab_path": "N/A"}, names, paths)
        assert paths == set()

    def test_the_real_cloud_package_is_currently_complete(self):
        """What the parametrized guard asserts, stated once as the claim
        #131 makes: nothing under +ndi/+cloud is unrecorded any more."""
        root = require_matlab_root()
        assert unrecorded(PACKAGES[0], root) == []

    @pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.id)
    def test_a_new_matlab_function_in_any_covered_package_would_fail(self, package):
        """Every registered package really is guarded, not merely listed.

        Proved by asking whether a function MATLAB does not have would be
        reported -- which is what a newly added .m file is on the day it
        lands. A package whose bridge somehow matched everything would
        pass the completeness test while checking nothing, and this is
        the difference.
        """
        index = read_bridge_index(package)
        assert not index.records(f"{package.matlab_dir}/aFunctionNobodyHasWritten.m")


class TestBothMatlabPathConventions:
    """The bridge files spell matlab_path two ways, and both must work.

    369 entries are relative to NDI-matlab's ``src/ndi``; 16 -- in app,
    calc and mock -- carry that prefix. Before this was handled, those 16
    matched no path at all: they fell through to the weaker bare-name
    match, and the stale-path check skipped them entirely. Registering
    those packages would then have been cosmetic, which is how this was
    found.
    """

    @pytest.mark.parametrize(
        "written,expected",
        [
            ("+ndi/+app/appdoc.m", "+ndi/+app/appdoc.m"),
            ("src/ndi/+ndi/+app/appdoc.m", "+ndi/+app/appdoc.m"),
            ("/+ndi/+app/appdoc.m", "+ndi/+app/appdoc.m"),
            ("+ndi\\+app\\appdoc.m", "+ndi/+app/appdoc.m"),
            ("  +ndi/+app/appdoc.m  ", "+ndi/+app/appdoc.m"),
            ("N/A", ""),
            ("", ""),
        ],
    )
    def test_both_spellings_reduce_to_one(self, written, expected):
        assert normalize_matlab_path(written) == expected

    def test_a_prefixed_entry_matches_by_path_not_by_luck(self):
        names: set[str] = set()
        paths: set[str] = set()
        _collect({"name": "appdoc", "matlab_path": "src/ndi/+ndi/+app/appdoc.m"}, names, paths)
        index = BridgeIndex(frozenset(), frozenset(paths), ())
        assert index.records("+ndi/+app/appdoc.m"), "the name was deliberately withheld"

    def test_the_prefixed_packages_really_do_match_by_path(self):
        """Not a synthetic case: app, calc and mock are registered above on
        the strength of this, so if it stops holding they are being guarded
        by bare names and the registration should be revisited."""
        root = require_matlab_root()
        for package in PACKAGES:
            if package.python_dir not in ("src/ndi/app", "src/ndi/calc", "src/ndi/mock"):
                continue
            index = read_bridge_index(package)
            for path in matlab_functions(package, root):
                assert path in index.paths, f"{path} is matched only by name"

    def test_a_prefixed_stale_path_is_now_caught(self):
        """The consequence that matters: before normalizing, a
        ``src/ndi/``-style entry naming a deleted file was invisible to the
        stale-path check, because the check filters on the bare prefix."""
        root = require_matlab_root()
        stale = normalize_matlab_path("src/ndi/+ndi/+app/deletedLongAgo.m")
        assert stale.startswith("+ndi/+app/"), "must survive the check's prefix filter"
        assert not (root / stale).exists()


class TestNestedEntriesCount:
    """The false-alarm trap, tested directly.

    ``readSyncIndex`` is recorded nowhere as a top-level ``name:``. It is a
    ``matlab_equivalent:`` on ``SyncIndex.read``, three levels down. A
    checker that misses that reports the sync index as missing -- which is
    what the first pass in #131 did.
    """

    def test_a_matlab_equivalent_on_a_method_is_a_record(self):
        names: set[str] = set()
        paths: set[str] = set()
        _collect(
            {
                "classes": [
                    {
                        "name": "SyncIndex",
                        "methods": [{"name": "read", "matlab_equivalent": "readSyncIndex"}],
                    }
                ]
            },
            names,
            paths,
        )
        assert "readSyncIndex" in names

    def test_the_real_sync_index_is_recorded_that_way(self):
        """Not a synthetic case -- this is how ndi/cloud/sync records it."""
        index = read_bridge_index(PACKAGES[0])
        for name in ("readSyncIndex", "writeSyncIndex", "updateSyncIndex"):
            assert name in index.names, f"{name} is no longer recorded on SyncIndex"

    def test_a_directory_matlab_path_covers_the_package_under_it(self):
        index = BridgeIndex(frozenset(), frozenset({"+ndi/+cloud/+sync/+internal/+index/"}), ())
        assert index.records("+ndi/+cloud/+sync/+internal/+index/readSyncIndex.m")
        assert not index.records("+ndi/+cloud/+sync/documentDifference.m")


class TestTheImplementationLayerExclusion:
    """The 62 files, and why they are excluded as a layer rather than listed."""

    def test_the_layer_is_excluded_not_the_files(self):
        ((prefix, _),) = PACKAGES[0].excluded_layers
        assert prefix.endswith("/"), "a layer exclusion is a directory prefix"

    def test_the_public_wrappers_are_still_required_to_be_recorded(self):
        """The exclusion covers +api/+implementation/ only. If it leaked to
        +api/ the wrappers would stop being checked, and that is the half
        that matters."""
        package = PACKAGES[0]
        excluded = tuple(prefix for prefix, _ in package.excluded_layers)
        assert not "+ndi/+cloud/+api/datasets/createDataset.m".startswith(excluded)
        assert "+ndi/+cloud/+api/+implementation/+datasets/CreateDataset.m".startswith(excluded)

    def test_it_covers_the_whole_layer(self):
        """Roughly 60 files, so a count that collapses means the prefix
        stopped matching and the layer is silently being checked (or, worse,
        silently excluded from somewhere else)."""
        root = require_matlab_root()
        package = PACKAGES[0]
        excluded = tuple(prefix for prefix, _ in package.excluded_layers)
        covered = [f for f in matlab_functions(package, root) if f.startswith(excluded)]
        assert len(covered) > 50


if __name__ == "__main__":
    pytest.main([__file__])
