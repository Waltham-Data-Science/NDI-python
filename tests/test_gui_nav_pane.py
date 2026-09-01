"""Tests for the navigator pane foundation: palette, state machine, geometry.

MATLAB counterparts: ndi.gui.cloudColors, ndi.gui.nav.pane, ndi.gui.nav.ndiPane

A pane layout has no cross-language artifact to compare, the way the VHSB and
parseText batteries compare computed results. So the state machine, the height
arithmetic, the glyphs and the palette are kept out of the Qt construction
path and checked here without a display.

``build()`` turns out to be testable too, which I had not expected: Qt runs
under QT_QPA_PLATFORM=offscreen, so the WIRING is checkable -- that toggling
actually hides the body and redraws the glyph, that a click on Prefs reaches
the navigator, that the broom really empties the caches. What no test here
covers is how any of it LOOKS; that still needs a person.

The Qt tests skip rather than fail without PySide6 or a usable platform
plugin, since PySide6 is an optional extra and its plugins need system
libraries a bare CI image may not carry.
"""

from __future__ import annotations

import math

import pytest

from ndi.gui.cloud_colors import CloudColors, cloud_colors, cloudColors, rgb_to_hex
from ndi.gui.nav.ndi_pane import BROOM, BROOM_WIDTH, BUTTON_SPACING, PREFS_WIDTH, NdiPane
from ndi.gui.nav.pane import HEADER_HEIGHT, TRIANGLE_DOWN, TRIANGLE_RIGHT, NavPane


class TestPalette:
    def test_channels_are_zero_to_one(self):
        """Stored in MATLAB's units, not 0..255 -- so a divergence between the
        ports would be a changed number, never a changed unit."""
        c = cloud_colors()
        for name in c._fields:
            for v in getattr(c, name):
                assert 0.0 <= v <= 1.0, f"{name} channel out of range: {v}"

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("light_blue", "#4ea5f8"),
            ("ok_green", "#2e9e47"),
            ("warn_amber", "#e69f21"),
            ("neutral_grey", "#8c949e"),
            ("white", "#ffffff"),
        ],
    )
    def test_hex_matches_the_documented_value(self, name, expected):
        assert rgb_to_hex(getattr(cloud_colors(), name)) == expected

    def test_dark_blue_renders_one_step_off_its_documented_hex(self):
        """MATLAB documents #082051 but stores a triplet that paints #081F51.

        0.1216 * 255 = 31.008, i.e. 0x1F; 0x20 would need 0.1255. The stored
        triplet is what renders, so it is what is mirrored -- matching the
        comment instead would make the two ports paint different navies. This
        test pins the discrepancy so it is visible rather than mysterious, and
        fails if either side is later corrected without the other.
        """
        assert rgb_to_hex(cloud_colors().dark_blue) == "#081f51"
        assert cloud_colors().dark_blue[1] == 0.1216

    def test_matlab_cased_aliases_agree(self):
        c = cloud_colors()
        assert c.darkBlue == c.dark_blue
        assert c.lightBlue == c.light_blue
        assert c.offWhite == c.off_white
        assert c.okGreen == c.ok_green
        assert c.warnAmber == c.warn_amber
        assert c.neutralGrey == c.neutral_grey
        assert cloudColors is cloud_colors

    def test_palette_is_a_singleton(self):
        assert cloud_colors() is cloud_colors()

    def test_immutable(self):
        """A NamedTuple, so one GUI cannot recolour another's palette."""
        with pytest.raises(AttributeError):
            cloud_colors().dark_blue = (0, 0, 0)

    def test_rgb_to_hex_clamps(self):
        assert rgb_to_hex((-1.0, 0.5, 2.0)) == "#0080ff"

    def test_default_construction_matches_the_singleton(self):
        assert CloudColors() == cloud_colors()


