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
