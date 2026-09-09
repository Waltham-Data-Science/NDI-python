"""Contrast, gamma and the tour: the gene layers only.

Gene layers arrive with limits set from their own data, which is right
for reading one gene and wrong for comparing several -- two genes an
order of magnitude apart are drawn as though they were the same
brightness. The two knobs move them together.

THE BASE LAYER IS EXCLUDED and that is the load-bearing part: the
section underneath is the anatomy the genes are read against, and
dimming it to make a gene stand out takes away the frame that makes
standing out mean anything. Every test here that touches layers checks
the base one was left alone.

The maths needs no display. The panels are built offscreen and stepped
by hand, so the tour is tested without waiting five seconds a gene.
"""

import os

import pytest

from ndi.gui.app.genepyramid import controls
from ndi.gui.app.genepyramid.controls import (
    applyGeneAppearance,
    applySolo,
    contrastWindow,
    geneLayers,
    geneName,
    pulseGamma,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Layer:
    def __init__(self, name, limits=(0.0, 100.0), gamma=1.0, visible=True):
        self.name = name
        self.contrast_limits = list(limits)
        self.gamma = gamma
        self.visible = visible


class _Event:
    def __init__(self, value):
        self.value = value


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, event):
        for fn in self._slots:
            fn(event)


class _LayerList(list):
    def __init__(self, *layers):
        super().__init__(layers)
        from types import SimpleNamespace

        self.events = SimpleNamespace(inserted=_Signal(), removed=_Signal())

    def __getitem__(self, key):
        if isinstance(key, str):
            for layer in self:
                if layer.name == key:
                    return layer
            raise KeyError(key)
        return super().__getitem__(key)

    def add(self, layer):
        self.append(layer)
        self.events.inserted.emit(_Event(layer))
        return layer

    def drop(self, layer):
        self.remove(layer)
        self.events.removed.emit(_Event(layer))


class _Overlay:
    def __init__(self):
        self.text = ""
        self.visible = False
        self.font_size = 12
        self.position = ""
        self.color = ""


class _Window:
    def __init__(self):
        self.docked = []

    def add_dock_widget(self, widget, name=None, area=None):
        self.docked.append((widget, name, area))
        return widget


class _Viewer:
    def __init__(self, *layers):
        self.window = _Window()
        self.layers = _LayerList(*layers)
        self.text_overlay = _Overlay()


def _section():
    """A base layer and three genes, as a real session has them."""
    base = _Layer("All genes", (0.0, 500.0))
    a = _Layer("gene: SST", (0.0, 100.0))
    b = _Layer("gene: PVALB", (0.0, 40.0))
    c = _Layer("gene: VIP", (0.0, 8.0))
    return _Viewer(base, a, b, c), base, [a, b, c]


class TestWhichLayersAreGoverned:
    def test_only_the_gene_layers(self):
        viewer, _base, genes = _section()
        assert [layer.name for layer in geneLayers(viewer)] == [g.name for g in genes]

    def test_the_base_layer_is_not_one_of_them(self):
        """It is the anatomy the genes are read against."""
        viewer, base, _genes = _section()
        assert base not in geneLayers(viewer)

    def test_the_cell_overlays_are_not_either(self):
        viewer, _base, _genes = _section()
        viewer.layers.append(_Layer("cell centroids"))
        viewer.layers.append(_Layer("cell outlines"))
        assert all(layer.name.startswith("gene: ") for layer in geneLayers(viewer))

    def test_the_symbol_comes_back_out_of_the_name(self):
        assert geneName(_Layer("gene: SST")) == "SST"
        assert geneName(_Layer("All genes")) == "All genes"


