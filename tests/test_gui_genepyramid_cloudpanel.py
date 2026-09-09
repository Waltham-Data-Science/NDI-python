"""Signing back in without closing the section.

A VIEWER OUTLIVES ITS TOKEN. Someone reading a section works for hours;
the token is good for rather less, and what running out looks like from
here is not a login prompt but MISSING DATA -- tiles already cached keep
drawing and the rest fail one at a time as the reader pans. The token
lives in this process's environment, so nothing outside it can reach in:
before this panel the remedy was to quit, log in elsewhere, and open the
section again.

The clock and the profile write are checked without widgets; the panel's
own wiring is built offscreen and skips where there is no Qt.
"""

import base64
import json
import os
import time

import pytest

from ndi.cloud import auth
from ndi.gui.app.genepyramid import controls

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _jwt(seconds_from_now: int) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg({'exp': int(time.time()) + seconds_from_now})}.sig"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("NDI_CLOUD_TOKEN", "NDI_CLOUD_USERNAME", "NDI_CLOUD_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


class TestTheClock:
    def test_it_counts_down_rather_than_only_reporting_the_end(self):
        """A reader who sees "12 min left" can sign in at a convenient
        moment. One who sees nothing until it lapses finds out through a
        tile that will not load."""
        assert "30 min left" in auth.tokenStatusLine(_jwt(1800))
        assert "signed in" in auth.tokenStatusLine(_jwt(1800))

    def test_an_expired_token_says_how_long_ago(self):
        line = auth.tokenStatusLine(_jwt(-1200))
        assert "EXPIRED" in line
        assert "20 min ago" in line

    def test_no_token_is_not_the_same_as_expired(self):
        assert auth.tokenStatusLine("") == "not signed in"

    def test_an_opaque_token_is_left_to_the_server(self):
        """No exp claim to read. Calling that expired would be a guess,
        and the guess would sign someone out who was signed in."""
        assert auth.tokenSecondsRemaining("nonsense") is None
        assert auth.tokenStatusLine("nonsense") == "unknown"

    def test_it_reads_the_environment_when_asked_for_nothing(self, monkeypatch):
        """Which is where a login leaves the token, and so where the
        panel's own tick finds it."""
        monkeypatch.setenv("NDI_CLOUD_TOKEN", _jwt(3600))
        assert "signed in" in auth.tokenStatusLine()


class TestWhenThePanelIsOffered:
    def test_a_token_in_the_environment_is_the_signal(self, monkeypatch):
        monkeypatch.setenv("NDI_CLOUD_TOKEN", _jwt(3600))
        assert controls.cloudSessionLooksLikely()

    def test_an_expired_token_still_counts(self, monkeypatch):
        """That is precisely when the panel is wanted."""
        monkeypatch.setenv("NDI_CLOUD_TOKEN", _jwt(-60))
        assert controls.cloudSessionLooksLikely()

    def test_a_local_pyramid_is_offered_nothing(self):
        """A login control on a window that needs no login implies the
        picture might be waiting on something."""
        assert not controls.cloudSessionLooksLikely()


class _Entry:
    def __init__(self, uid, email):
        self.UID = uid
        self.Email = email


class TestSavingToTheProfile:
    def test_an_existing_entry_is_corrected_rather_than_duplicated(self, monkeypatch):
        """Someone whose saved password is wrong is trying to CORRECT it.
        A second entry would leave the wrong one in place to be picked."""
        calls = {}
        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles",
            lambda: [_Entry("u1", "other@example.com"), _Entry("u2", "me@example.com")],
        )
        monkeypatch.setattr(
            "ndi.cloud.profile.set_password", lambda k, p: calls.setdefault("set", (k, p))
        )
        monkeypatch.setattr(
            "ndi.cloud.profile.set_default", lambda k: calls.setdefault("default", k)
        )
        monkeypatch.setattr("ndi.cloud.profile.add", lambda *a: calls.setdefault("add", a))

        controls.saveCloudProfile("me@example.com", "pw")
        assert calls["set"] == ("u2", "pw")
        assert calls["default"] == "u2"
        assert "add" not in calls

    def test_the_match_ignores_case(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles", lambda: [_Entry("u2", "Me@Example.com")]
        )
        monkeypatch.setattr(
            "ndi.cloud.profile.set_password", lambda k, p: calls.setdefault("set", (k, p))
        )
        monkeypatch.setattr("ndi.cloud.profile.set_default", lambda k: None)
        monkeypatch.setattr("ndi.cloud.profile.add", lambda *a: calls.setdefault("add", a))
        controls.saveCloudProfile("me@example.com", "pw")
        assert calls["set"][0] == "u2"
        assert "add" not in calls

    def test_a_new_email_is_added_and_made_the_default(self, monkeypatch):
        calls = {}
        monkeypatch.setattr("ndi.cloud.profile.list_profiles", lambda: [])
        monkeypatch.setattr("ndi.cloud.profile.set_password", lambda k, p: None)
        monkeypatch.setattr(
            "ndi.cloud.profile.set_default", lambda k: calls.setdefault("default", k)
        )

        def _add(*a):
            calls["add"] = a
            return "fresh"

        monkeypatch.setattr("ndi.cloud.profile.add", _add)
        controls.saveCloudProfile("me@example.com", "pw")
        assert calls["add"] == ("me", "me@example.com", "pw")
        assert calls["default"] == "fresh"


@pytest.fixture(scope="module")
def qt():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield widgets
    del app


class _Window:
    def __init__(self):
        self.docked = []

    def add_dock_widget(self, widget, name=None, area=None):
        self.docked.append((widget, name, area))
        return widget


