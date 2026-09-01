"""Tests for ndi.gui.component.ProgressBarWindow.

MATLAB counterpart: ndi.gui.component.ProgressBarWindow

Only the path an app actually walks: add a bar, move it, take it away. That
path was broken -- ``_BarRecord.__slots__`` did not include the ``_frame``
that ``addBar`` assigns, so every addBar raised AttributeError and no NDI app
could draw progress at all. The failure was invisible because every caller
wraps the bar in a try/except, which is right (a run that cannot draw
progress is still a run) and is exactly why nothing reported it.

Qt is required to build widgets, so these skip without a usable PySide6.
"""

from __future__ import annotations

import os

import pytest


def _qt_or_skip():
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    if QtWidgets.QApplication.instance() is None:
        QtWidgets.QApplication([])


def _window(title):
    from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow

    return ndi_gui_component_ProgressBarWindow(title, Overwrite=True)


class TestABarCanBeDrawn:
    def test_add_update_remove(self):
        _qt_or_skip()
        window = _window("add-update-remove")
        window.addBar(Label="Computing responses (2 element(s))", Tag="t1", Auto=False)
        assert window.getState("t1") == "Open"

        window.updateBar("t1", 0.5)
        assert window.getBarNum("t1")[0] == 0

        # Removing takes the row out altogether, as MATLAB's removeBar does,
        # so the window is back to having no bars at all.
        window.removeBar("t1")
        index, status = window.getBarNum("t1")
        assert index is None
        assert status["identifier"].endswith("NoBarsExist")

    def test_two_bars_cascade(self):
        """Concurrent tasks each get their own row."""
        _qt_or_skip()
        window = _window("two-bars")
        window.addBar(Label="one", Tag="a", Auto=False)
        window.addBar(Label="two", Tag="b", Auto=False)
        assert (window.getBarNum("a")[0], window.getBarNum("b")[0]) == (0, 1)