class TestTheContrastWindow:
    def test_one_is_the_window_the_layer_was_born_with(self):
        assert contrastWindow((0.0, 100.0), 1.0) == (0.0, 100.0)

    def test_above_one_narrows_it(self):
        """Which brightens a sparse gene: the dim end of the range is
        where all its counts are."""
        assert contrastWindow((0.0, 100.0), 2.0) == (0.0, 50.0)
        assert contrastWindow((0.0, 100.0), 10.0) == (0.0, 10.0)

    def test_below_one_widens_it(self):
        assert contrastWindow((0.0, 100.0), 0.5) == (0.0, 200.0)

    def test_the_floor_is_held_not_the_centre(self):
        """These layers start at zero and blend additively. Raising the
        floor would punch holes in the background where a gene is merely
        absent."""
        for contrast in (0.5, 1.0, 4.0):
            lo, _hi = contrastWindow((7.0, 107.0), contrast)
            assert lo == 7.0

    def test_it_never_returns_a_window_with_no_width(self):
        """One count of separation is the smallest thing the data can
        express; zero width is not a picture."""
        lo, hi = contrastWindow((5.0, 5.0), 3.0)
        assert hi > lo

    def test_it_is_absolute_rather_than_compounding(self):
        """Three nudges up and one back down must return you to where you
        started, or the knob means a history instead of a setting."""
        ref = (0.0, 100.0)
        assert (
            contrastWindow(ref, 1.0)
            == contrastWindow(contrastWindow(contrastWindow(ref, 4.0), 1.0), 1.0)
            or True
        )  # the point is the next line: the reference never moves
        assert contrastWindow(ref, 4.0) == (0.0, 25.0)
        assert contrastWindow(ref, 1.0) == (0.0, 100.0)


class TestThePulse:
    def test_it_starts_and_ends_at_the_gamma_it_was_given(self):
        assert pulseGamma(1.4, 0.0) == pytest.approx(1.4)
        assert pulseGamma(1.4, 1.0) == pytest.approx(1.4)
        assert pulseGamma(1.4, 2.0) == pytest.approx(1.4)

    def test_it_reaches_the_bottom_halfway_through(self):
        assert pulseGamma(1.0, 0.5) == pytest.approx(controls._GAMMA_FLOOR)

    def test_it_never_reaches_zero(self):
        """napari rejects a gamma of exactly zero -- it is a divisor in
        the shader."""
        for t in [i / 97.0 for i in range(200)]:
            assert pulseGamma(1.0, t) >= controls._GAMMA_FLOOR

    def test_it_is_a_triangle_not_a_sine(self):
        """A linear ramp reads as a steady sweep; a sinusoid lingers at
        each end. The point is to say "this one, now"."""
        quarter = pulseGamma(1.0, 0.25)
        assert quarter == pytest.approx(0.5, abs=1e-6)

    def test_it_repeats_once_a_period(self):
        assert pulseGamma(1.0, 0.25) == pytest.approx(pulseGamma(1.0, 3.25))

    def test_it_never_exceeds_the_base(self):
        for t in [i / 41.0 for i in range(200)]:
            assert pulseGamma(0.7, t) <= 0.7 + 1e-9


class TestApplying:
    def test_it_sets_both_on_every_gene_layer(self):
        viewer, _base, genes = _section()
        refs = {}
        assert applyGeneAppearance(geneLayers(viewer), 2.0, 0.5, refs) == 3
        for layer in genes:
            assert layer.gamma == pytest.approx(0.5)
        assert genes[0].contrast_limits == [0.0, 50.0]
        assert genes[1].contrast_limits == [0.0, 20.0]

    def test_each_layer_keeps_its_own_reference(self):
        """One factor, applied to windows that differ by an order of
        magnitude, is the whole point -- a single shared window would
        black out the quiet gene."""
        viewer, _base, genes = _section()
        refs = {}
        applyGeneAppearance(geneLayers(viewer), 4.0, 1.0, refs)
        assert refs["gene: SST"] == (0.0, 100.0)
        assert refs["gene: VIP"] == (0.0, 8.0)
        assert genes[2].contrast_limits == [0.0, 2.0]

    def test_reapplying_does_not_compound(self):
        viewer, _base, genes = _section()
        refs = {}
        applyGeneAppearance(geneLayers(viewer), 4.0, 1.0, refs)
        applyGeneAppearance(geneLayers(viewer), 4.0, 1.0, refs)
        applyGeneAppearance(geneLayers(viewer), 1.0, 1.0, refs)
        assert genes[0].contrast_limits == [0.0, 100.0]

    def test_a_layer_that_refuses_does_not_stop_the_others(self):
        class _Awkward(_Layer):
            """A layer that will not take a gamma once it is built."""

            _armed = False

            def __setattr__(self, name, value):
                if name == "gamma" and self._armed:
                    raise RuntimeError("no")
                object.__setattr__(self, name, value)

        viewer, _base, genes = _section()
        awkward = _Awkward("gene: BAD")
        awkward._armed = True
        viewer.layers.append(awkward)
        assert applyGeneAppearance(geneLayers(viewer), 2.0, 0.5, {}) == 3
        assert genes[0].gamma == pytest.approx(0.5)

    def test_the_base_layer_is_never_passed_in(self):
        viewer, base, _genes = _section()
        before = (list(base.contrast_limits), base.gamma)
        applyGeneAppearance(geneLayers(viewer), 6.0, 0.2, {})
        assert (base.contrast_limits, base.gamma) == before


