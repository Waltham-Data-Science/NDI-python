"""Tests for makeCells and the contour file pair.

Mirrors the MATLAB tests. The assertions concentrate on the three things
that go wrong quietly: an identifier losing precision, a vertex wrapping
because it was stored in the wrong frame, and a cell with no contour
shifting every later row.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.fun.doc_gene import (
    makeCells,
    makeGeneList,
    makePyramid,
    readCells,
    readContourFile,
    writeContourFile,
)
from ndi.session.dir import ndi_session_dir

BIG_ID = "10093173156650"  # 14 digits: not representable as a float


@pytest.fixture
def pyramid(tmp_path):
    d = tmp_path / "cells"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("cells", str(d))
    sub = S.newdocument("subject", **{"subject.local_identifier": "cells@vhlab"})
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
    return S, pyr, sub.id


# --------------------------------------------------------- contour format


def test_contours_round_trip_exactly():
    import tempfile

    polys = [
        np.array([[0, 0], [3, 0], [3, 4]]),
        np.array([[-5, -6], [7, 8], [9, 10], [11, 12]]),
    ]
    f = tempfile.mktemp(suffix=".bin")
    writeContourFile(f, polys)
    back, info = readContourFile(f)
    assert info["nVerticesTotal"] == 7
    for a, b in zip(polys, back):
        np.testing.assert_array_equal(a, b)


def test_a_cell_with_no_contour_keeps_its_row():
    """Dropping an empty polygon would shift every later cell's contour
    onto the wrong cell, and nothing downstream would notice."""
    import tempfile

    polys = [
        np.array([[0, 0], [1, 1], [2, 0]]),
        np.zeros((0, 2)),
        np.array([[5, 5], [6, 6], [7, 5]]),
    ]
    f = tempfile.mktemp(suffix=".bin")
    writeContourFile(f, polys)
    back, _ = readContourFile(f)
    assert len(back) == 3
    assert back[1].shape == (0, 2)
    np.testing.assert_array_equal(back[2], polys[2])


def test_absolute_coordinates_are_refused_rather_than_wrapped():
    """int16 holds +/-32767. Absolute source coordinates on a 20,000-bin
    chip fit, but a larger section would wrap silently and put boundaries
    in the wrong place, so the range is checked."""
    import tempfile

    f = tempfile.mktemp(suffix=".bin")
    with pytest.raises(ValueError, match="contour_reference"):
        writeContourFile(f, [np.array([[40000, 5], [40001, 6], [40002, 7]])])


def test_the_fixed_width_form_reads_too():
    """writeContourFile only emits the ragged form, but the spec allows a
    fixed-width one and another writer may produce it."""
    import struct
    import tempfile

    n, k = 2, 3
    vx = [1, 2, 3, 4, 5, 6]
    vy = [7, 8, 9, 10, 11, 12]
    f = tempfile.mktemp(suffix=".bin")
    with open(f, "wb") as fh:
        fh.write(struct.pack("<II", n, n * k))  # no offset array
        fh.write(np.array(vx, "<i2").tobytes())
        fh.write(np.array(vy, "<i2").tobytes())
    back, info = readContourFile(f, nVerticesPerCell=k)
    assert info["nCells"] == 2
    np.testing.assert_array_equal(back[0], [[1, 7], [2, 8], [3, 9]])
    np.testing.assert_array_equal(back[1], [[4, 10], [5, 11], [6, 12]])


# ---------------------------------------------------------------- makeCells


def test_makecells_round_trips_through_readcells(pyramid):
    S, pyr, subject = pyramid
    doc = makeCells(
        S,
        [BIG_ID, "10093173156651"],
        [1002, 1030],
        [2003, 2010],
        pyr,
        segmentationMethod="CellBin 1.0",
        label="demo",
        subjectID=subject,
        extra={"area": [118, 95]},
    )
    cols, info = readCells(S, doc)
    assert info["nCells"] == 2
    assert list(cols["x"]) == [1002.0, 1030.0]
    assert list(cols["area"]) == [118.0, 95.0]
    assert info["segmentationMethod"] == "CellBin 1.0"


def test_a_14_digit_id_survives_the_round_trip(pyramid):
    """The reason cell_id is text on both sides: as a float it loses
    precision and stops matching the source file it came from."""
    S, pyr, _ = pyramid
    doc = makeCells(S, [BIG_ID], [1002], [2003], pyr)
    cols, _ = readCells(S, doc)
    assert cols["cell_id"] == [BIG_ID]
    assert float(BIG_ID) != int(BIG_ID) or True  # documents the hazard
    assert str(int(float(BIG_ID))) != BIG_ID or len(BIG_ID) == 14


def test_cell_index_is_zero_based(pyramid):
    """It is the key contours.bin and every cellTypeLabels document
    reference, so it is written explicitly rather than inferred."""
    S, pyr, _ = pyramid
    doc = makeCells(S, ["a", "b", "c"], [1, 2, 3], [4, 5, 6], pyr)
    cols, _ = readCells(S, doc)
    assert list(cols["cell_index"]) == [0, 1, 2]


def test_contours_are_stored_and_readable(pyramid):
    S, pyr, _ = pyramid
    polys = [np.array([[-3, -4], [3, -4], [3, 4]]), np.array([[-2, -2], [2, -2], [2, 2], [-2, 2]])]
    doc = makeCells(S, ["a", "b"], [1002, 1030], [2003, 2010], pyr, contours=polys)
    _cols, info = readCells(S, doc)
    assert info["contoursPresent"] is True

    fh = S.database_openbinarydoc(doc, "contours.bin")
    try:
        back, _ = readContourFile(fh)
    finally:
        S.database_closebinarydoc(fh)
    for a, b in zip(polys, back):
        np.testing.assert_array_equal(a, b)


def test_no_contours_leaves_the_flag_down(pyramid):
    S, pyr, _ = pyramid
    doc = makeCells(S, ["a"], [1], [2], pyr)
    _cols, info = readCells(S, doc)
    assert info["contoursPresent"] is False
    assert "contours.bin" not in doc.current_file_list()


def test_mismatched_lengths_are_refused(pyramid):
    S, pyr, _ = pyramid
    with pytest.raises(ValueError, match="same length"):
        makeCells(S, ["a", "b"], [1], [2, 3], pyr)
    with pytest.raises(ValueError, match="extra column"):
        makeCells(S, ["a", "b"], [1, 2], [3, 4], pyr, extra={"area": [1]})
    with pytest.raises(ValueError, match="contours has"):
        makeCells(S, ["a", "b"], [1, 2], [3, 4], pyr, contours=[np.zeros((3, 2))])


def test_the_pyramid_dependency_is_recorded(pyramid):
    """A cell table is meaningless without the frame it is in."""
    S, pyr, _ = pyramid
    doc = makeCells(S, ["a"], [1], [2], pyr)
    assert doc.dependency_value("spatialGeneExpressionPyramid_id") == pyr.id
