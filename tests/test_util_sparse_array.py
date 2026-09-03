"""The NDI sparse array format, byte for byte.

MATLAB counterparts: ``+ndi/+util/writeSparse.m``, ``+ndi/+util/readSparse.m``

The point of this format is that both toolboxes read and write it, so a
test that only round-trips through Python would pass while the files were
useless to MATLAB. The tests below therefore assert the BYTES against the
layout MATLAB's ``fwrite`` sequence produces, and read a buffer assembled
the way MATLAB writes one.

MATLAB's ``writeSparse`` emits, in order: the 8-byte magic, uint32
version, uint32 ndims, ndims x uint64 shape, uint64 nnz, then ndims blocks
of nnz x uint64 subscripts (dimension-major, 0-based), then nnz x float64
values -- all little-endian.

Two things a reimplementation gets wrong and this catches:

**Entry order.** MATLAB's one-argument form takes its entries from
``find(A)``, which walks column-major. A writer that emits scipy's coo
order instead produces a file with the same VALUES in a different order --
still readable, no longer byte-identical, so any check that compares the
two toolboxes' output fails for a reason nobody can see.

**Subscript base.** The file is 0-based. MATLAB converts to 1-based on
read and back on write; Python does not convert at all. Get that backwards
in one language and every subscript is off by one.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest
from scipy.sparse import coo_matrix

from ndi.util import readSparse, writeSparse
from ndi.util.sparse_array import FORMAT_VERSION, MAGIC


def matlab_bytes(shape, subs_0based, vals):
    """The exact byte sequence MATLAB's writeSparse fwrite calls produce."""
    out = MAGIC + struct.pack("<II", FORMAT_VERSION, len(shape))
    out += np.asarray(shape, dtype="<u8").tobytes()
    out += np.asarray([len(vals)], dtype="<u8").tobytes()
    subs = np.asarray(subs_0based, dtype="<u8").reshape(len(vals), len(shape))
    for d in range(len(shape)):  # dimension-major
        out += np.ascontiguousarray(subs[:, d]).tobytes()
    out += np.asarray(vals, dtype="<f8").tobytes()
    return out


class TestTheBytesMatchMatlab:
    def test_the_example_from_matlabs_own_docstring(self, tmp_path):
        """``A = sparse([1 3 3],[1 2 4],[10 20 30.5],3,4)`` -- MATLAB's
        1-based subscripts, which are 0-based here and on disk."""
        a = coo_matrix(([10, 20, 30.5], ([0, 2, 2], [0, 1, 3])), shape=(3, 4))
        path = tmp_path / "activity.ndisparse"
        writeSparse(path, a)

        assert path.read_bytes() == matlab_bytes((3, 4), [[0, 0], [2, 1], [2, 3]], [10, 20, 30.5])

    def test_the_header_is_where_matlab_puts_it(self, tmp_path):
        path = tmp_path / "x.ndisparse"
        writeSparse(path, coo_matrix(([1.0], ([0], [0])), shape=(2, 2)))
        raw = path.read_bytes()

        assert raw[:8] == b"NDISPARS"
        assert struct.unpack_from("<I", raw, 8)[0] == 1  # version
        assert struct.unpack_from("<I", raw, 12)[0] == 2  # ndims
        assert np.frombuffer(raw, "<u8", count=2, offset=16).tolist() == [2, 2]

    def test_entries_are_column_major_like_matlabs_find(self, tmp_path):
        """scipy's coo order is not MATLAB's. Handing the entries over
        row-first would give the same matrix and a different file."""
        a = coo_matrix(
            ([1.0, 2.0, 3.0], ([0, 1, 0], [1, 0, 0])), shape=(2, 2)
        )  # deliberately unsorted
        path = tmp_path / "order.ndisparse"
        writeSparse(path, a)

        subs, vals, _ = readSparse(path, as_coordinates=True)
        # column-major: (0,0)=3, (1,0)=2, (0,1)=1
        assert subs.tolist() == [[0, 0], [1, 0], [0, 1]]
        assert vals.tolist() == [3.0, 2.0, 1.0]

    def test_subscripts_are_zero_based_on_disk(self, tmp_path):
        """The subscripts of an entry at Python [0,0] are 0 on disk. MATLAB
        writes the same zeros from its 1-based (1,1).

        Layout for ndims=2, nnz=1: magic 0-7, version 8-11, ndims 12-15,
        shape 16-31, nnz 32-39, then the subscript blocks from 40.
        """
        path = tmp_path / "base.ndisparse"
        writeSparse(path, coo_matrix(([7.0], ([0], [0])), shape=(1, 1)))
        raw = path.read_bytes()

        assert np.frombuffer(raw, "<u8", count=1, offset=32).tolist() == [1]  # nnz
        assert np.frombuffer(raw, "<u8", count=2, offset=40).tolist() == [0, 0]
        assert np.frombuffer(raw, "<f8", count=1, offset=56).tolist() == [7.0]


