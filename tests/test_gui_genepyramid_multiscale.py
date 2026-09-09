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

import importlib.util

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

# dask is part of the "napari" extra, not the base install, so a headless
# CI box does not have it. Only the ladder itself needs it; the coordinate
# transforms below are pure arithmetic and must keep running everywhere,
# because the registration bugs they catch are the ones that stay quiet.
needs_dask = pytest.mark.skipif(
    importlib.util.find_spec("dask") is None,
    reason="dask is not installed (pip install 'ndi[napari]')",
)

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


@needs_dask
def test_one_array_per_level_finest_first(pyramid):
    S, pyr = pyramid
    arrays = levelArrays(S, pyr)
    assert len(arrays) == 3
    # Finest first: each level is smaller than the one before it.
    heights = [a.shape[0] for a in arrays]
    widths = [a.shape[1] for a in arrays]
    assert heights == sorted(heights, reverse=True)
    assert widths == sorted(widths, reverse=True)


@needs_dask
def test_levels_are_cropped_to_their_true_size(pyramid):
    """The tile grid overshoots whenever a level does not divide evenly.
    Leaving the padding on makes levels disagree about their own field of
    view, and a viewer registering them by shape ratio misaligns them."""
    S, pyr = pyramid
    from ndi.fun.doc_gene import levelTable

    levels, _ = levelTable(S, pyr)
    for arr, lv in zip(levelArrays(S, pyr), levels):
        assert arr.shape == (lv["levelHeight"], lv["levelWidth"])


@needs_dask
def test_opening_the_ladder_reads_no_tile_bytes(pyramid, monkeypatch):
    """A 4.9 GB pyramid must open instantly: nothing is read until drawn."""
    S, pyr = pyramid
    from ndi.gui.app.genepyramid import multiscale as ms

    reads = []
    real = ms.readTileFile
    monkeypatch.setattr(ms, "readTileFile", lambda src: reads.append(src) or real(src))

    arrays = levelArrays(S, pyr)
    assert reads == [], f"building the ladder decoded {len(reads)} tiles"
    arrays[0][:4, :4].compute()
    assert reads, "computing a block must actually read a tile"


@needs_dask
def test_opening_the_ladder_opens_no_binary_documents(pyramid, monkeypatch):
    """The one that measures what a cloud session is actually billed for.

    This test's sibling above watches readTileFile -- the DECODE -- and it
    passed for a version of levelArrays that opened every tile of every
    level while building the ladder. On a directory-backed session that
    was free path resolution and the two look identical. On a cloud-backed
    one they are worlds apart: database_openbinarydoc RETRIEVES a remote
    file, so resolving a path and downloading it are the same call, and
    opening a viewer downloaded the entire pyramid before drawing
    anything. The blocks being lazy never helped, because the cost was
    already paid by the time dask chose which blocks it wanted.

    So this watches the FETCH, and it is the assertion that has teeth.
    """
    S, pyr = pyramid
    from ndi.session import session_base

    opens = []
    real = session_base.ndi_session.database_openbinarydoc
    monkeypatch.setattr(
        session_base.ndi_session,
        "database_openbinarydoc",
        lambda self, doc, fn: opens.append(fn) or real(self, doc, fn),
    )

    arrays = levelArrays(S, pyr)
    assert opens == [], (
        f"building the ladder opened {len(opens)} binary documents; on a "
        f"cloud session that is {len(opens)} downloads before a single pixel"
    )
    arrays[0][:4, :4].compute(scheduler="synchronous")
    assert opens, "computing a block must actually open its tile"


@needs_dask
def test_only_the_touched_tiles_are_fetched(pyramid):
    """Laziness is per TILE, not merely per level.

    A viewer pans; it must pay for the tiles under the window and no
    others. Level 0 of the fixture is a 2x2 grid, so one corner block is
    strictly fewer fetches than the whole level.
    """
    S, pyr = pyramid
    from ndi.session import session_base

    opens = []
    real = session_base.ndi_session.database_openbinarydoc

    def spy(self, doc, fn):
        opens.append(fn)
        return real(self, doc, fn)

    session_base.ndi_session.database_openbinarydoc = spy
    try:
        # A LADDER EACH. Resolved paths are memoised per fetcher, so
        # measuring both from one ladder would charge the whole level only
        # for the tiles the corner had not already seen and compare two
        # different things.
        corner_arrays = levelArrays(S, pyr)
        opens.clear()
        corner_arrays[0][:4, :4].compute(scheduler="threads")
        corner = len(opens)

        whole_arrays = levelArrays(S, pyr)
        opens.clear()
        whole_arrays[0].compute(scheduler="threads")
        whole = len(opens)
    finally:
        session_base.ndi_session.database_openbinarydoc = real

    assert corner >= 1, "the corner must fetch its own tile"
    assert corner < whole, (
        f"a corner cost {corner} fetches and the whole level {whole}: the "
        f"ladder is fetching more than the window asked for"
    )


@needs_dask
def test_a_resolved_tile_is_not_looked_up_twice(pyramid):
    """Re-rendering must not re-ask where a tile already is.

    DID names a cached file by its immutable uid, so a resolved path
    cannot change meaning -- the file is either still there or gone, never
    different. That makes the second render a stat() rather than a trip
    through the fetch threads, which is what a gene toggle or a band
    change does over and over.
    """
    S, pyr = pyramid
    from ndi.session import session_base

    opens = []
    real = session_base.ndi_session.database_openbinarydoc

    def spy(self, doc, fn):
        opens.append(fn)
        return real(self, doc, fn)

    session_base.ndi_session.database_openbinarydoc = spy
    try:
        arrays = levelArrays(S, pyr)
        first = np.asarray(arrays[0].compute(scheduler="threads"))
        assert opens, "the first render must resolve its tiles"
        opens.clear()
        second = np.asarray(arrays[0].compute(scheduler="threads"))
    finally:
        session_base.ndi_session.database_openbinarydoc = real

    assert opens == [], f"re-rendering re-opened {len(opens)} tiles"
    np.testing.assert_array_equal(first, second)


@needs_dask
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


@needs_dask
def test_a_computed_block_matches_readViewport(pyramid):
    """The lazy path and the documented reader must agree, or the viewer is
    drawing something no other caller would get."""
    S, pyr = pyramid
    arr = levelArrays(S, pyr)[0]
    got = np.asarray(arr[:8, :8].compute())
    want, _info = readViewport(S, pyr, 1, (0, 0, 8, 8), None)
    np.testing.assert_allclose(got, want)


@needs_dask
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


@needs_dask
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


@needs_dask
def test_layer_spec_is_what_add_image_takes(pyramid):
    S, pyr = pyramid
    spec = layerSpec(S, pyr)
    assert spec["multiscale"] is True
    assert len(spec["data"]) == 3
    assert spec["scale"] == (PY, PX)
    assert spec["translate"] == (OY * PY, OX * PX)
    assert spec["name"] == "opossum test"
    assert spec["rgb"] is False


@needs_dask
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