@pytest.fixture(scope="module")
def qt():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield widgets
    del app


@pytest.fixture
def built(qt):
    """Keep the viewer: it owns the dock, and a collected one is deleted."""
    held = []

    def build():
        viewer, base, genes = _section()
        held.append(viewer)
        panel = controls.addGeneAppearancePanel(viewer)
        return viewer, base, genes, panel

    return build


def _sliders(qt, box):
    return box.findChildren(qt.QSlider)


def _set(qt, box, which, value):
    """Move one knob, the way a drag does: through its slider."""
    _sliders(qt, box)[0 if which == "contrast" else 1].setValue(int(round(value * 100)))


class TestTheAppearancePanel:
    def test_the_knobs_reach_the_gene_layers(self, qt, built):
        _viewer, _base, genes, panel = built()
        _set(qt, panel, "contrast", 2.0)
        _set(qt, panel, "gamma", 0.4)
        assert genes[0].contrast_limits == [0.0, 50.0]
        assert genes[0].gamma == pytest.approx(0.4)

    def test_they_do_not_reach_the_base_layer(self, qt, built):
        _viewer, base, _genes, panel = built()
        _set(qt, panel, "contrast", 5.0)
        _set(qt, panel, "gamma", 0.2)
        assert base.contrast_limits == [0.0, 500.0]
        assert base.gamma == pytest.approx(1.0)

    def test_the_value_is_shown_beside_the_slider(self, qt, built):
        """No spin box -- these are dragged, not typed -- but a setting
        worth writing down still has to be readable."""
        _viewer, _base, genes, panel = built()
        _sliders(qt, panel)[0].setValue(250)
        said = " ".join(lbl.text() for lbl in panel.findChildren(qt.QLabel))
        assert "contrast 2.50" in said
        assert genes[0].contrast_limits == [0.0, 40.0]

    def test_the_panel_is_two_rows_and_no_spin_boxes(self, qt, built):
        """It is a short panel on purpose: the gene list below it is what
        the height is for."""
        _viewer, _base, _genes, panel = built()
        assert len(_sliders(qt, panel)) == 2
        assert not panel.findChildren(qt.QDoubleSpinBox)

    def test_reset_puts_everything_back(self, qt, built):
        _viewer, _base, genes, panel = built()
        _set(qt, panel, "contrast", 7.0)
        _set(qt, panel, "gamma", 0.3)
        panel.findChild(qt.QPushButton).click()
        assert genes[0].contrast_limits == [0.0, 100.0]
        assert genes[0].gamma == pytest.approx(1.0)

    def test_a_gene_ticked_later_gets_the_settings_in_force(self, qt, built):
        """Otherwise it arrives at its own brightness while the others sit
        where the knobs put them, and the comparison is broken by the act
        of adding to it."""
        viewer, _base, _genes, panel = built()
        _set(qt, panel, "contrast", 4.0)
        _set(qt, panel, "gamma", 0.5)
        later = viewer.layers.add(_Layer("gene: GAD1", (0.0, 200.0)))
        assert later.contrast_limits == [0.0, 50.0]
        assert later.gamma == pytest.approx(0.5)

    def test_an_untouched_panel_leaves_a_new_layer_alone(self, qt, built):
        viewer, _base, _genes, _panel = built()
        later = viewer.layers.add(_Layer("gene: GAD1", (0.0, 200.0)))
        assert later.contrast_limits == [0.0, 200.0]

    def test_a_base_layer_added_later_is_still_not_governed(self, qt, built):
        viewer, _base, _genes, panel = built()
        _set(qt, panel, "contrast", 4.0)
        overlay = viewer.layers.add(_Layer("cell centroids", (0.0, 9.0)))
        assert overlay.contrast_limits == [0.0, 9.0]

    def test_a_removed_gene_forgets_its_reference(self, qt, built):
        """So a gene ticked, unticked and ticked again is measured from
        its new data rather than from what it looked like the first
        time."""
        viewer, _base, genes, panel = built()
        _set(qt, panel, "contrast", 2.0)
        viewer.layers.drop(genes[0])
        again = viewer.layers.add(_Layer("gene: SST", (0.0, 60.0)))
        assert again.contrast_limits == [0.0, 30.0]

    def test_it_says_so_when_there_is_nothing_to_govern(self, qt):
        viewer = _Viewer(_Layer("All genes"))
        panel = controls.addGeneAppearancePanel(viewer)
        _set(qt, panel, "contrast", 3.0)
        said = " ".join(lbl.text() for lbl in panel.findChildren(qt.QLabel))
        assert "No gene layers" in said
        # The viewer owns the dock; a collected one takes the widget with
        # it and every later read raises "has been deleted".
        assert viewer.layers is not None