class TestPaneConstruction:
    def test_defaults(self):
        p = NavPane()
        assert p.title == ""
        assert p.collapsible is False
        assert p.engaged is True
        assert p.min_height == HEADER_HEIGHT
        assert p.height == HEADER_HEIGHT
        assert math.isnan(p.rendered_height)

    def test_non_collapsible_pane_is_always_engaged(self):
        """A pane with no triangle cannot be collapsed, so engaged=False would
        be a state the user could never undo."""
        assert NavPane(collapsible=False, engaged=False).engaged is True

    def test_collapsible_pane_honours_engaged_false(self):
        assert NavPane(collapsible=True, engaged=False).engaged is False

    def test_min_height_is_raised_to_the_header(self):
        """A pane shorter than its own header cannot render."""
        assert NavPane(min_height=5).min_height == HEADER_HEIGHT

    def test_height_is_clamped_up_to_min_height(self):
        p = NavPane(min_height=100, height=40)
        assert p.height == 100

    def test_height_above_min_is_kept(self):
        assert NavPane(min_height=100, height=250).height == 250

    def test_height_defaults_to_min_height(self):
        assert NavPane(min_height=120).height == 120


class TestCurrentHeight:
    def test_engaged_pane_reports_its_height(self):
        assert NavPane(collapsible=True, height=200, min_height=100).current_height() == 200

    def test_collapsed_pane_reports_header_only(self):
        p = NavPane(collapsible=True, engaged=False, height=200, min_height=100)
        assert p.current_height() == HEADER_HEIGHT

    def test_non_collapsible_pane_never_reports_header_only(self):
        p = NavPane(collapsible=False, height=200, min_height=100)
        p.engaged = False  # cannot happen through the API, but pin it anyway
        assert p.current_height() == 200

    def test_height_set_below_min_is_still_clamped(self):
        """height is a public attribute, so the clamp has to hold here too."""
        p = NavPane(min_height=100, height=150)
        p.height = 10
        assert p.current_height() == 100


class TestDisclosure:
    def test_glyphs(self):
        assert NavPane(collapsible=True, engaged=True).disclosure_glyph() == TRIANGLE_DOWN
        assert NavPane(collapsible=True, engaged=False).disclosure_glyph() == TRIANGLE_RIGHT

    def test_glyph_code_points_match_matlab(self):
        """MATLAB writes char(9654) and char(9660)."""
        assert ord(TRIANGLE_RIGHT) == 9654
        assert ord(TRIANGLE_DOWN) == 9660

    def test_tooltip_names_the_action_not_the_state(self):
        p = NavPane(title="Datasets", collapsible=True, engaged=True)
        assert p.disclosure_tooltip() == "Collapse the Datasets section"
        p.engaged = False
        assert p.disclosure_tooltip() == "Expand the Datasets section"

    def test_tooltip_without_a_title(self):
        assert NavPane(collapsible=True).disclosure_tooltip() == "Collapse this section"


class FakeNavigator:
    """Records the calls a pane makes back into the navigator."""

    def __init__(self):
        self.toggled = []
        self.layouts = 0
        self.alerts = []
        self.preferences_opened = 0

    def pane_toggled(self, pane):
        self.toggled.append(pane)

    def layout(self):
        self.layouts += 1

    def alert(self, message, title, *, success):
        self.alerts.append((message, title, success))

    def open_preferences(self):
        self.preferences_opened += 1


class TestToggling:
    """The structural / quiet distinction is the whole point of these two
    paths: a window that jumps because a background task started is a window
    the user did not ask to move."""

    def test_toggle_flips_and_notifies_the_navigator(self):
        nav = FakeNavigator()
        p = NavPane(nav, collapsible=True, engaged=True)
        p.toggle()
        assert p.engaged is False
        assert nav.toggled == [p]
        assert nav.layouts == 0  # structural: the navigator resizes, not re-lays

    def test_toggle_is_a_no_op_for_a_non_collapsible_pane(self):
        nav = FakeNavigator()
        p = NavPane(nav, collapsible=False)
        p.toggle()
        assert p.engaged is True
        assert nav.toggled == []

    def test_set_engaged_to_the_current_state_does_nothing(self):
        nav = FakeNavigator()
        p = NavPane(nav, collapsible=True, engaged=True)
        p.set_engaged(True)
        assert nav.toggled == []

    def test_set_engaged_goes_through_toggle(self):
        nav = FakeNavigator()
        p = NavPane(nav, collapsible=True, engaged=True)
        p.set_engaged(False)
        assert p.engaged is False
        assert nav.toggled == [p]

    def test_set_engaged_quietly_relayouts_instead_of_resizing(self):
        nav = FakeNavigator()
        p = NavPane(nav, collapsible=True, engaged=False)
        p.set_engaged_quietly(True)
        assert p.engaged is True
        assert nav.toggled == []  # NOT structural
        assert nav.layouts == 1

    def test_set_engaged_quietly_is_a_no_op_when_state_matches(self):
        nav = FakeNavigator()
        p = NavPane(nav, collapsible=True, engaged=True)
        p.set_engaged_quietly(True)
        assert nav.layouts == 0

    def test_quiet_engage_is_a_no_op_on_a_non_collapsible_pane(self):
        nav = FakeNavigator()
        NavPane(nav, collapsible=False).set_engaged_quietly(False)
        assert nav.layouts == 0

    def test_pane_with_no_navigator_does_not_crash(self):
        """Panes are constructed in tests and tools without a navigator."""
        p = NavPane(None, collapsible=True)
        p.toggle()
        p.set_engaged_quietly(True)
        assert p.engaged is True


