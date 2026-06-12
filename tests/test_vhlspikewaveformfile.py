"""Tests for the vlt vhlspikewaveformfile (.vsw) binary format port."""

import struct
import tempfile

import numpy as np

from ndi.util.vhlspikewaveformfile import (
    read_vhlspikewaveformfile,
    write_vhlspikewaveformfile,
)


def _params(C=2, S0=-1, S1=2, rate=30000.0, name="probeA", ref=7, comment="hi"):
    return {
        "numchannels": C,
        "S0": S0,
        "S1": S1,
        "samplingrate": rate,
        "name": name,
        "ref": ref,
        "comment": comment,
    }


def test_roundtrip():
    S0, S1, C, W = -1, 2, 2, 3
    S = S1 - S0 + 1
    wf = np.arange(S * C * W, dtype=float).reshape(S, C, W)
    fn = tempfile.mktemp(suffix=".vsw")
    write_vhlspikewaveformfile(fn, wf, _params(C, S0, S1))
    back, p = read_vhlspikewaveformfile(fn)
    assert back.shape == (S, C, W)
    np.testing.assert_array_almost_equal(back, wf)
    assert p["numchannels"] == C and p["S0"] == S0 and p["S1"] == S1
    assert p["name"] == "probeA" and p["ref"] == 7 and p["comment"] == "hi"
    assert abs(p["samplingrate"] - 30000.0) < 1e-2


def test_header_is_big_endian_matlab_layout():
    fn = tempfile.mktemp(suffix=".vsw")
    write_vhlspikewaveformfile(fn, np.zeros((4, 2, 1)), _params(C=2, S0=-1, S1=2))
    with open(fn, "rb") as f:
        head = f.read(168)
    assert head[0] == 2  # numchannels uint8
    assert struct.unpack(">b", head[1:2])[0] == -1  # S0 int8
    assert struct.unpack(">b", head[2:3])[0] == 2  # S1 int8
    assert head[3:9] == b"probeA"
    assert head[83] == 7  # ref
    assert abs(struct.unpack(">f", head[164:168])[0] - 30000.0) < 1e-2  # samplingrate BE f32


def test_data_is_event_channel_major_big_endian():
    # waveform stream per spike is the column-major flatten of (samples, channels)
    # = all samples of channel 0, then channel 1; spike after spike. Big-endian f32.
    S0, S1, C = 0, 1, 2  # S=2, W=2
    wf = np.array([[[1.0, 5.0], [2.0, 6.0]], [[3.0, 7.0], [4.0, 8.0]]])  # shape (S=2, C=2, W=2)
    fn = tempfile.mktemp(suffix=".vsw")
    write_vhlspikewaveformfile(fn, wf, _params(C=C, S0=S0, S1=S1))
    with open(fn, "rb") as f:
        f.seek(512)
        raw = np.frombuffer(f.read(), dtype=">f4")
    # expected: spike0[ch0 s0,s1][ch1 s0,s1], spike1[...]
    expected = np.transpose(wf, (2, 1, 0)).ravel()  # (W,C,S) row-major
    np.testing.assert_array_almost_equal(raw, expected)


def test_reads_hand_built_matlab_file():
    # Construct a file exactly as MATLAB newvhlspikewaveformfile+addvhlspikewaveformfile
    # would, and confirm we recover the waveforms.
    C, S0, S1 = 2, 0, 1
    S = S1 - S0 + 1
    fn = tempfile.mktemp(suffix=".vsw")
    with open(fn, "wb") as f:
        f.write(struct.pack(">B", C))
        f.write(struct.pack(">b", S0))
        f.write(struct.pack(">b", S1))
        f.write(b"\x00" * 80)  # name
        f.write(struct.pack(">B", 0))  # ref
        f.write(b"\x00" * 80)  # comment
        f.write(struct.pack(">f", 25000.0))
        f.write(b"\x00" * (512 - f.tell()))
        # one spike: ch0 samples [1,2], ch1 samples [3,4]  (big-endian f32)
        f.write(struct.pack(">4f", 1.0, 2.0, 3.0, 4.0))
    wf, p = read_vhlspikewaveformfile(fn)
    assert wf.shape == (S, C, 1)
    # wf[s, c, 0]: ch0 -> [1,2], ch1 -> [3,4]
    np.testing.assert_array_almost_equal(wf[:, 0, 0], [1.0, 2.0])
    np.testing.assert_array_almost_equal(wf[:, 1, 0], [3.0, 4.0])
    assert abs(p["samplingrate"] - 25000.0) < 1e-2


def test_subset_and_header_only():
    S0, S1, C, W = 0, 2, 1, 5
    S = S1 - S0 + 1
    wf = np.arange(S * C * W, dtype=float).reshape(S, C, W)
    fn = tempfile.mktemp(suffix=".vsw")
    write_vhlspikewaveformfile(fn, wf, _params(C=C, S0=S0, S1=S1))
    sub, _ = read_vhlspikewaveformfile(fn, 2, 4)  # 1-based inclusive
    np.testing.assert_array_almost_equal(sub, wf[:, :, 1:4])
    # wave_start < 1 -> header only
    empty, p = read_vhlspikewaveformfile(fn, 0)
    assert empty.shape[2] == 0 and p["numchannels"] == C


def test_empty_waveforms():
    fn = tempfile.mktemp(suffix=".vsw")
    write_vhlspikewaveformfile(fn, np.zeros((3, 2, 0)), _params(C=2, S0=0, S1=2))
    wf, p = read_vhlspikewaveformfile(fn)
    assert wf.shape[2] == 0 and p["numchannels"] == 2
