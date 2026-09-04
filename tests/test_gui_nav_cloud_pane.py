"""Tests for ndi.gui.nav.cloud_pane, and the navigator's non-blocking alert.

MATLAB counterpart: ndi.gui.nav.cloudPane

The pane is small; what matters is that its three buttons reach the right
actions, that the bulk check degrades honestly when there is no datasets
pane, and that showing a message does not stop the caller.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.nav.cloud_pane import (
    BUTTON_SPACING,
    CHECK_WIDTH,
    LOGOUT_MESSAGE,
    NO_DATASETS_PANE,
    PROFILE_WIDTH,
    RELOAD_WIDTH,
    CloudPane,
    reload_icon_file,
)


class RecordingNavigator:
    """A navigator stand-in: records alerts, offers a datasets pane or not."""

    def __init__(self, datasets_pane=None):
        self.figure = None
        self.alerts = []
        self._datasets_pane = datasets_pane

    def alert(self, message, title, *, success=True):
        self.alerts.append((message, title, success))

    def datasets_pane_handle(self):
        return self._datasets_pane


class FakeDatasetsPane:
    def __init__(self, report=None, raises=False):
        self._report = report or {"total": 2, "in_cloud": 1, "not_in_cloud": 1, "errors": 0}
        self._raises = raises
        self.progress_calls = []

    def check_all_cloud_status(self, on_progress=None):
        if self._raises:
            raise RuntimeError("cloud is unreachable")
        if on_progress is not None:
            on_progress(1.0, "Checking dataset 1 of 1...")
            self.progress_calls.append(1.0)
        return self._report


class TestPaneShape:
    def test_title_and_uncollapsible(self):
        pane = CloudPane()
        assert pane.title == "NDI Cloud"
        assert pane.collapsible is False
        assert pane.engaged is True

    def test_it_is_not_elastic(self):
        """Only Datasets absorbs leftover height."""
        from ndi.gui.nav import layout as nav_layout

        assert not nav_layout.is_elastic(CloudPane())

    def test_right_width_matches_matlabs_arithmetic(self):
        """26 (reload) + 4 + 26 (C) + 4 + 62 (Profile) = 122."""
        assert CloudPane().right_width() == 122
        assert (RELOAD_WIDTH + BUTTON_SPACING + CHECK_WIDTH + BUTTON_SPACING + PROFILE_WIDTH) == 122

    def test_it_has_no_body(self):
        assert CloudPane().has_body() is False


class TestReloadIcon:
    def test_the_file_is_shipped(self):
        assert reload_icon_file().is_file()

    def test_it_is_byte_identical_to_matlabs(self):
        """The two ports should draw the same button rather than each
        inventing an icon. Skipped when the MATLAB tree is not checked out
        beside this one."""
        from pathlib import Path

        matlab = Path("/home/user/NDI-matlab/src/ndi/+ndi/+gui/reload_icon.svg")
        if not matlab.is_file():
            pytest.skip("NDI-matlab not available for comparison")
        assert reload_icon_file().read_bytes() == matlab.read_bytes()


class TestCheckAllCloud:
    def test_it_reports_the_summary(self):
        pane = CloudPane(RecordingNavigator(FakeDatasetsPane()))
        report = pane.check_all_cloud()
        assert report["in_cloud"] == 1
        message, title, success = pane.navigator.alerts[0]
        assert "1 of 2 datasets are in NDI Cloud." in message
        assert title == "Check NDI Cloud status"
        assert success

    def test_no_datasets_pane_says_so_rather_than_raising(self):
        """Expected while datasetsPane is absent, and still possible after."""
        pane = CloudPane(RecordingNavigator(None))
        assert pane.check_all_cloud() is None
        assert pane.navigator.alerts[0][0] == NO_DATASETS_PANE
        assert pane.navigator.alerts[0][2] is False

    def test_a_failing_check_is_reported_not_propagated(self):
        pane = CloudPane(RecordingNavigator(FakeDatasetsPane(raises=True)))
        assert pane.check_all_cloud() is None
        assert "cloud is unreachable" in pane.navigator.alerts[0][0]

    def test_the_progress_callback_is_passed_through(self):
        """The datasets pane already accepts it, so a real progress widget
        slots in without touching that side."""
        dp = FakeDatasetsPane()
        CloudPane(RecordingNavigator(dp)).check_all_cloud()
        assert dp.progress_calls == [1.0]

    def test_no_navigator_at_all(self):
        assert CloudPane().check_all_cloud() is None


class TestRefreshLogin:
    def test_it_calls_logout_and_says_what_happens_next(self, monkeypatch):
        import ndi.cloud.auth as auth

        called = []
        monkeypatch.setattr(auth, "logout", lambda *a, **k: called.append(True))
        pane = CloudPane(RecordingNavigator())
        assert pane.refresh_login() is True
        assert called == [True]
        assert pane.navigator.alerts[0][0] == LOGOUT_MESSAGE

    def test_a_failing_logout_is_reported(self, monkeypatch):
        import ndi.cloud.auth as auth

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(auth, "logout", boom)
        pane = CloudPane(RecordingNavigator())
        assert pane.refresh_login() is False
        assert "network down" in pane.navigator.alerts[0][0]


class TestProfileEditor:
    """The button used to report that the editor was not ported. It is, so
    these test what it now does instead."""

    def test_a_failure_to_open_is_reported_not_raised(self, monkeypatch):
        """Opening reads the profile store, which can fail on a machine with
        no usable secrets backend. The click must say so, not raise into
        Qt's event loop where nothing would show the user anything."""
        import ndi.gui.profile_editor as pe

        def boom(*args, **kwargs):
            raise RuntimeError("profile store is unreadable")

        monkeypatch.setattr(pe, "ProfileEditor", boom)
        pane = CloudPane(RecordingNavigator())
        assert pane.open_profile_editor() is None
        message, title, success = pane.navigator.alerts[0]
        assert "unreadable" in message
        assert title == "Profile"
        assert success is False

    def test_nothing_is_held_when_opening_failed(self, monkeypatch):
        """A half-constructed editor must not be kept and then reused by the
        next click."""
        import ndi.gui.profile_editor as pe

        monkeypatch.setattr(pe, "ProfileEditor", _raise("nope"))
        pane = CloudPane(RecordingNavigator())
        pane.open_profile_editor()
        assert pane.profile_editor is None


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


