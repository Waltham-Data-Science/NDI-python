"""Blurring the gene ladder so sparse expression reads as a pattern.

A gene's counts are a handful of pixels scattered over a section. Drawn
honestly they are dust. Blurring spreads each one over its neighbourhood
so the pattern shows -- and the things worth holding are that the width
means ONE PHYSICAL DISTANCE at every level of the ladder, that blurring
per tile leaves NO SEAM at the tile boundaries, and that the kernel is
UNITY so width and brightness stay separate knobs.

Dask arrays and scipy only. No display, no napari, no Qt.
"""

import numpy as np
import pytest

from ndi.gui.app.genepyramid.controls import basePixelUm, blurLevels

da = pytest.importorskip("dask.array")
pytest.importorskip("scipy.ndimage")


def _ladder(binSizes=(1, 2, 4), side=64, chunks=16):
    """A point of counts in the middle of each level of a ladder."""
    out = []
    for _b in binSizes:
        a = np.zeros((side, side), dtype=np.float32)
        a[side // 2, side // 2] = 100.0
        out.append(da.from_array(a, chunks=chunks))
    return out


class TestTheWidth:
    def test_one_setting_is_one_distance_at_every_level(self):
        """A level binned 4x is four base pixels to the pixel, so the same
        world blur has to be a QUARTER as wide in that level's own pixels.
        Otherwise the blur visibly changes width as the viewer switches
        levels while zooming -- exactly what a ladder exists to avoid."""
        from scipy.ndimage import gaussian_filter

        bins = [1, 2, 4]
        got = blurLevels(_ladder(bins), bins, sigmaBasePixels=8.0)
        for arr, b in zip(got, bins):
            src = np.zeros((64, 64), dtype=np.float32)
            src[32, 32] = 100.0
            want = gaussian_filter(src, sigma=8.0 / b, truncate=3.0, mode="constant")
            assert np.allclose(np.asarray(arr), want, atol=1e-4)

    def test_no_blur_costs_nothing(self):
        """Zero and below return the ladder untouched -- the SAME arrays,
        not equal ones, so switching the knob off cannot cost a recompute."""
        levels = _ladder()
        for sigma in (0.0, -1.0, None):
            got = blurLevels(levels, [1, 2, 4], sigma)
            assert [id(a) for a in got] == [id(a) for a in levels]

    def test_the_input_ladder_is_not_modified(self):
        levels = _ladder()
        before = [np.asarray(a).copy() for a in levels]
        blurLevels(levels, [1, 2, 4], 4.0)
        for a, b in zip(levels, before):
            assert np.array_equal(np.asarray(a), b)


class TestTheSeams:
    def test_a_tiled_level_blurs_as_if_it_were_whole(self):
        """map_overlap's halo is the point of the whole function. A plain
        per-block filter sees each tile's edge as the end of the world and
        leaves a seam at every boundary -- in a GRID, which reads as an
        artefact of the data rather than of the drawing."""
        from scipy.ndimage import gaussian_filter

        rng = np.random.default_rng(11)
        src = rng.random((64, 64)).astype(np.float32)
        # 16 blocks, so there are interior boundaries in both directions.
        arr = da.from_array(src, chunks=16)
        got = np.asarray(blurLevels([arr], [1], 3.0)[0])
        want = gaussian_filter(src, sigma=3.0, truncate=3.0, mode="constant")
        assert np.max(np.abs(got - want)) == pytest.approx(0.0, abs=1e-5)

    def test_the_halo_grows_with_the_width(self):
        """A halo shorter than the kernel's reach is how a seam gets back
        in, so the widest blur has to survive too."""
        from scipy.ndimage import gaussian_filter

        rng = np.random.default_rng(12)
        src = rng.random((64, 64)).astype(np.float32)
        arr = da.from_array(src, chunks=8)
        for sigma in (0.5, 2.0, 7.0):
            got = np.asarray(blurLevels([arr], [1], sigma)[0])
            want = gaussian_filter(src, sigma=sigma, truncate=3.0, mode="constant")
            assert np.max(np.abs(got - want)) < 1e-5, sigma


class TestTheKernel:
    def test_it_spreads_rather_than_brightens(self):
        """Unity: the counts move outward, they do not multiply. Width and
        brightness have to stay separate knobs, because a reader adjusting
        one is not asking for the other."""
        levels = _ladder(binSizes=(1,), side=128)
        total = float(np.asarray(levels[0]).sum())
        for sigma in (1.0, 4.0, 12.0):
            got = np.asarray(blurLevels(levels, [1], sigma)[0])
            # Well inside the frame, so nothing leaves at the edges.
            assert float(got.sum()) == pytest.approx(total, rel=1e-4)
            assert float(got.max()) < total

    def test_the_peak_falls_as_the_width_grows(self):
        """Which is why the caller resets contrast limits afterwards: the
        limits that suited the unblurred layer would show black."""
        levels = _ladder(binSizes=(1,), side=128)
        peaks = [float(np.asarray(blurLevels(levels, [1], s)[0]).max()) for s in (1.0, 4.0, 12.0)]
        assert peaks[0] > peaks[1] > peaks[2]


class _Doc:
    def __init__(self, props):
        self.document_properties = props


class TestTheScale:
    def test_it_reads_the_pyramid(self):
        """The knob is in microns because that is the unit a reader thinks
        in; blurLevels works in base pixels. This is the conversion."""
        doc = _Doc({"spatialGeneExpressionPyramid": {"base_pixel_size_x": 0.25}})
        assert basePixelUm(doc) == pytest.approx(0.25)

    @pytest.mark.parametrize(
        "props",
        [
            {},
            {"spatialGeneExpressionPyramid": {}},
            {"spatialGeneExpressionPyramid": {"base_pixel_size_x": 0}},
            {"spatialGeneExpressionPyramid": {"base_pixel_size_x": -1}},
            {"spatialGeneExpressionPyramid": {"base_pixel_size_x": "wide"}},
        ],
    )
    def test_a_document_that_does_not_say_costs_the_default(self, props):
        """A zero would make the knob divide by zero and a missing field
        would traceback out of a spin box callback. Neither is worth a
        control, so the Stereo-seq pitch stands in."""
        assert basePixelUm(_Doc(props)) == pytest.approx(0.5)

    def test_the_fallback_is_the_caller_s_to_choose(self):
        assert basePixelUm(_Doc({}), fallback=2.0) == pytest.approx(2.0)
