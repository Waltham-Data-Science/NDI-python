"""Tests for the spatial gene expression document makers.

Mirrors NDI-matlab's TestGeneDocs. Assertions are chosen so the failures
that would actually occur are caught rather than averaged away.
"""

from __future__ import annotations

import pytest

from ndi.fun import doc_gene
from ndi.session.dir import ndi_session_dir


@pytest.fixture
def session(tmp_path):
    # ndi_session_dir requires the directory to exist already.
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    return ndi_session_dir("gene_test", str(d))


def test_geneList_counts_duplicate_symbols(session):
    """Symbols are not unique in real annotations, so the count of
    duplicated ones is computed rather than assumed."""
    ids = ["ENSX0001", "ENSX0002", "ENSX0003", "ENSX0004", "ENSX0005"]
    names = ["HOXA", "HOXA", "PAX6", "HOXA", ""]
    doc = doc_gene.makeGeneList(
        session, ids, names, genomeAssembly="testAsm", geneIdNamespace="Ensembl"
    )
    g = doc.document_properties["geneList"]
    assert g["n_genes"] == 5
    assert g["n_duplicate_gene_names"] == 1, "HOXA on three rows is ONE duplicated symbol"
    assert g["gene_name_completeness"] == pytest.approx(4 / 5)
    assert g["genome_assembly"] == "testAsm"
    assert g["gene_id_namespace"] == "Ensembl"


def test_geneList_writes_zero_based_index(session):
    """genes.tsv carries an explicit ZERO-BASED gene_index column.

    It is written explicitly so a reader can assert it rather than trust
    that row order survived transport, and zero-based so it matches the
    gene_index field in the tile files, which both languages read.
    """
    ids = [f"ENSY{k:04d}" for k in range(1, 5)]
    doc = doc_gene.makeGeneList(session, ids, ["a", "b", "c", "d"])

    fobj = session.database_openbinarydoc(doc, "genes.tsv")
    try:
        text = fobj.read().decode()
    finally:
        session.database_closebinarydoc(fobj)

    lines = text.strip().split("\n")
    assert lines[0].split("\t") == ["gene_index", "gene_id", "gene_name"]
    assert len(lines) == 5, "header plus four genes"
    assert lines[1].split("\t")[0] == "0", "first gene is index 0, not 1"
    assert lines[-1].split("\t")[0] == "3"
    # row order must match the input order
    assert [row.split("\t")[1] for row in lines[1:]] == ids


def test_geneList_blank_symbol_keeps_its_column(session):
    """A gene with no symbol still writes a third field.

    Real annotations leave 10-20% of symbols empty. Dropping the column
    for those rows would make the file ragged and shift a naive reader's
    fields by one.
    """
    doc = doc_gene.makeGeneList(session, ["ENSZ1", "ENSZ2"], ["", "PAX6"])
    fobj = session.database_openbinarydoc(doc, "genes.tsv")
    try:
        text = fobj.read().decode()
    finally:
        session.database_closebinarydoc(fobj)
    # split the raw line, not a stripped one -- stripping eats the
    # trailing tab that carries the empty symbol
    row = text.split("\n")[1]
    assert row.split("\t") == ["0", "ENSZ1", ""]


def test_geneList_rejects_mismatched_lengths(session):
    with pytest.raises(ValueError, match="same length"):
        doc_gene.makeGeneList(session, ["a", "b"], ["only one"])


@pytest.fixture
def subject(session):
    """A real subject document, not a fabricated id.

    The pyramid declares subject_id mustbenotempty, because a section is
    measured from an animal and NDI records that on the measurement.
    """
    from ndi.document import ndi_document

    sub = ndi_document(
        "subject",
        # session.id is a METHOD here, while document.id is a property.
        **{
            "base.session_id": session.id(),
            "subject.local_identifier": "gene_test@vhlab",
        },
    )
    session.database_add(sub)
    return sub


