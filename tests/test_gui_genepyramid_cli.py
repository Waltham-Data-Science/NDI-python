"""Tests for the napariViewGEF command line.

Everything here runs WITHOUT a display. --report and --list exist partly
so the entry point has a path CI can exercise: the argument handling, the
pyramid lookup and the gene resolution are the parts that break, and none
of them need napari.
"""

from __future__ import annotations

import pytest

from ndi.fun.doc_gene import makeGeneList, makePyramid
from ndi.gui.app.genepyramid.cli import build_parser, main
from ndi.session.dir import ndi_session_dir

SYMBOLS = ["SATB2", "GAD1", "SATB2", "AQP4"]  # SATB2 twice, as real lists repeat


def _session_with_pyramids(path, n=1):
    S = ndi_session_dir("cli", str(path))
    sub = S.newdocument("subject", **{"subject.local_identifier": "cli@vhlab"})
    S.database_add(sub)
    gl = makeGeneList(S, [f"ENSC{k:04d}" for k in range(len(SYMBOLS))], SYMBOLS)
    for i in range(n):
        makePyramid(
            S,
            [1000, 1005, 1030, 1031],
            [2000, 2003, 2010, 2011],
            [0, 1, 2, 3],
            [2, 3, 5, 7],
            gl,
            subjectID=sub.id,
            binSizes=[1, 2, 4],
            grid=2,
            basePixelSize=(0.5, 0.25),
            label=f"section {i}",
        )
    return S


@pytest.fixture
def one_pyramid(tmp_path):
    d = tmp_path / "one"
    d.mkdir(parents=True, exist_ok=True)
    _session_with_pyramids(d, 1)
    return str(d)


@pytest.fixture
def two_pyramids(tmp_path):
    d = tmp_path / "two"
    d.mkdir(parents=True, exist_ok=True)
    _session_with_pyramids(d, 2)
    return str(d)


def test_parser_defaults_to_density(one_pyramid):
    a = build_parser().parse_args([one_pyramid])
    assert a.no_density is False, "density is the default; levels must be comparable"


def test_report_needs_no_display(one_pyramid, capsys):
    assert main([one_pyramid, "--report"]) == 0
    out = capsys.readouterr().out
    assert "origin" in out and "extent" in out
    # the ladder, one row per level
    for b in ("1", "2", "4"):
        assert b in out


def test_list_shows_every_pyramid(two_pyramids, capsys):
    assert main([two_pyramids, "--list"]) == 0
    out = capsys.readouterr().out
    assert "2 pyramid(s)" in out
    assert "section 0" in out and "section 1" in out


def test_one_pyramid_needs_no_flag(one_pyramid):
    assert main([one_pyramid, "--report"]) == 0


def test_several_pyramids_refuse_to_guess(two_pyramids, capsys):
    """Guessing which section to show is worse than asking."""
    assert main([two_pyramids, "--report"]) == 1
    err = capsys.readouterr().err
    assert "--pyramid" in err
    assert "section 0" in err and "section 1" in err


def test_naming_a_pyramid_selects_it(two_pyramids, capsys):
    from ndi.query import ndi_query

    S = ndi_session_dir(two_pyramids)
    docs = S.database_search(ndi_query("").isa("spatialGeneExpressionPyramid"))
    target = docs[1]
    assert main([two_pyramids, "--pyramid", target.id, "--report"]) == 0
    assert target.id in capsys.readouterr().out


def test_an_unknown_pyramid_is_an_error(one_pyramid, capsys):
    assert main([one_pyramid, "--pyramid", "nope", "--report"]) == 1
    assert "--list" in capsys.readouterr().err


def test_a_session_with_no_pyramid_says_so(tmp_path, capsys):
    d = tmp_path / "empty"
    d.mkdir(parents=True, exist_ok=True)
    ndi_session_dir("empty", str(d))
    assert main([str(d), "--report"]) == 1
    assert "no spatialGeneExpressionPyramid" in capsys.readouterr().err


