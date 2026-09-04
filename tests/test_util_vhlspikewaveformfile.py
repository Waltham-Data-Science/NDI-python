"""Tests for ndi.util.vhlspikewaveformfile - the ``.vsw`` file format.

The point of this module is that MATLAB and Python read each other's
spike waveform storage byte-for-byte, so most of these tests inspect
the raw bytes rather than trusting the write+read round trip. The
canonical MATLAB counterparts (in ``vhlab-toolbox-matlab``) are quoted
in the module docstring; the header layout is::

    offset 0     u8 numchannels
    offset 1     i8 S0
    offset 2     i8 S1
    offset 3..82 80 bytes name (null-padded ASCII)
    offset 83    u8 ref
    offset 84..163 80 bytes comment (null-padded ASCII)
    offset 164..167 float32 samplingrate (big-endian)
    offset 168..511 zero padding

with the body being ``float32`` big-endian in Fortran order for the
``(samples_per_channel, num_channels, num_waves)`` array.
"""

from __future__ import annotations

import io
import os
import struct

import numpy as np
import pytest

from ndi.util.vhlspikewaveformfile import (
    COMMENT_LEN,
    HEADER_SIZE,
    NAME_LEN,
    VhlSpikeWaveformParameters,
    add_vhlspikewaveformfile,
    addvhlspikewaveformfile,
    new_vhlspikewaveformfile,
    newvhlspikewaveformfile,
    read_vhlspikewaveformfile,
    readvhlspikewaveformfile,
)


