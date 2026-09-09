"""Blurring sparse centroids so they read as a field rather than dust.

napari draws a Points layer as discrete marks and offers no kernel to
widen, so "broader dots" means rendering the cells into an image and
blurring THAT. The two things worth holding are the raster (does it land
where the cells are, at a size that can be blurred cheaply) and the
kernel's UNITY -- widening must spread each cell's contribution, not add
to it, or width and brightness stop being separate knobs.

No display and no napari needed for either.
"""

import numpy as np
import pytest

from ndi.gui.app.genepyramid.controls import blurRaster, densityRaster


class TestTheRaster:
    def test_it_lands_where_the_cells_are(self):
        """scale and translate have to put the raster back on top of the
        points it was built from, or the blur sits beside the cells."""
        row = np.array([100.0, 300.0])
        col = np.array([50.0, 250.0])
        counts, step, origin = densityRaster(row, col, max_side=64)
        assert origin == (100.0, 50.0)
        # Each cell must map back into the raster at its own corner.
        for r, c in zip(row, col):
            ri = int((r - origin[0]) / step)
            ci = int((c - origin[1]) / step)
            assert counts[ri, ci] >= 1

    def test_every_cell_is_counted_exactly_once(self):
        rng = np.random.default_rng(0)
        row = rng.uniform(0, 5000, 5000)
        col = rng.uniform(0, 9000, 5000)
        counts, _, _ = densityRaster(row, col, max_side=256)
        assert counts.sum() == 5000

    def test_the_long_side_is_capped(self):
        """A ferret section is ~40,000 x 59,000 base pixels; a full-res
        density image would be 2.4 billion pixels for a few hundred
        thousand cells."""
        row = np.array([0.0, 59000.0])
        col = np.array([0.0, 40000.0])
        counts, _, _ = densityRaster(row, col, max_side=512)
        assert max(counts.shape) <= 513
        assert counts.shape[0] >= counts.shape[1], "the taller axis stays taller"

    def test_no_cells_is_not_a_crash(self):
        counts, step, origin = densityRaster([], [], max_side=64)
        assert counts.shape == (1, 1)
        assert step > 0

    def test_a_single_cell_still_makes_a_raster_with_area(self):
        """A degenerate extent would otherwise give a histogram no bins."""
        counts, step, _ = densityRaster([7.0], [9.0], max_side=64)
        assert counts.sum() == 1
        assert step > 0

    def test_cells_in_a_line_still_work(self):
        counts, _, _ = densityRaster([5.0, 5.0, 5.0], [1.0, 2.0, 3.0], max_side=32)
        assert counts.sum() == 3


class TestTheKernelIsUnity:
    def test_blurring_spreads_rather_than_adds(self):
        """THE POINT. Widening must not brighten, or the contrast limits
        set at one width stop meaning anything at another.

        The frame is big enough for the kernel to fit inside it -- scipy
        truncates at 4 sigma, so a wide blur on a small raster loses mass
        off the edge, which is the deliberate behaviour the edge test
        below pins and not a failure of unity.
        """
        counts = np.zeros((128, 128), np.float32)
        counts[64, 64] = 1.0
        for sigma in (1.0, 3.0, 6.0):
            out = blurRaster(counts, sigma_world=sigma, step=1.0)
            assert out.sum() == pytest.approx(1.0, rel=1e-4)

    def test_a_wider_blur_lowers_the_peak(self):
        counts = np.zeros((64, 64), np.float32)
        counts[32, 32] = 1.0
        narrow = blurRaster(counts, 1.0, 1.0).max()
        wide = blurRaster(counts, 6.0, 1.0).max()
        assert wide < narrow

    def test_zero_sigma_is_the_input_unchanged(self):
        counts = np.arange(16, dtype=np.float32).reshape(4, 4)
        assert np.array_equal(blurRaster(counts, 0.0, 1.0), counts)
        assert np.array_equal(blurRaster(counts, -1.0, 1.0), counts)

    def test_sigma_is_in_world_units_not_raster_pixels(self):
        """The knob has to mean the same thing whatever the raster size,
        or its useful range would drift with the section's extent."""
        counts = np.zeros((64, 64), np.float32)
        counts[32, 32] = 1.0
        # 10 world units at 2 units/pixel is the same blur as 5 at 1.
        a = blurRaster(counts, sigma_world=10.0, step=2.0)
        b = blurRaster(counts, sigma_world=5.0, step=1.0)
        assert np.allclose(a, b)

    def test_edge_mass_leaves_rather_than_folding_back(self):
        """A section is not periodic; reflecting would double its border
        cells and put a bright rim around the tissue."""
        counts = np.zeros((32, 32), np.float32)
        counts[0, 0] = 1.0
        out = blurRaster(counts, 3.0, 1.0)
        assert out.sum() < 1.0, "mass at a corner should leave the frame"
        assert out.max() < 1.0


