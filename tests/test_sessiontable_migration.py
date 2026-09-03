"""ndi.session.sessiontable: one-time migration from legacy ~/.ndi/preferences/.

Since NDI-python #172 the default table file lives at
``~/.ndi/local_sessiontable.txt`` (parity with MATLAB via
NDI-matlab #922). Any table under the old
``~/.ndi/preferences/local_sessiontable.txt`` is migrated on first
instantiation so upgraders do not lose their registry.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from ndi.session.sessiontable import ndi_session_sessiontable


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a scratch directory for the duration of the test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_new_location_is_flat_under_ndi(fake_home):
    table = ndi_session_sessiontable()
    assert table._table_path == fake_home / ".ndi" / "local_sessiontable.txt"


def test_migration_copies_legacy_table_on_first_init(fake_home):
    legacy = fake_home / ".ndi" / "preferences" / "local_sessiontable.txt"
    _write(legacy, "session_id\tpath\nabc\t/data/one\n")

    table = ndi_session_sessiontable()

    new = fake_home / ".ndi" / "local_sessiontable.txt"
    assert new.is_file(), "migration should have copied the legacy file"
    assert new.read_text() == legacy.read_text()
    # Legacy left in place so a downgrade still works.
    assert legacy.is_file()
    entries = table.getsessiontable()
    assert entries == [{"session_id": "abc", "path": "/data/one"}]


def test_migration_also_copies_backup_siblings(fake_home):
    legacy = fake_home / ".ndi" / "preferences" / "local_sessiontable.txt"
    _write(legacy, "session_id\tpath\nabc\t/data/one\n")
    _write(legacy.parent / "local_sessiontable_bkup001.txt", "old-1")
    _write(legacy.parent / "local_sessiontable_bkup002.txt", "old-2")

    ndi_session_sessiontable()

    new_dir = fake_home / ".ndi"
    assert (new_dir / "local_sessiontable_bkup001.txt").read_text() == "old-1"
    assert (new_dir / "local_sessiontable_bkup002.txt").read_text() == "old-2"


def test_migration_is_no_op_when_new_file_exists(fake_home):
    new = fake_home / ".ndi" / "local_sessiontable.txt"
    _write(new, "session_id\tpath\nkeep\t/data/keep\n")
    legacy = fake_home / ".ndi" / "preferences" / "local_sessiontable.txt"
    _write(legacy, "session_id\tpath\nshould_not_win\t/data/nope\n")

    ndi_session_sessiontable()

    # New location wins; legacy content is not copied over the top.
    assert (
        new.read_text() == "session_id\tpath\nkeep\t/data/keep\n"
    ), "migration must not overwrite an existing new-location file"


def test_migration_no_op_when_no_legacy_present(fake_home):
    ndi_session_sessiontable()
    assert not (fake_home / ".ndi" / "local_sessiontable.txt").exists()


def test_migration_failure_is_warned_not_raised(fake_home):
    legacy = fake_home / ".ndi" / "preferences" / "local_sessiontable.txt"
    _write(legacy, "session_id\tpath\nabc\t/data/one\n")

    with patch.object(shutil, "copy2", side_effect=OSError("simulated")):
        with pytest.warns(UserWarning, match="Could not migrate legacy sessiontable"):
            ndi_session_sessiontable()

    # Should still be usable -- just with an empty table under the new path.
    table = ndi_session_sessiontable()
    # Second call: copy2 was patched only inside the with block.
    assert isinstance(table.getsessiontable(), list)


def test_custom_table_path_does_not_trigger_migration(fake_home, tmp_path):
    legacy = fake_home / ".ndi" / "preferences" / "local_sessiontable.txt"
    _write(legacy, "session_id\tpath\nabc\t/data/one\n")
    custom = tmp_path / "custom.txt"

    ndi_session_sessiontable(table_path=custom)

    # Only the default-path constructor migrates. Custom paths are left alone.
    assert not (fake_home / ".ndi" / "local_sessiontable.txt").exists()
    assert not custom.exists()
