"""ndi.util.vhlspikewaveformfile - the VHL spike-waveform (`.vsw`) file format.

MATLAB counterparts (in the vhlab-toolbox-matlab package, **not** in
NDI-matlab itself)::

    vlt.file.custom_file_formats.newvhlspikewaveformfile
    vlt.file.custom_file_formats.addvhlspikewaveformfile
    vlt.file.custom_file_formats.readvhlspikewaveformfile

Why it lives here: NDI-python issue #97 calls for the real ``.vsw`` format
at ``src/ndi/util/vhlspikewaveformfile.py`` so ``ndi.app.spikeextractor``
writes spike storage that ``ndi.app.spikeextractor`` in MATLAB can read
back verbatim, and vice versa. The byte layout on disk is the contract;
matching it is what makes the two languages interoperable.

File layout (all big-endian, always -- MATLAB opens ``'b'``):

* 512-byte header
    ==============  ====  =========================================
    offset (bytes)  type  field
    ==============  ====  =========================================
    0               u8    ``numchannels``
    1               i8    ``S0`` (samples before spike center; usually negative)
    2               i8    ``S1`` (samples after spike center; usually positive)
    3..82           char  ``name`` (80 bytes, null-padded, ASCII)
    83              u8    ``ref``
    84..163         char  ``comment`` (80 bytes, null-padded, ASCII)
    164..167        f32   ``samplingrate``
    168..511        u8    zero padding
    ==============  ====  =========================================
* Body: ``float32`` samples in Fortran order for a
  ``(samples_per_channel, numchannels, num_waveforms)`` array, i.e. one
  spike's ``samples_per_channel * numchannels`` values are contiguous on
  disk, sample index varying fastest, then channel, then spike. This
  matches MATLAB's ``fwrite`` after ``reshape(waveforms, ns*nc, nw)``.
  ``samples_per_channel = S1 - S0 + 1``.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import numpy as np

__all__ = [
    "HEADER_SIZE",
    "NAME_LEN",
    "COMMENT_LEN",
    "VhlSpikeWaveformParameters",
    "new_vhlspikewaveformfile",
    "add_vhlspikewaveformfile",
    "read_vhlspikewaveformfile",
    "write_vhlspikewaveformfile",
    "newvhlspikewaveformfile",
    "addvhlspikewaveformfile",
    "readvhlspikewaveformfile",
]

#: Size of the fixed header in bytes.
HEADER_SIZE = 512
#: Maximum ASCII characters kept from ``parameters['name']``.
NAME_LEN = 80
#: Maximum ASCII characters kept from ``parameters['comment']``.
COMMENT_LEN = 80

FileArg = str | os.PathLike | IO[bytes]


@dataclass
class VhlSpikeWaveformParameters:
    """Header fields of a ``.vsw`` file, in the same order they appear on disk.

    Matches the MATLAB ``parameters`` struct used by
    ``newvhlspikewaveformfile``: ``numchannels``, ``S0``, ``S1``, ``name``,
    ``ref``, ``comment``, ``samplingrate``. The reader returns an instance
    of this; a plain ``dict`` with the same keys is also accepted anywhere
    a ``parameters`` argument is expected.
    """

    numchannels: int
    S0: int  # noqa: N815 - MATLAB's field name
    S1: int  # noqa: N815 - MATLAB's field name
    name: str
    ref: int
    comment: str
    samplingrate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "numchannels": self.numchannels,
            "S0": self.S0,
            "S1": self.S1,
            "name": self.name,
            "ref": self.ref,
            "comment": self.comment,
            "samplingrate": self.samplingrate,
        }


def _params_get(params: Any, key: str, default: Any = None) -> Any:
    if isinstance(params, VhlSpikeWaveformParameters):
        return getattr(params, key)
    if hasattr(params, "get"):
        return params.get(key, default)
    return getattr(params, key, default)


def _encode_fixed_ascii(text: Any, length: int) -> bytes:
    """80-byte MATLAB-style char field: ASCII, truncated to length, null-padded.

    MATLAB truncates a char field with ``parameters.name(1:80)`` and writes
    the remaining ``80 - length(parameters.name)`` bytes as ``0``. The
    reader trims *every* zero byte (``find(parameters.name)``), not just
    trailing ones, so an embedded ``\\0`` disappears on the round trip --
    the same behavior we get from stripping ``b'\\x00'`` on the way in.
    """
    if text is None:
        text = ""
    if isinstance(text, bytes):
        raw = text
    else:
        raw = str(text).encode("ascii", errors="replace")
    raw = raw[:length]
    return raw + b"\x00" * (length - len(raw))


def _decode_fixed_ascii(raw: bytes) -> str:
    return raw.replace(b"\x00", b"").decode("ascii", errors="replace")


def _open_for_new(arg: FileArg) -> tuple[IO[bytes], bool]:
    if isinstance(arg, (str, os.PathLike)):
        return open(arg, "wb"), True
    return arg, False


def _open_for_add(arg: FileArg) -> tuple[IO[bytes], bool]:
    if isinstance(arg, (str, os.PathLike)):
        return open(arg, "ab"), True
    return arg, False


def _open_for_read(arg: FileArg) -> tuple[IO[bytes], bool]:
    if isinstance(arg, (str, os.PathLike)):
        return open(arg, "rb"), True
    return arg, False


def new_vhlspikewaveformfile(fid_or_filename: FileArg, parameters: Any) -> None:
    """Write a ``.vsw`` header, truncating the file if a path is given.

    MATLAB counterpart:
    ``vlt.file.custom_file_formats.newvhlspikewaveformfile(fid_or_filename, parameters)``.

    Parameters
    ----------
    fid_or_filename : str, os.PathLike, or binary file-like
        Where to write the header. A path is opened with ``'wb'`` and
        closed on return, matching MATLAB's ``fopen(...,'w','b')``. A
        file-like object must be open in a binary mode that permits
        writing; the seek position is *not* preserved (MATLAB
        ``fseek(fid,0,'bof')`` writes at offset 0, and this does too).
    parameters : mapping or VhlSpikeWaveformParameters
        Must supply ``numchannels`` (uint8), ``S0`` (int8), ``S1`` (int8),
        ``name`` (<=80 ASCII chars), ``ref`` (uint8), ``comment`` (<=80
        ASCII chars), ``samplingrate`` (float).
    """
    fid, opened = _open_for_new(fid_or_filename)
    try:
        fid.seek(0, io.SEEK_SET)
        header = bytearray(HEADER_SIZE)

        header[0] = int(_params_get(parameters, "numchannels")) & 0xFF
        # int8 is signed; struct-pack via numpy for readability.
        header[1:2] = np.int8(int(_params_get(parameters, "S0"))).tobytes()
        header[2:3] = np.int8(int(_params_get(parameters, "S1"))).tobytes()

        header[3 : 3 + NAME_LEN] = _encode_fixed_ascii(
            _params_get(parameters, "name", ""), NAME_LEN
        )
        header[3 + NAME_LEN] = int(_params_get(parameters, "ref", 0)) & 0xFF

        comment_offset = 4 + NAME_LEN  # == 84
        header[comment_offset : comment_offset + COMMENT_LEN] = _encode_fixed_ascii(
            _params_get(parameters, "comment", ""), COMMENT_LEN
        )

        samplingrate_offset = comment_offset + COMMENT_LEN  # == 164
        header[samplingrate_offset : samplingrate_offset + 4] = np.array(
            _params_get(parameters, "samplingrate"), dtype=">f4"
        ).tobytes()

        fid.write(bytes(header))
        # Match MATLAB: after writing the header, the file position is at
        # the end of the 512-byte header, ready for spikes.
        fid.seek(HEADER_SIZE, io.SEEK_SET)
    finally:
        if opened:
            fid.close()


def add_vhlspikewaveformfile(fid_or_filename: FileArg, waveforms: np.ndarray) -> None:
    """Append spike waveforms to a ``.vsw`` file.

    MATLAB counterpart:
    ``vlt.file.custom_file_formats.addvhlspikewaveformfile(fid_or_filename, waveforms)``.

    Parameters
    ----------
    fid_or_filename : str, os.PathLike, or binary file-like
        A path is opened with ``'ab'`` (append) and closed on return,
        matching MATLAB's ``fopen(...,'a','b')``. A file-like object must
        be open for binary writing; this call seeks to the end of the file
        before writing, matching MATLAB's ``fseek(fid,0,'eof')``.
    waveforms : numpy.ndarray
        Shape ``(num_samples, num_channels, num_waveforms)``. Written as
        ``float32`` big-endian in Fortran order so that
        ``read_vhlspikewaveformfile`` reshapes it back to the same
        ``(samples, channels, waves)`` layout MATLAB produces.
    """
    arr = np.asarray(waveforms)
    if arr.ndim == 2:
        # MATLAB's size() of a 2-D matrix reports [rows cols 1], so a
        # single waveform expressed as (num_samples, num_channels) is
        # treated as one spike -- keep parity here.
        arr = arr[:, :, np.newaxis]
    if arr.ndim != 3:
        raise ValueError(
            "waveforms must be shape (num_samples, num_channels, num_waveforms); "
            f"got shape {arr.shape!r}"
        )

    fid, opened = _open_for_add(fid_or_filename)
    try:
        fid.seek(0, io.SEEK_END)
        # F-order flatten with big-endian float32 matches MATLAB's
        # reshape+fwrite pipeline byte-for-byte. Building the array
        # directly with dtype='>f4' (rather than astype on a native
        # float32) guarantees the byteswap actually happens.
        payload = np.asarray(arr, dtype=">f4")
        fid.write(np.asfortranarray(payload).tobytes(order="F"))
    finally:
        if opened:
            fid.close()


def read_vhlspikewaveformfile(
    file_or_fid: FileArg,
    wave_start: int = 1,
    wave_end: int | float | None = None,
) -> tuple[np.ndarray, VhlSpikeWaveformParameters]:
    """Read spike waveforms and header parameters from a ``.vsw`` file.

    MATLAB counterpart:
    ``[waveforms, header] = vlt.file.custom_file_formats.readvhlspikewaveformfile(file_or_fid[, wave_start, wave_end])``.

    Parameters
    ----------
    file_or_fid : str, os.PathLike, or binary file-like
        A path is opened with ``'rb'`` and closed on return, matching
        MATLAB's ``fopen(...,'rb','b')``.
    wave_start : int, optional
        1-based index of the first waveform to return. If less than 1,
        only the header is read and ``waveforms`` is returned empty
        (matches MATLAB).
    wave_end : int, float, or None, optional
        1-based *inclusive* index of the last waveform to return.
        ``None`` (the default) or ``float('inf')`` means "to the end of
        the file", matching MATLAB's ``Inf`` sentinel.

    Returns
    -------
    waveforms : numpy.ndarray
        Shape ``(samples_per_channel, numchannels, num_waves_read)``
        where ``samples_per_channel = S1 - S0 + 1``. Empty array of
        shape ``(0, 0, 0)`` when ``wave_start < 1`` or the file holds
        no spikes past ``wave_start``.
    parameters : VhlSpikeWaveformParameters
        The parsed header.
    """
    if wave_end is None:
        wave_end = float("inf")

    fid, opened = _open_for_read(file_or_fid)
    try:
        fid.seek(0, io.SEEK_SET)
        header = fid.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            raise ValueError(
                f"file is shorter than the {HEADER_SIZE}-byte VSW header "
                f"(got {len(header)} bytes)"
            )

        numchannels = header[0]
        S0 = int(np.frombuffer(header[1:2], dtype=np.int8)[0])
        S1 = int(np.frombuffer(header[2:3], dtype=np.int8)[0])
        name = _decode_fixed_ascii(header[3 : 3 + NAME_LEN])
        ref = header[3 + NAME_LEN]
        comment_offset = 4 + NAME_LEN
        comment = _decode_fixed_ascii(header[comment_offset : comment_offset + COMMENT_LEN])
        samplingrate = float(
            np.frombuffer(
                header[comment_offset + COMMENT_LEN : comment_offset + COMMENT_LEN + 4], dtype=">f4"
            )[0]
        )

        parameters = VhlSpikeWaveformParameters(
            numchannels=int(numchannels),
            S0=S0,
            S1=S1,
            name=name,
            ref=int(ref),
            comment=comment,
            samplingrate=samplingrate,
        )

        samples_per_channel = S1 - S0 + 1
        if samples_per_channel <= 0 or numchannels <= 0:
            # Header is degenerate: return it, and an empty waveform block.
            return np.empty((0, 0, 0), dtype=np.float32), parameters

        wave_size = int(numchannels) * int(samples_per_channel)
        data_size = 4  # float32

        if wave_start < 1:
            return np.empty((0, 0, 0), dtype=np.float32), parameters

        seek_to = HEADER_SIZE + data_size * (wave_start - 1) * wave_size
        fid.seek(seek_to, io.SEEK_SET)

        if wave_end == float("inf"):
            raw = fid.read()
        else:
            waves_requested = int(wave_end) - int(wave_start) + 1
            if waves_requested <= 0:
                return (
                    np.empty((samples_per_channel, int(numchannels), 0), dtype=np.float32),
                    parameters,
                )
            n_bytes = waves_requested * wave_size * data_size
            raw = fid.read(n_bytes)

        if len(raw) == 0:
            return (
                np.empty((samples_per_channel, int(numchannels), 0), dtype=np.float32),
                parameters,
            )

        floats = np.frombuffer(raw, dtype=">f4")
        n_floats = floats.size
        waves_actually_read_float = n_floats / (int(numchannels) * int(samples_per_channel))
        waves_actually_read = int(round(waves_actually_read_float))
        if abs(waves_actually_read - waves_actually_read_float) > 1e-4:
            raise ValueError(
                "Got an odd number of samples for these spikes. Corrupted file perhaps?"
            )

        # Reshape (samples, channels, waves) in Fortran order to match
        # MATLAB's reshape(waveforms, samples_per_channel, numchannels, waves).
        waveforms = np.asarray(floats, dtype=np.float32).reshape(
            (int(samples_per_channel), int(numchannels), waves_actually_read),
            order="F",
        )
        return waveforms, parameters
    finally:
        if opened:
            fid.close()


def write_vhlspikewaveformfile(
    filename: FileArg,
    waveforms: np.ndarray,
    parameters: Any,
) -> None:
    """Write header + spike waveforms to a ``.vsw`` file in one call.

    Convenience wrapper: writes the fixed 512-byte header with
    :func:`new_vhlspikewaveformfile` and appends every waveform with
    :func:`add_vhlspikewaveformfile`. ``parameters`` may pass ``samplerate``
    instead of ``samplingrate`` — a common alias in the extractor.
    """
    if isinstance(parameters, dict):
        params = dict(parameters)
        if "samplingrate" not in params and "samplerate" in params:
            params["samplingrate"] = params["samplerate"]
        parameters = params
    new_vhlspikewaveformfile(filename, parameters)
    add_vhlspikewaveformfile(filename, waveforms)


# ---------------------------------------------------------------------------
# MATLAB-name aliases so ndi.util.vhlspikewaveformfile.readvhlspikewaveformfile
# (etc.) resolves the way a MATLAB reader expects.
# ---------------------------------------------------------------------------
newvhlspikewaveformfile = new_vhlspikewaveformfile
addvhlspikewaveformfile = add_vhlspikewaveformfile
readvhlspikewaveformfile = read_vhlspikewaveformfile


def _self_test() -> None:  # pragma: no cover - convenience for manual runs
    import tempfile

    rng = np.random.default_rng(0)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "spikewaves.vsw"
        parameters = {
            "numchannels": 4,
            "S0": -10,
            "S1": 20,
            "name": "my sort",
            "ref": 0,
            "comment": "test",
            "samplingrate": 30000.0,
        }
        new_vhlspikewaveformfile(str(path), parameters)
        n_samples = parameters["S1"] - parameters["S0"] + 1
        first = rng.standard_normal((n_samples, parameters["numchannels"], 5)).astype(np.float32)
        second = rng.standard_normal((n_samples, parameters["numchannels"], 3)).astype(np.float32)
        add_vhlspikewaveformfile(str(path), first)
        add_vhlspikewaveformfile(str(path), second)
        waves, header = read_vhlspikewaveformfile(str(path))
        assert waves.shape == (n_samples, parameters["numchannels"], 8)
        assert header.samplingrate == parameters["samplingrate"]
        np.testing.assert_allclose(waves[:, :, :5], first)
        np.testing.assert_allclose(waves[:, :, 5:], second)


if __name__ == "__main__":  # pragma: no cover
    _self_test()
    print("ok")
