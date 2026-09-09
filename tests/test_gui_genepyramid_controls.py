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


def test_a_redundant_pair_is_reported_but_both_are_kept():
    """Dropping one was wrong twice: below the threshold it did nothing
    and the reader still saw two, and above it the labeling vanished
    with no way back. The panel names the pair and offers a switch."""
    n = 200
    leiden = ["0"] * (n // 2) + ["1"] * (n // 2)
    subclass = ["Pvalb"] * (n // 2) + ["Sst"] * (n // 2)
    found = [
        (leiden, _info("leiden", unsup=True)),
        (subclass, _info("subclass_nn_column")),
    ]
    kept, redundant, missing = controls.selectLabelings(found)
    # Supervised first, so the pair is measured against the named call.
    assert [i["labelName"] for _lb, i in kept] == ["subclass_nn_column", "leiden"]
    assert redundant[0][0] == "leiden"
    assert redundant[0][1] == "subclass_nn_column"
    assert missing == []


def test_two_labelings_that_really_differ_raise_no_note():
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


# ---------------------------------------------------------- countsOrder


def test_the_loudest_gene_comes_first():
    assert list(controls.countsOrder([3, 100, 7])) == [1, 2, 0]


def test_ascending_puts_the_quietest_first():
    assert list(controls.countsOrder([3, 100, 7], ascending=True)) == [0, 2, 1]


def test_equal_counts_keep_the_order_they_arrived_in():
    """The list arrives alphabetical, and thousands of genes tie at the
    bottom of a real section; an unstable sort would shuffle them."""
    assert list(controls.countsOrder([5, 9, 5, 5, 9])) == [1, 4, 0, 2, 3]


def test_ties_stay_alphabetical_in_BOTH_directions():
    """Reversing the descending order would reverse the ties with it, so
    the same tied group would read forwards one way and backwards the
    other. Ascending is its own sort for that reason."""
    totals = [5, 9, 5, 5, 9]
    assert list(controls.countsOrder(totals, ascending=True)) == [0, 2, 3, 1, 4]
    assert list(controls.countsOrder(totals, ascending=True)) != list(
        reversed(controls.countsOrder(totals))
    )


def test_an_empty_list_sorts_to_nothing():
    assert list(controls.countsOrder([])) == []


# ------------------------------------------------------- addAllPanels


class _Recorder:
    """Stands in for a panel builder and remembers how it was called."""

    def __init__(self, boom=False):
        self.calls = []
        self.boom = boom

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.boom:
            raise RuntimeError("no such file")
        return object()


def test_the_chosen_labelings_reach_the_cell_type_panel(monkeypatch):
    """--labels was accepted, parsed, threaded through openPyramid, and
    then dropped at the last hop, so it silently did nothing. Nothing
    caught it because every other layer mentioned the argument."""
    # addAllPanels refuses to build anything without a Qt binding, and CI
    # installs none. What is under test here is the orchestration, not Qt.
    monkeypatch.setattr(controls, "_importQtWidgets", lambda: None)
    cells = _Recorder()
    monkeypatch.setattr(controls, "addDisplayPanel", _Recorder())
    monkeypatch.setattr(controls, "addCellTypePanel", cells)
    monkeypatch.setattr(controls, "addGenePanel", _Recorder())
    monkeypatch.setattr(controls, "addRotationPanel", _Recorder())

    controls.addAllPanels(
        object(),
        object(),
        object(),
        object(),
        True,
        cells_doc=object(),
        points_layer=object(),
        labelings=["subclass_nn_column"],
    )
    assert cells.calls, "the cell type panel was never built"
    args, _kwargs = cells.calls[0]
    assert args[-1] == ["subclass_nn_column"]


def test_a_panel_that_throws_does_not_take_the_window_with_it(monkeypatch, capsys):
    """The viewer is already on screen when the panels are built. A panel
    that raised unwound out of openPyramid before napari.run(), so the
    window appeared and the process exited -- which reads as napari
    opening briefly and closing, with the reason lost."""
    # addAllPanels refuses to build anything without a Qt binding, and CI
    # installs none. What is under test here is the orchestration, not Qt.
    monkeypatch.setattr(controls, "_importQtWidgets", lambda: None)
    genes = _Recorder()
    monkeypatch.setattr(controls, "addDisplayPanel", _Recorder(boom=True))
    monkeypatch.setattr(controls, "addCellTypePanel", _Recorder())
    monkeypatch.setattr(controls, "addGenePanel", genes)
    monkeypatch.setattr(controls, "addRotationPanel", _Recorder())

    made = controls.addAllPanels(object(), object(), object(), object(), True)

    assert made["display"] is None
    # The panels after the failing one must still be built.
    assert genes.calls, "a failing panel stopped the ones after it"
    err = capsys.readouterr().err
    assert "display" in err and "no such file" in err


def test_no_qt_binding_costs_the_panels_and_not_the_picture(monkeypatch, capsys):
    """A headless-ish install has no Qt binding, and CI is one of them.

    addAllPanels must then build nothing and say so, rather than raising
    into openPyramid after the viewer is already on screen. The message
    names what still works, because the image and --genes do.
    """

    def _no_qt():
        raise ImportError("No module named 'qtpy.QtWidgets'")

    monkeypatch.setattr(controls, "_importQtWidgets", _no_qt)
    built = _Recorder()
    monkeypatch.setattr(controls, "addDisplayPanel", built)
    monkeypatch.setattr(controls, "addGenePanel", built)
    monkeypatch.setattr(controls, "addRotationPanel", _Recorder())

    made = controls.addAllPanels(object(), object(), object(), object(), True)

    assert made == {}
    assert not built.calls, "no panel should be attempted without a binding"
    err = capsys.readouterr().err
    assert "control panels unavailable" in err
    assert "image is unaffected" in err


def test_the_rotation_panel_gets_all_three_layers(monkeypatch):
    """Rotation turns the section, the centroids and the outlines
    TOGETHER, so it has to be handed all three. Handing it fewer would
    leave the cells behind when the image turned -- a wrong picture that
    still looks like a picture."""
    monkeypatch.setattr(controls, "_importQtWidgets", lambda: None)
    rotation = _Recorder()
    monkeypatch.setattr(controls, "addDisplayPanel", _Recorder())
    monkeypatch.setattr(controls, "addCellTypePanel", _Recorder())
    monkeypatch.setattr(controls, "addGenePanel", _Recorder())
    monkeypatch.setattr(controls, "addRotationPanel", rotation)

    image, points, shapes = object(), object(), object()
    controls.addAllPanels(
        object(),
        object(),
        object(),
        image,
        True,
        cells_doc=object(),
        points_layer=points,
        shapes_layer=shapes,
    )
    assert rotation.calls, "the rotation panel was never built"
    args, _kwargs = rotation.calls[0]
    assert set(map(id, args[1])) == {id(image), id(shapes), id(points)}


def test_a_session_with_no_cells_still_gets_rotation(monkeypatch):
    """Outlines and centroids are optional. The panel takes None for the
    ones that are absent rather than being skipped, because the image
    alone is still worth being able to turn."""
    monkeypatch.setattr(controls, "_importQtWidgets", lambda: None)
    rotation = _Recorder()
    monkeypatch.setattr(controls, "addDisplayPanel", _Recorder())
    monkeypatch.setattr(controls, "addCellTypePanel", _Recorder())
    monkeypatch.setattr(controls, "addGenePanel", _Recorder())
    monkeypatch.setattr(controls, "addRotationPanel", rotation)

    made = controls.addAllPanels(object(), object(), object(), object(), True)
    assert made["rotation"] is not None
    args, _kwargs = rotation.calls[0]
    assert args[1][1] is None and args[1][2] is None


def test_the_cloud_panel_is_only_offered_when_there_is_a_token_to_expire(monkeypatch):
    """A login control on a window that needs no login is clutter, and it
    implies the picture might be waiting on something. A local pyramid
    has no cloud token in its environment; a cloud one does."""
    monkeypatch.setattr(controls, "_importQtWidgets", lambda: None)
    for name in ("addDisplayPanel", "addCellTypePanel", "addGenePanel", "addRotationPanel"):
        monkeypatch.setattr(controls, name, _Recorder())
    cloud = _Recorder()
    monkeypatch.setattr(controls, "addCloudPanel", cloud)

    monkeypatch.delenv("NDI_CLOUD_TOKEN", raising=False)
    made = controls.addAllPanels(object(), object(), object(), object(), True)
    assert "cloud" not in made
    assert not cloud.calls

    monkeypatch.setenv("NDI_CLOUD_TOKEN", "anything")
    made = controls.addAllPanels(object(), object(), object(), object(), True)
    assert cloud.calls, "a cloud session was offered no way to sign back in"


def test_a_failing_cloud_panel_costs_only_itself(monkeypatch, capsys):
    """It is the last panel and the least essential one -- a keyring that
    will not open must not cost the section."""
    monkeypatch.setattr(controls, "_importQtWidgets", lambda: None)
    for name in ("addDisplayPanel", "addCellTypePanel", "addGenePanel", "addRotationPanel"):
        monkeypatch.setattr(controls, name, _Recorder())
    monkeypatch.setattr(controls, "addCloudPanel", _Recorder(boom=True))
    monkeypatch.setenv("NDI_CLOUD_TOKEN", "anything")

    made = controls.addAllPanels(object(), object(), object(), object(), True)
    assert made["cloud"] is None
    assert made["genes"] is not None
    assert "cloud" in capsys.readouterr().err
