"""Tests for ndi.gui.nav.progress_pane and ndi.gui.nav.session_info.

MATLAB counterparts: ndi.gui.nav.progressPane, ndi.gui.nav.sessionInfo

Both were ported with the reading and the arithmetic separated from the
widget construction, so both are checkable here without a display. The Qt
build tests skip without PySide6, as in test_gui_nav_pane.py.
"""

from __future__ import annotations

import pytest

from ndi.gui.nav.pane import HEADER_HEIGHT
from ndi.gui.nav.progress_pane import BODY_HEIGHT, MAX_BODY_PX, ROW_UNIT_PX, ProgressPane
from ndi.gui.nav.session_info import (
    NO_DAQ,
    NO_ID,
    NONE_ROW,
    UNNAMED_DAQ,
    UNNAMED_SESSION,
    SessionInfo,
)


class FakeNavigator:
    def __init__(self):
        self.toggled = []
        self.layouts = 0

    def pane_toggled(self, pane):
        self.toggled.append(pane)

    def layout(self):
        self.layouts += 1


class TestProgressPaneGeometry:
    def test_idle_height_is_header_plus_body(self):
        assert ProgressPane().current_height() == HEADER_HEIGHT + BODY_HEIGHT

    def test_collapsed_height_is_header_only(self):
        p = ProgressPane()
        p.engaged = False
        assert p.current_height() == HEADER_HEIGHT

    def test_has_a_body_and_is_collapsible(self):
        p = ProgressPane()
        assert p.has_body() is True
        assert p.collapsible is True
        assert p.engaged is True

    def test_min_height_matches_the_idle_height(self):
        """The pane can never be squeezed below its own idle size."""
        assert ProgressPane().min_height == HEADER_HEIGHT + BODY_HEIGHT


class TestFitToBars:
    def test_converts_row_units_to_pixels(self):
        assert ProgressPane().fit_to_bars(2) == 2 * ROW_UNIT_PX

    def test_never_shrinks_below_the_idle_body(self):
        """A single short bar must not make the pane thinner than idle."""
        assert ProgressPane().fit_to_bars(0.5) == BODY_HEIGHT

    def test_zero_bars_is_the_idle_body(self):
        assert ProgressPane().fit_to_bars(0) == BODY_HEIGHT

    def test_caps_a_tall_cascade(self):
        """Beyond the cap the body scrolls rather than crowding other panes."""
        assert ProgressPane().fit_to_bars(100) == MAX_BODY_PX

    def test_exactly_at_the_cap(self):
        assert ProgressPane().fit_to_bars(MAX_BODY_PX / ROW_UNIT_PX) == MAX_BODY_PX

    def test_negative_is_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            ProgressPane().fit_to_bars(-1)

    def test_growth_is_quiet_not_structural(self):
        """The property that matters: a background task starting must not
        resize the window. A quiet engage re-lays out; a structural one would
        show up as a pane_toggled callback."""
        nav = FakeNavigator()
        p = ProgressPane(nav)
        p.engaged = False
        p.fit_to_bars(3)
        assert p.engaged is True
        assert nav.toggled == []  # never structural
        assert nav.layouts >= 1

    def test_height_follows_the_bars(self):
        nav = FakeNavigator()
        p = ProgressPane(nav)
        p.fit_to_bars(3)
        assert p.current_height() == HEADER_HEIGHT + 3 * ROW_UNIT_PX

    def test_works_without_a_navigator(self):
        assert ProgressPane().fit_to_bars(2) == 2 * ROW_UNIT_PX


class TestReleaseBars:
    def test_returns_to_the_idle_height(self):
        nav = FakeNavigator()
        p = ProgressPane(nav)
        p.fit_to_bars(6)
        assert p.desired_body_px > BODY_HEIGHT
        p.release_bars()
        assert p.desired_body_px == BODY_HEIGHT
        assert p.current_height() == HEADER_HEIGHT + BODY_HEIGHT

    def test_drops_the_docked_app(self):
        p = ProgressPane()
        p.register_app(object())
        assert p.active_app is not None
        p.release_bars()
        assert p.active_app is None

    def test_asks_the_navigator_to_relayout(self):
        nav = FakeNavigator()
        p = ProgressPane(nav)
        before = nav.layouts
        p.release_bars()
        assert nav.layouts > before

    def test_release_does_not_collapse_the_pane(self):
        """Idle is a thin OPEN pane, not a collapsed one."""
        p = ProgressPane()
        p.fit_to_bars(4)
        p.release_bars()
        assert p.engaged is True

    def test_release_without_a_navigator_is_safe(self):
        ProgressPane().release_bars()


