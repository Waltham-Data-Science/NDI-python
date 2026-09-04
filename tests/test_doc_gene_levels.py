"""Tests for levelTable, chooseLevel and readViewportBase.

Python mirror of:
    tests/+ndi/+unittest/+fun/+doc/+gene/TestLevelTools.m

Same fixture and same assertions, so the two languages agree about the
join across documents and about the rounding at a viewport's edges rather
than each being self-consistent.

The fixture uses a non-zero origin and a wider-than-tall extent on
purpose: an implementation that forgets to subtract the origin, or that
transposes width and height, must fail rather than coincidentally agree.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.fun.doc_gene import (
    chooseLevel,
    levelTable,
    makeGeneList,
    makePyramid,
    readViewport,
    readViewportBase,
)
from ndi.session.dir import ndi_session_dir

OX, OY = 1000, 2000
COUNTS = [2, 3, 5, 7]


@pytest.fixture
def pyramid(tmp_path):
    d = tmp_path / "gene_lt"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("gene_lt", str(d))

    sub = S.newdocument("subject", **{"subject.local_identifier": "lt@vhlab"})
    S.database_add(sub)

    gl = makeGeneList(
        S,
        [f"ENSL{k:04d}" for k in range(1, 5)],
        ["a", "b", "c", "d"],
    )
    x = [OX + 0, OX + 5, OX + 30, OX + 31]
    y = [OY + 0, OY + 3, OY + 10, OY + 11]
    gi = [0, 1, 2, 3]
    # MATLAB name-value spellings are preserved for options (users type
    # 'binSizes'); positional argument names take Python style. That split
    # is the existing convention in this module, not a new one.
    pyr, _tiles = makePyramid(
        S,
        x,
        y,
        gi,
        COUNTS,
        gl,
        subjectID=sub.id,
        binSizes=[1, 2, 4],
        grid=2,
        basePixelSize=(0.5, 0.5),
    )
    return S, pyr


# ---------------------------------------------------------------- levelTable


def test_level_table_has_one_row_per_level_finest_first(pyramid):
    S, pyr = pyramid
    levels, _frame = levelTable(S, pyr)
    assert len(levels) == 3
    assert [r["binSize"] for r in levels] == [1, 2, 4]


def test_level_table_joins_both_documents(pyramid):
    """The point of the function: geometry from the tiles documents and the
    frame from the pyramid document, in one place."""
    S, pyr = pyramid
    levels, frame = levelTable(S, pyr)
    p = pyr.document_properties["spatialGeneExpressionPyramid"]

    assert all(r["tileRows"] == p["tile_rows"] for r in levels)
    assert levels[0]["levelWidth"] == p["extent_x"]
    assert levels[0]["levelHeight"] == p["extent_y"]

    assert frame["originX"] == p["origin_x"]
    assert frame["originY"] == p["origin_y"]
    assert frame["extentX"] == p["extent_x"]
    assert frame["extentY"] == p["extent_y"]


def test_level_table_coarser_levels_shrink(pyramid):
    S, pyr = pyramid
    levels, _ = levelTable(S, pyr)
    w = [r["levelWidth"] for r in levels]
    h = [r["levelHeight"] for r in levels]
    assert all(b <= a for a, b in zip(w, w[1:]))
    assert all(b <= a for a, b in zip(h, h[1:]))
    assert all(r["nTilesStored"] <= r["nTilesGrid"] for r in levels)


# --------------------------------------------------------------- chooseLevel


def test_choose_level_picks_coarsest_that_meets_target(pyramid):
    S, pyr = pyramid
    levels, _ = levelTable(S, pyr)
    rect = (OX, OY, 32, 16)
    # 32 source units across: bin1 -> 32 px, bin2 -> 16, bin4 -> 8.
    assert chooseLevel(levels, rect, 32)[0] == 1
    assert chooseLevel(levels, rect, 16)[0] == 2
    assert chooseLevel(levels, rect, 8)[0] == 4


def test_choose_level_reports_when_it_cannot_meet_the_target(pyramid):
    S, pyr = pyramid
    levels, _ = levelTable(S, pyr)
    b, info = chooseLevel(levels, (OX, OY, 32, 16), 100000)
    assert b == 1
    assert info["metTarget"] is False


def test_choose_level_rejects_an_empty_rectangle(pyramid):
    S, pyr = pyramid
    levels, _ = levelTable(S, pyr)
    with pytest.raises(ValueError, match="positive width and height"):
        chooseLevel(levels, (0, 0, 0, 10), 16)


# ---------------------------------------------------------- readViewportBase


def test_base_viewport_subtracts_the_origin(pyramid):
    """The whole reason the function exists."""
    S, pyr = pyramid
    _img, info = readViewportBase(S, pyr, 1, (OX, OY, 8, 8), None)
    assert info["rectLevel"][:2] == (0, 0)


def test_base_viewport_matches_readviewport_on_the_same_region(pyramid):
    S, pyr = pyramid
    a, _ = readViewportBase(S, pyr, 1, (OX, OY, 8, 8), None)
    b, _ = readViewport(S, pyr, 1, (0, 0, 8, 8), None)
    np.testing.assert_array_equal(a, b)


def test_base_viewport_covers_rather_than_clips_the_request(pyramid):
    """At bin 4 a request starting 2 source units in cannot land on a bin
    edge; the low edge must floor, never round toward the middle."""
    S, pyr = pyramid
    img, info = readViewportBase(S, pyr, 4, (OX + 2, OY + 2, 8, 8), None)
    cov = info["rectSourceCovered"]
    assert cov[0] <= OX + 2
    assert cov[1] <= OY + 2
    assert cov[0] + cov[2] >= OX + 2 + 8
    assert cov[1] + cov[3] >= OY + 2 + 8
    assert img.shape == (info["rectLevel"][3], info["rectLevel"][2])


def test_base_viewport_none_rect_means_whole_extent(pyramid):
    S, pyr = pyramid
    img, info = readViewportBase(S, pyr, 1, None, None)
    p = pyr.document_properties["spatialGeneExpressionPyramid"]
    assert img.shape == (p["extent_y"], p["extent_x"])
    assert info["rectSourceCovered"][:2] == (p["origin_x"], p["origin_y"])


def test_base_viewport_off_the_edge_is_empty_not_an_error(pyramid):
    """A viewer pans off the edge routinely."""
    S, pyr = pyramid
    img, info = readViewportBase(S, pyr, 1, (900000, 900000, 10, 10), None)
    assert img.size == 0
    assert info["rectLevel"][2:] == (0, 0)


def test_base_viewport_rejects_an_unknown_level(pyramid):
    S, pyr = pyramid
    with pytest.raises(ValueError, match="no level with bin_size 3"):
        readViewportBase(S, pyr, 3, (OX, OY, 8, 8), None)


def test_base_viewport_conserves_counts(pyramid):
    S, pyr = pyramid
    img, _ = readViewportBase(S, pyr, 1, None, None, density=False)
    assert img.sum() == pytest.approx(sum(COUNTS))