class TestReadingWhatMatlabWrote:
    def test_a_matlab_assembled_buffer_reads_back(self, tmp_path):
        """Not our own output: bytes built to MATLAB's spec directly."""
        path = tmp_path / "from_matlab.ndisparse"
        path.write_bytes(matlab_bytes((3, 4), [[0, 0], [2, 1], [2, 3]], [10, 20, 30.5]))

        m = readSparse(path)
        assert m.shape == (3, 4)
        assert m.toarray()[0, 0] == 10
        assert m.toarray()[2, 1] == 20
        assert m.toarray()[2, 3] == 30.5

    def test_a_bad_magic_is_refused(self, tmp_path):
        path = tmp_path / "not_sparse.ndisparse"
        path.write_bytes(b"NOTSPARS" + bytes(64))
        with pytest.raises(ValueError, match="not an NDI sparse file"):
            readSparse(path)

    def test_an_unknown_version_is_refused(self, tmp_path):
        path = tmp_path / "v9.ndisparse"
        raw = bytearray(matlab_bytes((1, 1), [[0, 0]], [1.0]))
        struct.pack_into("<I", raw, 8, 9)
        path.write_bytes(bytes(raw))
        with pytest.raises(ValueError, match="version 9"):
            readSparse(path)

    def test_a_truncated_file_is_refused_rather_than_silently_short(self, tmp_path):
        """Reading past the end would otherwise yield fewer entries than the
        header promises -- a quietly wrong matrix."""
        path = tmp_path / "short.ndisparse"
        full = matlab_bytes((3, 4), [[0, 0], [2, 1], [2, 3]], [10, 20, 30.5])
        path.write_bytes(full[:-9])
        with pytest.raises(OSError, match="ends early"):
            readSparse(path)


class TestRoundTrip:
    @pytest.mark.parametrize(
        "dense",
        [
            np.array([[0.0, 0.0], [0.0, 0.0]]),
            np.array([[1.0, 0.0], [0.0, 2.0]]),
            np.array([[0.0, -3.5, 0.0], [4.0, 0.0, 1e10]]),
        ],
    )
    def test_a_matrix_survives(self, tmp_path, dense):
        path = tmp_path / "rt.ndisparse"
        writeSparse(path, coo_matrix(dense))
        assert np.array_equal(readSparse(path).toarray(), dense)

    def test_a_dense_array_is_accepted_too(self, tmp_path):
        dense = np.array([[0.0, 5.0], [0.0, 0.0]])
        path = tmp_path / "dense.ndisparse"
        writeSparse(path, dense)
        assert np.array_equal(readSparse(path).toarray(), dense)

    def test_an_empty_matrix_keeps_its_shape(self, tmp_path):
        path = tmp_path / "empty.ndisparse"
        writeSparse(path, coo_matrix((4, 7)))
        m = readSparse(path)
        assert m.shape == (4, 7)
        assert m.nnz == 0

    def test_explicitly_stored_zeros_are_not_written(self, tmp_path):
        """scipy can carry a stored zero; MATLAB's find never sees one, so
        writing it would make the two files differ for equal matrices."""
        a = coo_matrix(([0.0, 2.0], ([0, 1], [0, 1])), shape=(2, 2))
        path = tmp_path / "storedzero.ndisparse"
        writeSparse(path, a)
        _, vals, _ = readSparse(path, as_coordinates=True)
        assert vals.tolist() == [2.0]


