"""``matlab_last_sync_hash`` names a COMMIT in NDI-matlab, never a blob.

MATLAB counterpart: every ``ndi_matlab_python_bridge.yaml`` against the
NDI-matlab object store.

The field records the point in NDI-matlab's history an entry was last
examined against, so a later reader can ask whether the file has moved:

    git log <matlab_last_sync_hash>..HEAD -- <matlab_path>

That question only has an answer if the value is a **commit**. It is not
the only plausible thing to put there, which is the whole problem:
``git hash-object <file>`` returns the hash of the file's *contents*, is
the same shape, looks equally reasonable in the YAML, and is silently
useless -- a blob is not a point in history to walk from.

WHY THIS TEST EXISTS. 35 entries carried blob hashes. Nothing caught them,
and two things conspired to keep it that way:

* The written spec was ambiguous. It said "the short git hash of the MATLAB
  .m file", which reads as the hash OF THE FILE, while the command beside it
  (``git log -1 --format=%h``) yields a commit. Both readings were in use.
* ``git log <blob>..HEAD -- <path>`` does not error. It returns commits, so
  a freshness sweep counts a blob-hash entry as merely *stale* rather than
  unusable. ``git diff`` is what rejects it. A wrong answer, not an error.

All 35 were recovered by walking each file's history and comparing
``git rev-parse <commit>:<path>`` against the recorded blob, and 24 of them
turned out to be current -- the ports were fine, only the field was the
wrong kind of hash. This test is what stops the next one.

EITHER KIND OF COMMIT IS FINE, and both are in use: the file's own
last-touching commit (what the documented command gives), or a repo-wide
commit such as NDI-matlab ``HEAD`` when a batch of entries was examined
together -- 123 entries share a handful of such commits. Both are points in
history, so both answer the freshness question. This test therefore checks
the object TYPE and nothing more; it deliberately does not require the
commit to touch the file it is recorded against.

DRIFT IS ALSO CHECKED HERE, as of NDI-python#211. An entry DRIFTS when
NDI-matlab has commits touching its ``matlab_path`` after its recorded hash.
That falsifies what the entry claims: "ported" asserts that this Python
matches that MATLAB, and once MATLAB moves the assertion is unverified until
somebody reads the diff. Red is the honest state.

THE DRIFT CHECK IS PATH-FILTERED, always::

    git log <matlab_last_sync_hash>..HEAD -- <matlab_path>

so unrelated activity in NDI-matlab never trips it. That is why BOTH hash
forms stay legal -- the file's own last-touching commit, or a repo-wide
commit from a batch sync. 103 entries record the latter, their files have
not moved, and their records are true; a rule demanding the hash EQUAL the
file's last commit would fail all 103 for bookkeeping and teach everyone to
ignore the check.

AND EVERY ENTRY NAMING A matlab_path MUST CARRY A HASH. One without a hash
can never drift, so it claims its port is current forever and no check can
contradict it -- the same false assurance as a stale hash, but silent rather
than red. 147 entries were in that state when the gate went up.

Neither check imposes a ``decision_log`` obligation. That field explains a
DIVERGENCE, and a regular port has none; re-examining one against a newer
MATLAB commit and finding nothing to follow does not create one. The bumped
hash is itself the record of examination.

WHERE THE MATLAB TREE COMES FROM
Same rule as the completeness guard it sits beside: absent, the check
skips -- unless ``NDI_BRIDGE_CHECK_STRICT`` is set, which CI does after
checking the repo out, so a workflow that stops providing the tree fails
instead of quietly passing (issue #77).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from tests.test_matlab_bridge_completeness import (
    BRIDGE_FILENAME,
    REPO_ROOT,
    normalize_matlab_path,
    require_matlab_root,
)


def matlab_repo() -> Path:
    """The NDI-matlab repository root -- the directory git works from.

    :func:`require_matlab_root` returns ``<repo>/src/ndi``; git needs the
    repo above it.
    """
    return require_matlab_root().parent.parent


def require_full_history(repo: Path) -> None:
    """Fail if the NDI-matlab checkout is shallow.

    A shallow clone holds only the tip commit, so every recorded hash comes
    back "missing" and this check reports the whole bridge as broken --
    a confident wrong answer, which is worse than not running. CI therefore
    checks NDI-matlab out with ``fetch-depth: 0``; this says so out loud if
    that is ever dropped, rather than emitting 336 false failures.
    """
    shallow = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert shallow != "true", (
        f"the NDI-matlab checkout at {repo} is shallow, so recorded commits "
        "cannot be resolved and every entry would look broken. Clone with full "
        "history (CI: fetch-depth: 0 on the NDI-matlab checkout step)."
    )


def git_object_type(repo: Path, revision: str) -> str:
    """``commit`` / ``blob`` / ``tree`` / ``tag``, or ``missing``.

    ``missing`` covers a hash that resolves to nothing at all, which is a
    different mistake from recording the wrong KIND of object and is worth
    saying differently in the failure.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", revision],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "missing"