def _params(**overrides):
    base = {
        "numchannels": 4,
        "S0": -10,
        "S1": 20,
        "name": "my sort",
        "ref": 0,
        "comment": "test comment",
        "samplingrate": 30000.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Header byte layout -- the interoperability contract with MATLAB.
# ---------------------------------------------------------------------------


class TestHeaderByteLayout:
    def test_header_is_exactly_512_bytes(self, tmp_path):
        path = tmp_path / "h.vsw"
        new_vhlspikewaveformfile(str(path), _params())
        assert path.stat().st_size == HEADER_SIZE

    def test_field_offsets_match_matlab(self, tmp_path):
        path = tmp_path / "h.vsw"
        p = _params(
            numchannels=3, S0=-5, S1=10, name="hello", ref=7, comment="c", samplingrate=25000.0
        )
        new_vhlspikewaveformfile(str(path), p)
        header = path.read_bytes()

        assert header[0] == 3
        assert struct.unpack(">b", header[1:2])[0] == -5
        assert struct.unpack(">b", header[2:3])[0] == 10
        assert header[3 : 3 + NAME_LEN].startswith(b"hello")
        assert header[3 + NAME_LEN] == 7
        assert header[4 + NAME_LEN : 4 + NAME_LEN + COMMENT_LEN].startswith(b"c")
        assert struct.unpack(">f", header[164:168])[0] == pytest.approx(25000.0)
        assert header[168:HEADER_SIZE] == b"\x00" * (HEADER_SIZE - 168)

    def test_negative_s0_encoded_as_signed_int8(self, tmp_path):
        path = tmp_path / "h.vsw"
        new_vhlspikewaveformfile(str(path), _params(S0=-127, S1=127))
        header = path.read_bytes()
        # struct.unpack with 'b' gives signed int8, which is what MATLAB's
        # int8 field is.
        assert struct.unpack(">b", header[1:2])[0] == -127
        assert struct.unpack(">b", header[2:3])[0] == 127

    def test_samplingrate_is_big_endian_float32(self, tmp_path):
        # Little-endian bytes for 30000.0 are 46 c3 50 00 written LE ->
        # 00 50 c3 46, so big-endian must be 46 c3 50 00 verbatim.
        path = tmp_path / "h.vsw"
        new_vhlspikewaveformfile(str(path), _params(samplingrate=30000.0))
        header = path.read_bytes()
        assert header[164:168] == bytes.fromhex("46ea6000")

    def test_name_padded_with_nulls_and_truncated_at_80(self, tmp_path):
        path = tmp_path / "h.vsw"
        long_name = "a" * 200
        new_vhlspikewaveformfile(str(path), _params(name=long_name))
        header = path.read_bytes()
        name_bytes = header[3 : 3 + NAME_LEN]
        assert name_bytes == b"a" * NAME_LEN

        path2 = tmp_path / "h2.vsw"
        new_vhlspikewaveformfile(str(path2), _params(name="short"))
        h2 = path2.read_bytes()
        name_bytes2 = h2[3 : 3 + NAME_LEN]
        assert name_bytes2[:5] == b"short"
        assert name_bytes2[5:] == b"\x00" * (NAME_LEN - 5)

    def test_comment_padded_with_nulls_and_truncated_at_80(self, tmp_path):
        path = tmp_path / "h.vsw"
        long_comment = "c" * 200
        new_vhlspikewaveformfile(str(path), _params(comment=long_comment))
        header = path.read_bytes()
        comment_bytes = header[84 : 84 + COMMENT_LEN]
        assert comment_bytes == b"c" * COMMENT_LEN


# ---------------------------------------------------------------------------
# Round-trip semantics.
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_header_round_trip_all_fields(self, tmp_path):
        path = tmp_path / "h.vsw"
        p = _params(
            numchannels=5,
            S0=-12,
            S1=17,
            name="run-42",
            ref=3,
            comment="epoch 7",
            samplingrate=20000.5,
        )
        new_vhlspikewaveformfile(str(path), p)
        _, header = read_vhlspikewaveformfile(str(path))
        assert isinstance(header, VhlSpikeWaveformParameters)
        assert header.numchannels == 5
        assert header.S0 == -12
        assert header.S1 == 17
        assert header.name == "run-42"
        assert header.ref == 3
        assert header.comment == "epoch 7"
        assert header.samplingrate == pytest.approx(20000.5)

    def test_waveform_round_trip_shape_and_values(self, tmp_path):
        path = tmp_path / "w.vsw"
        p = _params(numchannels=3, S0=-4, S1=5)
        new_vhlspikewaveformfile(str(path), p)

        rng = np.random.default_rng(42)
        n_samples = p["S1"] - p["S0"] + 1  # 10
        waves = rng.standard_normal((n_samples, p["numchannels"], 6)).astype(np.float32)
        add_vhlspikewaveformfile(str(path), waves)

        read, header = read_vhlspikewaveformfile(str(path))
        assert read.shape == (n_samples, p["numchannels"], 6)
        assert read.dtype == np.float32
        np.testing.assert_allclose(read, waves)
        assert header.numchannels == 3

    def test_multiple_appends_accumulate(self, tmp_path):
        path = tmp_path / "w.vsw"
        p = _params(numchannels=2, S0=0, S1=4)
        new_vhlspikewaveformfile(str(path), p)

        n_samples = p["S1"] - p["S0"] + 1
        first = np.arange(n_samples * 2 * 3, dtype=np.float32).reshape((n_samples, 2, 3), order="F")
        second = (
            np.arange(n_samples * 2 * 2, dtype=np.float32).reshape((n_samples, 2, 2), order="F")
            - 1000.0
        )
        add_vhlspikewaveformfile(str(path), first)
        add_vhlspikewaveformfile(str(path), second)

        read, _ = read_vhlspikewaveformfile(str(path))
        assert read.shape == (n_samples, 2, 5)
        np.testing.assert_allclose(read[:, :, :3], first)
        np.testing.assert_allclose(read[:, :, 3:], second)

    def test_channel_layout_is_fortran_order(self, tmp_path):
        """A known per-channel pattern lands on the right channel index.

        This is where a mistaken row-major reshape would silently swap
        channel and sample axes.
        """
        path = tmp_path / "w.vsw"
        p = _params(numchannels=2, S0=0, S1=3)  # 4 samples/channel
        new_vhlspikewaveformfile(str(path), p)

        n_samples = p["S1"] - p["S0"] + 1  # 4
        w = np.zeros((n_samples, 2, 1), dtype=np.float32)
        w[:, 0, 0] = [1.0, 2.0, 3.0, 4.0]  # channel 0
        w[:, 1, 0] = [10.0, 20.0, 30.0, 40.0]  # channel 1
        add_vhlspikewaveformfile(str(path), w)

        read, _ = read_vhlspikewaveformfile(str(path))
        np.testing.assert_array_equal(read[:, 0, 0], [1.0, 2.0, 3.0, 4.0])
        np.testing.assert_array_equal(read[:, 1, 0], [10.0, 20.0, 30.0, 40.0])

    def test_body_bytes_are_big_endian_fortran_ordered(self, tmp_path):
        """Same content as the layout test, checked at the byte level so a
        MATLAB reader sees exactly what our reader sees."""
        path = tmp_path / "w.vsw"
        p = _params(numchannels=2, S0=0, S1=1)  # 2 samples/channel -> 4 floats/spike
        new_vhlspikewaveformfile(str(path), p)

        w = np.array([[1.0, 3.0], [2.0, 4.0]], dtype=np.float32).reshape((2, 2, 1), order="F")
        add_vhlspikewaveformfile(str(path), w)

        body = path.read_bytes()[HEADER_SIZE:]
        floats_be = np.frombuffer(body, dtype=">f4")
        # Fortran order for (samples=2, channels=2, waves=1) with the
        # values above gives [1, 2, 3, 4].
        np.testing.assert_array_equal(floats_be, [1.0, 2.0, 3.0, 4.0])


# ---------------------------------------------------------------------------
# wave_start / wave_end slicing.
# ---------------------------------------------------------------------------


class TestWaveSlicing:
    @pytest.fixture
    def written(self, tmp_path):
        path = tmp_path / "s.vsw"
        p = _params(numchannels=2, S0=-1, S1=1)
        new_vhlspikewaveformfile(str(path), p)
        n_samples = p["S1"] - p["S0"] + 1  # 3
        # Distinct values per spike so slicing errors are visible.
        waves = np.stack(
            [np.full((n_samples, 2), fill_value=i, dtype=np.float32) for i in range(8)],
            axis=-1,
        )
        add_vhlspikewaveformfile(str(path), waves)
        return path, n_samples, waves

    def test_default_reads_all_spikes(self, written):
        path, n_samples, waves = written
        read, _ = read_vhlspikewaveformfile(str(path))
        assert read.shape == (n_samples, 2, 8)
        np.testing.assert_array_equal(read, waves)

    def test_wave_start_less_than_one_returns_empty_and_header(self, written):
        path, _, _ = written
        read, header = read_vhlspikewaveformfile(str(path), wave_start=0)
        assert read.shape == (0, 0, 0)
        assert header.numchannels == 2

    def test_slice_middle_range(self, written):
        path, n_samples, waves = written
        read, _ = read_vhlspikewaveformfile(str(path), wave_start=3, wave_end=5)
        assert read.shape == (n_samples, 2, 3)
        np.testing.assert_array_equal(read, waves[:, :, 2:5])

    def test_wave_end_none_reads_to_end(self, written):
        path, n_samples, waves = written
        read, _ = read_vhlspikewaveformfile(str(path), wave_start=6)
        assert read.shape == (n_samples, 2, 3)
        np.testing.assert_array_equal(read, waves[:, :, 5:])

    def test_wave_end_inf_reads_to_end(self, written):
        path, n_samples, waves = written
        read, _ = read_vhlspikewaveformfile(str(path), wave_start=6, wave_end=float("inf"))
        assert read.shape == (n_samples, 2, 3)
        np.testing.assert_array_equal(read, waves[:, :, 5:])

    def test_wave_start_past_end_returns_empty(self, written):
        path, n_samples, _ = written
        read, _ = read_vhlspikewaveformfile(str(path), wave_start=100)
        # Nothing to read; shape must have channels/samples correct so
        # callers can still stack results without a special case.
        assert read.shape[2] == 0


# ---------------------------------------------------------------------------
# Filename vs file-like handling.
# ---------------------------------------------------------------------------


class TestFileArgHandling:
    def test_file_object_write_then_read(self, tmp_path):
        path = tmp_path / "f.vsw"
        p = _params(numchannels=2, S0=-1, S1=1)
        with open(path, "wb") as f:
            new_vhlspikewaveformfile(f, p)
        # Header wrote, file was NOT closed by the function -- we should
        # be able to reopen normally.
        with open(path, "ab") as f:
            waves = np.ones((3, 2, 4), dtype=np.float32)
            add_vhlspikewaveformfile(f, waves)

        with open(path, "rb") as f:
            read, _ = read_vhlspikewaveformfile(f)
        np.testing.assert_array_equal(read, waves)

    def test_bytesio_round_trip(self):
        buf = io.BytesIO()
        p = _params(numchannels=2, S0=0, S1=1)
        new_vhlspikewaveformfile(buf, p)
        waves = np.arange(2 * 2 * 3, dtype=np.float32).reshape((2, 2, 3), order="F")
        add_vhlspikewaveformfile(buf, waves)
        buf.seek(0)
        read, header = read_vhlspikewaveformfile(buf)
        np.testing.assert_array_equal(read, waves)
        assert header.samplingrate == pytest.approx(p["samplingrate"])

    def test_matlab_named_aliases_are_the_same_callables(self):
        # These aliases exist so ndi.util.vhlspikewaveformfile.readvhlspikewaveformfile
        # etc. resolve, matching the MATLAB module and function names.
        assert newvhlspikewaveformfile is new_vhlspikewaveformfile
        assert addvhlspikewaveformfile is add_vhlspikewaveformfile
        assert readvhlspikewaveformfile is read_vhlspikewaveformfile


# ---------------------------------------------------------------------------
# Input validation.
# ---------------------------------------------------------------------------


class TestValidation:
    def test_add_accepts_2d_single_spike(self, tmp_path):
        path = tmp_path / "v.vsw"
        p = _params(numchannels=2, S0=0, S1=2)
        new_vhlspikewaveformfile(str(path), p)

        one = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]], dtype=np.float32)
        add_vhlspikewaveformfile(str(path), one)

        read, _ = read_vhlspikewaveformfile(str(path))
        assert read.shape == (3, 2, 1)
        np.testing.assert_array_equal(read[:, :, 0], one)

    def test_add_rejects_wrong_dim(self, tmp_path):
        path = tmp_path / "v.vsw"
        p = _params(numchannels=2, S0=0, S1=2)
        new_vhlspikewaveformfile(str(path), p)

        with pytest.raises(ValueError, match=r"waveforms"):
            add_vhlspikewaveformfile(str(path), np.zeros((3,), dtype=np.float32))
        with pytest.raises(ValueError, match=r"waveforms"):
            add_vhlspikewaveformfile(str(path), np.zeros((3, 2, 1, 1), dtype=np.float32))

    def test_read_rejects_short_file(self, tmp_path):
        path = tmp_path / "short.vsw"
        path.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match=r"512-byte VSW header"):
            read_vhlspikewaveformfile(str(path))

    def test_read_rejects_truncated_body(self, tmp_path):
        path = tmp_path / "trunc.vsw"
        p = _params(numchannels=2, S0=0, S1=1)
        new_vhlspikewaveformfile(str(path), p)
        waves = np.zeros((2, 2, 2), dtype=np.float32)
        add_vhlspikewaveformfile(str(path), waves)
        # Chop off the last float32 of the last spike -- 4 bytes.
        os.truncate(path, path.stat().st_size - 4)
        with pytest.raises(ValueError, match=r"odd number of samples"):
            read_vhlspikewaveformfile(str(path))

    def test_parameters_dataclass_accepted_by_writer(self, tmp_path):
        path = tmp_path / "dc.vsw"
        p = VhlSpikeWaveformParameters(
            numchannels=2,
            S0=-1,
            S1=1,
            name="dc",
            ref=1,
            comment="from dataclass",
            samplingrate=1000.0,
        )
        new_vhlspikewaveformfile(str(path), p)
        _, header = read_vhlspikewaveformfile(str(path))
        assert header.name == "dc"
        assert header.samplingrate == pytest.approx(1000.0)