def test_the_default_raster_stays_inside_a_slider_drag():
    """The blur is redrawn on every change of the width knob, so the cap
    is on the interactive path. Measured with scipy's gaussian_filter:
    1024^2 is 38-126 ms across the useful sigma range, 2048^2 is 177-442,
    4096^2 is 757-1815. A default that lags the drag is the wrong default,
    and this is the sort of number that drifts back up unnoticed."""
    import numpy as np

    row = np.array([0.0, 59000.0])
    col = np.array([0.0, 40000.0])
    counts, _, _ = densityRaster(row, col)
    assert max(counts.shape) <= 1025


class TestTheViewportRectangle:
    """The standing raster covers the whole section, so it goes blocky
    when you zoom past it. "Re-blur here" re-bins just what is on screen,
    which puts the same number of raster pixels over a smaller region.

    The arithmetic is where this can be wrong, and it needs no display.
    """

    def test_the_visible_extent_is_the_canvas_over_the_zoom(self):
        """napari's zoom is canvas PIXELS PER WORLD UNIT."""
        from ndi.gui.app.genepyramid.controls import viewportBounds

        # 800x600 canvas at 2 px per world unit -> 400 x 300 world units.
        r0, r1, c0, c1 = viewportBounds((0.0, 100.0, 200.0), 2.0, (800, 600))
        assert (c1 - c0) == pytest.approx(400.0)
        assert (r1 - r0) == pytest.approx(300.0)

    def test_width_belongs_to_columns_and_height_to_rows(self):
        """The one thing here that is easy to get backwards, and invisible
        whenever the window happens to be square."""
        from ndi.gui.app.genepyramid.controls import viewportBounds

        r0, r1, c0, c1 = viewportBounds((0.0, 0.0, 0.0), 1.0, (1000, 200))
        assert (c1 - c0) == pytest.approx(1000.0), "canvas WIDTH spans columns"
        assert (r1 - r0) == pytest.approx(200.0), "canvas HEIGHT spans rows"

    def test_it_is_centred_on_the_camera(self):
        from ndi.gui.app.genepyramid.controls import viewportBounds

        r0, r1, c0, c1 = viewportBounds((0.0, 50.0, -20.0), 1.0, (100, 100))
        assert (r0 + r1) / 2 == pytest.approx(50.0)
        assert (c0 + c1) / 2 == pytest.approx(-20.0)

    def test_a_zoom_of_zero_is_refused_rather_than_dividing(self):
        from ndi.gui.app.genepyramid.controls import viewportBounds

        with pytest.raises(ValueError, match="zoom must be positive"):
            viewportBounds((0.0, 0.0, 0.0), 0.0, (100, 100))

    def test_a_viewport_raster_is_finer_than_a_whole_section_one(self):
        """THE POINT OF THE BUTTON: same max_side, smaller region."""
        rng = np.random.default_rng(1)
        row = rng.uniform(0, 59000, 20000)
        col = rng.uniform(0, 40000, 20000)
        _, whole_step, _ = densityRaster(row, col, max_side=256)

        keep = (row > 29000) & (row < 30000) & (col > 20000) & (col < 21000)
        _, view_step, _ = densityRaster(row[keep], col[keep], max_side=256)
        assert view_step < whole_step / 10


class TestTheCanvasSizeIsOptional:
    """It is reached through private napari attributes that have moved
    between versions, so a miss falls back to the whole section rather
    than failing -- a blur over the wrong rectangle would be worse than a
    coarse one over the right rectangle."""

    def test_a_viewer_that_will_not_say_returns_none(self):
        from ndi.gui.app.genepyramid.controls import canvasSize

        class Bare:
            window = object()

        assert canvasSize(Bare()) is None

    def test_it_reads_the_canvas_when_one_is_there(self):
        from ndi.gui.app.genepyramid.controls import canvasSize

        class Canvas:
            size = (1280, 720)

        class QtViewer:
            canvas = Canvas()

        class Window:
            _qt_viewer = QtViewer()

        class Viewer:
            window = Window()

        assert canvasSize(Viewer()) == (1280.0, 720.0)
