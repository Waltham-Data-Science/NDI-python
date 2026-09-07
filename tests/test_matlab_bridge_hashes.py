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

WHAT THIS DOES NOT CHECK. Whether an entry is *stale* -- that is
NDI-python#191, and needs a sweep of 61 entries plus a policy for the 143
entries that carry no hash at all. This test is the precondition: a
freshness check cannot be written until every hash present is walkable.

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
