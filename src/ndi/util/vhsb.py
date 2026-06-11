"""
ndi.util.vhsb - VH-Lab Series Binary (VHSB) read/write.

A faithful Python port of vlt.file.custom_file_formats.vhsb_write / vhsb_read
(VH-Lab toolbox). VHSB stores a time series as an X (time) column paired with
a Y (data) array; samples are interleaved on disk as ``[X0 Y0 X1 Y1 ...]``
after a fixed 1836-byte little-endian header. This is the format MATLAB NDI
writes for ``epoch_binary_data.vhsb`` — the Python port previously dumped raw
``datapoints.tobytes()`` with no header, dropping the time axis and making the
file unreadable by MATLAB.

Only the case NDI uses is implemented: float64 X and Y with the X stamps
stored. Reading and writing round-trip, and the byte layout matches the MATLAB
writer so files are cross-language readable.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

HEADER_SIZE = 1836
_ID = b"This is a VHSB file, http://github.com/VH-Lab\n"
_DTYPE_FLOAT = 4  # char=1, uint=2, int=3, float=4


def _pad(b: bytes, n: int) -> bytes:
    """Right-pad/truncate *b* to exactly *n* bytes with NULs."""
    return b[:n] + b"\x00" * max(0, n - len(b))


def vhsb_write(
    path: str | Path,
    x: np.ndarray,
    y: np.ndarray,
    *,
    x_units: str = "",
    y_units: str = "",
) -> None:
    """Write time series ``(x, y)`` to *path* in VHSB format.

    Args:
        path: Output file path.
        x: Sample times, shape ``(N,)`` or ``(N, 1)``.
        y: Sample data, shape ``(N,)`` or ``(N, C)`` (C channels per sample).
        x_units, y_units: Optional unit strings (<=255 chars).
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    n = x.shape[0]
    if y.shape[0] != n:
        raise ValueError(
            f"x and y must have the same number of samples (rows); got {n} and {y.shape[0]}"
        )
    channels = int(np.prod(y.shape[1:])) if y.ndim > 1 else 1

    x_start = float(x[0]) if n > 1 else 0.0
    x_increment = float(np.median(np.diff(x))) if n > 2 else 0.0
    # Regularly sampled iff the second difference is ~0 everywhere.
    if n > 3:
        x_constant = 1 if np.max(np.abs(np.diff(np.diff(x)))) < 1e-7 else 0
    else:
        x_constant = 0

    # Y_dim mirrors MATLAB size(y): [N, C, ...] padded to 100 uint64 entries.
    y_dim = [n, channels]

    header = bytearray(HEADER_SIZE)
    header[0:200] = _pad(_ID, 200)
    struct.pack_into("<I", header, 200, 1)  # version
    header[204:460] = _pad(b"little-endian\n", 256)  # machine_format
    struct.pack_into("<I", header, 460, 64)  # X_data_size (bits)
    struct.pack_into("<H", header, 464, _DTYPE_FLOAT)  # X_data_type
    # Y_dim: 100 uint64 @ 466
    ydim_full = (y_dim + [0] * 100)[:100]
    struct.pack_into("<100Q", header, 466, *ydim_full)
    struct.pack_into("<I", header, 1266, 64)  # Y_data_size
    struct.pack_into("<H", header, 1270, _DTYPE_FLOAT)  # Y_data_type
    struct.pack_into("<B", header, 1272, 1)  # X_stored
    struct.pack_into("<B", header, 1273, x_constant)  # X_constantinterval
    struct.pack_into("<d", header, 1274, x_start)  # X_start (float64)
    struct.pack_into("<d", header, 1282, x_increment)  # X_increment (float64)
    header[1290:1546] = _pad(x_units.encode() + b"\n", 256)
    header[1546:1802] = _pad(y_units.encode() + b"\n", 256)
    struct.pack_into("<B", header, 1802, 0)  # X_usescale
    struct.pack_into("<B", header, 1803, 0)  # Y_usescale
    struct.pack_into("<d", header, 1804, 1.0)  # X_scale
    struct.pack_into("<d", header, 1812, 0.0)  # X_offset
    struct.pack_into("<d", header, 1820, 1.0)  # Y_scale
    struct.pack_into("<d", header, 1828, 0.0)  # Y_offset

    # Interleave X then Y per sample: [x0, y0_0..y0_{C-1}, x1, ...].
    interleaved = np.empty((n, 1 + channels), dtype=np.float64)
    interleaved[:, 0] = x
    interleaved[:, 1:] = y.reshape(n, channels)

    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(interleaved.astype("<f8").tobytes())


def vhsb_read(
    path: str | Path,
    x0: float = -np.inf,
    x1: float = np.inf,
) -> tuple[np.ndarray, np.ndarray]:
    """Read a VHSB file, returning ``(y, x)`` for the window ``[x0, x1]``.

    Args:
        path: VHSB file path.
        x0, x1: Inclusive time window. Defaults read all samples.

    Returns:
        Tuple ``(y, x)`` where *y* has shape ``(M,)`` for scalar data or
        ``(M, C)`` for multi-channel, and *x* has shape ``(M,)``.
    """
    with open(path, "rb") as fh:
        header = fh.read(HEADER_SIZE)
        body = fh.read()

    x_constant = struct.unpack_from("<B", header, 1273)[0]
    x_start = struct.unpack_from("<d", header, 1274)[0]
    x_increment = struct.unpack_from("<d", header, 1282)[0]
    y_dim = struct.unpack_from("<100Q", header, 466)
    # channels = product of Y_dim[1:] up to the first zero entry.
    dims = []
    for d in y_dim:
        if d == 0:
            break
        dims.append(d)
    channels = int(np.prod(dims[1:])) if len(dims) > 1 else 1

    sample_size = 8 + channels * 8  # X float64 + C Y float64
    if sample_size == 0:
        return np.array([]), np.array([])
    num_samples = len(body) // sample_size
    if num_samples == 0:
        return np.array([]), np.array([])

    flat = np.frombuffer(body[: num_samples * sample_size], dtype="<f8")
    table = flat.reshape(num_samples, 1 + channels)
    x = table[:, 0].copy()
    y = table[:, 1:].copy()

    if x_constant and (x0 != -np.inf or x1 != np.inf):
        # Constant interval: clip the requested window to sample indices.
        def point_to_sample(p: float) -> float:
            if x_increment == 0:
                return 1.0
            return (p - x_start) / x_increment + 1.0

        s0 = int(np.clip(np.floor(point_to_sample(x0)), 1, num_samples))
        s1 = int(np.clip(np.ceil(point_to_sample(x1)), 1, num_samples))
        x = x[s0 - 1 : s1]
        y = y[s0 - 1 : s1]
    else:
        mask = (x >= x0) & (x <= x1)
        x = x[mask]
        y = y[mask]

    if channels == 1:
        y = y.reshape(-1)
    return y, x