# ----------------------------------------------------------------------
# session info
# ----------------------------------------------------------------------
class FakeEpochSystem:
    def __init__(self, name, epochs):
        self.name = name
        self._epochs = epochs

    def epochtable(self):
        return self._epochs, None


class FakeElement:
    def __init__(self, s, t):
        self._s = s
        self.type = t

    def elementstring(self):
        return self._s


class FakeDoc:
    def __init__(self, identifier, description):
        self.document_properties = {
            "subject": {"local_identifier": identifier, "description": description}
        }


class FakeSession:
    def __init__(self, *, reference="sess1", daqs=None, elements=None, subjects=None):
        self.reference = reference
        self._daqs = daqs if daqs is not None else []
        self._elements = elements if elements is not None else []
        self._subjects = subjects if subjects is not None else []

    def daqsystem_load(self, **kwargs):
        return self._daqs

    def getelements(self):
        return self._elements

    def database_search(self, q):
        return self._subjects


def info(session):
    return SessionInfo(session, build=False)


class TestSessionRef:
    def test_uses_the_reference(self):
        assert info(FakeSession(reference="abc")).session_ref() == "abc"

    def test_blank_reference_falls_back(self):
        assert info(FakeSession(reference="")).session_ref() == UNNAMED_SESSION

    def test_a_session_that_raises_falls_back(self):
        class Bad:
            @property
            def reference(self):
                raise RuntimeError("no")

        assert info(Bad()).session_ref() == UNNAMED_SESSION


class TestDaqRows:
    def test_one_row_per_epoch(self):
        s = FakeSession(
            daqs=[
                FakeEpochSystem(
                    "daq1",
                    [
                        {"epoch_number": 1, "epoch_id": "e1"},
                        {"epoch_number": 2, "epoch_id": "e2"},
                    ],
                )
            ]
        )
        assert info(s).daq_rows() == [("daq1", 1, "e1"), ("daq1", 2, "e2")]

    def test_a_daq_with_no_epochs_still_gets_a_row(self):
        """Otherwise it reads as 'there is no such DAQ system' rather than
        'it has no epochs'."""
        s = FakeSession(daqs=[FakeEpochSystem("daq1", [])])
        assert info(s).daq_rows() == [("daq1", "", "")]

    def test_no_daq_systems_at_all(self):
        assert info(FakeSession()).daq_rows() == [(NO_DAQ, "", "")]

    def test_epoch_number_falls_back_to_position(self):
        s = FakeSession(daqs=[FakeEpochSystem("d", [{"epoch_id": "x"}])])
        assert info(s).daq_rows() == [("d", 1, "x")]

    def test_missing_epoch_id_is_marked(self):
        s = FakeSession(daqs=[FakeEpochSystem("d", [{"epoch_number": 1}])])
        assert info(s).daq_rows() == [("d", 1, NO_ID)]

    def test_a_daq_whose_epochtable_raises_still_appears(self):
        """One failing lookup must not delete the row entirely."""

        class Exploding:
            name = "boom"

            def epochtable(self):
                raise RuntimeError("nope")

        assert info(FakeSession(daqs=[Exploding()])).daq_rows() == [("boom", "", "")]

    def test_unnamed_daq_is_labelled(self):
        s = FakeSession(daqs=[FakeEpochSystem("", [])])
        assert info(s).daq_rows() == [(UNNAMED_DAQ, "", "")]

    def test_a_session_that_cannot_list_daqs(self):
        class Bad(FakeSession):
            def daqsystem_load(self, **kwargs):
                raise RuntimeError("no")

        assert info(Bad()).daq_rows() == [(NO_DAQ, "", "")]


class TestElementRows:
    def test_uses_elementstring_not_just_the_name(self):
        s = FakeSession(elements=[FakeElement("probe1 | 1", "n-trode")])
        assert info(s).element_rows() == [("probe1 | 1", "n-trode")]

    def test_falls_back_to_name(self):
        class NoString:
            name = "fallback"
            type = "t"

            def elementstring(self):
                raise RuntimeError("no")

        assert info(FakeSession(elements=[NoString()])).element_rows() == [("fallback", "t")]

    def test_empty_is_marked(self):
        assert info(FakeSession()).element_rows() == [(NONE_ROW, "")]

    def test_a_session_that_cannot_list_elements(self):
        class Bad(FakeSession):
            def getelements(self):
                raise RuntimeError("no")

        assert info(Bad()).element_rows() == [(NONE_ROW, "")]


