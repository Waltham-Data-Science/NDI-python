"""
ndi.util.vhlspikewaveformfile - read/write the vlt spike-waveform (.vsw) format.

Port of ``vlt.file.custom_file_formats.{newvhlspikewaveformfile,
addvhlspikewaveformfile,readvhlspikewaveformfile}`` (vhlab-toolbox-matlab),
which the Python vlt port does not provide. ``ndi.app.spikeextractor`` writes
spike waveforms with this format and ``ndi.app.spikesorter`` reads them, so the
files are byte-compatible with MATLAB (a MATLAB-extracted ``spikewaves.vsw`` can
be read here and vice versa).

Binary format (BIG-ENDIAN; single-precision float32 data):

    512-byte header:
        byte 0      : numchannels   (uint8)
        byte 1      : S0            (int8)  -- samples before spike center
        byte 2      : S1            (int8)  -- samples after spike center
        bytes 3-82  : name          (80 chars, zero-padded)
        byte 83     : ref           (uint8)
        bytes 84-163: comment       (80 chars, zero-padded)
        bytes 164-167: samplingrate (float32)
        bytes 168-511: zero padding
    data (from byte 512):
        per waveform, ``numchannels * (S1-S0+1)`` float32 values, stored
        channel-block-of-samples then waveform after waveform
        (MATLAB ``reshape(waveforms, samples_per_channel, numchannels, nwaves)``).
"""

from __future__ import annotations

import struct
from typing import Any

import numpy as np

HEADER_SIZE = 512
_DATA_DTYPE = ">f4"  # big-endian float32, matching MATLAB fopen(...,'b')


def _encode_field(s: str, width: int = 80) -> bytes:
    b = (s or "").encode("latin-1", "replace")[:width]
    return b + b"\x00" * (width - len(b))


def write_vhlspikewaveformfile(
    filename: str,
    waveforms: np.ndarray,
    parameters: dict[str, Any],
) -> None:
    """Write spike waveforms to a ``.vsw`` file.

    MATLAB equivalent: ``newvhlspikewaveformfile`` (header) + ``addvhlspikewaveformfile``
    (data), combined.

    Args:
        filename: Output path.
        waveforms: ``(num_samples, numchannels, num_waveforms)`` float array,
            where ``num_samples == S1 - S0 + 1``.
        parameters: dict with ``numchannels``, ``S0``, ``S1``, ``samplingrate``
            (or ``samplerate``); optional ``name`` (<=80), ``ref``, ``comment``.
    """
    waveforms = np.asarray(waveforms)
    if waveforms.ndim != 3:
        raise ValueError("waveforms must be (num_samples, numchannels, num_waveforms)")
    numchannels = int(parameters["numchannels"])
    S0 = int(parameters["S0"])
    S1 = int(parameters["S1"])
    samplingrate = float(parameters.get("samplingrate", parameters.get("samplerate", 0.0)))
    if waveforms.shape[0] != (S1 - S0 + 1):
        raise ValueError(f"num_samples ({waveforms.shape[0]}) must equal S1-S0+1 ({S1 - S0 + 1})")

    with open(filename, "wb") as f:
        f.write(struct.pack(">B", numchannels & 0xFF))
        f.write(struct.pack(">b", S0))
        f.write(struct.pack(">b", S1))
        f.write(_encode_field(str(parameters.get("name", "")), 80))
        f.write(struct.pack(">B", int(parameters.get("ref", 0)) & 0xFF))
        f.write(_encode_field(str(parameters.get("comment", "")), 80))
        f.write(struct.pack(">f", samplingrate))
        f.write(b"\x00" * (HEADER_SIZE - f.tell()))
        # Data: MATLAB reshape(waveforms, S*C, nwaves) column-major, written
        # float32. For an (S, C, W) array the byte stream is, per waveform, the
        # column-major flatten of (S, C) -- i.e. transpose to (W, C, S) then
        # row-major bytes.
        if waveforms.shape[2] > 0:
            stream = np.ascontiguousarray(np.transpose(waveforms, (2, 1, 0)), dtype=_DATA_DTYPE)
            f.write(stream.tobytes())


def read_vhlspikewaveformfile(
    file_or_fid: Any,
    wave_start: int = 1,
    wave_end: int | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a ``.vsw`` file.

    MATLAB equivalent: ``readvhlspikewaveformfile``.

    Args:
        file_or_fid: path, or an open binary file-like object.
        wave_start: 1-based first waveform to read. If < 1, only the header is
            read and an empty ``(num_samples, numchannels, 0)`` array returned.
        wave_end: 1-based last waveform (inclusive). ``None`` reads to the end.

    Returns:
        ``(waveforms, parameters)`` where ``waveforms`` is
        ``(num_samples, numchannels, num_waveforms)`` and ``parameters`` carries
        the header fields.
    """
    own = not hasattr(file_or_fid, "read")
    f = open(file_or_fid, "rb") if own else file_or_fid
    try:
        f.seek(0)
        numchannels = struct.unpack(">B", f.read(1))[0]
        S0 = struct.unpack(">b", f.read(1))[0]
        S1 = struct.unpack(">b", f.read(1))[0]
        name = f.read(80).rstrip(b"\x00").decode("latin-1", "replace")
        ref = struct.unpack(">B", f.read(1))[0]
        comment = f.read(80).rstrip(b"\x00").decode("latin-1", "replace")
        samplingrate = float(struct.unpack(">f", f.read(4))[0])

        samples_per_channel = S1 - S0 + 1
        wave_size = numchannels * samples_per_channel  # floats per waveform
        params: dict[str, Any] = {
            "numchannels": numchannels,
            "S0": S0,
            "S1": S1,
            "name": name,
            "ref": ref,
            "comment": comment,
            "samplingrate": samplingrate,
        }

        if wave_size <= 0:
            return np.empty((max(samples_per_channel, 0), numchannels, 0), dtype=float), params

        # total waveforms available
        f.seek(0, 2)
        filesize = f.tell()
        total_waves = max(0, (filesize - HEADER_SIZE) // (wave_size * 4))

        if wave_start < 1:  # header-only request
            return np.empty((samples_per_channel, numchannels, 0), dtype=float), params

        end = total_waves if wave_end is None else min(int(wave_end), total_waves)
        nwaves = max(0, end - wave_start + 1)
        if nwaves == 0:
            return np.empty((samples_per_channel, numchannels, 0), dtype=float), params

        f.seek(HEADER_SIZE + (wave_start - 1) * wave_size * 4, 0)
        raw = np.frombuffer(f.read(nwaves * wave_size * 4), dtype=_DATA_DTYPE)
        # Reverse of the write layout: (W, C, S) row-major -> (S, C, W).
        waveforms = raw.reshape(nwaves, numchannels, samples_per_channel).transpose(2, 1, 0)
        return np.ascontiguousarray(waveforms, dtype=float), params
    finally:
        if own:
            f.close()
