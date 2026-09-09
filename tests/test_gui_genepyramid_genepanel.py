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

from ndi.gui.app.genepyramid import controls

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


class _AddedLayer:
    """Whatever viewer.add_image handed back, as the panel treats it."""

    def __init__(self, name, colormap=None, blending=None):
        self.name = name
        self.colormap = colormap
        self.blending = blending
        self.data = None

    def reset_contrast_limits(self):
        pass


class _Viewer:
    def __init__(self):
        self.window = _Window()
        self.layers = _Layers()
        self.added = []

    def add_image(self, **kwargs):
        layer = _AddedLayer(kwargs.get("name", ""), kwargs.get("colormap"), kwargs.get("blending"))
        self.added.append(layer)
        self.layers[layer.name] = layer
        return layer


@pytest.fixture
def panelWith(qt, monkeypatch):
    """Build the gene panel over a stub list, with genes preset."""
    held = []

    def build(initial=None, symbols=None):
        from ndi.fun import doc_gene_export
        from ndi.gui.app.genepyramid import controls

        names = list(symbols or [f"GENE{i:04d}" for i in range(40)])
        monkeypatch.setattr(
            doc_gene_export, "readGeneList", lambda *a, **k: (list(names), list(names))
        )
        monkeypatch.setattr(
            doc_gene_export,
            "readGeneTotals",
            lambda *a, **k: (np.arange(len(names), dtype=float), None),
        )
        from ndi.gui.app.genepyramid import multiscale

        monkeypatch.setattr(
            multiscale,
            "layerSpec",
            lambda _s, _p, _rows, _d, name: {"data": [], "name": name},
        )
        viewer = _Viewer()
        held.append(viewer)
        panel = controls.addGenePanel(viewer, object(), object(), initial=initial)
        return viewer, panel

    return build


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


class TestGenesOpenedAtLaunch:
    """``--gene-layers`` reaches the panel as ``initial``.

    A DIFFERENT REQUEST from ``--genes``, which filters the base image
    down to a subset and leaves one picture. These arrive as their own
    additive layers ON TOP of the base, which is what makes several
    genes comparable -- and it is why the demo command carries the one
    option and not the other.
    """

    def test_each_gene_becomes_its_own_layer(self, panelWith):
        viewer, _panel = panelWith(initial=[("GENE0000", "green"), ("GENE0001", "blue")])
        assert [layer.name for layer in viewer.added] == ["gene: GENE0000", "gene: GENE0001"]

    def test_the_named_colours_are_used(self, panelWith):
        viewer, _panel = panelWith(initial=[("GENE0000", "green"), ("GENE0001", "bop orange")])
        assert [layer.colormap for layer in viewer.added] == ["green", "bop orange"]

    def test_they_blend_additively(self, panelWith):
        """Which is what lets two genes be read over one another rather
        than one hiding the other."""
        viewer, _panel = panelWith(initial=[("GENE0000", "green")])
        assert viewer.added[0].blending == "additive"

    def test_a_gene_with_no_colour_takes_one_from_the_cycle(self, panelWith):
        viewer, _panel = panelWith(initial=[("GENE0000", None)])
        assert viewer.added[0].colormap == controls._GENE_COLORMAPS[0]

    def test_a_named_colour_does_not_advance_the_cycle(self, panelWith):
        """Otherwise the first hand-ticked gene's colour would depend on
        how many were preset, which is a surprise with no upside."""
        viewer, _panel = panelWith(
            initial=[("GENE0000", "green"), ("GENE0001", "blue"), ("GENE0002", None)]
        )
        assert viewer.added[2].colormap == controls._GENE_COLORMAPS[0]

    def test_the_boxes_are_ticked_too(self, qt, panelWith):
        """Ticked through the panel's own checkbox, not by adding the
        layer behind its back: otherwise unticking a preset gene would do
        nothing at all."""
        _viewer, panel = panelWith(initial=[("GENE0000", "green")])
        listw = panel.findChild(qt.QListWidget)
        # Qt.Checked is 2; compared numerically rather than importing the
        # enum, which qtpy spells differently across bindings.
        ticked = [
            listw.item(i).text()
            for i in range(listw.count())
            if int(listw.item(i).checkState()) == 2
        ]
        assert len(ticked) == 1
        assert ticked[0].startswith("GENE0000")

    def test_a_gene_not_in_this_pyramid_is_said_out_loud(self, qt, panelWith):
        """A demo that quietly opens four of six layers looks like the
        viewer working."""
        viewer, panel = panelWith(initial=[("GENE0000", "green"), ("NOTHERE", "red")])
        said = " ".join(lbl.text() for lbl in panel.findChildren(qt.QLabel))
        assert "NOTHERE" in said
        # and the ones that ARE there still open
        assert [layer.name for layer in viewer.added] == ["gene: GENE0000"]

    def test_no_preset_opens_nothing(self, panelWith):
        viewer, _panel = panelWith()
        assert viewer.added == []

    def test_the_ferret_demo_spec_opens_six_coloured_layers(self, panelWith):
        """End to end from the string NDI-matlab builds."""
        spec = "HPCAL1:green,RORB:blue,FEZF2:bop orange,TSHZ2:yellow,NXPH4:red,SST:cyan"
        symbols = ["HPCAL1", "RORB", "FEZF2", "TSHZ2", "NXPH4", "SST", "OTHER"]
        viewer, _panel = panelWith(initial=controls.parseGeneLayers(spec), symbols=symbols)
        assert [layer.name for layer in viewer.added] == [f"gene: {s}" for s in symbols[:6]]
        assert [layer.colormap for layer in viewer.added] == [
            "green",
            "blue",
            "bop orange",
            "yellow",
            "red",
            "cyan",
        ]


