"""The upsample fallback fills in fine-level gaps with coarser cached data.

Napari's slicer asks for every chunk overlapping a slice at once, so a
fine level with tens of thousands of tiles takes minutes to complete
one view -- and every unfinished tile paints as black. The fix
composites coarser cached data (put on disk by the coarsest-level
prefetch) UNDER the unfinished fine tiles.

These tests pin the pure helpers -- world-bbox math, coarse-chunk
lookup, nearest-neighbour upsampling -- so the tricky geometry does
not silently drift into "one chunk offset by one pixel" on a
refactor.
"""

import os
import unittest
from unittest import mock

import numpy as np

from ndi.gui.app.lightsheetZarr import upsample_fallback as uf


class TestLevelGeometry(unittest.TestCase):
    def test_it_reads_the_common_fields_out_of_a_level_document(self):
        props = {
            "shape": (4, 8),
            "chunks": (2, 4),
            "chunk_grid": (2, 2),
            "voxel_size": [1.0, 2.0],
            "translation": [0.0, 10.0],
            "axes_order": "yx",
        }
        g = uf.levelGeometry(props)
        self.assertEqual(g.shape, (4, 8))
        self.assertEqual(g.chunks, (2, 4))
        self.assertEqual(g.chunk_grid, (2, 2))
        self.assertEqual(g.voxel_size, [1.0, 2.0])
        self.assertEqual(g.translation, [0.0, 10.0])

    def test_missing_voxel_size_and_translation_default_to_neutral(self):
        # A malformed document should not crash the reader with a
        # KeyError on every dask task; missing entries fall back to
        # voxel size 1.0 and translation 0.0 so the fallback still
        # returns *something* rather than blowing up the whole slice.
        props = {"shape": (4, 8), "chunks": (2, 4), "chunk_grid": (2, 2)}
        g = uf.levelGeometry(props)
        self.assertEqual(g.voxel_size, [1.0, 1.0])
        self.assertEqual(g.translation, [0.0, 0.0])


class TestFineChunkWorldBox(unittest.TestCase):
    def test_it_returns_the_world_extent_of_one_chunk(self):
        props = {
            "shape": (4, 8),
            "chunks": (2, 4),
            "chunk_grid": (2, 2),
            "voxel_size": [1.0, 0.5],
            "translation": [10.0, 100.0],
            "axes_order": "yx",
        }
        g = uf.levelGeometry(props)
        # Chunk (0, 0) covers pixel [0:2, 0:4] -> world Y [10, 12), X [100, 102).
        starts, ends = uf.fineChunkWorldBox(g, (0, 0))
        self.assertEqual(starts, [10.0, 100.0])
        self.assertEqual(ends, [12.0, 102.0])
        # Chunk (1, 1) covers pixel [2:4, 4:8] -> world Y [12, 14), X [102, 104).
        starts, ends = uf.fineChunkWorldBox(g, (1, 1))
        self.assertEqual(starts, [12.0, 102.0])
        self.assertEqual(ends, [14.0, 104.0])


class TestFindCoveringCoarseChunk(unittest.TestCase):
    def _pyramid(self):
        # Level 0 (fine): 4x4 pixels, 2x2 chunks, chunk_grid 2x2, vs=1.
        # Level 1 (coarse): 2x2 pixels, 2x2 chunks, chunk_grid 1x1, vs=2.
        # Translations are 0 so pixel k maps to world k * vs.
        fine = uf.levelGeometry(
            {
                "shape": (4, 4),
                "chunks": (2, 2),
                "chunk_grid": (2, 2),
                "voxel_size": [1.0, 1.0],
                "translation": [0.0, 0.0],
                "axes_order": "yx",
            }
        )
        coarse = uf.levelGeometry(
            {
                "shape": (2, 2),
                "chunks": (2, 2),
                "chunk_grid": (1, 1),
                "voxel_size": [2.0, 2.0],
                "translation": [0.0, 0.0],
                "axes_order": "yx",
            }
        )
        return fine, coarse

    def test_a_fine_chunk_maps_to_its_covering_coarse_sub_slice(self):
        fine, coarse = self._pyramid()
        # Fine chunk (1, 0) covers world Y [2, 4), X [0, 2).
        # In coarse pixels that is Y [1, 2), X [0, 1) inside coarse
        # chunk (0, 0).
        starts, ends = uf.fineChunkWorldBox(fine, (1, 0))
        got = uf.findCoveringCoarseChunk(coarse, starts, ends)
        self.assertIsNotNone(got)
        idx, sub = got
        self.assertEqual(idx, (0, 0))
        self.assertEqual(sub, (slice(1, 2), slice(0, 1)))

    def test_a_fine_chunk_outside_the_coarse_extent_gets_None(self):
        fine, coarse = self._pyramid()
        # Pretend the fine chunk sits far outside the coarse level.
        got = uf.findCoveringCoarseChunk(coarse, [100.0, 100.0], [102.0, 102.0])
        self.assertIsNone(got)

    def test_a_straddling_fine_chunk_gets_None_rather_than_a_partial_answer(self):
        # v1 does not stitch multiple coarse chunks -- if the fine
        # chunk crosses a coarse boundary, we return None so the
        # reader falls through to fill_value. When we grow the
        # feature to stitch, this test flips.
        coarse = uf.levelGeometry(
            {
                "shape": (4, 4),
                "chunks": (2, 2),
                "chunk_grid": (2, 2),
                "voxel_size": [1.0, 1.0],
                "translation": [0.0, 0.0],
                "axes_order": "yx",
            }
        )
        # A world bbox that spans y=[1, 3) crosses the y=2 chunk boundary.
        got = uf.findCoveringCoarseChunk(coarse, [1.0, 0.0], [3.0, 1.0])
        self.assertIsNone(got)


