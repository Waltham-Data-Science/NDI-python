"""Tests for makeCellTypeLabels.

Mirrors the MATLAB tests. The assertions concentrate on what goes wrong
quietly: a labeling shifted against its cells, an unlabeled cell counted
as a category, and an unsupervised clustering recorded as if it were a
cell type call.
"""

from __future__ import annotations

import pytest

from ndi.fun.doc_gene import makeCells, makeCellTypeLabels, makeGeneList, makePyramid
from ndi.session.dir import ndi_session_dir


@pytest.fixture
def cells(tmp_path):
    d = tmp_path / "labels"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("labels", str(d))
    sub = S.newdocument("subject", **{"subject.local_identifier": "labels@vhlab"})
    S.database_add(sub)
    gl = makeGeneList(S, ["E1", "E2"], ["a", "b"])
    pyr, _ = makePyramid(
        S,
        [1000, 1005],
        [2000, 2003],
        [0, 1],
        [2, 3],
        gl,
        subjectID=sub.id,
        binSizes=[1],
        grid=1,
    )
    cells_doc = makeCells(
        S,
        ["c0", "c1", "c2", "c3"],
        [1000, 1002, 1004, 1006],
        [2000, 2001, 2002, 2003],
        pyr,
    )
    return S, cells_doc


def _props(doc):
    return doc.document_properties["cellTypeLabels"]


def test_counts_are_computed_not_supplied(cells):
    S, cells_doc = cells
    doc = makeCellTypeLabels(S, ["Pvalb", "L2/3 IT", "Pvalb", ""], cells_doc, isUnsupervised=False)
    p = _props(doc)
    assert p["n_cells"] == 4
    # Two distinct categories; the empty string is UNLABELED, not a third.
    assert p["n_categories"] == 2
    assert p["n_unlabeled"] == 1


def test_unlabeled_is_a_state_not_an_error(cells):
    """A labeling covering a third of the cells is legitimate."""
    S, cells_doc = cells
    doc = makeCellTypeLabels(S, ["", "", "Astro", ""], cells_doc)
    p = _props(doc)
    assert p["n_unlabeled"] == 3
    assert p["n_categories"] == 1


def test_is_unsupervised_defaults_to_the_safer_assumption(cells):
    """Default is "do not read biology into it"."""
    S, cells_doc = cells
    doc = makeCellTypeLabels(S, ["0", "1", "0", "2"], cells_doc)
    assert _props(doc)["is_unsupervised"] == 1


def test_a_cell_type_call_must_say_so(cells):
    S, cells_doc = cells
    doc = makeCellTypeLabels(
        S,
        ["Pvalb", "Astro", "Pvalb", "Astro"],
        cells_doc,
        isUnsupervised=False,
        labelName="subclass_nn_column",
        taxonomyLevel="subclass",
        assignmentMethod="nearest neighbour from dissociated atlas",
    )
    p = _props(doc)
    assert p["is_unsupervised"] == 0
    assert p["label_name"] == "subclass_nn_column"
    assert p["taxonomy_level"] == "subclass"
    assert "nearest neighbour" in p["assignment_method"]


def test_length_mismatch_is_refused(cells):
    """A shifted labeling gives every cell its neighbour's type, silently."""
    S, cells_doc = cells
    with pytest.raises(ValueError, match="ROW ORDER"):
        makeCellTypeLabels(S, ["a", "b", "c"], cells_doc)


def test_empty_labels_refused(cells):
    S, cells_doc = cells
    with pytest.raises(ValueError, match="empty"):
        makeCellTypeLabels(S, [], cells_doc)


def test_depends_on_the_cells_document(cells):
    S, cells_doc = cells
    doc = makeCellTypeLabels(S, ["a", "b", "a", "b"], cells_doc)
    assert doc.dependency_value("cells_document_id") == cells_doc.id


def test_labels_tsv_is_attached_to_the_document(cells):
    """The file is ingested, so the check is that it reached the document."""
    S, cells_doc = cells
    doc = makeCellTypeLabels(S, ["a", "b", "", "b"], cells_doc)
    files = doc.document_properties.get("files", {}).get("file_list", [])
    assert "labels.tsv" in files


def test_several_labelings_coexist_on_one_segmentation(cells):
    """The reason labels are their own document."""
    S, cells_doc = cells
    atlas = makeCellTypeLabels(
        S,
        ["Pvalb", "Astro", "Pvalb", "Astro"],
        cells_doc,
        isUnsupervised=False,
        labelName="subclass_nn_column",
    )
    leiden = makeCellTypeLabels(
        S,
        ["0", "1", "0", "2"],
        cells_doc,
        labelName="leiden_res1.0",
    )
    assert atlas.id != leiden.id
    assert atlas.dependency_value("cells_document_id") == cells_doc.id
    assert leiden.dependency_value("cells_document_id") == cells_doc.id
    assert _props(atlas)["is_unsupervised"] == 0
    assert _props(leiden)["is_unsupervised"] == 1


class _LFH:
    def __init__(self, text):
        self._t = text.encode("utf-8")

    def read(self):
        return self._t


class _LDoc:
    id = "labels-doc"

    def __init__(self, n_cells=4, name="leiden", unsupervised=1):
        self.document_properties = {
            "cellTypeLabels": {
                "label": "",
                "label_name": name,
                "taxonomy_level": "",
                "n_cells": n_cells,
                "n_categories": 2,
                "n_unlabeled": 1,
                "assignment_method": "",
                "is_unsupervised": unsupervised,
            }
        }


class _LSession:
    def __init__(self, text):
        self.text = text

    def database_openbinarydoc(self, doc, name):
        assert name == "labels.tsv"
        return _LFH(self.text)

    def database_closebinarydoc(self, fh):
        pass


def test_labels_are_placed_by_cell_index_not_file_order():
    """The rows arrive shuffled; every label must still land on its cell."""
    from ndi.fun.doc_gene import readCellTypeLabels

    text = "cell_index\tlabel\n2\tB\n0\tA\n3\t\n1\tA\n"
    labels, info = readCellTypeLabels(_LSession(text), _LDoc())
    assert labels == ["A", "A", "B", ""]
    assert info["categories"] == ["A", "B"]
    assert info["nUnlabeled"] == 1
    assert info["isUnsupervised"] is True
    assert info["labelName"] == "leiden"


def test_an_unlabelled_cell_is_empty_rather_than_dropped():
    """Dropping it would shift every later cell onto the wrong label."""
    from ndi.fun.doc_gene import readCellTypeLabels

    text = "cell_index\tlabel\n0\tA\n1\t\n2\tB\n3\tB\n"
    labels, _ = readCellTypeLabels(_LSession(text), _LDoc())
    assert len(labels) == 4
    assert labels[1] == ""


def test_a_labels_file_with_the_wrong_header_is_refused():
    from ndi.fun.doc_gene import readCellTypeLabels

    text = "row\tvalue\n0\tA\n"
    with pytest.raises(ValueError, match="expected cell_index and label"):
        readCellTypeLabels(_LSession(text), _LDoc())