class TestSubjectRows:
    def test_reads_identifier_and_description(self):
        s = FakeSession(subjects=[FakeDoc("mouse23@vhlab.org", "a mouse")])
        assert info(s).subject_rows() == [("mouse23@vhlab.org", "a mouse")]

    def test_missing_fields_become_blank(self):
        class Sparse:
            document_properties = {"subject": {}}

        assert info(FakeSession(subjects=[Sparse()])).subject_rows() == [("", "")]

    def test_empty_is_marked(self):
        assert info(FakeSession()).subject_rows() == [(NONE_ROW, "")]

    def test_a_session_that_cannot_search(self):
        class Bad(FakeSession):
            def database_search(self, q):
                raise RuntimeError("no")

        assert info(Bad()).subject_rows() == [(NONE_ROW, "")]


class TestSectionsAreIndependent:
    def test_one_broken_lookup_does_not_empty_the_others(self):
        """The defensive wrapping is the point: two thirds of a window beats
        none of it."""

        class PartlyBroken(FakeSession):
            def getelements(self):
                raise RuntimeError("no")

        s = PartlyBroken(
            daqs=[FakeEpochSystem("d", [{"epoch_number": 1, "epoch_id": "e"}])],
            subjects=[FakeDoc("s1", "d1")],
        )
        i = info(s)
        assert i.daq_rows() == [("d", 1, "e")]
        assert i.element_rows() == [(NONE_ROW, "")]
        assert i.subject_rows() == [("s1", "d1")]


# ----------------------------------------------------------------------
# the Qt half
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


class TestQtBuild:
    def test_progress_pane_builds_with_a_placeholder_body(self):
        _qt_or_skip()
        from PySide6 import QtWidgets

        win = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(win)
        p = ProgressPane()
        p.build(layout, 0)
        assert p.body_container is not None
        assert p.title_label.text() == "Progress"
        assert p.disclosure_button is not None

    def test_adopt_bar_grid_replaces_the_placeholder(self):
        _qt_or_skip()
        from PySide6 import QtWidgets

        win = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(win)
        p = ProgressPane()
        p.build(layout, 0)
        grid = p.adopt_bar_grid()
        assert grid is not None
        assert p.bar_grid is grid

    def test_release_after_adopt_restores_the_placeholder(self):
        _qt_or_skip()
        from PySide6 import QtWidgets

        win = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(win)
        p = ProgressPane()
        p.build(layout, 0)
        p.adopt_bar_grid()
        p.release_bars()
        assert p.bar_grid is None

    def test_adopt_bar_grid_has_bar_percent_close_columns(self):
        """MATLAB's grid is {'17.5x', '1.5x', '1x'} -- bar, percent, close.
        A docking client (ProgressBarWindow) counts on that column shape;
        a bare vertical stack silently loses the three-column layout."""
        _qt_or_skip()
        from PySide6 import QtWidgets

        win = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(win)
        p = ProgressPane()
        p.build(layout, 0)
        grid = p.adopt_bar_grid().layout()
        assert isinstance(grid, QtWidgets.QGridLayout)
        # 35 : 3 : 2 preserves 17.5 : 1.5 : 1 exactly.
        assert grid.columnStretch(0) == 35
        assert grid.columnStretch(1) == 3
        assert grid.columnStretch(2) == 2

    def test_session_info_window_lists_every_section(self):
        _qt_or_skip()
        from PySide6 import QtWidgets

        s = FakeSession(
            daqs=[FakeEpochSystem("daq1", [{"epoch_number": 1, "epoch_id": "e1"}])],
            elements=[FakeElement("probe1 | 1", "n-trode")],
            subjects=[FakeDoc("mouse23", "a mouse")],
        )
        i = SessionInfo(s)
        tables = i.figure.findChildren(QtWidgets.QTableWidget)
        assert len(tables) == 3
        assert tables[0].item(0, 0).text() == "daq1"
        assert tables[1].item(0, 0).text() == "probe1 | 1"
        assert tables[2].item(0, 0).text() == "mouse23"
        assert "sess1" in i.figure.windowTitle()
