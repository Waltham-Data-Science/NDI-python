"""The two decisions the control panels make before Qt is involved.

Both are about NOT SHOWING THE SAME THING TWICE, and both were reported
from the demo session rather than guessed at: a gene list that named the
same symbol many times over, and two labelings that turned out to be one.
"""

from __future__ import annotations

from ndi.gui.app.genepyramid import controls

# ------------------------------------------------------------ geneIndex


def test_one_entry_per_symbol_however_many_rows_it_names():
    ids = ["ENS1", "ENS2", "ENS3", "ENS4"]
    names = ["Sox2", "Gad1", "Sox2", "Sox2"]
    index = controls.geneIndex(ids, names)
    assert list(index) == ["Gad1", "Sox2"]
    assert index["Sox2"]["rows"] == [0, 2, 3]
    assert index["Sox2"]["accessions"] == ["ENS1", "ENS3", "ENS4"]


def test_every_row_is_kept_because_the_layer_sums_them():
    """Taking the first would draw part of a gene and look like all of it."""
    ids = [f"ENS{i}" for i in range(5)]
    names = ["A", "B", "A", "B", "A"]
    index = controls.geneIndex(ids, names)
    assert sorted(r for e in index.values() for r in e["rows"]) == [0, 1, 2, 3, 4]


def test_a_row_with_no_symbol_falls_back_to_its_accession():
    index = controls.geneIndex(["ENSX", "ENSY"], ["", None])
    assert list(index) == ["ENSX", "ENSY"]
    assert index["ENSX"]["rows"] == [0]


def test_a_row_with_neither_is_still_selectable():
    """Dropping it would shift nothing, but it would hide a real column."""
    index = controls.geneIndex(["", ""], ["", ""])
    assert list(index) == ["row 0", "row 1"]


def test_symbols_are_ordered_case_insensitively():
    index = controls.geneIndex(["1", "2", "3"], ["bcl2", "Actb", "Zic1"])
    assert list(index) == ["Actb", "bcl2", "Zic1"]


# ------------------------------------------------------- labelAgreement


def _info(name, unsup=False):
    return {"labelName": name, "isUnsupervised": unsup, "categories": [], "nUnlabeled": 0}


def test_a_per_cluster_renaming_determines_the_call_exactly():
    leiden = ["0", "0", "1", "2", "1"]
    subclass = ["L2/3", "L2/3", "Pvalb", "Sst", "Pvalb"]
    assert controls.labelAgreement(leiden, subclass) == 1.0


def test_a_handful_of_disagreeing_cells_is_not_a_second_opinion():
    """Exact partition equality missed this, which is why it is measured."""
    leiden = ["0"] * 100 + ["1"] * 100
    subclass = ["A"] * 99 + ["B"] + ["B"] * 100
    # Not the same partition -- one cell moved -- but not two opinions.
    assert controls.labelAgreement(leiden, subclass) == 0.995


def test_the_measure_is_directional():
    """A fine clustering determines a coarse call, not the other way."""
    fine = ["0", "1", "2", "3"]
    coarse = ["A", "A", "B", "B"]
    assert controls.labelAgreement(fine, coarse) == 1.0
    assert controls.labelAgreement(coarse, fine) == 0.5


def test_labelings_of_different_lengths_are_refused():
    import pytest

    with pytest.raises(ValueError, match="not labelings of the same cells"):
        controls.labelAgreement(["a"], ["a", "b"])


# ------------------------------------------------------ selectLabelings