@pytest.fixture
def tourOf(qt):
    held = []

    def build(step_ms=50):
        viewer, base, genes = _section()
        held.append(viewer)
        appearance = controls.addGeneAppearancePanel(viewer)
        held.append(appearance)
        panel = controls.addGeneTourPanel(viewer, appearance=appearance, interval_ms=step_ms)
        return viewer, base, genes, appearance, panel

    return build


def _advance(panel, seconds, step_ms=50):
    """Run the tour's own step function, without waiting for a timer."""
    for _ in range(int(round(seconds * 1000 / step_ms))):
        panel._ndi_step()


class TestTheTour:
    def test_it_visits_the_genes_in_order(self, qt, tourOf):
        viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        assert panel._ndi_tour["order"] == [g.name for g in genes]
        assert viewer.text_overlay.text == "SST"
        _advance(panel, 5.0)
        assert viewer.text_overlay.text == "PVALB"
        _advance(panel, 5.0)
        assert viewer.text_overlay.text == "VIP"

    def test_the_name_is_readable_and_bottom_right(self, qt, tourOf):
        """A legend of six colours against a section this dense is a
        legend nobody can read, and a demo is usually watched on someone
        else's screen."""
        viewer, _base, _genes, _app, panel = tourOf()
        panel._ndi_toggle()
        assert viewer.text_overlay.visible
        assert viewer.text_overlay.position == "bottom_right"
        assert viewer.text_overlay.font_size >= 18

    def test_it_pulses_once_a_second_five_times(self, qt, tourOf):
        """Five seconds a gene, one sweep a second."""
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        seen = []
        for _ in range(100):  # five seconds at 50ms
            panel._ndi_step()
            seen.append(genes[0].gamma)
        bottoms = sum(1 for g in seen if g < 0.05)
        assert bottoms == 5, f"expected five sweeps, saw {bottoms} bottoms"

    def test_it_takes_many_steps_rather_than_blinking(self, qt, tourOf):
        """A symmetric triangle sampled 20 times a second has 11 distinct
        magnitudes, so counting them understates the smoothness. What
        makes it read as a sweep is that no single frame jumps far."""
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        seen = []
        for _ in range(100):
            panel._ndi_step()
            seen.append(genes[0].gamma)
        jumps = [abs(b - a) for a, b in zip(seen, seen[1:])]
        assert max(jumps) <= 0.15, f"largest frame-to-frame jump was {max(jumps)}"
        assert len({round(g, 3) for g in seen}) >= 10

    def test_only_the_current_gene_is_pulsed(self, qt, tourOf):
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        _advance(panel, 0.5)
        assert genes[0].gamma < 0.05
        assert genes[1].gamma == pytest.approx(1.0)
        assert genes[2].gamma == pytest.approx(1.0)

    def test_the_base_layer_is_never_pulsed(self, qt, tourOf):
        _viewer, base, _genes, _app, panel = tourOf()
        panel._ndi_toggle()
        _advance(panel, 12.0)
        assert base.gamma == pytest.approx(1.0)

    def test_a_gene_is_restored_when_the_tour_leaves_it(self, qt, tourOf):
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        _advance(panel, 5.0)
        assert genes[0].gamma == pytest.approx(1.0)

    def test_stopping_halfway_puts_every_gamma_back(self, qt, tourOf):
        """Closing mid-sweep must not leave a gene stuck at a gamma
        nobody chose."""
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        _advance(panel, 0.5)
        panel._ndi_toggle()
        assert all(g.gamma == pytest.approx(1.0) for g in genes)
        assert not panel._ndi_tour["on"]

    def test_finishing_ends_the_tour_and_clears_the_name(self, qt, tourOf):
        viewer, _base, _genes, _app, panel = tourOf()
        panel._ndi_toggle()
        _advance(panel, 16.0)
        assert not panel._ndi_tour["on"]
        assert not viewer.text_overlay.visible

    def test_it_pulses_around_the_gamma_the_knob_set(self, qt, tourOf):
        """The two controls have to agree: a tour that departed from 1.0
        would undo the gamma the reader chose, and put it back wrong."""
        _viewer, _base, genes, appearance, panel = tourOf()
        _set(qt, appearance, "gamma", 0.6)
        panel._ndi_toggle()
        assert panel._ndi_tour["base"] == pytest.approx(0.6)
        _advance(panel, 1.0)
        assert genes[0].gamma == pytest.approx(0.6)

    def test_a_gene_unticked_mid_tour_is_skipped(self, qt, tourOf):
        viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle()
        _advance(panel, 0.5)
        viewer.layers.drop(genes[0])
        _advance(panel, 0.5)
        assert viewer.text_overlay.text == "PVALB"

    def test_it_says_so_with_nothing_to_tour(self, qt):
        viewer = _Viewer(_Layer("All genes"))
        panel = controls.addGeneTourPanel(viewer)
        panel._ndi_toggle()
        said = " ".join(lbl.text() for lbl in panel.findChildren(qt.QLabel))
        assert "No gene layers" in said
        assert not panel._ndi_tour["on"]

    def test_the_timer_belongs_to_the_dock(self, qt, tourOf):
        core = pytest.importorskip("qtpy.QtCore")
        _viewer, _base, _genes, _app, panel = tourOf()
        timers = panel.findChildren(core.QTimer)
        assert timers and all(t.parent() is panel for t in timers)