class TestRenderedHeight:
    def test_starts_nan_and_records(self):
        p = NavPane()
        assert math.isnan(p.rendered_height)
        p.set_rendered_height(140)
        assert p.rendered_height == 140


class TestNdiPane:
    def test_is_the_uncollapsible_header_pane(self):
        p = NdiPane()
        assert p.title == "NDI"
        assert p.collapsible is False
        assert p.engaged is True
        assert p.has_body() is False
        assert p.current_height() == HEADER_HEIGHT

    def test_right_width_is_the_sum_of_its_buttons(self):
        assert NdiPane().right_width() == BROOM_WIDTH + BUTTON_SPACING + PREFS_WIDTH
        assert NdiPane().right_width() == 92  # the number MATLAB hardcodes

    def test_broom_is_a_single_code_point(self):
        """MATLAB needs a UTF-16 surrogate pair for U+1F9F9; Python does not,
        and writing the pair here would render as two broken glyphs."""
        assert len(BROOM) == 1
        assert ord(BROOM) == 0x1F9F9

    def test_prefs_button_calls_the_navigator(self):
        nav = FakeNavigator()
        NdiPane(nav)._open_preferences()
        assert nav.preferences_opened == 1

    def test_clear_caches_reports_success(self):
        nav = FakeNavigator()
        NdiPane(nav).clear_caches()
        assert len(nav.alerts) == 1
        message, title, success = nav.alerts[0]
        assert success is True
        assert title == "Clear Caches"

    def test_clear_caches_reports_a_failure_instead_of_swallowing_it(self, monkeypatch):
        from ndi.fun import cache as cache_mod

        def boom():
            raise RuntimeError("nope")

        monkeypatch.setattr(cache_mod, "clear_all_caches", boom)
        nav = FakeNavigator()
        assert NdiPane(nav).clear_caches() == []
        message, _, success = nav.alerts[0]
        assert success is False
        assert "nope" in message

    def test_clear_caches_without_a_navigator_does_not_crash(self):
        NdiPane().clear_caches()


class TestClearAllCaches:
    """Non-vacuity matters here: a 'clear all' that clears nothing still
    returns cleanly, so the test populates the caches first."""

    def test_clears_the_caches_that_are_populated(self):
        from ndi import class_registry, common, probe, validate
        from ndi.fun.cache import clear_all_caches

        common.getCache()
        probe.getProbeTypeMap()
        class_registry.get_class("ndi.element")
        validate._schema_cache["x"] = {}

        assert common._cache_singleton is not None
        assert probe._PROBE_TYPE_MAP is not None
        assert class_registry._REGISTRY is not None

        cleared = clear_all_caches()

        assert common._cache_singleton is None
        assert probe._PROBE_TYPE_MAP is None
        assert class_registry._REGISTRY is None
        assert validate._schema_cache == {}
        assert len(cleared) >= 4

    def test_reports_what_it_cleared(self):
        from ndi import common
        from ndi.fun.cache import clear_all_caches

        common.getCache()
        assert any("getCache" in name for name in clear_all_caches())

    def test_clearing_twice_is_safe_and_reports_nothing_the_second_time(self):
        from ndi import common
        from ndi.fun.cache import clear_all_caches

        common.getCache()
        first = clear_all_caches()
        second = clear_all_caches()
        assert first and not second

    def test_caches_rebuild_after_clearing(self):
        """The point of clearing is a fresh read, not a broken library."""
        from ndi import probe
        from ndi.fun.cache import clear_all_caches

        before = probe.getProbeTypeMap()
        clear_all_caches()
        assert probe.getProbeTypeMap() == before

    def test_extra_objects_are_cleared_too(self):
        from ndi.fun.cache import clear_all_caches

        class Thing:
            def __init__(self):
                self.cleared = False

            def clear(self):
                self.cleared = True

        t = Thing()
        clear_all_caches(t)
        assert t.cleared is True

    def test_matlab_cased_alias(self):
        from ndi.fun.cache import clear_all_caches, clearAllCaches

        assert clearAllCaches is clear_all_caches