def entries_with_a_sync_hash(node: Any) -> list[dict[str, Any]]:
    """Every mapping carrying both a ``matlab_path`` and a sync hash.

    Recursive: bridge entries live at several depths, and a nested one
    counts, exactly as in the completeness guard.
    """
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("matlab_path"), str) and isinstance(
            node.get("matlab_last_sync_hash"), str
        ):
            found.append(node)
        for value in node.values():
            found.extend(entries_with_a_sync_hash(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(entries_with_a_sync_hash(item))
    return found


def display_path(source: Path) -> str:
    """A bridge file as repo-relative text, or its own path when outside.

    Every bridge file shares a filename, so the directory is the only part
    that identifies it; the fallback keeps the guard tests below able to
    pass a temporary file.
    """
    try:
        return str(source.relative_to(REPO_ROOT))
    except ValueError:
        return source.name


def bridge_files() -> list[Path]:
    """Every bridge YAML in the tree.

    A plain glob rather than a walk of the bridged packages: three of these
    files sit directly in ``src/ndi/`` under no package
    (``ndi_matlab_python_bridge_database*.yaml``) and the package-driven
    walk never reaches them, which is how a stale entry survived there.
    """
    found = set(REPO_ROOT.glob(f"src/**/{BRIDGE_FILENAME}"))
    found |= set(REPO_ROOT.glob("src/ndi/ndi_matlab_python_bridge_*.yaml"))
    return sorted(found)


def not_commits(repo: Path, sources: list[Path]) -> list[str]:
    """Entries whose ``matlab_last_sync_hash`` is not a commit."""
    offenders = []
    for source in sources:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        for entry in entries_with_a_sync_hash(data):
            if not normalize_matlab_path(entry["matlab_path"]):
                continue
            sync_hash = entry["matlab_last_sync_hash"]
            kind = git_object_type(repo, sync_hash)
            if kind != "commit":
                name = entry.get("name", "<unnamed>")
                offenders.append(f"{display_path(source)}: {name} -- {sync_hash!r} is a {kind}")
    return offenders


ALLOWLIST = REPO_ROOT / "tests" / "bridge_drift_allowlist.yaml"

#: A real MATLAB path starts with the package prefix. Everything else is a
#: placeholder naming no file -- ``"N/A"``, ``"n/a (Python only)"``,
#: ``"(inline in getData.m)"``. This is the same rule the completeness
#: guard's stale-path check already relies on (it filters on the package
#: prefix), stated here rather than re-derived: `normalize_matlab_path`
#: strips only the exact string ``"N/A"``, so the other placeholders survive
#: it and would otherwise be treated as files.
MATLAB_PATH_PREFIX = "+ndi/"


def matlab_file(entry: dict[str, Any]) -> str:
    """The entry's MATLAB path, or ``""`` when it names no file."""
    path = normalize_matlab_path(entry.get("matlab_path") or "")
    return path if path.startswith(MATLAB_PATH_PREFIX) else ""


def allowlisted() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """The pre-existing debt, as ``(drifted, missing-a-hash)`` key sets.

    Keys are ``(matlab_path, name)`` -- the same key the duplicate guard
    uses, because several entries may legitimately share one path.
    """
    data = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}

    def keys(section: str) -> set[tuple[str, str]]:
        return {
            (normalize_matlab_path(e["matlab_path"]), e["name"]) for e in (data.get(section) or [])
        }

    return keys("drifted"), keys("no_hash")


def drift_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (matlab_file(entry), entry.get("name", "<unnamed>"))


def has_drifted(repo: Path, entry: dict[str, Any]) -> bool:
    """Have commits touching this entry's MATLAB file landed since its hash?

    Path-filtered on purpose: an unrelated commit elsewhere in NDI-matlab is
    not this entry's problem and must not turn CI red.
    """
    full = f"src/ndi/{matlab_file(entry)}"
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            f"{entry['matlab_last_sync_hash']}..HEAD",
            "--oneline",
            "--",
            full,
        ],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def entries_with_a_matlab_path(node: Any) -> list[dict[str, Any]]:
    """Every mapping naming a real ``matlab_path``, hash or no hash."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if matlab_file(node):
            found.append(node)
        for value in node.values():
            found.extend(entries_with_a_matlab_path(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(entries_with_a_matlab_path(item))
    return found


class TestNothingDriftsFromMatlab:
    """The gate. NDI-python#211.

    A ``ported`` entry is a claim that this Python matches that MATLAB. When
    MATLAB moves, the claim is no longer known to be true, so CI goes red
    until a human reads the diff and either ports the change or confirms
    there is nothing to follow.
    """

    def test_no_entry_has_drifted(self):
        repo = matlab_repo()
        require_full_history(repo)
        allowed, _ = allowlisted()
        offenders = []
        for source in bridge_files():
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in entries_with_a_sync_hash(data):
                if not matlab_file(entry):
                    continue
                key = drift_key(entry)
                if key in allowed:
                    continue
                full = repo / "src" / "ndi" / key[0]
                if not full.exists():
                    continue
                if has_drifted(repo, entry):
                    offenders.append(
                        f"{display_path(source)}: {key[1]} ({key[0]}) -- MATLAB has "
                        f"moved since {entry['matlab_last_sync_hash']}"
                    )
        assert not offenders, (
            "these bridge entries have drifted -- NDI-matlab changed the file after "
            "the commit the entry was examined against, so the port is no longer "
            "known to match:\n  " + "\n  ".join(offenders) + "\n\n"
            "Read the diff:\n"
            "    git -C ../NDI-matlab diff <matlab_last_sync_hash>..HEAD -- src/ndi/<matlab_path>\n"
            "then port the behavioural change and bump the hash, or -- if nothing on "
            "the Python side must follow -- just bump it. No decision_log is required "
            "for a regular port. See section 7 of "
            "docs/developer_notes/ndi_matlab_python_bridge.yaml."
        )

    def test_every_matlab_path_entry_carries_a_hash(self):
        """An entry with no hash can never drift, so it claims its port is
        current forever. Needs no MATLAB checkout -- it reads only this repo,
        so it runs in every job rather than the bridge job alone."""
        _, allowed = allowlisted()
        offenders = []
        for source in bridge_files():
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in entries_with_a_matlab_path(data):
                if isinstance(entry.get("matlab_last_sync_hash"), str):
                    continue
                key = drift_key(entry)
                if key in allowed:
                    continue
                offenders.append(f"{display_path(source)}: {key[1]} ({key[0]})")
        assert not offenders, (
            "these entries name a matlab_path but record no matlab_last_sync_hash, "
            "so nothing can ever detect them drifting:\n  "
            + "\n  ".join(offenders)
            + "\n\nRecord the commit you examined the file against:\n"
            "    git -C ../NDI-matlab log -1 --format=%h -- src/ndi/<matlab_path>"
        )


class TestTheAllowlistOnlyShrinks:
    """A burn-down list that keeps entries it no longer needs is just a
    permanent exemption with extra steps.
    """

    def test_the_allowlist_has_no_stale_entries(self):
        repo = matlab_repo()
        require_full_history(repo)
        drifted_allowed, nohash_allowed = allowlisted()
        live_drifted, live_nohash = set(), set()
        for source in bridge_files():
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in entries_with_a_matlab_path(data):
                key = drift_key(entry)
                if not isinstance(entry.get("matlab_last_sync_hash"), str):
                    live_nohash.add(key)
                    continue
                if not (repo / "src" / "ndi" / key[0]).exists():
                    continue
                if has_drifted(repo, entry):
                    live_drifted.add(key)
        fixed = sorted(
            [f"drifted: {n} ({p})" for p, n in drifted_allowed - live_drifted]
            + [f"no_hash: {n} ({p})" for p, n in nohash_allowed - live_nohash]
        )
        assert not fixed, (
            "these entries are listed in tests/bridge_drift_allowlist.yaml but no "
            "longer need to be -- delete them from it:\n  "
            + "\n  ".join(fixed)
            + "\n\nThe list is a burn-down, not a permanent exemption: an entry that "
            "has been fixed must leave it in the same PR, so the file only shrinks."
        )


class TestEverySyncHashIsACommit:
    def test_no_bridge_entry_records_a_blob(self):
        repo = matlab_repo()
        require_full_history(repo)
        offenders = not_commits(repo, bridge_files())
        assert not offenders, (
            "matlab_last_sync_hash must name a commit in NDI-matlab:\n  "
            + "\n  ".join(offenders)
            + "\n\nA blob is what `git hash-object <file>` returns -- the hash of the "
            "file's contents, which cannot be walked from. Use the commit you "
            "examined against:\n"
            "    git log -1 --format=%h -- <matlab_path>\n"
            "A repo-wide commit (NDI-matlab HEAD when you examined a batch) is "
            "equally fine. See docs/developer_notes/PYTHON_PORTING_GUIDE.md section 3."
        )


class TestTheGuardWouldActuallyCatchOne:
    """The check passes on a clean tree, which is also what a check that
    inspects nothing does. These build the two failures by hand.
    """

    @staticmethod
    def _bridge(tmp_path: Path, sync_hash: str) -> list[Path]:
        source = tmp_path / BRIDGE_FILENAME
        source.write_text(
            "functions:\n"
            "  - name: readTileFile\n"
            '    matlab_path: "+ndi/+fun/+doc/+gene/readTileFile.m"\n'
            f'    matlab_last_sync_hash: "{sync_hash}"\n',
            encoding="utf-8",
        )
        return [source]

    def test_a_blob_hash_is_reported(self, tmp_path):
        """The exact mistake that put 35 blob hashes in the tree.

        The blob is taken from whatever NDI-matlab actually tracks rather
        than a named file, so the guard cannot quietly start skipping if
        that file is renamed.
        """
        repo = matlab_repo()
        listing = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "HEAD", "--name-only", "src/ndi"],
            capture_output=True,
            text=True,
        )
        tracked = [line for line in listing.stdout.split("\n") if line.strip()]
        assert tracked, "NDI-matlab checkout tracks no files under src/ndi"
        blob = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", f"HEAD:{tracked[0]}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert git_object_type(repo, blob) == "blob", "fixture must be a blob"

        offenders = not_commits(repo, self._bridge(tmp_path, blob))
        assert len(offenders) == 1
        assert "is a blob" in offenders[0]

    def test_a_hash_that_resolves_to_nothing_is_reported(self, tmp_path):
        """Four entries carried ``234c356``, which is no object at all."""
        offenders = not_commits(matlab_repo(), self._bridge(tmp_path, "234c356"))
        assert len(offenders) == 1
        assert "is a missing" in offenders[0]

    def test_a_real_commit_passes(self, tmp_path):
        repo = matlab_repo()
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert not_commits(repo, self._bridge(tmp_path, head)) == []
