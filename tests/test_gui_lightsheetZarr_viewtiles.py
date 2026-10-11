"""The viewer says how many tiles the current view needs, not only how
many are in flight; and the launch window, once closed, stays closed.

Before this, zooming into a new region showed "12 in flight" with no way
to tell whether that was most of the view or a sliver of it. The chunk
grid and the stored-chunk list on the level documents make the total
knowable: napari draws one level over one region at one slice.
"""

import io
import types

import numpy as np
import pytest

from ndi.gui.app.lightsheetZarr import progress, viewtiles
from ndi.gui.app.lightsheetZarr.viewer import _FetchCounter


def _meta(chunks=(1, 1, 4, 10, 10), grid=(1, 2, 3, 5, 5), stored=None, axes="tczyx"):
    return {
        "doc": types.SimpleNamespace(id="lvl"),
        "axes": axes,
        "chunks": chunks,
        "chunk_grid": grid,
        "stored": stored,
    }


# ------------------------------------------------------------ chunksInBox


class TestChunksInBox:
    def test_the_box_covers_the_chunks_it_touches(self):
        m = _meta(chunks=(10, 10), grid=(5, 5), axes="yx")
        names = viewtiles.chunksInBox(m, [5, 15], [12, 29])
        # rows 0..1, cols 1..2 -> linear 1-based (r*5 + c) + 1
        assert sorted(names) == sorted(["chunk.bin_2", "chunk.bin_3", "chunk.bin_7", "chunk.bin_8"])

    def test_sparse_chunks_need_no_fetch_and_are_not_counted(self):
        m = _meta(chunks=(10, 10), grid=(5, 5), axes="yx", stored={"chunk.bin_2"})
        assert viewtiles.chunksInBox(m, [0, 0], [19, 29]) == ["chunk.bin_2"]

    def test_a_box_past_the_edge_is_clipped(self):
        m = _meta(chunks=(10, 10), grid=(2, 2), axes="yx")
        assert len(viewtiles.chunksInBox(m, [-5, -5], [999, 999])) == 4

    def test_a_huge_box_is_not_tallied(self, monkeypatch):
        monkeypatch.setattr(viewtiles, "MAX_POSITIONS", 3)
        m = _meta(chunks=(10, 10), grid=(2, 2), axes="yx")
        assert viewtiles.chunksInBox(m, [0, 0], [19, 19]) is None

    def test_linear_index_matches_the_reader(self):
        from ndi.pyramid.multiscale import _linear_chunk_index

        m = _meta()
        names = viewtiles.chunksInBox(m, [0, 1, 8, 30, 40], [0, 1, 8, 30, 40])
        assert names == [f"chunk.bin_{_linear_chunk_index((0, 1, 2, 3, 4), m['chunk_grid'])}"]


# ------------------------------------------------------------ layerBox


def _fakeViewer(point, displayed=(1, 2), ndim=3):
    dims = types.SimpleNamespace(point=point, displayed=displayed, ndim=ndim)
    return types.SimpleNamespace(dims=dims)


def _fakeLayer(level, corners, n_levels=2, factors=None, visible=True):
    factors = factors or [(1, 1, 1), (2, 2, 2)]
    return types.SimpleNamespace(
        multiscale=True,
        data=[None] * n_levels,
        data_level=level,
        corner_pixels=np.array(corners),
        ndim=3,
        visible=visible,
        downsample_factors=np.array(factors, dtype=float),
        world_to_data=lambda p: list(p),
    )


class TestLayerBox:
    def test_displayed_axes_come_from_corner_pixels_and_z_from_the_slice(self):
        metas = [_meta(), _meta()]
        layer = _fakeLayer(1, [[0, 3, 4], [0, 25, 31]])
        viewer = _fakeViewer(point=(10.0, 0.0, 0.0))
        level, lo, hi = viewtiles.layerBox(layer, viewer, metas, channel=1)
        assert level == 1
        # t, c, z, y, x on the grid; z is world 10 / factor 2 = 5.
        assert lo == [0, 1, 5, 3, 4]
        assert hi == [0, 1, 5, 25, 31]

    def test_a_tzyx_layer_maps_onto_a_tczyx_grid(self):
        layer = _fakeLayer(0, [[0, 0, 2, 3], [0, 0, 8, 9]], n_levels=1, factors=[(1, 1, 1, 1)])
        layer.ndim = 4
        viewer = _fakeViewer(point=(0.0, 6.0, 0.0, 0.0), displayed=(2, 3), ndim=4)
        _level, lo, hi = viewtiles.layerBox(layer, viewer, [_meta()], channel=2)
        assert lo == [0, 2, 6, 2, 3]
        assert hi == [0, 2, 6, 8, 9]

    def test_a_single_level_layer_is_not_tallied(self):
        layer = _fakeLayer(0, [[0, 0, 0], [0, 1, 1]])
        layer.multiscale = False
        assert viewtiles.layerBox(layer, _fakeViewer((0, 0, 0)), [_meta()]) is None

    def test_a_ladder_that_does_not_match_the_docs_is_not_tallied(self):
        layer = _fakeLayer(0, [[0, 0, 0], [0, 1, 1]], n_levels=3)
        assert viewtiles.layerBox(layer, _fakeViewer((0, 0, 0)), [_meta(), _meta()]) is None

    def test_napari_without_the_attributes_is_unknown_not_a_crash(self):
        layer = types.SimpleNamespace(multiscale=True, data=[None])
        assert viewtiles.layerBox(layer, _fakeViewer((0, 0, 0)), [_meta()]) is None