class TestUpsampleToBlock(unittest.TestCase):
    def test_integer_factor_uses_kron_style_repeat(self):
        # 1x1 coarse region upsampled 2x2 -> 2x2 fine.
        coarse = np.array([[7]], dtype=np.uint16)
        out = uf.upsampleToBlock(coarse, (slice(0, 1), slice(0, 1)), (2, 2))
        self.assertIsNotNone(out)
        np.testing.assert_array_equal(out, np.full((2, 2), 7, dtype=np.uint16))

    def test_bigger_region_and_bigger_output(self):
        # 2x2 region upsampled 4x4 -> 8x8 (each source pixel repeats 4x4).
        coarse = np.array([[1, 2], [3, 4]], dtype=np.uint16)
        out = uf.upsampleToBlock(coarse, (slice(0, 2), slice(0, 2)), (8, 8))
        self.assertEqual(out.shape, (8, 8))
        # Top-left 4x4 quadrant should all be 1s, top-right all 2s, etc.
        self.assertTrue((out[:4, :4] == 1).all())
        self.assertTrue((out[:4, 4:] == 2).all())
        self.assertTrue((out[4:, :4] == 3).all())
        self.assertTrue((out[4:, 4:] == 4).all())

    def test_non_integer_ratio_uses_the_nearest_neighbour_fallback(self):
        # 2x2 region upsampled to 3x3 -- the ratio isn't an integer,
        # so the code takes the nearest-neighbour path.
        coarse = np.array([[10, 20], [30, 40]], dtype=np.uint16)
        out = uf.upsampleToBlock(coarse, (slice(0, 2), slice(0, 2)), (3, 3))
        self.assertEqual(out.shape, (3, 3))
        # The exact values depend on rounding; the important
        # property is that the corners come from the corners.
        self.assertEqual(out[0, 0], 10)
        self.assertEqual(out[-1, -1], 40)

    def test_an_empty_sub_slice_returns_None(self):
        coarse = np.array([[1, 2], [3, 4]], dtype=np.uint16)
        out = uf.upsampleToBlock(coarse, (slice(0, 0), slice(0, 0)), (2, 2))
        self.assertIsNone(out)


class TestCoarseChunkFilename(unittest.TestCase):
    def test_it_matches_the_linear_index_math_in_the_grid_builder(self):
        # multi (0, 0) in a 2x2 grid is chunk 1 (row-major, 1-based).
        self.assertEqual(uf._coarse_chunk_filename((0, 0), (2, 2)), "chunk.bin_1")
        self.assertEqual(uf._coarse_chunk_filename((0, 1), (2, 2)), "chunk.bin_2")
        self.assertEqual(uf._coarse_chunk_filename((1, 0), (2, 2)), "chunk.bin_3")
        self.assertEqual(uf._coarse_chunk_filename((1, 1), (2, 2)), "chunk.bin_4")

    def test_it_respects_row_major_with_the_expected_stride(self):
        # 2x3 grid: (0,0)->1, (0,1)->2, (0,2)->3, (1,0)->4, (1,1)->5, (1,2)->6
        pairs = [
            ((0, 0), "chunk.bin_1"),
            ((0, 1), "chunk.bin_2"),
            ((0, 2), "chunk.bin_3"),
            ((1, 0), "chunk.bin_4"),
            ((1, 1), "chunk.bin_5"),
            ((1, 2), "chunk.bin_6"),
        ]
        for multi, name in pairs:
            self.assertEqual(uf._coarse_chunk_filename(multi, (2, 3)), name, multi)


class TestEnvGate(unittest.TestCase):
    def test_absent_env_is_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NDI_LIGHTSHEET_UPSAMPLE_FALLBACK", None)
            self.assertFalse(uf.env_on())

    def test_truthy_env_is_on(self):
        for value in ("1", "true", "on", "yes", "TRUE"):
            with mock.patch.dict(
                os.environ, {"NDI_LIGHTSHEET_UPSAMPLE_FALLBACK": value}, clear=False
            ):
                self.assertTrue(uf.env_on(), value)

    def test_zero_is_off(self):
        with mock.patch.dict(os.environ, {"NDI_LIGHTSHEET_UPSAMPLE_FALLBACK": "0"}, clear=False):
            self.assertFalse(uf.env_on())


if __name__ == "__main__":
    unittest.main()