# ----------------------------------------------------------------------
# The Qt construction path
# ----------------------------------------------------------------------
def _qt_or_skip():
    """A QApplication on the offscreen platform, or skip.

    I had assumed the widget half of this port could only be checked by eye.
    It can't be checked for LOOK that way, but it can be checked for
    STRUCTURE: Qt runs headless under QT_QPA_PLATFORM=offscreen, so the
    wiring -- that toggling hides the body, that the glyph follows the state,
    that the buttons exist with the right text -- is testable after all. Only
    the visual result still needs a person.

    Skips rather than fails when PySide6 or a usable platform plugin is
    missing: PySide6 is an optional extra, and its plugins need system
    libraries (libEGL and friends) that a bare CI image may not carry.
    """
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


@pytest.fixture
def qt_host():
    app = _qt_or_skip()
    from PySide6 import QtWidgets

    win = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(win)
    return app, win, layout


class BodyPane(NavPane):
    """A pane with a body, for the build tests."""

    def has_body(self) -> bool:
        return True

    def build_body(self, container):
        from PySide6 import QtWidgets

        QtWidgets.QLabel("body", container)


class TestBuild:
    def test_ndi_pane_builds_its_header(self, qt_host):
        _, _, layout = qt_host
        p = NdiPane()
        panel = p.build(layout, 0)
        assert panel is not None
        assert p.title_label.text() == "NDI"
        assert p.prefs_button.text() == "Prefs"
        assert p.broom_button.text() == BROOM

    def test_non_collapsible_pane_has_no_disclosure_button(self, qt_host):
        _, _, layout = qt_host
        p = NdiPane()
        p.build(layout, 0)
        assert p.disclosure_button is None

    def test_collapsible_pane_gets_a_disclosure_button(self, qt_host):
        _, _, layout = qt_host
        p = BodyPane(collapsible=True, engaged=True, min_height=100)
        p.build(layout, 0)
        assert p.disclosure_button is not None
        assert p.disclosure_button.text() == TRIANGLE_DOWN

    def test_toggling_hides_the_body_and_updates_the_glyph(self, qt_host):
        """The wiring, end to end: a click on the triangle must actually hide
        the body and redraw the glyph, not just flip a flag."""
        _, win, layout = qt_host
        p = BodyPane(collapsible=True, engaged=True, min_height=100)
        p.build(layout, 0)
        win.show()

        assert p.body_container.isVisible() is True
        p.toggle()
        assert p.engaged is False
        assert p.body_container.isVisible() is False
        assert p.disclosure_button.text() == TRIANGLE_RIGHT

        p.toggle()
        assert p.body_container.isVisible() is True
        assert p.disclosure_button.text() == TRIANGLE_DOWN

    def test_body_starts_hidden_when_built_collapsed(self, qt_host):
        _, win, layout = qt_host
        p = BodyPane(collapsible=True, engaged=False, min_height=100)
        p.build(layout, 0)
        win.show()
        assert p.body_container.isVisible() is False

    def test_pane_without_a_body_builds_no_body_container(self, qt_host):
        _, _, layout = qt_host
        p = NavPane(title="plain")
        p.build(layout, 0)
        assert p.body_container is None

    def test_header_is_the_declared_height(self, qt_host):
        _, _, layout = qt_host
        p = NdiPane()
        p.build(layout, 0)
        assert p.header_grid.height() == HEADER_HEIGHT

    def test_prefs_click_reaches_the_navigator(self, qt_host):
        _, _, layout = qt_host
        nav = FakeNavigator()
        p = NdiPane(nav)
        p.build(layout, 0)
        p.prefs_button.click()
        assert nav.preferences_opened == 1

    def test_broom_click_clears_caches_and_reports(self, qt_host):
        _, _, layout = qt_host
        from ndi import common

        common.getCache()
        nav = FakeNavigator()
        p = NdiPane(nav)
        p.build(layout, 0)
        p.broom_button.click()
        assert common._cache_singleton is None
        assert nav.alerts and nav.alerts[-1][2] is True