def test_genes_accepts_symbols_and_keeps_every_duplicate(one_pyramid, capsys):
    """A symbol can name several rows -- the opossum list repeats 5,531 of
    them -- so dropping the duplicates would silently show part of a
    gene's signal."""
    assert main([one_pyramid, "--genes", "SATB2", "--report"]) == 0
    assert "2 of the list selected" in capsys.readouterr().out


def test_genes_accepts_accessions(one_pyramid, capsys):
    assert main([one_pyramid, "--genes", "ENSC0001", "--report"]) == 0
    assert "1 of the list selected" in capsys.readouterr().out


def test_an_unknown_gene_names_itself(one_pyramid):
    with pytest.raises(SystemExit, match="NOT_A_GENE"):
        main([one_pyramid, "--genes", "NOT_A_GENE", "--report"])


# ------------------------------------------------------------------ cells

CELLS_TSV = (
    "cell_index\tcell_id\tx\ty\tdnbCount\tn_genes_by_counts\n"
    "0\t10093173156650\t1002\t2003\t96\t187\n"
    "1\t10093173156651\t1030\t2010\t42\t101\n"
)


def _write_cells_dir(path, text=CELLS_TSV):
    path.mkdir(parents=True, exist_ok=True)
    (path / "cells.tsv").write_text(text)
    return str(path)


def test_cells_from_a_directory(one_pyramid, tmp_path, capsys):
    d = _write_cells_dir(tmp_path / "cellsdir")
    assert main([one_pyramid, "--cells", d, "--report"]) == 0
    out = capsys.readouterr().out
    assert "2 centroids" in out


def test_cells_keeps_the_writers_own_column_names(tmp_path):
    """extract_cells.py writes dnbCount and n_genes_by_counts where the
    spec says dnb_count and n_genes. Reading by position would silently
    map one measurement onto another's name."""
    from ndi.fun.doc_gene import _parse_cells_tsv

    cols, _ = _parse_cells_tsv(CELLS_TSV)
    assert "dnbCount" in cols and "n_genes_by_counts" in cols
    assert "dnb_count" not in cols


def test_cells_centroids_are_source_coordinates(tmp_path):
    from ndi.fun.doc_gene import _parse_cells_tsv

    cols, _ = _parse_cells_tsv(CELLS_TSV)
    # The fixture's pyramid origin is (1000, 2000); these are absolute,
    # not origin-relative, and a viewer must transform them.
    assert list(cols["x"]) == [1002.0, 1030.0]
    assert list(cols["y"]) == [2003.0, 2010.0]


def test_cell_id_is_never_parsed_as_a_number(tmp_path):
    """A 14-digit id would lose precision as a float and stop matching
    the source file it came from."""
    from ndi.fun.doc_gene import _parse_cells_tsv

    cols, _ = _parse_cells_tsv(CELLS_TSV)
    assert cols["cell_id"] == ["10093173156650", "10093173156651"]


def test_a_missing_required_column_names_it(tmp_path):
    from ndi.fun.doc_gene import _parse_cells_tsv

    with pytest.raises(ValueError, match="cell_id"):
        _parse_cells_tsv("cell_index\tx\ty\n0\t1\t2\n")


def test_a_directory_without_cells_tsv_says_what_it_wants(one_pyramid, tmp_path):
    empty = tmp_path / "notcells"
    empty.mkdir(parents=True, exist_ok=True)
    with pytest.raises(SystemExit, match="extract_cells.py"):
        main([one_pyramid, "--cells", str(empty), "--report"])


def test_auto_cells_with_no_document_says_so(one_pyramid):
    """Nothing writes a cells document yet, so this is the path a caller
    hits today; it must name the alternative rather than traceback."""
    with pytest.raises(SystemExit, match="no spatialGeneExpressionCells"):
        main([one_pyramid, "--cells", "--report"])


def test_no_cells_flag_means_no_overlay(one_pyramid, capsys):
    assert main([one_pyramid, "--report"]) == 0
    assert "centroids" not in capsys.readouterr().out
