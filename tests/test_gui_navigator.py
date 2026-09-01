"""Tests for ndi.gui.navigator and its pure layout arithmetic.

MATLAB counterpart: ndi.gui.navigator

The weight here is on ndi.gui.nav.layout. A navigator bug is almost never an
exception -- it is a gap at the bottom of a window, a pane that will not drag
down to its minimum, or a window that walks up the screen. Those are wrong
numbers, so the numbers are what get tested.

The Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import math

import pytest

from ndi.gui.nav import layout as nav_layout
from ndi.gui.nav.pane import HEADER_HEIGHT, NavPane
from ndi.gui.nav.progress_pane import ProgressPane
from ndi.gui.navigator import DEFAULT_POSITION, Navigator


class FakePane:
    """The minimum a pane must be for the layout module."""

    def __init__(
        self,
        height=100,
        *,
        min_height=50,
        collapsible=False,
        engaged=True,
        resizable=False,
        rendered_height=float("nan"),
    ):
        self._height = height
        self.min_height = min_height
        self.collapsible = collapsible
        self.engaged = engaged
        self.resizable = resizable
        self.rendered_height = rendered_height

    def current_height(self):
        if self.collapsible and not self.engaged:
            return HEADER_HEIGHT
        return self._height

    def set_rendered_height(self, h):
        self.rendered_height = h


class TestIsElastic:
    def test_needs_all_three_conditions(self):
        assert nav_layout.is_elastic(FakePane(resizable=True, collapsible=True, engaged=True))

    def test_a_collapsed_pane_is_not_elastic(self):
        """It has no body to stretch."""
        assert not nav_layout.is_elastic(FakePane(resizable=True, collapsible=True, engaged=False))

    def test_a_non_resizable_pane_is_not_elastic(self):
        assert not nav_layout.is_elastic(FakePane(resizable=False, collapsible=True, engaged=True))

    def test_a_pane_without_the_attribute_at_all(self):
        """The base pane never declares `resizable`; MATLAB tests with
        isprop, so a missing attribute must read as False, not raise."""
        assert not nav_layout.is_elastic(NavPane(collapsible=True, engaged=True))

    def test_first_elastic_index(self):
        panes = [FakePane(), FakePane(resizable=True, collapsible=True)]
        assert nav_layout.first_elastic_index(panes) == 1

    def test_first_elastic_index_when_none(self):
        assert nav_layout.first_elastic_index([FakePane(), FakePane()]) is None


class TestHeightArithmetic:
    def test_content_height_removes_padding_and_spacing(self):
        # 4 panes: 2*PAD top and bottom, 3 gaps between them.
        assert nav_layout.content_height(500, 4) == 500 - 2 * 6 - 3 * 4

    def test_content_height_of_a_single_pane_has_no_spacing(self):
        assert nav_layout.content_height(500, 1) == 500 - 2 * 6

    def test_content_height_of_an_empty_stack(self):
        """max(n-1, 0): zero panes must not subtract negative spacing."""
        assert nav_layout.content_height(500, 0) == 500 - 2 * 6

    def test_figure_height_for_content_is_the_inverse(self):
        for n in (1, 2, 4):
            content = nav_layout.content_height(500, n)
            assert nav_layout.figure_height_for_content(content, n, 0) == 500

    def test_figure_height_respects_the_floor(self):
        assert nav_layout.figure_height_for_content(10, 1, 400) == 400


class TestMinFigureHeight:
    def test_collapsed_panes_need_only_their_headers(self):
        panes = [
            FakePane(height=200, collapsible=True, engaged=False),
            FakePane(height=300, collapsible=True, engaged=False),
        ]
        assert nav_layout.min_figure_height(panes) == 2 * HEADER_HEIGHT + 2 * 6 + 4

    def test_an_elastic_pane_contributes_its_minimum_not_its_height(self):
        panes = [FakePane(height=400, min_height=90, resizable=True, collapsible=True)]
        assert nav_layout.min_figure_height(panes) == 90 + 2 * 6

    def test_a_fixed_pane_contributes_its_current_height(self):
        assert nav_layout.min_figure_height([FakePane(height=123)]) == 123 + 2 * 6

    def test_everything_collapsed_shrinks_to_the_header_stack(self):
        """Content-driven: no fixed floor holds the window open."""
        panes = [FakePane(height=500, collapsible=True, engaged=False) for _ in range(3)]
        got = nav_layout.min_figure_height(panes)
        assert got == 3 * HEADER_HEIGHT + 2 * 6 + 2 * 4
        assert got < 200  # far below MIN_HEIGHT, and that is correct


class TestDistributeWithoutElasticPanes:
    """The current navigator stack: no resizable pane yet."""

    def test_each_pane_gets_what_it_asks_for(self):
        panes = [FakePane(height=50), FakePane(height=120)]
        heights, _ = nav_layout.distribute(panes, 500)
        assert heights == [50, 120]

    def test_the_window_is_sized_to_the_content(self):
        """No elastic pane can absorb slack, so the window must shrink --
        this is what stops a gap opening below the bottom pane."""
        panes = [FakePane(height=50), FakePane(height=120)]
        _, new_height = nav_layout.distribute(panes, 500)
        assert new_height == 50 + 120 + 2 * 6 + 4

    def test_no_resize_when_the_window_already_fits(self):
        panes = [FakePane(height=50), FakePane(height=120)]
        exact = 50 + 120 + 2 * 6 + 4
        _, new_height = nav_layout.distribute(panes, exact)
        assert new_height is None

    def test_a_one_pixel_difference_is_tolerated(self):
        """Without the tolerance a rounding difference would ping-pong
        between resize and layout forever."""
        panes = [FakePane(height=50)]
        exact = 50 + 2 * 6
        assert nav_layout.distribute(panes, exact + 1)[1] is None
        assert nav_layout.distribute(panes, exact - 1)[1] is None
        assert nav_layout.distribute(panes, exact + 2)[1] is not None


class TestDistributeWithElasticPanes:
    def test_the_elastic_pane_absorbs_the_leftover(self):
        fixed = FakePane(height=100)
        elastic = FakePane(height=100, min_height=50, resizable=True, collapsible=True)
        heights, new_height = nav_layout.distribute([fixed, elastic], 500)
        assert heights[0] == 100
        assert heights[1] == nav_layout.content_height(500, 2) - 100
        assert new_height is None  # the window is never resized in this branch

    def test_the_elastic_pane_never_goes_below_its_minimum(self):
        """A small window must not squash it; the minimum wins."""
        fixed = FakePane(height=200)
        elastic = FakePane(height=100, min_height=80, resizable=True, collapsible=True)
        heights, _ = nav_layout.distribute([fixed, elastic], 250)
        assert heights[1] == 80

    def test_two_elastic_panes_share_equally(self):
        fixed = FakePane(height=100)
        a = FakePane(min_height=10, resizable=True, collapsible=True)
        b = FakePane(min_height=10, resizable=True, collapsible=True)
        heights, _ = nav_layout.distribute([fixed, a, b], 500)
        assert heights[1] == heights[2]
        assert heights[1] == (nav_layout.content_height(500, 3) - 100) / 2

    def test_a_collapsed_resizable_pane_is_fixed_not_elastic(self):
        """It takes its header height and the branch changes to no-elastic."""
        collapsed = FakePane(
            height=300, min_height=80, resizable=True, collapsible=True, engaged=False
        )
        heights, new_height = nav_layout.distribute([FakePane(height=100), collapsed], 500)
        assert heights[1] == HEADER_HEIGHT
        assert new_height is not None  # window shrinks to the content

    def test_the_sum_fills_the_window_exactly(self):
        """The property the whole model exists for: no dead space."""
        panes = [
            FakePane(height=40),
            FakePane(height=100, min_height=50, resizable=True, collapsible=True),
            FakePane(height=60),
        ]
        heights, _ = nav_layout.distribute(panes, 600)
        assert sum(heights) == pytest.approx(nav_layout.content_height(600, 3))


class TestToggleDelta:
    def test_expanding_adds_the_body(self):
        pane = FakePane(height=150, collapsible=True, engaged=True)
        assert nav_layout.toggle_delta(pane) == 150 - HEADER_HEIGHT

    def test_collapsing_removes_what_was_rendered(self):
        """Not the current height -- by now the pane already reports
        header-only, so the body it lost is only knowable from the screen."""
        pane = FakePane(height=150, collapsible=True, engaged=False, rendered_height=150)
        assert nav_layout.toggle_delta(pane) == HEADER_HEIGHT - 150

    def test_collapsing_before_anything_was_rendered(self):
        pane = FakePane(collapsible=True, engaged=False, rendered_height=float("nan"))
        assert nav_layout.toggle_delta(pane) == 0

    def test_a_nonsense_rendered_height_is_floored(self):
        pane = FakePane(collapsible=True, engaged=False, rendered_height=3)
        assert nav_layout.toggle_delta(pane) == 0

    def test_expand_then_collapse_is_symmetric(self):
        """The window must end up where it started."""
        pane = FakePane(height=150, collapsible=True, engaged=True)
        grew = nav_layout.toggle_delta(pane)
        pane.rendered_height = 150
        pane.engaged = False
        shrank = nav_layout.toggle_delta(pane)
        assert grew + shrank == 0


class TestPaneBottomEdge:
    def test_first_pane(self):
        panes = [FakePane(height=40, rendered_height=40), FakePane(height=60)]
        assert nav_layout.pane_bottom_edge(panes, 0, 500) == 500 - 6 - 40

    def test_second_pane_includes_the_gap(self):
        panes = [FakePane(rendered_height=40), FakePane(rendered_height=60)]
        assert nav_layout.pane_bottom_edge(panes, 1, 500) == 500 - 6 - 40 - 4 - 60

    def test_falls_back_to_the_requested_height(self):
        """Before the first layout nothing has been rendered."""
        panes = [FakePane(height=40, rendered_height=float("nan"))]
        assert nav_layout.pane_bottom_edge(panes, 0, 500) == 500 - 6 - 40


class TestNavigatorWithoutQt:
    def test_position_is_clamped_to_the_minimums(self):
        nav = Navigator(position=(0, 0, 10, 10), build=False)
        assert nav.position[2] == nav_layout.MIN_WIDTH
        assert nav.position[3] == nav_layout.MIN_HEIGHT

    def test_a_large_position_is_kept(self):
        nav = Navigator(position=(5, 5, 800, 900), build=False)
        assert nav.position == (5, 5, 800, 900)

    def test_default_position(self):
        assert Navigator(build=False).position == DEFAULT_POSITION

    def test_layout_of_an_empty_stack_is_a_no_op(self):
        assert Navigator(build=False).layout() == []

    def test_layout_distributes_and_records(self):
        nav = Navigator(build=False)
        nav.panes = [FakePane(height=40), FakePane(height=60)]
        heights = nav.layout()
        assert heights == [40, 60]
        assert [p.rendered_height for p in nav.panes] == [40, 60]

    def test_set_height_keeps_the_top_edge_fixed(self):
        """Top-anchored: growing downward leaves the window where the user
        put it, where growing upward would walk it off the screen."""
        nav = Navigator(position=(10, 100, 300, 400), build=False)
        nav.panes = [FakePane(height=40)]
        top_before = nav.position[1] + nav.position[3]
        nav._set_figure_height(200)
        assert nav.position[1] + nav.position[3] == top_before
        assert nav.position[3] == 200

    def test_height_never_drops_below_the_minimum(self):
        nav = Navigator(build=False)
        nav.panes = [FakePane(height=300)]
        nav._set_figure_height(10)
        assert nav.position[3] == nav.min_figure_height()

    def test_resize_by_delta(self):
        nav = Navigator(position=(0, 0, 300, 500), build=False)
        nav.panes = [FakePane(height=400)]
        assert nav._resize_figure_by(50) == 550

    def test_enforce_min_size_widens_a_narrow_window(self):
        nav = Navigator(build=False)
        nav.position = (0, 0, 100, 500)
        nav.panes = [FakePane(height=400)]
        w, _ = nav.enforce_min_size()
        assert w == nav_layout.MIN_WIDTH

    def test_pane_toggled_grows_then_shrinks_back(self):
        """End to end through the navigator: a collapse and re-expand must
        leave the window height where it started."""
        nav = Navigator(position=(0, 0, 300, 600), build=False)
        pane = FakePane(height=200, min_height=50, collapsible=True, engaged=True)
        nav.panes = [FakePane(height=100), pane]
        nav.layout()
        start = nav.position[3]

        pane.engaged = False
        nav.pane_toggled(pane)
        collapsed = nav.position[3]
        assert collapsed < start

        pane.engaged = True
        nav.pane_toggled(pane)
        assert nav.position[3] == start

    def test_grip_is_absent_without_an_elastic_pane(self):
        nav = Navigator(build=False)
        nav.panes = [FakePane(height=40)]
        assert nav.grip_edge_y() is None
        assert nav.is_on_grip(100) is False
        assert nav.begin_drag(100) is False

    def test_grip_hit_test(self):
        nav = Navigator(position=(0, 0, 300, 500), build=False)
        nav.panes = [FakePane(height=40, min_height=20, resizable=True, collapsible=True)]
        edge = nav.grip_edge_y()
        assert nav.is_on_grip(edge)
        assert nav.is_on_grip(edge + nav_layout.GRIP_PIXELS)
        assert not nav.is_on_grip(edge + nav_layout.GRIP_PIXELS + 1)

    def test_dragging_down_grows_the_window(self):
        """Screen Y increases upward, so pulling the grip DOWN is a negative
        delta and must GROW the window. Getting this sign backwards reads as
        'the drag is broken', not as an inverted constant."""
        nav = Navigator(position=(0, 0, 300, 500), build=False)
        nav.panes = [FakePane(height=400, min_height=20, resizable=True, collapsible=True)]
        edge = nav.grip_edge_y()
        assert nav.begin_drag(edge)
        before = nav.position[3]
        after = nav.drag_to(edge - 30)  # pointer moved DOWN 30px
        assert after == before + 30

    def test_dragging_up_shrinks_the_window(self):
        nav = Navigator(position=(0, 0, 300, 900), build=False)
        nav.panes = [FakePane(height=400, min_height=20, resizable=True, collapsible=True)]
        edge = nav.grip_edge_y()
        nav.begin_drag(edge)
        before = nav.position[3]
        assert nav.drag_to(edge + 30) == before - 30

    def test_drag_without_begin_is_ignored(self):
        nav = Navigator(build=False)
        nav.panes = [FakePane(resizable=True, collapsible=True)]
        assert nav.drag_to(10) is None

    def test_zero_movement_does_nothing(self):
        nav = Navigator(position=(0, 0, 300, 500), build=False)
        nav.panes = [FakePane(height=400, min_height=20, resizable=True, collapsible=True)]
        edge = nav.grip_edge_y()
        nav.begin_drag(edge)
        assert nav.drag_to(edge) is None

    def test_end_drag_stops_it(self):
        nav = Navigator(position=(0, 0, 300, 500), build=False)
        nav.panes = [FakePane(height=400, min_height=20, resizable=True, collapsible=True)]
        nav.begin_drag(nav.grip_edge_y())
        nav.end_drag()
        assert nav.drag_to(0) is None

    def test_refresh_reaches_every_pane(self):
        class Counting(FakePane):
            def __init__(self):
                super().__init__()
                self.refreshed = 0

            def refresh(self):
                self.refreshed += 1

        nav = Navigator(build=False)
        nav.panes = [Counting(), Counting()]
        nav.refresh()
        assert all(p.refreshed == 1 for p in nav.panes)

    def test_datasets_pane_handle_is_none_until_that_pane_exists(self):
        nav = Navigator(build=False)
        nav.panes = [FakePane()]
        assert nav.datasets_pane_handle() is None


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestNavigatorQt:
    def test_builds_the_ported_pane_stack(self):
        """MATLAB's stack is NDI, NDI Cloud, Datasets, Progress. Only NDI
        Cloud is still unported; it inserts at index 1 when it lands."""
        _qt_or_skip()
        nav = Navigator()
        assert [p.title for p in nav.panes] == ["NDI", "Datasets", "Progress"]

    def test_progress_pane_is_findable(self):
        _qt_or_skip()
        nav = Navigator()
        assert isinstance(nav.progress_pane_handle(), ProgressPane)

    def test_window_is_titled_and_tagged(self):
        _qt_or_skip()
        nav = Navigator()
        assert nav.figure.windowTitle() == "NDI Navigator"
        assert nav.figure.objectName() == "ndiNavigator"

    def test_panes_are_the_heights_the_layout_computed(self):
        _qt_or_skip()
        nav = Navigator()
        heights = nav.layout()
        for pane, h in zip(nav.panes, heights):
            assert pane.panel.height() == int(round(h))

    def test_the_stack_leaves_no_dead_space(self):
        """The property the layout model exists for."""
        _qt_or_skip()
        nav = Navigator()
        heights = nav.layout()
        expected = nav_layout.figure_height_for_content(
            sum(heights), len(nav.panes), nav.min_figure_height()
        )
        assert abs(nav.position[3] - expected) <= 1

    def test_docking_does_not_move_the_window(self):
        """The quiet path's promise, now through the REAL stack: a background
        task engaging the progress pane must not move the window.

        This stood in a fake elastic pane while datasetsPane was unported.
        The datasets pane is the real one, and it keeps the invariant: it
        shrinks to make room instead of the window growing.
        """
        _qt_or_skip()
        nav = Navigator()
        progress = nav.progress_pane_handle()
        before = nav.position[3]
        datasets_before = nav.panes[1].rendered_height
        progress.fit_to_bars(3)
        assert nav.position[3] == before
        assert nav.panes[1].rendered_height < datasets_before

    def test_the_datasets_pane_absorbs_the_leftover_height(self):
        """With an elastic pane present the rows fill the window exactly and
        distribute() leaves the window alone -- no gap at the bottom, and no
        window that resizes itself when content changes."""
        _qt_or_skip()
        nav = Navigator()
        heights = nav.layout()
        available = nav_layout.content_height(nav.figure_height, len(nav.panes))
        assert abs(sum(heights) - available) <= 1
        _, new_height = nav_layout.distribute(nav.panes, nav.figure_height)
        assert new_height is None

    def test_collapsing_the_datasets_pane_does_resize_the_window(self):
        """A STRUCTURAL change still moves the window: with the only elastic
        pane collapsed there is nothing left to absorb, so the window sizes
        to its content."""
        _qt_or_skip()
        nav = Navigator()
        before = nav.position[3]
        nav.panes[1].toggle()
        assert nav.position[3] < before

    def test_a_pane_toggle_does_resize_the_window(self):
        _qt_or_skip()
        nav = Navigator()
        progress = nav.progress_pane_handle()
        before = nav.position[3]
        progress.toggle()
        assert nav.position[3] != before

    def test_ndi_pane_prefs_click_opens_the_preferences_editor(self):
        _qt_or_skip()
        from ndi.gui.preferences_editor import WINDOW_TAG as PREFS_TAG

        nav = Navigator()
        editor = nav.open_preferences()
        assert editor is not None
        assert editor.figure.objectName() == PREFS_TAG
        editor.close()

    def test_a_second_prefs_click_raises_the_editor_already_open(self):
        """MATLAB opens a fresh figure per click; here the handle has to be
        held anyway (an unreferenced Qt window is garbage collected), so the
        open one is raised rather than stacked."""
        _qt_or_skip()
        nav = Navigator()
        first = nav.open_preferences()
        assert nav.open_preferences() is first
        first.close()

    def test_min_height_follows_the_panes_not_a_constant(self):
        """An ELASTIC pane contributes its MINIMUM here, not the height it
        currently asks for -- otherwise the window could never be dragged
        smaller than whatever size the datasets tree happened to open at."""
        _qt_or_skip()
        nav = Navigator()
        computed = (
            sum(
                p.min_height if getattr(p, "resizable", False) else p.current_height()
                for p in nav.panes
            )
            + 2 * nav_layout.PAD
            + (len(nav.panes) - 1) * nav_layout.SPACING
        )
        assert nav.min_figure_height() == computed
        assert nav.min_figure_height() < sum(p.current_height() for p in nav.panes)
        assert not math.isnan(nav.min_figure_height())