class TestCloudPaneQt:
    def test_the_stack_is_now_matlabs_four_panes(self):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        assert [p.title for p in nav.panes] == [
            "NDI",
            "NDI Cloud",
            "Datasets",
            "Progress",
        ]

    def test_the_three_buttons_are_built_at_matlabs_widths(self):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        pane = Navigator().panes[1]
        assert pane.reload_button.width() == RELOAD_WIDTH
        assert pane.check_button.text() == "C"
        assert pane.check_button.width() == CHECK_WIDTH
        assert pane.profile_button.text() == "Profile"
        assert pane.profile_button.width() == PROFILE_WIDTH

    def test_the_reload_button_carries_the_icon_not_the_fallback_glyph(self):
        """The glyph is only for a Qt build with no SVG support; if it shows
        up here the icon silently failed to load."""
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        pane = Navigator().panes[1]
        assert not pane.reload_button.icon().isNull()
        assert pane.reload_button.text() == ""

    def test_check_all_reaches_the_real_datasets_pane(self):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        report = nav.panes[1].check_all_cloud()
        # No datasets in an empty workspace, but the wiring is what is
        # under test: the handle resolves and the report comes back.
        assert report == {
            "total": 0,
            "in_cloud": 0,
            "not_in_cloud": 0,
            "errors": 0,
            "inCloud": 0,
            "notInCloud": 0,
        }


class TestNavigatorAlertDoesNotBlock:
    """MATLAB's uialert returns immediately; exec() would not."""

    def test_alert_returns_and_the_caller_carries_on(self):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        box = nav.alert("hello", "Title")
        # Reaching this line at all is the assertion: with exec() the call
        # would sit here until someone clicked OK, which nothing can do.
        assert box is not None
        assert box.text() == "hello"

    def test_a_shown_box_is_held_so_it_is_not_collected(self):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        nav.alert("one", "T")
        nav.alert("two", "T")
        assert len(nav._alert_boxes) == 2

    def test_dismissing_a_box_drops_it(self):
        """Otherwise the list grows for the life of the window."""
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator()
        box = nav.alert("one", "T")
        box.done(0)
        assert nav._alert_boxes == []

    def test_no_figure_means_no_box(self):
        _qt_or_skip()
        from ndi.gui.navigator import Navigator

        nav = Navigator(build=False)
        assert nav.alert("hello", "Title") is None


if __name__ == "__main__":
    pytest.main([__file__])


def _raise(message):
    def boom(*args, **kwargs):
        raise RuntimeError(message)

    return boom
