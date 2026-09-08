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


# ------------------------------------------------------- labelPartition


def test_a_renaming_of_the_same_groups_compares_equal():
    """Why the panel drops one: a transferred call renames its clusters."""
    leiden = ["0", "0", "1", "2", "1"]
    subclass = ["L2/3", "L2/3", "Pvalb", "Sst", "Pvalb"]
    assert controls.labelPartition(leiden) == controls.labelPartition(subclass)


def test_genuinely_different_labelings_do_not_compare_equal():
    a = ["0", "0", "1", "2", "1"]
    b = ["0", "1", "1", "2", "1"]
    assert controls.labelPartition(a) != controls.labelPartition(b)


def test_unlabelled_cells_are_a_group_of_their_own():
    """Two labelings that leave DIFFERENT cells blank are not the same."""
    a = ["", "x", "x"]
    b = ["x", "", "x"]
    assert controls.labelPartition(a) != controls.labelPartition(b)


def test_the_same_names_in_a_different_order_are_a_different_partition():
    assert controls.labelPartition(["a", "b"]) != controls.labelPartition(["b", "b"])