def _small_pyramid(session, subject, grid=2, bins=(1, 2)):
    """Six records placed so x and y are never interchangeable and the
    origin is not zero -- a transposed or origin-shifted reader fails
    rather than coincidentally matching."""
    ids = [f"ENSY{k:04d}" for k in range(1, 7)]
    gl = doc_gene.makeGeneList(session, ids, list("ABCDEF"))
    ox, oy = 1000, 2000
    x = [ox + 0, ox + 0, ox + 3, ox + 9, ox + 9, ox + 9]
    y = [oy + 0, oy + 0, oy + 1, oy + 7, oy + 7, oy + 7]
    gi = [0, 1, 2, 3, 4, 5]
    c = [5, 7, 11, 13, 17, 19]
    pyr, tiles = doc_gene.makePyramid(
        session,
        x,
        y,
        gi,
        c,
        gl,
        subjectID=subject.id,
        binSizes=bins,
        grid=grid,
        basePixelSize=(0.5, 0.5),
    )
    return gl, pyr, tiles, sum(c)


def test_pyramid_shape_and_dependencies(session, subject):
    gl, pyr, tiles, _ = _small_pyramid(session, subject)
    assert len(tiles) == 2, "one tiles document per bin size"
    p = pyr.document_properties["spatialGeneExpressionPyramid"]
    assert p["origin_x"] == 1000, "origin comes from the data"
    assert p["origin_y"] == 2000
    assert p["tile_rows"] == 2
    assert p["bin_sizes"] == [1, 2]
    assert (
        pyr.dependency_value("subject_id") == subject.id
    ), "the pyramid must carry the subject it was measured from"
    assert pyr.dependency_value("geneList_id") == gl.id
    for t in tiles:
        assert t.dependency_value("spatialGeneExpressionPyramid_id") == pyr.id


@pytest.mark.parametrize("b", [1, 2])
def test_counts_are_conserved_at_every_level(session, subject, b):
    """Binning SUMS, so a dropped or double-counted record fails here
    rather than shifting a mean slightly."""
    _, pyr, _, total = _small_pyramid(session, subject)
    img, _ = doc_gene.readViewport(session, pyr, b, density=False)
    assert img.sum() == pytest.approx(total), f"counts must be conserved at bin{b}"


def test_known_gene_lands_at_known_pixel(session, subject):
    _, pyr, _, _ = _small_pyramid(session, subject)
    img, _ = doc_gene.readViewport(session, pyr, 1, gene_rows=[2], density=False)
    assert img.sum() == pytest.approx(11), "gene row 2 carries 11 counts"
    # zero-based (x=3, y=1); a transposed reader puts it at (1, 3)
    assert img[1, 3] == pytest.approx(11)
    assert img[3, 1] == pytest.approx(0)


def test_density_divides_by_bin_area(session, subject):
    _, pyr, _, total = _small_pyramid(session, subject)
    img, _ = doc_gene.readViewport(session, pyr, 2, density=True)
    assert img.sum() == pytest.approx(total / 4), "at bin2 the divisor must be 4"


def test_export_region_returns_raw_counts(session, subject):
    """Export must NOT normalize; doing so would make it lossy."""
    ids = [f"ENSZ{k:04d}" for k in range(1, 5)]
    gl = doc_gene.makeGeneList(session, ids, ["g1", "g2", "g3", "g4"])
    x, y = [10, 10, 12, 40], [20, 20, 21, 50]
    pyr, _ = doc_gene.makePyramid(
        session,
        x,
        y,
        [0, 1, 2, 3],
        [2, 3, 4, 5],
        gl,
        subjectID=subject.id,
        binSizes=(1,),
        grid=2,
    )
    M, pixel_xy = doc_gene.exportRegion(session, pyr, 1)
    assert M.shape == (3, 4), "three occupied pixels: two records share one"
    assert int(M.sum()) == 14, "raw counts, with no density normalization"
    assert pixel_xy.shape == (3, 2)
    assert (pixel_xy >= 0).all(), "pixel coordinates are level-relative"


def test_pyramid_requires_a_subject(session):
    gl = doc_gene.makeGeneList(session, ["ENSA1"], ["A"])
    with pytest.raises(ValueError, match="subject"):
        doc_gene.makePyramid(session, [1], [1], [0], [1], gl, subjectID="")


def test_gene_index_out_of_range_is_rejected(session, subject):
    gl = doc_gene.makeGeneList(session, ["ENSA1", "ENSA2"], ["A", "B"])
    with pytest.raises(ValueError, match="ZERO-BASED"):
        doc_gene.makePyramid(session, [1], [1], [2], [1], gl, subjectID=subject.id, grid=2)