class _Viewer:
    def __init__(self):
        self.window = _Window()


@pytest.fixture
def panelOf(qt):
    """Build a panel and KEEP THE VIEWER, which owns the widget.

    A temporary _Viewer() is collected as soon as the call returns, and
    Qt deletes the C++ object underneath the Python wrapper -- every
    later attribute read then raises "has been deleted", which looks
    like a panel bug and is a test one.
    """
    held = []

    def build():
        viewer = _Viewer()
        held.append(viewer)
        return controls.addCloudPanel(viewer)

    return build


def _fields(qt, box):
    edits = box.findChildren(qt.QLineEdit)
    email = next(e for e in edits if e.echoMode() == qt.QLineEdit.Normal)
    password = next(e for e in edits if e.echoMode() == qt.QLineEdit.Password)
    return email, password


class TestThePanel:
    def test_the_password_is_never_shown(self, qt, panelOf):
        _email, password = _fields(qt, panelOf())
        assert password.echoMode() == qt.QLineEdit.Password

    def test_signing_in_passes_exactly_what_was_typed(self, qt, monkeypatch, panelOf):
        seen = {}
        monkeypatch.setattr(
            "ndi.cloud.auth.login", lambda who, secret: seen.update(who=who, secret=secret)
        )
        box = panelOf()
        email, password = _fields(qt, box)
        email.setText("  me@example.com  ")
        password.setText("pw")
        box.findChild(qt.QPushButton).click()
        assert seen == {"who": "me@example.com", "secret": "pw"}

    def test_the_password_is_cleared_afterwards(self, qt, monkeypatch, panelOf):
        """It goes to the login call and nothing else -- not to a field
        that stays filled in a dock somebody is screen-sharing."""
        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: None)
        box = panelOf()
        email, password = _fields(qt, box)
        email.setText("me@example.com")
        password.setText("pw")
        box.findChild(qt.QPushButton).click()
        assert password.text() == ""

    def test_a_failed_sign_in_clears_it_too(self, qt, monkeypatch, panelOf):
        """The attempt most likely to be a typo is the one that failed."""

        def boom(*_a):
            raise RuntimeError("HTTP 401")

        monkeypatch.setattr("ndi.cloud.auth.login", boom)
        box = panelOf()
        email, password = _fields(qt, box)
        email.setText("me@example.com")
        password.setText("wrong")
        box.findChild(qt.QPushButton).click()
        assert password.text() == ""

    def test_a_bad_password_is_reported_not_raised(self, qt, monkeypatch, panelOf):
        def boom(*_a):
            raise RuntimeError("HTTP 401")

        monkeypatch.setattr("ndi.cloud.auth.login", boom)
        box = panelOf()
        email, password = _fields(qt, box)
        email.setText("me@example.com")
        password.setText("wrong")
        box.findChild(qt.QPushButton).click()
        said = [lbl.text() for lbl in box.findChildren(qt.QLabel) if lbl.text()]
        assert any("401" in t for t in said)

    def test_an_empty_field_asks_rather_than_calling(self, qt, monkeypatch, panelOf):
        called = []
        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: called.append(a))
        box = panelOf()
        box.findChild(qt.QPushButton).click()
        assert called == []

    def test_the_profile_is_only_written_when_asked(self, qt, monkeypatch, panelOf):
        saved = []
        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: None)
        monkeypatch.setattr(controls, "saveCloudProfile", lambda *a: saved.append(a))
        box = panelOf()
        email, password = _fields(qt, box)
        email.setText("me@example.com")
        password.setText("pw")
        box.findChild(qt.QPushButton).click()
        assert saved == []

        box2 = panelOf()
        email2, password2 = _fields(qt, box2)
        email2.setText("me@example.com")
        password2.setText("pw")
        box2.findChild(qt.QCheckBox).setChecked(True)
        box2.findChild(qt.QPushButton).click()
        assert saved == [("me@example.com", "pw")]

    def test_a_profile_that_will_not_save_does_not_undo_the_sign_in(self, qt, monkeypatch, panelOf):
        def boom(*_a):
            raise RuntimeError("no keyring")

        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: None)
        monkeypatch.setattr(controls, "saveCloudProfile", boom)
        box = panelOf()
        email, password = _fields(qt, box)
        email.setText("me@example.com")
        password.setText("pw")
        box.findChild(qt.QCheckBox).setChecked(True)
        box.findChild(qt.QPushButton).click()
        said = " ".join(lbl.text() for lbl in box.findChildren(qt.QLabel))
        assert "Signed in" in said
        assert "keyring" in said

    def test_the_clock_warns_before_it_bites(self, qt, monkeypatch, panelOf):
        monkeypatch.setenv("NDI_CLOUD_TOKEN", _jwt(600))
        box = panelOf()
        said = " ".join(lbl.text() for lbl in box.findChildren(qt.QLabel))
        assert "before it runs out" in said

    def test_an_expired_clock_says_what_will_go_wrong(self, qt, monkeypatch, panelOf):
        monkeypatch.setenv("NDI_CLOUD_TOKEN", _jwt(-60))
        box = panelOf()
        said = " ".join(lbl.text() for lbl in box.findChildren(qt.QLabel))
        assert "fail to load" in said

    def test_the_timer_belongs_to_the_dock(self, qt, panelOf):
        """A free timer keeps firing at a deleted label and takes the
        process with it when the dock is closed."""
        core = pytest.importorskip("qtpy.QtCore")
        box = panelOf()
        timers = box.findChildren(core.QTimer)
        assert timers and all(t.parent() is box for t in timers)
