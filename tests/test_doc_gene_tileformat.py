"""Conformance tests for the spatialGeneExpressionTiles binary codec.

These assert against ``tests/fixtures/gene/conformance_tile.bin``, the
SAME 86-byte fixture NDI-matlab's ``TestTileFormat`` asserts on. That is
the point: three implementations agreeing on one artifact is a stronger
claim than any two agreeing with each other, and the format is read by
one language after being written by another.

The fixture's records are chosen to fail loudly under the errors that
actually cross language boundaries, not under arbitrary ones:

* a pixel at (x=1, y=5) with none at (x=5, y=1), so a transposed reader
  diverges rather than coincidentally matching;
* a count of 999, which a uint8 field would truncate;
* a gene row of 70000, which a uint16 index would truncate;
* unsorted input, so grouping and the CSR row pointer are exercised.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ndi.fun import doc_gene

FIXTURES = Path(__file__).parent / "fixtures" / "gene"


@pytest.fixture(scope="module")
def expected() -> dict:
    return json.loads((FIXTURES / "conformance_tile.json").read_text())


@pytest.fixture(scope="module")
def tile() -> dict:
    return doc_gene.readTileFile(str(FIXTURES / "conformance_tile.bin"))


def test_decode_matches_fixture(tile, expected):
    """Every field decodes to the documented value."""
    assert tile["n_pixels"] == expected["n_pixels"]
    assert tile["n_nonzero"] == expected["n_nonzero"]
    for field in ("x", "y", "offset", "gene_index", "count"):
        np.testing.assert_array_equal(
            np.asarray(tile[field], np.int64),
            np.asarray(expected[field], np.int64),
            err_msg=f"field {field!r} differs from the conformance fixture")


def test_wide_fields_are_not_truncated(tile):
    """The two records that would break a narrower field survive."""
    # gene row 70000 does not fit uint16; count 999 does not fit uint8.
    assert 70000 in set(tile["gene_index"].tolist())
    assert 999 in set(tile["count"].tolist())


def test_render_all_genes(tile, expected):
    img = doc_gene.renderTile(tile, None, expected["height"], expected["width"])
    assert img.sum() == pytest.approx(expected["render_all_genes_sum"])
    for px in expected["render_all_genes_nonzero_pixels"]:
        assert img[px["y"], px["x"]] == pytest.approx(px["value"]), (
            f"pixel (x={px['x']}, y={px['y']}) should hold {px['value']}")
    # Exactly those pixels and no others, so a reader that lands values in
    # the right total but the wrong places still fails.
    assert int(np.count_nonzero(img)) == len(
        expected["render_all_genes_nonzero_pixels"])


def test_render_single_gene(tile, expected):
    img = doc_gene.renderTile(tile, [70000], expected["height"],
                              expected["width"])
    assert img.sum() == pytest.approx(expected["render_gene_70000_sum"])


def test_render_boolean_mask_matches_row_list(tile, expected):
    """The boolean fast path and the row-list path must agree."""
    mask = np.zeros(70001, bool)
    mask[70000] = True
    by_mask = doc_gene.renderTile(tile, mask, expected["height"],
                                  expected["width"])
    by_rows = doc_gene.renderTile(tile, [70000], expected["height"],
                                  expected["width"])
    np.testing.assert_array_equal(by_mask, by_rows)


def test_render_binsize_divides_by_area(tile, expected):
    """binSize divides by the AREA, not the linear factor."""
    img = doc_gene.renderTile(tile, None, expected["height"],
                              expected["width"], binSize=4)
    assert img.sum() == pytest.approx(expected["render_binsize4_sum"])
    assert img.sum() == pytest.approx(expected["render_all_genes_sum"] / 16)


def test_roundtrip_is_byte_identical(tile, tmp_path):
    """Re-encoding must reproduce the fixture exactly.

    Reading the format is not enough if this side cannot also write it --
    a writer that is merely self-consistent would let the three
    implementations drift apart the first time Python wrote a tile that
    MATLAB read.
    """
    raw = (FIXTURES / "conformance_tile.bin").read_bytes()
    # Expand CSR back to flat, pixel-repeated records.
    n = np.diff(tile["offset"])
    x = np.repeat(tile["x"], n)
    y = np.repeat(tile["y"], n)
    out = tmp_path / "roundtrip.bin"
    doc_gene.writeTileFile(str(out), x, y, tile["gene_index"], tile["count"])
    assert out.read_bytes() == raw


def test_write_sorts_unordered_records(tmp_path):
    """Records handed over out of order still produce a valid tile."""
    x = [9, 0, 5, 9]
    y = [2, 0, 1, 2]
    g = [11, 5, 70000, 3]
    c = [999, 1, 300, 50]
    out = tmp_path / "unsorted.bin"
    doc_gene.writeTileFile(str(out), x, y, g, c)
    t = doc_gene.readTileFile(str(out))
    assert t["n_pixels"] == 3          # (0,0), (5,1), (9,2)
    assert t["n_nonzero"] == 4
    # row-major: y ascending, then x
    np.testing.assert_array_equal(np.asarray(t["y"], np.int64), [0, 1, 2])
    np.testing.assert_array_equal(np.asarray(t["x"], np.int64), [0, 5, 9])
    img = doc_gene.renderTile(t, None, 16, 16)
    assert img.sum() == pytest.approx(sum(c))


def test_empty_tile_roundtrips(tmp_path):
    out = tmp_path / "empty.bin"
    doc_gene.writeTileFile(str(out), [], [], [], [])
    t = doc_gene.readTileFile(str(out))
    assert t["n_pixels"] == 0
    assert t["n_nonzero"] == 0
    assert doc_gene.renderTile(t, None, 4, 4).sum() == 0


def test_truncated_file_is_rejected(tmp_path):
    """A short read must raise rather than return a plausible tile."""
    raw = (FIXTURES / "conformance_tile.bin").read_bytes()
    bad = tmp_path / "truncated.bin"
    bad.write_bytes(raw[:-4])
    with pytest.raises(ValueError, match="bytes"):
        doc_gene.readTileFile(str(bad))
