"""Turning the whole picture: the affine, the pivot, and the layers together.

Sections are not mounted square, and lining one up against an atlas plate
or a companion section wants an arbitrary angle rather than the 90-degree
steps napari offers on the canvas.

Everything worth holding here is testable with no display and no napari:
the SIGN of the rotation, the PIVOT it turns about, and that every layer
gets the SAME matrix. The panel's ARRANGEMENT needs real widgets, so
those tests build it offscreen and skip where there is no Qt binding
-- which is CI today.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from ndi.gui.app.genepyramid.controls import (
    applyRotation,
    rotationAffine,
    rotationCenter,
)


def apply(a, point):
    """Push a ``(row, col)`` point through a 3x3 homogeneous affine."""
    v = a @ np.array([point[0], point[1], 1.0])
    return (v[0], v[1])


class TestTheMatrix:
    def test_zero_is_the_identity(self):
        assert np.allclose(rotationAffine(0, (100.0, 200.0)), np.eye(3))

    def test_a_full_turn_is_the_identity(self):
        assert np.allclose(rotationAffine(360, (100.0, 200.0)), np.eye(3), atol=1e-9)

    def test_the_pivot_is_the_one_point_that_does_not_move(self):
        """The whole promise of 'rotate about the view centre'."""
        c = (137.0, -41.5)
        for angle in (-180, -33, 0, 17, 90, 180):
            assert np.allclose(apply(rotationAffine(angle, c), c), c, atol=1e-9)

    def test_positive_is_anticlockwise_on_screen(self):
        """THE SIGN, checked rather than reasoned about.

        napari rows increase DOWNWARD (the pyramid records
        ``origin_corner: upper-left``). A point to the RIGHT of the pivot
        must land ABOVE it -- smaller row, same column -- at +90 degrees.
        """
        c = (0.0, 0.0)
        row, col = apply(rotationAffine(90, c), (0.0, 1.0))
        assert row == pytest.approx(-1.0, abs=1e-9), "right of pivot should go ABOVE it"
        assert col == pytest.approx(0.0, abs=1e-9)

    def test_it_is_a_rotation_not_a_scale_or_a_flip(self):
        """A determinant of -1 would mirror the section, which would be a
        wrong picture that still looks like a picture."""
        for angle in (13, 47, 90, 180, -75):
            m = rotationAffine(angle, (10.0, 20.0))[:2, :2]
            assert np.linalg.det(m) == pytest.approx(1.0, abs=1e-12)
            assert np.allclose(m @ m.T, np.eye(2), atol=1e-12)

    def test_distance_from_the_pivot_is_preserved(self):
        c = (50.0, 60.0)
        p = (110.0, -20.0)
        before = np.hypot(p[0] - c[0], p[1] - c[1])
        got = apply(rotationAffine(29, c), p)
        after = np.hypot(got[0] - c[0], got[1] - c[1])
        assert after == pytest.approx(before, rel=1e-12)

    def test_opposite_angles_undo_each_other(self):
        """The control is ABSOLUTE, not accumulated, but the matrix still
        has to be a proper inverse or repeated adjustment would drift."""
        c = (7.0, 3.0)
        a = rotationAffine(38, c)
        b = rotationAffine(-38, c)
        assert np.allclose(a @ b, np.eye(3), atol=1e-12)


class TestTheCentre:
    class FakeCamera:
        def __init__(self, center):
            self.center = center

    class FakeViewer:
        def __init__(self, center):
            self.camera = TestTheCentre.FakeCamera(center)

    def test_a_3d_camera_centre_gives_row_and_column(self):
        """napari reports ``(z, y, x)`` even for 2D data, with z = 0."""
        assert rotationCenter(self.FakeViewer((0.0, 250.0, 400.0))) == (250.0, 400.0)

    def test_a_2_tuple_still_works(self):
        """Taking the LAST two rather than indexing 1 and 2."""
        assert rotationCenter(self.FakeViewer((250.0, 400.0))) == (250.0, 400.0)

    def test_a_centre_with_nothing_to_read_raises(self):
        with pytest.raises(ValueError, match="no row/column"):
            rotationCenter(self.FakeViewer((5.0,)))


class FakeLayer:
    def __init__(self):
        self.affine = None


class TestTheLayersMoveTogether:
    def test_every_layer_gets_the_same_matrix(self):
        """The section, the cells and their outlines are ONE picture. A
        control that could slide them apart is one that can produce a
        wrong picture."""
        layers = [FakeLayer(), FakeLayer(), FakeLayer()]
        applied = applyRotation(layers, 23.5, (100.0, 100.0))
        for layer in layers:
            assert np.allclose(layer.affine, applied)

    def test_missing_layers_are_skipped_not_an_error(self):
        """Outlines and centroids are optional; a session without them is
        the normal case."""
        image = FakeLayer()
        applyRotation([image, None, None], 10.0, (0.0, 0.0))
        assert image.affine is not None

    def test_it_returns_what_it_applied(self):
        image = FakeLayer()
        applied = applyRotation([image], 45.0, (1.0, 2.0))
        assert np.allclose(applied, rotationAffine(45.0, (1.0, 2.0)))

    def test_a_later_angle_replaces_rather_than_compounds(self):
        """Absolute, not accumulated: two 30-degree settings leave the
        picture at 30 degrees, not 60."""
        image = FakeLayer()
        applyRotation([image], 30.0, (0.0, 0.0))
        applyRotation([image], 30.0, (0.0, 0.0))
        assert np.allclose(image.affine, rotationAffine(30.0, (0.0, 0.0)))


# --------------------------------------------------------------- layout


@pytest.fixture(scope="module")
def qt():
    """A real Qt, drawn to nowhere, or a skip.

    The panel's arrangement is the thing being checked here, and an
    arrangement is a property of real widgets in a real layout -- stubbing
    them out would only test the stubs. The offscreen platform gives real
    widgets with no display, which is what CI has. CI does not install Qt
    at all today, so this skips there and runs for anyone who does.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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


