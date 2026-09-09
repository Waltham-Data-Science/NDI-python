"""The cloud token's clock, and when a sign-in is offered at all.

A VIEWER OUTLIVES ITS TOKEN. Someone reading a section works for hours;
the token is good for rather less, and what running out looks like from
here is not a login prompt but MISSING DATA -- tiles already cached keep
drawing and the rest fail one at a time as the reader pans. The token
lives in this process's environment, so nothing outside it can reach in:
before this panel the remedy was to quit, log in elsewhere, and open the
section again.

All of this needs no widgets: the clock is arithmetic on a JWT, the
offer is one environment variable, and the profile write is a call
against a stubbed store.
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
        assert "add" not in calls
        # The default is NOT moved. Saving a password is not a request to
        # switch accounts -- and one email can own a dev profile and a
        # prod one, where re-pointing the default silently changes which
        # account everything afterwards authenticates as.
        assert "default" not in calls

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


# The panel's own shape, its sign-in dialog and the profile chooser are
# tested in test_gui_genepyramid_genelayers.py, which builds the dialog
# through buildCloudSignInDialog rather than through the button.
#
# NOTHING HERE MAY CLICK "Sign in". It opens a MODAL dialog, and a modal
# dialog in a test with no one to close it blocks the process until the
# suite is killed -- which is what the docked-fields tests that used to
# live here started doing the moment the credentials moved behind a
# button. The seam exists so that never has to happen again.