class TestTheBlurKnobWaits:
    """A spin box emits on every keystroke.

    Typing "50" asks for 5 um first, and re-blurring is a whole-ladder
    map_overlap that takes long enough to see -- so the picture visibly
    redrew at the wrong width before the second digit landed.
    """

    def test_typing_does_not_reblur_at_once(self, qt, panel):
        blur = next(b for b in panel.findChildren(qt.QDoubleSpinBox) if b.suffix().strip() == "um")
        wait = panel._ndi_blur_wait
        assert not wait.isActive()
        blur.setValue(5.0)
        assert wait.isActive(), "the blur applied on the first keystroke"

    def test_it_waits_long_enough_for_a_second_digit(self, qt, panel):
        """Past the gap between two digits, and short enough not to feel
        stuck."""
        assert 1000 <= panel._ndi_blur_wait.interval() <= 2000

    def test_the_wait_restarts_with_each_keystroke(self, qt, panel):
        """Otherwise "500" would fire partway through, at 50."""
        blur = next(b for b in panel.findChildren(qt.QDoubleSpinBox) if b.suffix().strip() == "um")
        wait = panel._ndi_blur_wait
        blur.setValue(5.0)
        first = wait.remainingTime()
        blur.setValue(50.0)
        assert wait.remainingTime() >= first - 50

    def test_it_fires_once_rather_than_repeating(self, qt, panel):
        assert panel._ndi_blur_wait.isSingleShot()

    def test_the_wait_belongs_to_the_panel(self, qt, panel):
        core = pytest.importorskip("qtpy.QtCore")
        assert panel._ndi_blur_wait.parent() is panel
        assert isinstance(panel._ndi_blur_wait, core.QTimer)

    def test_finishing_the_edit_stops_the_wait(self, qt, panel):
        """Enter, or clicking away, means the number IS finished -- no
        reason to sit out the rest of the wait."""
        blur = next(b for b in panel.findChildren(qt.QDoubleSpinBox) if b.suffix().strip() == "um")
        blur.setValue(50.0)
        assert panel._ndi_blur_wait.isActive()
        blur.editingFinished.emit()
        assert not panel._ndi_blur_wait.isActive()
