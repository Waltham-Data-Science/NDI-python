"""
Regression tests for the sync index -- NDI-python issue #101.

The index at ``<dataset>/.ndi/sync/index.json`` is the record of what sync
has already done. Three things were wrong with it:

1. ``write`` opened the file with mode ``"w"``, which truncates *before*
   ``flock`` was called, so the lock protected nothing.
2. ``read`` took no lock, so a reader racing a writer could see the
   truncated file and raise ``JSONDecodeError`` -- or read an empty index
   and conclude nothing had ever been synced.
3. ``import fcntl`` at module level made the whole sync package
   unimportable on Windows.

All three are answered by writing to a temp file and ``os.replace``-ing it
into place. These tests pin that down.
"""

import ast
import json
import multiprocessing
import sys
from pathlib import Path

import pytest

from ndi.cloud.sync.index import SyncIndex

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "ndi"

#: Standard-library modules that do not exist on Windows. A module-level
#: import of any of these makes every importer of it Windows-fatal.
POSIX_ONLY_MODULES = {
    "fcntl",
    "termios",
    "tty",
    "pty",
    "pwd",
    "grp",
    "crypt",
    "posix",
    "resource",
    "syslog",
    "nis",
    "spwd",
}


# ===========================================================================
# 3. Windows importability
# ===========================================================================


def _module_level_imports(tree: ast.Module) -> set[str]:
    """Top-level module names imported at module scope (not inside a def/if)."""
    names: set[str] = set()
    for node in tree.body:  # module scope only -- a lazy import is fine
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


class TestNoPosixOnlyImports:
    def test_sync_index_does_not_import_fcntl(self):
        tree = ast.parse((SRC_ROOT / "cloud" / "sync" / "index.py").read_text())
        assert "fcntl" not in _module_level_imports(tree)

    def test_no_module_in_src_imports_a_posix_only_module(self):
        """A single one of these anywhere in ``ndi`` breaks Windows for
        every importer of that module. CI is Linux-only, so nothing else
        catches it."""
        offenders = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - would fail elsewhere
                continue
            bad = _module_level_imports(tree) & POSIX_ONLY_MODULES
            if bad:
                offenders.append(f"{path.relative_to(SRC_ROOT.parent.parent)}: {sorted(bad)}")
        assert not offenders, "POSIX-only imports at module scope:\n" + "\n".join(offenders)


# ===========================================================================
# 1 & 2. The write is atomic and never exposes a truncated file
# ===========================================================================


class TestAtomicWrite:
    def test_a_reader_never_sees_a_truncated_file(self, tmp_path):
        """Rewrite the index many times and read it back after each write.
        Under the old truncate-then-lock code the window was real; here the
        replace is atomic, so every read must parse."""
        idx = SyncIndex()
        for n in range(50):
            idx.update([f"local-{i}" for i in range(n)], [f"remote-{i}" for i in range(n)])
            idx.write(tmp_path)
            loaded = SyncIndex.read(tmp_path)
            assert len(loaded.local_doc_ids_last_sync) == n

    def test_an_existing_index_survives_a_failed_write(self, tmp_path, monkeypatch):
        """The old code destroyed the previous contents the moment it opened
        the file. An atomic write must leave them intact if the new write
        cannot complete."""
        good = SyncIndex()
        good.update(["keep-me"], ["keep-me-too"])
        good.write(tmp_path)

        import os as os_module

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(os_module, "replace", boom)

        doomed = SyncIndex()
        doomed.update(["clobbered"], [])
        with pytest.raises(OSError):
            doomed.write(tmp_path)

        reloaded = SyncIndex.read(tmp_path)
        assert reloaded.local_doc_ids_last_sync == ["keep-me"]
        assert reloaded.remote_doc_ids_last_sync == ["keep-me-too"]

    def test_a_failed_write_leaves_no_temp_file_behind(self, tmp_path, monkeypatch):
        SyncIndex().write(tmp_path)
        sync_dir = tmp_path / ".ndi" / "sync"

        import os as os_module

        monkeypatch.setattr(
            os_module, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
        )
        with pytest.raises(OSError):
            SyncIndex().write(tmp_path)

        assert sorted(p.name for p in sync_dir.iterdir()) == ["index.json"]

    def test_write_leaves_no_temp_file_on_success(self, tmp_path):
        idx = SyncIndex()
        idx.update(["a"], ["b"])
        idx.write(tmp_path)
        idx.write(tmp_path)
        sync_dir = tmp_path / ".ndi" / "sync"
        assert sorted(p.name for p in sync_dir.iterdir()) == ["index.json"]

    def test_the_written_file_is_still_the_documented_json(self, tmp_path):
        idx = SyncIndex()
        idx.update(["d1", "d2"], ["r1"])
        idx.write(tmp_path)
        raw = json.loads((tmp_path / ".ndi" / "sync" / "index.json").read_text())
        assert raw["local_doc_ids_last_sync"] == ["d1", "d2"]
        assert raw["remote_doc_ids_last_sync"] == ["r1"]
        assert raw["last_sync_timestamp"]


# ---------------------------------------------------------------------------
# The concurrency test proper: a writer process hammering the index while a
# reader process reads it. Every read must yield a complete, parseable index.
# ---------------------------------------------------------------------------


def _writer(dataset_path: str, rounds: int) -> None:
    idx = SyncIndex()
    for n in range(rounds):
        # A payload big enough that a non-atomic write would take more than
        # one filesystem block, widening the torn-read window.
        idx.update([f"local-{i:06d}" for i in range(n % 400)], ["remote"])
        idx.write(Path(dataset_path))


def _reader(dataset_path: str, rounds: int, errors) -> None:
    for _ in range(rounds):
        try:
            SyncIndex.read(Path(dataset_path))
        except Exception as exc:  # JSONDecodeError under the old code
            errors.append(repr(exc))
            return


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="fork-based multiprocessing; the atomicity itself is platform-independent",
)
def test_concurrent_read_during_write_never_sees_a_partial_index(tmp_path):
    SyncIndex().write(tmp_path)

    ctx = multiprocessing.get_context("fork") if hasattr(multiprocessing, "get_context") else None
    if ctx is None:  # pragma: no cover
        pytest.skip("no fork context")

    manager = ctx.Manager()
    errors = manager.list()

    writer = ctx.Process(target=_writer, args=(str(tmp_path), 300))
    readers = [ctx.Process(target=_reader, args=(str(tmp_path), 300, errors)) for _ in range(3)]

    writer.start()
    for r in readers:
        r.start()
    writer.join(60)
    for r in readers:
        r.join(60)

    assert not list(errors), f"readers saw a partial index: {list(errors)[:3]}"