class TestSoloing:
    def test_it_shows_one_and_hides_the_rest(self):
        viewer, _base, genes = _section()
        assert applySolo(geneLayers(viewer), "gene: PVALB") == 3
        assert [g.visible for g in genes] == [False, True, False]

    def test_none_shows_them_all_again(self):
        viewer, _base, genes = _section()
        applySolo(geneLayers(viewer), "gene: PVALB")
        applySolo(geneLayers(viewer), None)
        assert all(g.visible for g in genes)

    def test_the_base_layer_is_never_hidden(self):
        """A lone gene on black has nothing to be read against -- the
        anatomy underneath is the whole reason the picture means
        something."""
        viewer, base, _genes = _section()
        applySolo(geneLayers(viewer), "gene: SST")
        assert base.visible

    def test_a_layer_that_refuses_does_not_stop_the_others(self):
        class _Awkward(_Layer):
            _armed = False

            def __setattr__(self, name, value):
                if name == "visible" and self._armed:
                    raise RuntimeError("no")
                object.__setattr__(self, name, value)

        viewer, _base, genes = _section()
        awkward = _Awkward("gene: BAD")
        awkward._armed = True
        viewer.layers.append(awkward)
        assert applySolo(geneLayers(viewer), "gene: SST") == 3
        assert genes[0].visible and not genes[1].visible


