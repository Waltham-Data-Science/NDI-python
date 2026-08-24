"""SQLite handles must be closed before a session/dataset ``.ndi`` is removed.

Port of the NDI-matlab fix for issue #870 (``71758b893``, then ``26d0638bf``
which widened ``mksqlite('close')`` to ``mksqlite(0,'close')`` so that *every*
open connection is closed, not just dbid 1). MATLAB's erase paths called
``rmdir`` while the SQLite handle on ``did-sqlite.sqlite`` was still open; on
Windows an open file cannot be deleted, so the erase failed with
``MATLAB:RMDIR:SomeDirectoriesNotRemoved``.

Python has the identical exposure: DID-python's ``SQLiteDB`` opens a
``sqlite3.Connection`` in its constructor and holds it in ``self.dbid`` until
``close()`` is called -- it is never reopened lazily -- and NDI's three erase
paths called ``shutil.rmtree`` without closing it.

POSIX happily unlinks an open file, so on macOS/Linux a "did rmtree succeed?"
test is green whether or not the fix is present and proves nothing. These
tests instead assert the thing that actually differs: that the connection
object is closed, and that it is closed *before* the tree is removed.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from ndi.dataset._dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.session.dir import ndi_session_dir


def _live_connection(session) -> sqlite3.Connection:
    """Return the open sqlite3 connection backing *session*'s database.

    Fails loudly rather than skipping if the driver stack ever stops holding a
    connection, so this test cannot quietly stop testing anything.
    """
    database = session.database
    assert database is not None, "session has no database"
    conn = database._driver._db.dbid
    assert isinstance(conn, sqlite3.Connection), (
        f"expected a live sqlite3.Connection on the DID driver, got {conn!r}; "
        f"the driver stack changed and this regression test needs updating"
    )
    conn.execute("SELECT 1")  # alive
    return conn


def _assert_closed(conn: sqlite3.Connection, what: str) -> None:
    """Assert *conn* is really closed, not merely dereferenced."""
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return
    pytest.fail(f"{what} left the SQLite connection open on did-sqlite.sqlite")


def _populated_session(path: Path) -> ndi_session_dir:
    """A session with one document, so the SQLite file is real and written."""
    path.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("erase_ref", path)
    doc = ndi_document("base", **{"base.name": "doc-under-erase"})
    session.database_add(doc)
    return session


class TestSessionEraseClosesSQLite:
    def test_database_erase_closes_the_connection(self, tmp_path):
        session = _populated_session(tmp_path / "sess")
        conn = _live_connection(session)

        ndi_session_dir.database_erase(session, "yes")

        _assert_closed(conn, "database_erase")
        assert not (tmp_path / "sess" / ".ndi").exists()

    def test_delete_session_data_structures_closes_the_connection(self, tmp_path):
        session = _populated_session(tmp_path / "sess")
        conn = _live_connection(session)

        assert session.deleteSessionDataStructures(are_you_sure=True) is None

        _assert_closed(conn, "deleteSessionDataStructures")
        assert not (tmp_path / "sess" / ".ndi").exists()

    def test_database_erase_leaves_the_tree_alone_without_confirmation(self, tmp_path):
        """No confirmation -> no close and no delete."""
        session = _populated_session(tmp_path / "sess")
        conn = _live_connection(session)

        ndi_session_dir.database_erase(session, "no")

        conn.execute("SELECT 1")  # still usable
        assert (tmp_path / "sess" / ".ndi").exists()


class TestDatasetEraseClosesSQLite:
    def test_dataset_erase_closes_the_connection(self, tmp_path):
        dataset = ndi_dataset_dir(tmp_path / "ds", reference="erase_ds")
        conn = _live_connection(dataset._session)

        ndi_dataset_dir.dataset_erase(dataset, "yes")

        _assert_closed(conn, "dataset_erase")
        assert not (tmp_path / "ds" / ".ndi").exists()

    def test_dataset_erase_leaves_the_tree_alone_without_confirmation(self, tmp_path):
        dataset = ndi_dataset_dir(tmp_path / "ds", reference="erase_ds")
        conn = _live_connection(dataset._session)

        ndi_dataset_dir.dataset_erase(dataset, "no")

        conn.execute("SELECT 1")
        assert (tmp_path / "ds" / ".ndi").exists()


class TestCloseHappensBeforeRemoval:
    """The Windows failure is about ORDER, not about closing eventually.

    Closing after ``rmtree`` would satisfy the tests above but still fail on
    Windows, so pin the ordering directly: at the instant ``rmtree`` is
    entered, the connection must already be closed.
    """

    @staticmethod
    def _rmtree_spy(monkeypatch, conn: sqlite3.Connection, module):
        seen: list[bool] = []
        real_rmtree = shutil.rmtree

        def spy(path, *args, **kwargs):
            try:
                conn.execute("SELECT 1")
                seen.append(False)  # still open when rmtree was called
            except sqlite3.ProgrammingError:
                seen.append(True)
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(module, "rmtree", spy)
        return seen

    def test_session_database_erase_closes_first(self, tmp_path, monkeypatch):
        session = _populated_session(tmp_path / "sess")
        conn = _live_connection(session)
        seen = self._rmtree_spy(monkeypatch, conn, shutil)

        ndi_session_dir.database_erase(session, "yes")

        assert seen == [True], "rmtree ran while the SQLite handle was still open"

    def test_delete_session_data_structures_closes_first(self, tmp_path, monkeypatch):
        session = _populated_session(tmp_path / "sess")
        conn = _live_connection(session)
        seen = self._rmtree_spy(monkeypatch, conn, shutil)

        session.deleteSessionDataStructures(are_you_sure=True)

        assert seen == [True], "rmtree ran while the SQLite handle was still open"

    def test_dataset_erase_closes_first(self, tmp_path, monkeypatch):
        dataset = ndi_dataset_dir(tmp_path / "ds", reference="erase_ds")
        conn = _live_connection(dataset._session)
        seen = self._rmtree_spy(monkeypatch, conn, shutil)

        ndi_dataset_dir.dataset_erase(dataset, "yes")

        assert seen == [True], "rmtree ran while the SQLite handle was still open"


class TestMockSessionCleanupClosesSQLite:
    """Python's counterpart to MATLAB's ``closeAndRemoveDir`` test helper.

    ``ndi_session_mock.close()`` rmtree's the whole temp directory, ``.ndi``
    included -- the same Windows exposure the MATLAB helper had.
    """

    def test_mock_session_close_closes_the_connection(self):
        from ndi.session.mock import ndi_session_mock

        session = ndi_session_mock("mock_erase")
        session.database_add(ndi_document("base", **{"base.name": "doc"}))
        conn = _live_connection(session)
        tmpdir = Path(session._tmpdir)

        session.close()

        _assert_closed(conn, "ndi_session_mock.close")
        assert not tmpdir.exists()


class TestNoOrphanedConnections:
    """Rebinding ``_session`` must not leak a handle on the same SQLite file.

    ``ndi_dataset_dir`` re-creates its backing session over the SAME
    ``did-sqlite.sqlite`` more than once during construction. Each discarded
    session keeps its DID connection open until it happens to be
    garbage-collected, and on Windows that orphan blocks the later erase --
    the "the connection locking the directory is not the one you closed"
    failure NDI-matlab ``26d0638bf`` fixed with ``mksqlite(0,'close')``.
    """

    def test_dataset_construction_leaves_only_one_open_connection(self, tmp_path, monkeypatch):
        import sys

        # ``ndi.session.dir`` the attribute is the class, not the module
        # (ndi.session re-exports it), so reach the module through sys.modules.
        session_dir_module = sys.modules["ndi.session.dir"]

        created: list[ndi_session_dir] = []
        real_cls = session_dir_module.ndi_session_dir

        def recording_ndi_session_dir(*args, **kwargs):
            session = real_cls(*args, **kwargs)
            created.append(session)
            return session

        monkeypatch.setattr(session_dir_module, "ndi_session_dir", recording_ndi_session_dir)

        dataset = ndi_dataset_dir(
            "orphan_ref",
            tmp_path / "ds",
            documents=[ndi_document("base", **{"base.name": "seed"})],
        )

        assert len(created) > 1, (
            "expected the dataset constructor to re-create its session; if it "
            "no longer does, this orphaned-handle test needs updating"
        )
        for session in created:
            conn = session.database._driver._db.dbid
            if session is dataset._session:
                assert isinstance(conn, sqlite3.Connection)
                conn.execute("SELECT 1")  # the live one stays usable
            else:
                assert conn is None, (
                    "a discarded session still holds an open SQLite handle on "
                    "the dataset's did-sqlite.sqlite"
                )


class TestDatabaseClose:
    """``ndi_database.close()`` is the primitive the erase paths call."""

    def test_close_is_idempotent(self, tmp_path):
        session = _populated_session(tmp_path / "sess")
        database = session.database
        conn = _live_connection(session)

        database.close()
        database.close()  # must not raise

        _assert_closed(conn, "close")