class _Viewer:
    def __init__(self):
        self.window = _Window()
        self.camera = SimpleNamespace(center=(0.0, 100.0, 200.0))


def _rotationPanel(qt):
    from ndi.gui.app.genepyramid.controls import addRotationPanel

    viewer = _Viewer()
    return addRotationPanel(viewer, [])


def _rows(qt, box):
    """The panel's top-level layout, as a list of rows.

    Each entry is either a widget or the list of widgets on a nested row,
    which is exactly the distinction the arrangement turns on.
    """
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


class TestTheArrangement:
    def test_the_slider_gets_a_row_of_its_own(self, qt):
        """Sharing a row with the number and the Reset button left it a
        stub too short to aim with: a dock panel is narrow and those two
        take a fixed width out of it whatever is left over."""
        box = _rotationPanel(qt)
        rows = _rows(qt, box)
        sliders = [r for r in rows if isinstance(r, qt.QSlider)]
        assert len(sliders) == 1, "the slider is not a row by itself"

    def test_the_slider_sits_under_the_number(self, qt):
        """Which is where it was asked for, and reads as belonging to the
        angle above it rather than as a third control beside it."""
        box = _rotationPanel(qt)
        rows = _rows(qt, box)
        spin_row = next(
            i
            for i, r in enumerate(rows)
            if isinstance(r, list) and any(isinstance(w, qt.QDoubleSpinBox) for w in r)
        )
        slider_row = next(i for i, r in enumerate(rows) if isinstance(r, qt.QSlider))
        assert slider_row > spin_row

    def test_the_number_keeps_the_reset_button_company(self, qt):
        box = _rotationPanel(qt)
        rows = _rows(qt, box)
        row = next(r for r in rows if isinstance(r, list))
        assert any(isinstance(w, qt.QDoubleSpinBox) for w in row)
        assert any(isinstance(w, qt.QPushButton) for w in row)


class TestTheStep:
    def test_the_buttons_move_five_degrees(self, qt):
        """Half a degree took ten clicks to show anything. Five is a turn
        you can see, and the box still takes a typed 12.5 for finer."""
        box = _rotationPanel(qt)
        spin = box.findChild(qt.QDoubleSpinBox)
        assert spin.singleStep() == pytest.approx(5.0)

    def test_finer_can_still_be_typed(self, qt):
        box = _rotationPanel(qt)
        spin = box.findChild(qt.QDoubleSpinBox)
        assert spin.decimals() >= 1
        spin.setValue(12.5)
        assert spin.value() == pytest.approx(12.5)