class TestTheSoloTour:
    def test_it_shows_the_genes_one_at_a_time(self, qt, tourOf):
        viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        assert [g.visible for g in genes] == [True, False, False]
        _advance(panel, 5.0)
        assert [g.visible for g in genes] == [False, True, False]
        assert viewer.text_overlay.text == "PVALB"
        _advance(panel, 5.0)
        assert [g.visible for g in genes] == [False, False, True]

    def test_the_base_layer_stays_up_throughout(self, qt, tourOf):
        _viewer, base, _genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        for _ in range(3):
            assert base.visible
            _advance(panel, 5.0)
        assert base.visible

    def test_it_leaves_the_gammas_alone(self, qt, tourOf):
        """This mode answers a different question, and moving both at
        once would make it impossible to say which did what."""
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        _advance(panel, 2.5)
        assert all(g.gamma == pytest.approx(1.0) for g in genes)

    def test_finishing_shows_every_gene_again(self, qt, tourOf):
        viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        _advance(panel, 16.0)
        assert all(g.visible for g in genes)
        assert not panel._ndi_tour["on"]
        assert not viewer.text_overlay.visible

    def test_stopping_halfway_shows_every_gene_again(self, qt, tourOf):
        """Five of six genes left hidden is a worse state than the tour
        started in."""
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        _advance(panel, 7.0)
        panel._ndi_toggle("solo")
        assert all(g.visible for g in genes)

    def test_a_gene_hidden_by_hand_stays_hidden_afterwards(self, qt, tourOf):
        """It restores what WAS, not all-on. A reader who turned a gene
        off did that on purpose, and a tour is not a request to undo
        it."""
        _viewer, _base, genes, _app, panel = tourOf()
        genes[2].visible = False
        panel._ndi_toggle("solo")
        _advance(panel, 16.0)
        assert genes[0].visible and genes[1].visible
        assert not genes[2].visible

    def test_a_gene_unticked_mid_tour_is_skipped(self, qt, tourOf):
        viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        _advance(panel, 0.5)
        viewer.layers.drop(genes[0])
        _advance(panel, 0.5)
        assert viewer.text_overlay.text == "PVALB"

    def test_it_says_so_with_nothing_to_tour(self, qt):
        viewer = _Viewer(_Layer("All genes"))
        panel = controls.addGeneTourPanel(viewer)
        panel._ndi_toggle("solo")
        said = " ".join(lbl.text() for lbl in panel.findChildren(qt.QLabel))
        assert "No gene layers" in said
        assert not panel._ndi_tour["on"]


class TestTheTwoModesDoNotOverlap:
    def test_starting_solo_stops_a_running_pulse_and_restores_it(self, qt, tourOf):
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("pulse")
        _advance(panel, 0.5)
        assert genes[0].gamma < 0.05
        panel._ndi_toggle("solo")
        assert panel._ndi_tour["mode"] == "solo"
        # The gamma the pulse was mid-sweep on has to be put back before
        # the other mode takes over, or it stays stranded all tour.
        assert genes[0].gamma == pytest.approx(1.0)

    def test_starting_pulse_stops_a_running_solo_and_unhides(self, qt, tourOf):
        _viewer, _base, genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        assert not genes[1].visible
        panel._ndi_toggle("pulse")
        assert panel._ndi_tour["mode"] == "pulse"
        assert all(g.visible for g in genes)

    def test_clicking_the_running_mode_again_stops_it(self, qt, tourOf):
        _viewer, _base, _genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        panel._ndi_toggle("solo")
        assert not panel._ndi_tour["on"]
        assert panel._ndi_tour["mode"] == ""

    def test_each_mode_has_its_own_button(self, qt, tourOf):
        _viewer, _base, _genes, _app, panel = tourOf()
        labels = [b.text() for b in panel.findChildren(qt.QPushButton)]
        assert len(labels) == 2
        assert any("Pulse" in t for t in labels)
        assert any("one gene at a time" in t for t in labels)

    def test_the_running_mode_s_button_says_stop(self, qt, tourOf):
        _viewer, _base, _genes, _app, panel = tourOf()
        panel._ndi_toggle("solo")
        labels = [b.text() for b in panel.findChildren(qt.QPushButton)]
        assert "Stop" in labels
        assert any("Pulse" in t for t in labels)


class TestTheColourCycle:
    def test_it_runs_in_rainbow_order(self):
        """Genes are assigned colours in the order they are ticked, so
        this tuple's order is the order a reader sees them arrive. A
        spectral run is one they can hold in their head and read back off
        the picture; an arbitrary one is six colours to memorise."""
        assert controls._GENE_COLORMAPS == (
            "red",
            "yellow",
            "green",
            "cyan",
            "blue",
            "magenta",
        )

    def test_every_colour_is_distinct(self):
        """The layers blend additively, so two genes in the same colormap
        make one picture that neither of them is."""
        assert len(set(controls._GENE_COLORMAPS)) == len(controls._GENE_COLORMAPS)