class TestNDimensional:
    """MATLAB has no native N-D sparse type, so it returns a struct; Python
    mirrors that with a dict rather than inventing a container."""

    def test_a_three_d_array_round_trips(self, tmp_path):
        subs = np.array([[0, 0, 0], [1, 2, 3]])
        vals = np.array([1.5, -2.5])
        path = tmp_path / "nd.ndisparse"
        writeSparse(path, subs, vals, (2, 3, 4))

        out = readSparse(path)
        assert set(out) == {"subs", "vals", "size"}
        assert out["size"] == (2, 3, 4)
        assert out["subs"].tolist() == subs.tolist()
        assert out["vals"].tolist() == vals.tolist()

    def test_the_coordinate_form_preserves_the_callers_order(self, tmp_path):
        """MATLAB's 4-argument form writes SUBS as given, without sorting.
        Sorting here would make the two languages disagree."""
        subs = np.array([[1, 2, 3], [0, 0, 0]])  # deliberately not sorted
        path = tmp_path / "order_nd.ndisparse"
        writeSparse(path, subs, [9.0, 8.0], (2, 3, 4))
        assert readSparse(path)["subs"].tolist() == subs.tolist()

    def test_a_one_d_array_comes_back_as_a_column(self, tmp_path):
        """MATLAB returns an m-by-1 column vector for a 1-D array."""
        path = tmp_path / "oned.ndisparse"
        writeSparse(path, np.array([[2], [0]]), [4.0, 5.0], (5,))
        m = readSparse(path)
        assert m.shape == (5, 1)
        assert m.toarray()[2, 0] == 4.0


class TestTheErrorsMirrorMatlabs:
    def test_a_three_d_dense_array_is_refused_in_the_one_argument_form(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:not2D."""
        with pytest.raises(ValueError, match="2-D array"):
            writeSparse(tmp_path / "x", np.zeros((2, 2, 2)))

    def test_a_non_numeric_array_is_refused(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:notNumeric."""
        with pytest.raises(ValueError, match="numeric or logical"):
            writeSparse(tmp_path / "x", np.array([["a", "b"], ["c", "d"]]))

    def test_a_subs_shape_mismatch_is_refused(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:subsSizeMismatch."""
        with pytest.raises(ValueError, match="must equal len\\(shape\\)"):
            writeSparse(tmp_path / "x", np.array([[0, 0]]), [1.0], (2, 3, 4))

    def test_a_vals_length_mismatch_is_refused(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:valsSizeMismatch."""
        with pytest.raises(ValueError, match="VALS has"):
            writeSparse(tmp_path / "x", np.array([[0, 0], [1, 1]]), [1.0], (2, 2))

    def test_a_negative_subscript_is_refused(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:badSubs. Its check is subs<1 because
        MATLAB is 1-based; ours is subs<0."""
        with pytest.raises(ValueError, match="non-negative integer"):
            writeSparse(tmp_path / "x", np.array([[-1, 0]]), [1.0], (2, 2))

    def test_a_subscript_past_the_shape_is_refused(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:subsOutOfBounds."""
        with pytest.raises(ValueError, match="outside the size"):
            writeSparse(tmp_path / "x", np.array([[0, 9]]), [1.0], (2, 2))

    def test_a_wrong_argument_count_is_refused(self, tmp_path):
        """MATLAB: ndi:util:writeSparse:badNargin."""
        with pytest.raises(ValueError, match="call as writeSparse"):
            writeSparse(tmp_path / "x", np.array([[0, 0]]), [1.0])


if __name__ == "__main__":
    pytest.main([__file__])
