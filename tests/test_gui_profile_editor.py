"""Tests for ndi.gui.profile_editor.

MATLAB counterpart: ndi.gui.profileEditor

The editor is the only route to choosing the ACTIVE cloud account, so what
its table shows is what a user believes their uploads and syncs are going
to. The row-marker tests are therefore the important ones: a missing or
misplaced marker does not raise, it just tells someone the wrong account is
in use.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.profile_editor import (
    COLUMNS,
    MARKER,
    NO_SELECTION,
    WINDOW_TAG,
    ProfileEditor,
    add_failure_message,
    profile_rows,
    remove_confirm_message,
)


class FakeEntry:
    def __init__(self, uid="u1", nickname="nick", email="a@b.c"):
        self.UID = uid
        self.Nickname = nickname
        self.Email = email
        self.Stage = "prod"


class TestProfileRows:
    def test_one_row_per_profile_in_column_order(self):
        rows = profile_rows([FakeEntry("u1", "one", "one@x"), FakeEntry("u2", "two", "two@x")])
        assert len(rows) == 2
        assert rows[0] == ["", "", "one", "one@x", "u1"]
        assert len(rows[0]) == len(COLUMNS)

    def test_the_current_profile_is_marked(self):
        entries = [FakeEntry("u1"), FakeEntry("u2")]
        rows = profile_rows(entries, current=entries[1])
        assert rows[0][0] == ""
        assert rows[1][0] == MARKER

    def test_the_default_profile_is_marked_in_its_own_column(self):
        entries = [FakeEntry("u1"), FakeEntry("u2")]
        rows = profile_rows(entries, default=entries[0])
        assert rows[0][1] == MARKER
        assert rows[0][0] == ""

    def test_a_profile_that_is_both_carries_both_markers(self):
        """A real and common state -- you set a default and this session is
        using it. Showing only one of the two would misreport it."""
        entries = [FakeEntry("u1")]
        rows = profile_rows(entries, current=entries[0], default=entries[0])
        assert rows[0][0] == MARKER
        assert rows[0][1] == MARKER

    def test_matching_is_by_uid_not_identity(self):
        """The entries handed in may be separate reads of the same stored
        profile, so identity would leave the row unmarked."""
        rows = profile_rows([FakeEntry("u1")], current=FakeEntry("u1"))
        assert rows[0][0] == MARKER

    def test_no_current_and_no_default_marks_nothing(self):
        rows = profile_rows([FakeEntry("u1"), FakeEntry("u2")])
        assert all(row[0] == "" and row[1] == "" for row in rows)

    def test_an_empty_store_is_an_empty_table(self):
        assert profile_rows([]) == []

    def test_a_profile_with_no_uid_is_never_marked(self):
        """An empty UID must not collide with an absent current/default,
        which is also the empty string."""
        rows = profile_rows([FakeEntry("", "no uid", "x@y")], current=None)
        assert rows[0][0] == ""
        assert rows[0][1] == ""


class TestAddFailureMessage:
    @pytest.mark.parametrize(
        "nickname,email,password",
        [("", "a@b", "pw"), ("n", "", "pw"), ("n", "a@b", ""), ("  ", "a@b", "pw")],
    )
    def test_any_missing_field_is_refused(self, nickname, email, password):
        assert add_failure_message(nickname, email, password)

    def test_all_three_present_is_allowed(self):
        assert add_failure_message("n", "a@b", "pw") == ""

    def test_a_whitespace_password_is_allowed(self):
        """Only the two text fields are stripped. A password is taken as
        typed -- trimming it would silently store something else."""
        assert add_failure_message("n", "a@b", "  ") == ""


class TestRemoveConfirmMessage:
    def test_it_names_both_nickname_and_email(self):
        """Nicknames are user-chosen and need not be unique, so the email is
        what makes it unambiguous whose credentials are about to go."""
        message = remove_confirm_message(FakeEntry("u1", "work", "me@lab.org"))
        assert "work" in message
        assert "me@lab.org" in message


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class FakeStore:
    """A stand-in for ndi.cloud.profile, recording what it was asked to do."""

    def __init__(self, entries=None, current=None, default=None):
        self.entries = list(entries or [])
        self.current = current
        self.default = default
        self.calls = []

    def list_profiles(self):
        return list(self.entries)

    def get_current(self):
        return self.current

    def get_default(self):
        return self.default

    def get(self, uid):
        for e in self.entries:
            if e.UID == uid:
                return e
        raise KeyError(f"no profile {uid}")

    def add(self, nickname, email, password):
        self.calls.append(("add", nickname, email, password))
        entry = FakeEntry(f"u{len(self.entries) + 1}", nickname, email)
        self.entries.append(entry)
        return entry.UID

    def remove(self, uid):
        self.calls.append(("remove", uid))
        self.entries = [e for e in self.entries if e.UID != uid]

    def set_current(self, uid):
        self.calls.append(("set_current", uid))
        self.current = self.get(uid)

    def set_default(self, uid):
        self.calls.append(("set_default", uid))
        self.default = self.get(uid)

    def clear_default(self):
        self.calls.append(("clear_default",))
        self.default = None

    def set_password(self, uid, password):
        self.calls.append(("set_password", uid, password))


def _editor(monkeypatch, store, select=None):
    """A built editor wired to STORE, with alerts recorded not shown."""
    import ndi.cloud.profile as real

    for name in (
        "list_profiles",
        "get_current",
        "get_default",
        "get",
        "add",
        "remove",
        "set_current",
        "set_default",
        "clear_default",
        "set_password",
    ):
        monkeypatch.setattr(real, name, getattr(store, name))

    editor = ProfileEditor()
    editor.alerts = []
    editor.alert = lambda m, t, success=False: editor.alerts.append((m, t, success))
    editor.refresh()
    if select is not None:
        editor.selected_row = select
    return editor


class TestTheTable:
    def test_it_draws_the_rows_the_model_computed(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1", "one", "one@x"), FakeEntry("u2", "two", "two@x")])
        editor = _editor(monkeypatch, store)
        assert editor.table.rowCount() == 2
        assert editor.table.item(1, COLUMNS.index("Nickname")).text() == "two"

    def test_the_window_is_titled_and_tagged(self, monkeypatch):
        _qt_or_skip()
        editor = _editor(monkeypatch, FakeStore())
        assert editor.figure.windowTitle() == "NDI Cloud Profiles"
        assert editor.figure.objectName() == WINDOW_TAG

    def test_refresh_rebuilds_rather_than_appends(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")])
        editor = _editor(monkeypatch, store)
        editor.refresh()
        assert editor.table.rowCount() == 1

    def test_selected_uid_reads_the_rendered_row(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1"), FakeEntry("u2")])
        editor = _editor(monkeypatch, store, select=1)
        assert editor.selected_uid() == "u2"

    def test_a_selection_past_the_end_is_no_selection(self, monkeypatch):
        """A stale index must not act on whichever profile slid into that
        position."""
        _qt_or_skip()
        editor = _editor(monkeypatch, FakeStore([FakeEntry("u1")]), select=5)
        assert editor.selected_uid() == ""


class TestButtonsThatNeedASelection:
    @pytest.mark.parametrize(
        "action", ["set_current", "set_default", "change_password", "remove_profile"]
    )
    def test_they_refuse_and_say_so_without_one(self, monkeypatch, action):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")])
        editor = _editor(monkeypatch, store)
        assert getattr(editor, action)() is False
        assert any(NO_SELECTION in m for m, _, _ in editor.alerts)
        assert store.calls == []

    def test_set_current_applies_to_the_selected_profile(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1"), FakeEntry("u2")])
        editor = _editor(monkeypatch, store, select=1)
        assert editor.set_current() is True
        assert ("set_current", "u2") in store.calls

    def test_set_default_applies_to_the_selected_profile(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1"), FakeEntry("u2")])
        editor = _editor(monkeypatch, store, select=0)
        assert editor.set_default() is True
        assert ("set_default", "u1") in store.calls

    def test_the_new_marker_shows_after_setting_current(self, monkeypatch):
        """The point of the button: the table must then say which account is
        in use."""
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1"), FakeEntry("u2")])
        editor = _editor(monkeypatch, store, select=1)
        editor.set_current()
        assert editor.table.item(1, COLUMNS.index("Current")).text() == MARKER
        assert editor.table.item(0, COLUMNS.index("Current")).text() == ""

    def test_a_failing_store_is_reported_not_raised(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")])

        def boom(uid):
            raise RuntimeError("profile file is read-only")

        store.set_current = boom
        editor = _editor(monkeypatch, store, select=0)
        assert editor.set_current() is False
        assert any("read-only" in m for m, _, _ in editor.alerts)


class TestClearDefault:
    def test_it_needs_no_selection(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")], default=FakeEntry("u1"))
        editor = _editor(monkeypatch, store)
        assert editor.clear_default() is True
        assert ("clear_default",) in store.calls

    def test_the_marker_goes_away(self, monkeypatch):
        _qt_or_skip()
        entry = FakeEntry("u1")
        store = FakeStore([entry], default=entry)
        editor = _editor(monkeypatch, store)
        assert editor.table.item(0, COLUMNS.index("Default")).text() == MARKER
        editor.clear_default()
        assert editor.table.item(0, COLUMNS.index("Default")).text() == ""


class TestAdd:
    def test_cancelling_the_prompt_adds_nothing(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore()
        editor = _editor(monkeypatch, store)
        monkeypatch.setattr(editor, "_ask_fields", lambda p, t, secret_last=False: None)
        assert editor.add_profile() == ""
        assert store.calls == []

    def test_a_missing_field_is_refused_before_the_store_is_touched(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore()
        editor = _editor(monkeypatch, store)
        monkeypatch.setattr(
            editor, "_ask_fields", lambda p, t, secret_last=False: ["nick", "", "pw"]
        )
        assert editor.add_profile() == ""
        assert store.calls == []
        assert any("must all be provided" in m for m, _, _ in editor.alerts)

    def test_a_complete_answer_adds_and_refreshes(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore()
        editor = _editor(monkeypatch, store)
        monkeypatch.setattr(
            editor, "_ask_fields", lambda p, t, secret_last=False: [" nick ", " a@b ", "pw"]
        )
        uid = editor.add_profile()
        assert uid
        assert ("add", "nick", "a@b", "pw") in store.calls
        assert editor.table.rowCount() == 1

    def test_the_password_is_not_stripped(self, monkeypatch):
        """Nickname and email are trimmed; trimming a password would store
        something the user did not type."""
        _qt_or_skip()
        store = FakeStore()
        editor = _editor(monkeypatch, store)
        monkeypatch.setattr(
            editor, "_ask_fields", lambda p, t, secret_last=False: ["n", "a@b", " pw "]
        )
        editor.add_profile()
        assert ("add", "n", "a@b", " pw ") in store.calls


class TestChangePassword:
    def test_an_empty_password_is_refused(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")])
        editor = _editor(monkeypatch, store, select=0)
        monkeypatch.setattr(editor, "_ask_fields", lambda p, t, secret_last=False: [""])
        assert editor.change_password() is False
        assert store.calls == []

    def test_cancelling_changes_nothing(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")])
        editor = _editor(monkeypatch, store, select=0)
        monkeypatch.setattr(editor, "_ask_fields", lambda p, t, secret_last=False: None)
        assert editor.change_password() is False
        assert store.calls == []

    def test_it_sets_the_password_on_the_selected_profile(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1"), FakeEntry("u2")])
        editor = _editor(monkeypatch, store, select=1)
        monkeypatch.setattr(editor, "_ask_fields", lambda p, t, secret_last=False: ["new"])
        assert editor.change_password() is True
        assert ("set_password", "u2", "new") in store.calls


class TestRemove:
    def test_declining_the_confirmation_removes_nothing(self, monkeypatch):
        """Removing also deletes the stored secret, so a stray click must
        not do it."""
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1")])
        editor = _editor(monkeypatch, store, select=0)
        monkeypatch.setattr(editor, "confirm", lambda m, t, accept="": False)
        assert editor.remove_profile() is False
        assert store.calls == []

    def test_accepting_removes_and_drops_the_selection(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1"), FakeEntry("u2")])
        editor = _editor(monkeypatch, store, select=0)
        monkeypatch.setattr(editor, "confirm", lambda m, t, accept="": True)
        assert editor.remove_profile() is True
        assert ("remove", "u1") in store.calls
        assert editor.selected_row is None
        assert editor.table.rowCount() == 1

    def test_the_confirmation_names_the_profile(self, monkeypatch):
        _qt_or_skip()
        store = FakeStore([FakeEntry("u1", "work", "me@lab.org")])
        editor = _editor(monkeypatch, store, select=0)
        seen = []
        monkeypatch.setattr(editor, "confirm", lambda m, t, accept="": seen.append(m) or False)
        editor.remove_profile()
        assert "work" in seen[0] and "me@lab.org" in seen[0]


class TestTheCloudPaneButton:
    def test_it_opens_the_editor_and_holds_it(self, monkeypatch):
        """A Qt window with no reference is collected the moment the method
        returns, so holding it is what makes the button work at all."""
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        pane = nav.panes[1]
        editor = pane.open_profile_editor()
        assert editor is not None
        assert pane.profile_editor is editor

    def test_a_second_click_reuses_the_window(self, monkeypatch):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        pane = nav.panes[1]
        first = pane.open_profile_editor()
        assert pane.open_profile_editor() is first


class TestBackendDetectionSurvivesABrokenInstall:
    """A partially-built native extension must not take the store down.

    pyo3 raises PanicException, which is NOT an Exception subclass, so the
    probe catching only ImportError let it escape -- and no ordinary caller
    downstream could have defended against it.

    Each test asserts the probes were actually reached. Without that, they
    would pass vacuously anywhere the real backends happen to be missing.
    """

    @staticmethod
    def _patch_import(monkeypatch, raiser):
        import builtins

        seen = []
        real = builtins.__import__

        def fake(name, *args, **kwargs):
            if name in ("keyring", "cryptography.hazmat.primitives.ciphers"):
                seen.append(name)
                raiser()
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake)
        return seen

    def test_a_panicking_probe_falls_back_to_memory(self, monkeypatch):
        import ndi.cloud.profile as profile

        class Panic(BaseException):
            """Stands in for pyo3's PanicException."""

        def boom():
            raise Panic("native extension is broken")

        seen = self._patch_import(monkeypatch, boom)
        assert profile._detect_backend() == "memory"
        assert seen == [
            "keyring",
            "cryptography.hazmat.primitives.ciphers",
        ], "both probes must be reached, or this test proves nothing"

    def test_an_import_error_still_falls_back(self, monkeypatch):
        """The original behaviour, unchanged."""
        import ndi.cloud.profile as profile

        def boom():
            raise ImportError("not installed")

        seen = self._patch_import(monkeypatch, boom)
        assert profile._detect_backend() == "memory"
        assert len(seen) == 2

    def test_keyboard_interrupt_is_not_swallowed(self, monkeypatch):
        """The user asking to stop is not a backend being unavailable."""
        import ndi.cloud.profile as profile

        def boom():
            raise KeyboardInterrupt

        self._patch_import(monkeypatch, boom)
        with pytest.raises(KeyboardInterrupt):
            profile._detect_backend()

    def test_a_working_keyring_is_still_preferred(self, monkeypatch):
        """The fallback must not have become the only path."""
        import builtins

        import ndi.cloud.profile as profile

        real = builtins.__import__

        def fake(name, *args, **kwargs):
            if name == "keyring":
                return object()
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake)
        assert profile._detect_backend() == "keyring"


if __name__ == "__main__":
    pytest.main([__file__])
