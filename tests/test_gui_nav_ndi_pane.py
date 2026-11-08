"""The NDI pane's coffee-cup button (ndi.util.keep_awake as a toggle).

MATLAB counterpart: ``ndiPane.toggleAwake`` / ``showAwake`` in
``+ndi/+gui/+nav/ndiPane.m``. The choice of icon and tooltip is pure and
tested without Qt; the button's wiring is tested under
QT_QPA_PLATFORM=offscreen and skips without PySide6 (as tests/test_gui_nav_pane.py).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ndi.gui.nav.ndi_pane import CUP_WIDTH, NdiPane, cup_appearance, cup_icon_file
from ndi.util.keep_awake import ndi_util_KeepAwake

MATLAB_GUI = (
    Path(os.environ.get("NDI_MATLAB_PATH", "../NDI-matlab")) / "src" / "ndi" / "+ndi" / "+gui"
)


class FakeProcess:
    def __init__(self, args):
        self.alive = True

    def isAlive(self):
        return self.alive

    def destroy(self):
        self.alive = False


@pytest.fixture
def keep_awake(monkeypatch):
    k = ndi_util_KeepAwake()
    k.Launcher = FakeProcess
    monkeypatch.setattr(ndi_util_KeepAwake, "_the", k)
    yield k
    k.delete()


class TestCupLogic:
    def test_icons_exist(self):
        assert cup_icon_file(True).name == "coffee_hot_icon.svg"
        assert cup_icon_file(False).name == "coffee_cold_icon.svg"
        assert cup_icon_file(True).is_file()
        assert cup_icon_file(False).is_file()

    @pytest.mark.skipif(not MATLAB_GUI.is_dir(), reason="NDI-matlab not checked out")
    @pytest.mark.parametrize("on", [True, False])
    def test_icons_are_copies_of_matlabs(self, on):
        f = cup_icon_file(on)
        assert f.read_bytes() == (MATLAB_GUI / f.name).read_bytes()

    def test_appearance_follows_keep_awake(self, keep_awake):
        icon, tip = cup_appearance()
        assert icon == cup_icon_file(False)
        assert tip.startswith("Let this computer sleep as usual.")
        keep_awake.hold("job:x", 'job "x" is running')
        icon, tip = cup_appearance(keep_awake)
        assert icon == cup_icon_file(True)
        assert 'job "x" is running' in tip

    def test_toggle_awake_is_the_manual_hold(self, keep_awake):
        p = NdiPane()
        p.toggle_awake()
        assert keep_awake.manualOn() and keep_awake.isOn()
        p.toggle_awake()
        assert not keep_awake.manualOn() and not keep_awake.isOn()

    def test_show_awake_without_a_button_does_nothing(self, keep_awake):
        assert NdiPane().show_awake() is None

    def test_cup_width(self):
        assert CUP_WIDTH == 28


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


@pytest.fixture
def qt_layout():
    app = _qt_or_skip()
    from PySide6 import QtWidgets

    win = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(win)
    yield app, win, layout
    win.deleteLater()


class TestCupButton:
    def test_built_between_the_broom_and_update(self, keep_awake, qt_layout):
        _, _, layout = qt_layout
        p = NdiPane()
        p.build(layout, 0)
        assert p.cup_button is not None
        assert p.cup_button.width() == CUP_WIDTH or p.cup_button.maximumWidth() == CUP_WIDTH
        row = p.cup_button.parentWidget().layout()
        order = [row.itemAt(i).widget() for i in range(row.count())]
        assert order.index(p.broom_button) < order.index(p.cup_button)
        assert order.index(p.cup_button) < order.index(p.update_button)
        assert p.cup_button.toolTip().startswith("Let this computer sleep as usual.")
        assert not p.cup_button.icon().isNull()

    def test_click_toggles_and_redraws(self, keep_awake, qt_layout):
        app, _, layout = qt_layout
        p = NdiPane()
        p.build(layout, 0)
        p.cup_button.click()
        app.processEvents()
        assert keep_awake.manualOn()
        assert "stop keeping it awake yourself" in p.cup_button.toolTip()
        p.cup_button.click()
        app.processEvents()
        assert not keep_awake.isOn()
        assert p.cup_button.toolTip().startswith("Let this computer sleep as usual.")

    def test_a_job_hold_redraws_the_cup(self, keep_awake, qt_layout):
        app, _, layout = qt_layout
        p = NdiPane()
        p.build(layout, 0)
        keep_awake.hold("job:x", 'job "x" is running')
        app.processEvents()
        assert 'job "x" is running' in p.cup_button.toolTip()
        keep_awake.release("job:x")
        app.processEvents()
        assert p.cup_button.toolTip().startswith("Let this computer sleep as usual.")

    def test_listener_goes_with_the_button(self, keep_awake, qt_layout):
        app, _, layout = qt_layout

        p = NdiPane()
        p.build(layout, 0)
        assert len(keep_awake._listeners) == 1
        # Delete just this button, now. (Flushing every deferred delete with
        # sendPostedEvents(None, DeferredDelete) also frees widgets other tests
        # still hold, which crashed a full run.)
        from shiboken6 import Shiboken

        Shiboken.delete(p.cup_button)
        app.processEvents()
        assert keep_awake._listeners == []
        keep_awake.hold("a")  # must not touch the deleted button
