"""How the Genes panel is laid out, checked on real widgets.

A dock panel is narrow, and a wide control that shares its row with a
label ends up a stub. That went wrong twice -- the rotation slider, then
the abundance band, whose two value labels ate what little track was
left and made it unreachable rather than merely cramped. An arrangement
is a property of real widgets in a real layout, so these build the panel
offscreen rather than stubbing it, and skip where there is no Qt.

What the panel DOES -- the filters, the sorting, the layers -- is tested
in test_gui_genepyramid_controls.py with no widgets at all.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


class _Layers(dict):
    events = None


class _Viewer:
    def __init__(self):
        self.window = _Window()
        self.layers = _Layers()


@pytest.fixture
def panel(qt, monkeypatch):
    """The real Genes panel over a stub gene list."""
    from ndi.fun import doc_gene_export
    from ndi.gui.app.genepyramid import controls

    symbols = [f"GENE{i:04d}" for i in range(40)]
    monkeypatch.setattr(
        doc_gene_export, "readGeneList", lambda *a, **k: (list(symbols), list(symbols))
    )
    monkeypatch.setattr(
        doc_gene_export,
        "readGeneTotals",
        lambda *a, **k: (np.arange(len(symbols), dtype=float), None),
    )
    viewer = _Viewer()
    return controls.addGenePanel(viewer, object(), object())


def _rows(box):
    """The panel's top-level layout: widgets, and nested rows as lists."""
    layout = box.layout()
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is not None:
            out.append(item.widget())
        elif item.layout() is not None:
            sub = item.layout()
            out.append(
                [sub.itemAt(j).widget() for j in range(sub.count()) if sub.itemAt(j).widget()]
            )
    return out


def _index(rows, predicate):
    return next(i for i, r in enumerate(rows) if predicate(r))


class TestTheAbundanceBand:
    def test_the_slider_shares_its_row_with_nothing(self, qt, panel):
        """Its own value labels sit at each end of the track, so a label
        beside it leaves the numbers and no track between them."""
        superqt = pytest.importorskip("superqt")
        rows = _rows(panel)
        row = _index(
            rows,
            lambda r: isinstance(r, list)
            and any(isinstance(w, superqt.QLabeledDoubleRangeSlider) for w in r),
        )
        assert len(rows[row]) == 1

    def test_its_label_is_the_line_above(self, qt, panel):
        superqt = pytest.importorskip("superqt")
        rows = _rows(panel)
        row = _index(
            rows,
            lambda r: isinstance(r, list)
            and any(isinstance(w, superqt.QLabeledDoubleRangeSlider) for w in r),
        )
        above = rows[row - 1]
        assert isinstance(above, qt.QLabel)
        assert "Abundance band" in above.text()

    def test_the_band_still_spans_the_whole_range(self, qt, panel):
        """The move is layout only: a band that came up narrowed would
        hide genes before anyone touched it."""
        superqt = pytest.importorskip("superqt")
        slider = panel.findChild(superqt.QLabeledDoubleRangeSlider)
        assert tuple(slider.value()) == (0.0, 100.0)


class TestTheList:
    def test_it_opens_tall_enough_to_read(self, qt, panel):
        """Four rows of 26,444 genes is a porthole. The dock is only as
        tall as it is asked to be, so it is asked."""
        listw = panel.findChild(qt.QListWidget)
        assert listw.minimumHeight() >= 200

    def test_it_takes_the_space_that_is_going(self, qt, panel):
        """Everything else on the panel is a fixed row; growth belongs to
        the list, not to the gap under it."""
        layout = panel.layout()
        listw = panel.findChild(qt.QListWidget)
        i = next(i for i in range(layout.count()) if layout.itemAt(i).widget() is listw)
        assert layout.stretch(i) >= 1


class TestTheBlur:
    def test_the_knob_is_on_the_gene_panel(self, qt, panel):
        """Which is the point of it: the gene layers are what is sparse."""
        boxes = panel.findChildren(qt.QDoubleSpinBox)
        assert any(b.suffix().strip() == "um" for b in boxes)

    def test_it_starts_off(self, qt, panel):
        blur = next(b for b in panel.findChildren(qt.QDoubleSpinBox) if b.suffix().strip() == "um")
        assert blur.value() == pytest.approx(0.0)
