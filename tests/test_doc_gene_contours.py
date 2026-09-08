"""readContours: contours.bin placed in the frame the pyramid uses.

readContourFile already parsed these bytes; readContours is the document
layer over it -- finding the file and applying contour_reference. So the
tests here are about THAT, and the parsing errors they trigger are
readContourFile's own.

The case worth testing hardest is ``contour_reference``. Vertices are
usually stored RELATIVE to their cell's centroid -- that is what makes
them fit in int16 -- and a reader that ignores that draws every outline
in a small cluster near the origin. It produces a picture, and the
picture is of nothing. So the two references are asserted separately AND
asserted to differ, since a reader that silently treated everything as
absolute would pass a test that only checked one of them.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from ndi.fun import doc_gene


def _binary(polys, offset_dtype="<u4", vertex_dtype="<i2"):
    """A contours.bin, laid out as writeContourFile documents it."""
    offs, vx, vy = [0], [], []
    for p in polys:
        vx += list(p[:, 0])
        vy += list(p[:, 1])
        offs.append(len(vx))
    raw = struct.pack("<II", len(polys), len(vx))
    raw += np.array(offs, dtype=offset_dtype).tobytes()
    raw += np.array(vx, dtype=vertex_dtype).tobytes()
    raw += np.array(vy, dtype=vertex_dtype).tobytes()
    return raw


class _FH:
    def __init__(self, b):
        self._b = b

    def read(self):
        return self._b


class _Doc:
    id = "cells-doc"

    def __init__(self, reference="centroid", per_cell=0, n_cells=3, present=1):
        self.document_properties = {
            "spatialGeneExpressionCells": {
                "contours_present": present,
                "contour_reference": reference,
                "data_type_vertex": "int16",
                "data_type_offset": "uint32",
                "n_vertices_per_cell": per_cell,
                "n_cells": n_cells,
                "coordinate_units": "bin",
                "segmentation_method": "test",
            }
        }


class _Session:
    def __init__(self, raw):
        self.raw = raw

    def database_openbinarydoc(self, doc, name):
        assert name == "contours.bin"
        return _FH(self.raw)

    def database_closebinarydoc(self, fh):
        pass


SQUARE = np.array([[-2, -2], [2, -2], [2, 2], [-2, 2]])
EMPTY = np.zeros((0, 2))
TRIANGLE = np.array([[0, -3], [3, 3], [-3, 3]])
CENTROIDS = {
    "cell_index": [0, 1, 2],
    "cell_id": ["a", "b", "c"],
    "x": [100.0, 200.0, 300.0],
    "y": [10.0, 20.0, 30.0],
}


@pytest.fixture()
def centroids(monkeypatch):
    monkeypatch.setattr(doc_gene, "readCells", lambda s, d: (CENTROIDS, {}))


def test_centroid_referenced_vertices_land_on_their_cell(centroids):
    raw = _binary([SQUARE, EMPTY, TRIANGLE])
    polys, info = doc_gene.readContours(_Session(raw), _Doc("centroid"))

    assert info["nCells"] == 3
    assert info["nVerticesTotal"] == 7
    # cell 0's centroid is (100, 10), so its square is centred there
    np.testing.assert_allclose(polys[0], [[98, 8], [102, 8], [102, 12], [98, 12]])
    np.testing.assert_allclose(polys[2][0], [300, 27])


def test_absolute_referenced_vertices_are_untouched(centroids):
    raw = _binary([SQUARE, EMPTY, TRIANGLE])
    polys, _ = doc_gene.readContours(_Session(raw), _Doc("absolute"))
    np.testing.assert_allclose(polys[0], SQUARE)


def test_the_two_references_do_not_agree(centroids):
    """The point of the field. If these matched it would be ignored."""
    raw = _binary([SQUARE, EMPTY, TRIANGLE])
    rel, _ = doc_gene.readContours(_Session(raw), _Doc("centroid"))
    absolute, _ = doc_gene.readContours(_Session(raw), _Doc("absolute"))
    assert not np.allclose(rel[0], absolute[0])


def test_a_cell_with_no_boundary_comes_back_empty_not_missing(centroids):
    """Dropping it would shift every later polygon onto the wrong cell."""
    raw = _binary([SQUARE, EMPTY, TRIANGLE])
    polys, info = doc_gene.readContours(_Session(raw), _Doc("centroid"))
    assert len(polys) == 3
    assert polys[1].shape == (0, 2)
    assert info["nEmpty"] == 1


def test_fixed_width_files_are_read_too(centroids):
    """No offset array; vertex j of cell i sits at i*K+j."""
    quads = [SQUARE, SQUARE + 1, SQUARE + 2]
    raw = struct.pack("<II", 3, 12)
    raw += np.array([p[:, 0] for p in quads], dtype="<i2").ravel().tobytes()
    raw += np.array([p[:, 1] for p in quads], dtype="<i2").ravel().tobytes()
    polys, info = doc_gene.readContours(_Session(raw), _Doc("absolute", per_cell=4))
    assert info["nVerticesPerCell"] == 4
    np.testing.assert_allclose(polys[1], SQUARE + 1)


def test_a_fixed_width_file_that_contradicts_itself_is_refused(centroids):
    raw = struct.pack("<II", 3, 99)
    polys_doc = _Doc("absolute", per_cell=4)
    with pytest.raises(ValueError, match="implying 12 vertices"):
        doc_gene.readContours(_Session(raw), polys_doc)


def test_a_truncated_file_is_refused_rather_than_read_short(centroids):
    """The message comes from readContourFile, which does the parsing."""
    raw = _binary([SQUARE, EMPTY, TRIANGLE])[:-6]
    with pytest.raises(ValueError, match="but only .* remain"):
        doc_gene.readContours(_Session(raw), _Doc("centroid"))


def test_a_document_without_contours_says_so(centroids):
    raw = _binary([SQUARE])
    with pytest.raises(ValueError, match="contours_present"):
        doc_gene.readContours(_Session(raw), _Doc("centroid", present=0))


def test_centroid_count_mismatch_is_refused(monkeypatch):
    """Centroid-relative vertices cannot be placed without one each."""
    monkeypatch.setattr(doc_gene, "readCells", lambda s, d: ({"x": [1.0], "y": [2.0]}, {}))
    raw = _binary([SQUARE, EMPTY, TRIANGLE])
    with pytest.raises(ValueError, match="cannot be placed"):
        doc_gene.readContours(_Session(raw), _Doc("centroid"))


def test_an_unknown_reference_is_refused(centroids):
    raw = _binary([SQUARE])
    with pytest.raises(ValueError, match="expected 'centroid' or 'absolute'"):
        doc_gene.readContours(_Session(raw), _Doc("sideways", n_cells=1))
