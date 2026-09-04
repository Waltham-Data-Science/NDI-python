"""The root branch SQLiteDriver creates must be a root structurally.

NDI-python#66. DID's ``add_branch`` reads an empty or omitted parent as "the
current branch" rather than "no parent", so a branch is a root only when it is
created while no current branch exists. These tests pin that down, and pin the
behaviour on a database that has branches but not the one NDI wants.
"""

import pytest

from ndi.database import SQLiteDriver


def _did_db(path):
    from did.implementations.sqlitedb import SQLiteDB

    return SQLiteDB(str(path))


class TestRootBranch:
    def test_branch_is_created_as_a_root(self, tmp_path):
        db_path = tmp_path / "did-sqlite.sqlite"
        driver = SQLiteDriver(db_path)

        assert driver._branch_id == "a"
        assert "a" in driver._db.all_branch_ids()
        assert driver._db.get_branch_parent("a") in (None, "")

    def test_no_parent_is_passed_when_creating_the_branch(self, tmp_path, monkeypatch):
        """Root-ness must come from the guard, not from DID's initial state.

        Passing an empty parent produced a root only because ``did.database``
        starts ``current_branch_id`` empty and never restores it from the file.
        DID reads an empty parent as "the current branch", so that spelling
        would make the branch a *child* the moment either of those facts
        changed. The fix is to omit the parent entirely, which is only sound
        under the "no branches at all" guard -- so assert the call shape.
        """
        from did.implementations.sqlitedb import SQLiteDB

        calls = []
        real_add_branch = SQLiteDB.add_branch

        def recording_add_branch(self, branch_id, *args, **kwargs):
            calls.append((branch_id, args, kwargs))
            return real_add_branch(self, branch_id, *args, **kwargs)

        monkeypatch.setattr(SQLiteDB, "add_branch", recording_add_branch)

        SQLiteDriver(tmp_path / "did-sqlite.sqlite")

        assert calls == [("a", (), {})], (
            "add_branch must be called with no parent argument; an empty "
            f"parent means 'the current branch' in DID. Got: {calls}"
        )

    def test_an_existing_root_is_left_alone_on_reopen(self, tmp_path):
        db_path = tmp_path / "did-sqlite.sqlite"

        db = _did_db(db_path)
        db.add_branch("a")
        db.set_branch("a")
        del db

        driver = SQLiteDriver(db_path)
        assert sorted(driver._db.all_branch_ids()) == ["a"]
        assert driver._db.get_branch_parent("a") in (None, "")

    def test_reopening_does_not_add_a_second_branch(self, tmp_path):
        db_path = tmp_path / "did-sqlite.sqlite"
        SQLiteDriver(db_path)
        driver = SQLiteDriver(db_path)
        assert sorted(driver._db.all_branch_ids()) == ["a"]


class TestMissingBranch:
    def test_non_empty_database_without_the_branch_raises(self, tmp_path):
        """Creating it here would parent it to whatever is current, so refuse.

        The message has to name the file and the branches that are present --
        the alternative is DID:Database:InvalidBranch from the next read, which
        names neither.
        """
        db_path = tmp_path / "did-sqlite.sqlite"

        db = _did_db(db_path)
        db.add_branch("main")
        del db

        with pytest.raises(ValueError) as excinfo:
            SQLiteDriver(db_path)

        message = str(excinfo.value)
        assert "main" in message
        assert "'a'" in message
        assert str(db_path) in message

    def test_the_requested_branch_is_accepted_when_present(self, tmp_path):
        db_path = tmp_path / "did-sqlite.sqlite"

        db = _did_db(db_path)
        db.add_branch("main")
        db.add_branch("side")
        del db

        driver = SQLiteDriver(db_path, branch_id="side")
        assert driver._branch_id == "side"
