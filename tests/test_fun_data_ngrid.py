"""``ndi.fun.data`` ngrid helpers against ``+ndi/+fun/+data/``.

The ngrid format is the one place these two languages hand each other raw
bytes, so the parts that decide byte layout are worth pinning explicitly:
little-endian, column-major, and the ``data_type`` string that says how to
read the file back.

WHAT WAS WRONG. ``mat2ngrid`` recorded a boolean array's ``data_type`` as
``"logical"``. MATLAB's ends with
``if islogical(x), ngrid.data_type = 'ubit1'; end``, so it always records
``ubit1``. The port reverse-mapped the dtype by scanning ``_TYPE_MAP``, and
both keys map to the same dtype -- so which name came out was decided by
dict order, and the two languages disagreed on the recorded type of every
boolean ngrid.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.fun.data import mat2ngrid, readngrid, writengrid


class TestMat2NgridDataType:
    """MATLAB counterpart: ``+ndi/+fun/+data/mat2ngrid.m``."""

    def test_a_boolean_array_is_recorded_as_ubit1(self):
        """The regression. MATLAB names logical data ubit1, unconditionally."""
        assert mat2ngrid(np.array([[True, False], [False, True]]))["data_type"] == "ubit1"

    @pytest.mark.parametrize(
        "dtype, expected",
        [
            ("<f8", "double"),
            ("<f4", "single"),
            ("<i1", "int8"),
            ("<i2", "int16"),
            ("<i4", "int32"),
            ("<i8", "int64"),
            ("<u1", "uint8"),
            ("<u2", "uint16"),
            ("<u4", "uint32"),
            ("<u8", "uint64"),
        ],
    )
    def test_numeric_types_keep_matlabs_class_names(self, dtype, expected):
        """MATLAB uses ``class(x)``, so the MATLAB spelling wins over the
        NumPy alias where ``_TYPE_MAP`` carries both."""
        assert mat2ngrid(np.zeros((2, 2), dtype=dtype))["data_type"] == expected

    def test_data_size_is_bytes_per_element(self):
        """MATLAB computes ``props.bytes/numel(x)``."""
        assert mat2ngrid(np.zeros((3, 4), dtype="<f8"))["data_size"] == 8
        assert mat2ngrid(np.zeros((3, 4), dtype="<i2"))["data_size"] == 2

    def test_data_dim_is_the_shape(self):
        assert mat2ngrid(np.zeros((3, 4, 5)))["data_dim"] == [3, 4, 5]


class TestNgridByteLayout:
    """MATLAB counterparts: ``readngrid.m`` / ``writengrid.m``.

    Both force ``ieee-le``, and ``fread``/``fwrite`` walk an array in
    column-major order. A port that used NumPy's defaults would round-trip
    with itself perfectly and be unreadable by MATLAB, which is the failure
    mode worth a test rather than a comment.
    """

    def test_the_file_is_written_column_major(self):
        """The on-disk order is MATLAB's, not NumPy's."""
        import tempfile
        from pathlib import Path

        data = np.array([[1.0, 2.0], [3.0, 4.0]])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "g.bin"
            writengrid(data, f, "double")
            flat = np.fromfile(str(f), dtype="<f8")
        # Column-major: down the first column, then the second.
        np.testing.assert_array_equal(flat, [1.0, 3.0, 2.0, 4.0])

    def test_a_multidimensional_grid_round_trips(self, tmp_path):
        data = np.arange(24, dtype="<f8").reshape((2, 3, 4))
        f = tmp_path / "g.bin"
        writengrid(data, f, "double")
        np.testing.assert_array_equal(readngrid(f, (2, 3, 4), "double"), data)

    def test_the_file_is_little_endian_whatever_the_host(self, tmp_path):
        """MATLAB opens with 'ieee-le' explicitly; ``_TYPE_MAP`` pins ``<``
        on every numeric type so the bytes do not depend on the machine."""
        f = tmp_path / "g.bin"
        writengrid(np.array([1], dtype="<i2"), f, "int16")
        assert f.read_bytes() == b"\x01\x00"

    def test_a_size_mismatch_is_refused(self, tmp_path):
        """MATLAB warns and returns what it read; this refuses. The
        divergence is recorded on the bridge entry."""
        f = tmp_path / "g.bin"
        writengrid(np.array([1.0, 2.0]), f, "double")
        with pytest.raises(ValueError, match="mismatch"):
            readngrid(f, (5,), "double")

    def test_an_unknown_type_is_refused(self, tmp_path):
        """MATLAB warns and lets fread try; this refuses up front."""
        with pytest.raises(ValueError, match="Unknown data type"):
            writengrid(np.array([1]), tmp_path / "g.bin", "complex128")
