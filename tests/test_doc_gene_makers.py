"""Tests for the spatial gene expression document makers.

Mirrors NDI-matlab's TestGeneDocs. Assertions are chosen so the failures
that would actually occur are caught rather than averaged away.
"""
from __future__ import annotations

import pytest

from ndi.session.dir import ndi_session_dir
from ndi.fun import doc_gene


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
    doc = doc_gene.makeGeneList(session, ids, names,
                                genomeAssembly="testAsm",
                                geneIdNamespace="Ensembl")
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
    assert [l.split("\t")[1] for l in lines[1:]] == ids


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