def test_the_named_call_is_what_survives_a_redundant_pair():
    n = 200
    leiden = ["0"] * (n // 2) + ["1"] * (n // 2)
    subclass = ["Pvalb"] * (n // 2) + ["Sst"] * (n // 2)
    found = [
        (leiden, _info("leiden", unsup=True)),
        (subclass, _info("subclass_nn_column")),
    ]
    kept, redundant, missing = controls.selectLabelings(found)
    assert [i["labelName"] for _lb, i in kept] == ["subclass_nn_column"]
    assert redundant[0][0] == "leiden"
    assert redundant[0][1] == "subclass_nn_column"
    assert missing == []


def test_two_labelings_that_really_differ_are_both_kept():
    a = ["x"] * 50 + ["y"] * 50
    b = ["p", "q"] * 50
    found = [(a, _info("a")), (b, _info("b"))]
    kept, redundant, _ = controls.selectLabelings(found)
    assert len(kept) == 2
    assert redundant == []


def test_naming_a_labeling_overrides_the_collapsing():
    leiden = ["0"] * 100 + ["1"] * 100
    subclass = ["Pvalb"] * 100 + ["Sst"] * 100
    found = [(leiden, _info("leiden", unsup=True)), (subclass, _info("subclass_nn_column"))]
    kept, redundant, missing = controls.selectLabelings(found, ["leiden"])
    assert [i["labelName"] for _lb, i in kept] == ["leiden"]
    assert redundant == [] and missing == []


def test_asking_for_a_labeling_that_is_not_there_says_so():
    found = [(["a", "b"], _info("real"))]
    kept, _redundant, missing = controls.selectLabelings(found, ["typo"])
    assert kept == []
    assert missing == ["typo"]


def test_an_empty_selection_shows_nothing_rather_than_everything():
    """'--labels none' is a choice, and it is not the same as no choice."""
    found = [(["a", "b"], _info("real"))]
    kept, _redundant, missing = controls.selectLabelings(found, [])
    assert kept == [] and missing == []


# -------------------------------------------------------- abundanceBand


def test_the_full_band_keeps_everything():
    keep, info = controls.abundanceBand([1, 2, 3], 0.0, 100.0)
    assert keep.all()
    assert info["nKept"] == 3
    assert info["pctReads"] == 100.0
    assert info["droppedTop"] == []


def test_the_band_is_a_percentile_of_READS_not_of_the_list():
    """The distinction is the whole point of the control."""
    # 900 genes with one read each, 10 with a hundred. The top half of
    # the READS is those 10 genes -- barely 1% of the list.
    totals = [1] * 900 + [100] * 10
    keep, info = controls.abundanceBand(totals, 50.0, 100.0)
    assert info["nKept"] == 10
    assert keep[900:].all() and not keep[:900].any()
    assert round(info["pctReads"], 1) == 52.6


def test_dropping_the_top_names_what_it_dropped():
    # The loud gene's interval is [19.8, 100], so its midpoint is 59.9
    # and only a cut below that reaches it.
    totals = [1] * 99 + [400]
    _keep, info = controls.abundanceBand(totals, 0.0, 50.0)
    assert info["droppedTop"] == [99]


def test_a_gene_too_loud_for_a_small_top_cut_survives_it():
    """Looks like a bug the first time; it is arithmetic, and reported."""
    totals = [10] * 70 + [300]
    keep, info = controls.abundanceBand(totals, 0.0, 99.0)
    assert keep[-1]
    assert info["droppedTop"] == []
    assert info["topShare"] == 30.0
    # The cut that WOULD drop it: its interval is [70, 100], midpoint 85.
    assert info["topMid"] == 85.0


def test_ties_land_on_the_same_side_of_a_cut():
    """Otherwise identical totals split on sort order, which is arbitrary."""
    totals = [5] * 10 + [1000]
    keep, _info = controls.abundanceBand(totals, 0.0, 50.0)
    assert len({bool(v) for v in keep[:10]}) == 1


def test_a_pyramid_with_no_reads_is_not_filtered_into_nothing():
    keep, info = controls.abundanceBand([0, 0, 0], 10.0, 90.0)
    assert keep.all()
    assert info["available"] is False


def test_an_empty_list_is_handled_rather_than_dividing_by_zero():
    keep, info = controls.abundanceBand([], 0.0, 100.0)
    assert len(keep) == 0
    assert info["available"] is False