class TestViewTally:
    def test_ready_counts_what_is_on_disk_and_shared_chunks_count_once(self):
        # Channel chunk spans both channels -> two layers, same chunks.
        m = _meta(chunks=(1, 2, 4, 10, 10), grid=(1, 1, 3, 5, 5))
        layers = [_fakeLayer(0, [[0, 0, 0], [0, 19, 9]], n_levels=1) for _ in range(2)]
        viewer = _fakeViewer(point=(0.0, 0.0, 0.0))

        class Fetcher:
            def chunkPathIfCached(self, doc, name):
                return "/x" if name == "chunk.bin_1" else None

        assert viewtiles.viewTally(viewer, layers, [m], Fetcher()) == (1, 2)

    def test_hidden_layers_need_nothing(self):
        m = _meta(chunks=(10, 10, 10), grid=(1, 2, 2), axes="zyx")
        layer = _fakeLayer(0, [[0, 0, 0], [0, 19, 19]], n_levels=1, visible=False)

        class Fetcher:
            def chunkPathIfCached(self, doc, name):
                return None

        assert viewtiles.viewTally(_fakeViewer((0, 0, 0)), [layer], [m], Fetcher()) == (0, 0)


# ------------------------------------------------------------ counter


class _Reporter:
    def __init__(self):
        self.pushed = []

    def push(self, message, *, overlay=""):
        self.pushed.append((message, overlay))


class TestCounterReportsTheView:
    def _counter(self):
        out = io.StringIO()
        rep = _Reporter()
        c = _FetchCounter(out=out, idle_interval=3600, status_reporter=rep)
        return c, out, rep

    def test_status_and_overlay_say_how_much_of_the_view_is_left(self):
        c, _out, rep = self._counter()
        try:
            c("start", "u1", 0, None)
            c.set_view_tally(37, 120)
            message, overlay = rep.pushed[-1]
            assert "view 37/120 tiles ready" in message
            assert overlay == "Loading view: 37 / 120 tiles (1 in flight)"
        finally:
            c.stop()

    def test_a_complete_view_hides_the_overlay_and_logs_how_long_it_took(self):
        c, out, rep = self._counter()
        try:
            c.set_view_tally(0, 4)
            c.set_view_tally(4, 4)
            assert rep.pushed[-1][1] == ""
            assert "view complete: 4 tile(s)" in out.getvalue()
        finally:
            c.stop()

    def test_an_untallied_view_falls_back_to_in_flight(self):
        c, _out, rep = self._counter()
        try:
            c("start", "u1", 0, None)
            c.set_view_tally(None, None)
            assert rep.pushed[-1][1] == "Loading tiles ... (1 in flight)"
        finally:
            c.stop()


# ------------------------------------------------------------ launch window


class TestTheLaunchWindowStaysClosed:
    def test_a_note_after_closing_does_not_build_a_new_window(self, monkeypatch):
        """closeLaunchWindow then note("viewer running ...") used to go
        through _mode() -> _launchWindow(), find no window, and open a
        fresh "starting ..." window that nothing ever closed."""
        monkeypatch.setattr(progress, "_window", None)
        monkeypatch.setattr(progress, "_window_failed", False)
        monkeypatch.setattr(progress, "_window_closed", False)
        monkeypatch.delenv("NDI_LIGHTSHEET_PROGRESS", raising=False)
        monkeypatch.delenv("NDI_LIGHTSHEET_QUIET", raising=False)

        class Widget:
            def __getattr__(self, _name):
                return lambda *a, **k: None

        monkeypatch.setattr(
            progress, "_window", {"widget": Widget(), "app": Widget(), "step": None, "bar": None}
        )
        progress.closeLaunchWindow()
        progress.note("viewer running")

        assert progress._launchWindow() is None
        # It short-circuited on the close latch; it never got as far as
        # trying (and failing) to build a window.
        assert progress._window_failed is False


if __name__ == "__main__":
    pytest.main([__file__])
