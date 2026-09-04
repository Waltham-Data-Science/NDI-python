"""Tests for the pyramid -> multiscale-viewer conversion.

Headless on purpose: the part that goes quietly wrong is the coordinate
registration, not the window. An off-by-one in the origin puts every
level somewhere plausible and wrong, which looks fine until cells are
overlaid and miss.

The fixture uses a non-zero origin, a non-square base pixel size, and a
wider-than-tall extent, so a transform that drops the origin, transposes
the axes, or confuses x-scale with y-scale fails rather than
coincidentally agrees.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.fun.doc_gene import makeGeneList, makePyramid, readViewport
from ndi.gui.app.genepyramid.multiscale import (
    layerSpec,
    levelArrays,
    sourceToWorld,
    worldTransform,
)
from ndi.session.dir import ndi_session_dir

OX, OY = 1000, 2000
PX, PY = 0.5, 0.25  # deliberately NOT equal
COUNTS = [2, 3, 5, 7]


@pytest.fixture
def pyramid(tmp_path):
    d = tmp_path / "gp"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("gp", str(d))
    sub = S.newdocument("subject", **{"subject.local_identifier": "gp@vhlab"})
    S.database_add(sub)
    gl = makeGeneList(S, [f"ENSG{k:04d}" for k in range(1, 5)], ["a", "b", "c", "d"])
    x = [OX + 0, OX + 5, OX + 30, OX + 31]
    y = [OY + 0, OY + 3, OY + 10, OY + 11]
    pyr, _ = makePyramid(
        S,
        x,
        y,
        [0, 1, 2, 3],
        COUNTS,
        gl,
        subjectID=sub.id,
        binSizes=[1, 2, 4],
        grid=2,
        basePixelSize=(PX, PY),
        label="opossum test",
    )
    return S, pyr


# ------------------------------------------------------------- the ladder


def test_one_array_per_level_finest_first(pyramid):
    S, pyr = pyramid
    arrays = levelArrays(S, pyr)
    assert len(arrays) == 3
    # Finest first: each level is smaller than the one before it.
    heights = [a.shape[0] for a in arrays]
    widths = [a.shape[1] for a in arrays]
    assert heights == sorted(heights, reverse=True)
    assert widths == sorted(widths, reverse=True)


def test_levels_are_cropped_to_their_true_size(pyramid):
    """The tile grid overshoots whenever a level does not divide evenly.
    Leaving the padding on makes levels disagree about their own field of
    view, and a viewer registering them by shape ratio misaligns them."""
    S, pyr = pyramid
    from ndi.fun.doc_gene import levelTable

    levels, _ = levelTable(S, pyr)
    for arr, lv in zip(levelArrays(S, pyr), levels):
        assert arr.shape == (lv["levelHeight"], lv["levelWidth"])


def test_opening_the_ladder_reads_no_tile_bytes(pyramid, monkeypatch):
    """A 4.9 GB pyramid must open instantly. Tile PATHS are resolved when
    the ladder is built -- see the note in multiscale.py about worker
    threads -- but no tile bytes may be read until something is drawn."""
    S, pyr = pyramid
    from ndi.gui.app.genepyramid import multiscale as ms

    reads = []
    real = ms.readTileFile
    monkeypatch.setattr(ms, "readTileFile", lambda src: reads.append(src) or real(src))

    arrays = levelArrays(S, pyr)
    assert reads == [], f"building the ladder decoded {len(reads)} tiles"
    arrays[0][:4, :4].compute()
    assert reads, "computing a block must actually read a tile"


def test_blocks_work_on_the_threaded_scheduler(pyramid):
    """The regression guard that matters.

    NDI's database is SQLite and its connections are not usable from
    another thread. dask runs blocks on a thread pool by default, and that
    is also how napari drives multiscale loading, so a block that touched
    the session failed with "ndi_document ... not found" -- the database
    returning nothing rather than raising -- and ONLY under the threaded
    scheduler. The synchronous scheduler passed, which is the worst shape
    a bug can have before a live demo.
    """
    S, pyr = pyramid
    arr = levelArrays(S, pyr)[0]
    threaded = np.asarray(arr[:8, :8].compute(scheduler="threads"))
    sync = np.asarray(arr[:8, :8].compute(scheduler="synchronous"))
    np.testing.assert_array_equal(threaded, sync)
    assert threaded.sum() > 0, "fixture must put counts in this corner"


def test_a_computed_block_matches_readViewport(pyramid):
    """The lazy path and the documented reader must agree, or the viewer is
    drawing something no other caller would get."""
    S, pyr = pyramid
    arr = levelArrays(S, pyr)[0]
    got = np.asarray(arr[:8, :8].compute())
    want, _info = readViewport(S, pyr, 1, (0, 0, 8, 8), None)
    np.testing.assert_allclose(got, want)


def test_density_makes_levels_comparable(pyramid):
    """Binning sums, so without the divisor a coarse level is binSize^2
    brighter and one contrast range cannot serve the ladder -- the
    brightness would jump every time the viewer switched levels."""
    S, pyr = pyramid
    dense = [np.asarray(a.compute()).sum() for a in levelArrays(S, pyr, density=True)]
    raw = [np.asarray(a.compute()).sum() for a in levelArrays(S, pyr, density=False)]
    assert raw[0] == pytest.approx(sum(COUNTS))
    # raw totals are conserved across levels; density divides by binSize^2
    assert raw[1] == pytest.approx(sum(COUNTS))
    assert dense[1] == pytest.approx(sum(COUNTS) / 4)
    assert dense[2] == pytest.approx(sum(COUNTS) / 16)


def test_gene_selection_costs_no_extra_reads(pyramid):
    S, pyr = pyramid
    one = np.asarray(levelArrays(S, pyr, gene_rows=[0])[0].compute())
    assert one.sum() == pytest.approx(COUNTS[0])


# ---------------------------------------------------------- the placement


def test_scale_is_the_finest_bin_and_is_not_transposed(pyramid):
    """napari applies the layer scale to level 0 and infers the rest from
    shape ratios, so the scale is the FINEST bin, not a per-level value."""
    S, pyr = pyramid
    scale, _translate = worldTransform(S, pyr)
    # (row, column) = (y, x). PX and PY differ, so a transposed
    # implementation cannot pass.
    assert scale == (PY, PX)


def test_translate_carries_the_origin(pyramid):
    """Forgetting the origin puts the section somewhere plausible and
    wrong; it looks fine until cells are overlaid and miss."""
    S, pyr = pyramid
    _scale, translate = worldTransform(S, pyr)
    assert translate == (OY * PY, OX * PX)


def test_source_to_world_swaps_the_axes(pyramid):
    """Source x is the COLUMN axis and source y is the ROW axis."""
    S, pyr = pyramid
    row, col = sourceToWorld(S, pyr, [10, 20], [30, 40])
    np.testing.assert_allclose(row, np.array([30, 40]) * PY)
    np.testing.assert_allclose(col, np.array([10, 20]) * PX)


def test_source_to_world_does_not_apply_the_origin_twice(pyramid):
    """The layer's translate already carries the origin. Subtracting it
    here as well would double-apply it, which is the mistake this exists
    to prevent."""
    S, pyr = pyramid
    _scale, translate = worldTransform(S, pyr)
    row, col = sourceToWorld(S, pyr, [OX], [OY])
    # A point at the pyramid origin must land exactly on the layer's
    # translate, not at zero and not at twice the offset.
    assert row[0] == pytest.approx(translate[0])
    assert col[0] == pytest.approx(translate[1])


def test_layer_spec_is_what_add_image_takes(pyramid):
    S, pyr = pyramid
    spec = layerSpec(S, pyr)
    assert spec["multiscale"] is True
    assert len(spec["data"]) == 3
    assert spec["scale"] == (PY, PX)
    assert spec["translate"] == (OY * PY, OX * PX)
    assert spec["name"] == "opossum test"
    assert spec["rgb"] is False


def test_layer_spec_name_falls_back_when_the_pyramid_has_no_label(tmp_path):
    d = tmp_path / "gp2"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("gp2", str(d))
    sub = S.newdocument("subject", **{"subject.local_identifier": "gp2@vhlab"})
    S.database_add(sub)
    gl = makeGeneList(S, ["ENSQ0001"], ["q"])
    pyr, _ = makePyramid(
        S,
        [5],
        [7],
        [0],
        [1],
        gl,
        subjectID=sub.id,
        binSizes=[1],
        grid=1,
    )
    assert layerSpec(S, pyr)["name"] == "genes"
