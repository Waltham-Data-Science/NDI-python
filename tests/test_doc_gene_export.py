"""Round-trip tests for the GEF and HDF5 exporters.

The claim an exporter has to earn is that the data survives, so these
compare against the ORIGINAL records rather than against the exporter's
own output. A writer that is merely self-consistent passes a
write-then-read test and still loses data.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.document import ndi_document
from ndi.fun import doc_gene, doc_gene_export
from ndi.session.dir import ndi_session_dir

h5py = pytest.importorskip("h5py")


@pytest.fixture
def built(tmp_path):
    """A pyramid from known records, plus those records for comparison."""
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("export_test", str(d))
    sub = ndi_document(
        "subject",
        **{"base.session_id": S.id(), "subject.local_identifier": "exp@vhlab"},
    )
    S.database_add(sub)

    rng = np.random.default_rng(3)
    n, ng, side = 4000, 40, 400
    ox, oy = 1000, 2000  # non-zero origin, so a lost origin shows
    x = rng.integers(0, side, n, dtype=np.int64) + ox
    y = rng.integers(0, side, n, dtype=np.int64) + oy
    g = rng.integers(0, ng, n, dtype=np.int64)
    c = rng.integers(1, 20, n, dtype=np.int64)

    gl = doc_gene.makeGeneList(
        S, [f"ENS{i:05d}" for i in range(ng)], [f"Gene{i}" for i in range(ng)]
    )
    pyr, _ = doc_gene.makePyramid(
        S,
        x,
        y,
        g,
        c,
        gl,
        subjectID=sub.id,
        binSizes=(1, 2),
        grid=3,
        origin=(ox, oy),
    )
    return S, pyr, x, y, g, c, ng


def test_gef_roundtrips_every_record(built, tmp_path):
    """Total counts, record count and per-gene totals must all survive."""
    S, pyr, x, y, g, c, ng = built
    out = tmp_path / "out.gef"
    info = doc_gene_export.exportGef(S, pyr, 1, str(out))

    assert info["total_counts"] == int(c.sum()), "counts must survive the export"
    assert info["n_genes"] == ng

    with h5py.File(out, "r") as f:
        expr = f["/geneExp/bin1/expression"][...]
        gene = f["/geneExp/bin1/gene"][...]
        assert int(expr["count"].sum()) == int(c.sum())
        # Per-gene totals, compared against the ORIGINAL records.
        want = np.bincount(g, weights=c, minlength=ng).astype(np.int64)
        got = np.zeros(ng, np.int64)
        for i in range(ng):
            lo = int(gene["offset"][i])
            hi = lo + int(gene["count"][i])
            got[i] = expr["count"][lo:hi].sum()
        np.testing.assert_array_equal(got, want)


def test_gef_restores_source_coordinates(built, tmp_path):
    """Positions come back in chip units, not level-relative ones."""
    S, pyr, x, y, g, c, _ = built
    out = tmp_path / "out.gef"
    doc_gene_export.exportGef(S, pyr, 1, str(out))
    with h5py.File(out, "r") as f:
        expr = f["/geneExp/bin1/expression"][...]
        assert int(expr["x"].min()) == int(x.min()), "origin must be added back"
        assert int(expr["y"].min()) == int(y.min())
        assert int(expr["x"].max()) == int(x.max())
        assert int(expr["y"].max()) == int(y.max())


def test_gef_writes_bounds_on_the_bin_group_not_only_the_root(built, tmp_path):
    """A reader that probes only the root and finds nothing derives a 1x1
    extent -- the bug this project already hit once."""
    S, pyr, *_ = built
    out = tmp_path / "out.gef"
    doc_gene_export.exportGef(S, pyr, 1, str(out))
    with h5py.File(out, "r") as f:
        for where in (f["/geneExp/bin1"], f):
            for k in ("minX", "minY", "maxX", "maxY", "resolution"):
                assert k in where.attrs, f"{k} missing from {where.name}"


def test_exported_gef_is_readable_by_the_reference_reader(built, tmp_path):
    """The point of a GEF export is that somebody else's tool can open it,
    so parse it back the way an outside reader would."""
    S, pyr, x, y, g, c, ng = built
    out = tmp_path / "out.gef"
    doc_gene_export.exportGef(S, pyr, 1, str(out))
    with h5py.File(out, "r") as f:
        gene = f["/geneExp/bin1/gene"][...]
        expr = f["/geneExp/bin1/expression"][...]
        # Offsets must be contiguous and ascending, which is what lets a
        # reader derive each record's gene from the counts alone.
        expected = np.concatenate([[0], np.cumsum(gene["count"])[:-1]])
        np.testing.assert_array_equal(gene["offset"].astype(np.int64), expected)
        assert len(expr) == int(gene["count"].sum())
        assert gene["geneID"][0].decode() == "ENS00000"


def test_hdf5_roundtrips_counts_and_both_coordinate_frames(built, tmp_path):
    S, pyr, x, y, g, c, ng = built
    out = tmp_path / "out.h5"
    info = doc_gene_export.exportHdf5(S, pyr, 1, str(out))
    assert info["total_counts"] == int(c.sum())

    with h5py.File(out, "r") as f:
        assert int(f["data/counts"][...].sum()) == int(c.sum())
        assert f["gene"].attrs["index_base"] == 0
        # Both frames present, and the source frame really is offset.
        xs, xl = f["pixel/x_source"][...], f["pixel/x_level"][...]
        assert int(xs.min()) == int(x.min())
        assert int(xl.min()) == int(x.min()) - 1000
        # The document metadata came along.
        assert f.attrs["pyramid_origin_x"] == 1000
        assert f.attrs["level_bin_size"] == 1


def test_hdf5_gene_subset(built, tmp_path):
    S, pyr, x, y, g, c, _ = built
    out = tmp_path / "sub.h5"
    info = doc_gene_export.exportHdf5(S, pyr, 1, str(out), genes=[0, 1, 2])
    assert info["n_genes"] == 3
    want = int(c[np.isin(g, [0, 1, 2])].sum())
    assert info["total_counts"] == want


def test_coarse_level_conserves_counts(built, tmp_path):
    """Binning sums, so bin2 must export the same total as bin1."""
    S, pyr, x, y, g, c, _ = built
    a = doc_gene_export.exportGef(S, pyr, 1, str(tmp_path / "b1.gef"))
    b = doc_gene_export.exportGef(S, pyr, 2, str(tmp_path / "b2.gef"))
    assert a["total_counts"] == b["total_counts"] == int(c.sum())
    assert b["n_records"] < a["n_records"], "binning must merge some records"


def test_readGeneList_asserts_zero_based_order(built):
    S, pyr, *_ = built
    ids, names = doc_gene_export.readGeneList(S, pyr)
    assert ids[0] == "ENS00000"
    assert names[3] == "Gene3"
    assert len(ids) == len(names)
