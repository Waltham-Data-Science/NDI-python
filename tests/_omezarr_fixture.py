"""Programmatic OME-Zarr fixture (copied from NDR-python tests/_omezarr_fixture.py).

Python mirror of ``+ndr/+test/+format/+omezarr/makeExampleFixture.m``.

Builds a dual-pyramid store that matches the lab layout in
``ferret-lightsheet/formats/OurUsualZarrFormat.md``: one shared level-0
array plus separate ``mean`` and ``max`` downsample chains. Without
``with_chunks`` only metadata files are written; with ``with_chunks`` a
seeded uint16 volume is written so chunks exist on disk and their
ground-truth downsamples come back for comparison.

The chunks are uncompressed by default. ``codec="blosc-zstd"`` instead writes
every array through zarr-python with Blosc+Zstd, the codec the lab's own data
uses and the one ``makeExampleFixture.m`` writes. The OME-Zarr symmetry test
needs that: MATLAB's reader hand-rolls the Blosc/Zstd path, so only a fixture
compressed by zarr-python itself checks it against real zarr-python output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class GroundTruth:
    level0: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint16))
    mean_level1: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint16))
    max_level1: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint16))
    mean_level2: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint16))
    max_level2: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint16))
    shape0: tuple[int, ...] = ()
    chunk_shape0: tuple[int, ...] = ()
    dtype: str = "<u2"


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj))


def _write_zgroup(dir_path: Path) -> None:
    _write_json(dir_path / ".zgroup", {"zarr_format": 2})


def _write_zarray(
    array_dir: Path, shape: tuple[int, ...], chunks: tuple[int, ...], dtype: str
) -> None:
    array_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "zarr_format": 2,
        "shape": list(shape),
        "chunks": list(chunks),
        "dtype": dtype,
        "compressor": None,
        "fill_value": 0,
        "order": "C",
        "filters": None,
        "dimension_separator": ".",
    }
    _write_json(array_dir / ".zarray", meta)


def _make_dataset(path_str: str, scale: list[int]) -> dict[str, Any]:
    return {
        "path": path_str,
        "coordinateTransformations": [{"type": "scale", "scale": scale}],
    }


def _downsample_block(vol: np.ndarray, reducer: str) -> np.ndarray:
    """Mirror ``downsampleBlock`` from the MATLAB fixture.

    Downsample by 2 on the last three axes (c, z, y, x volumes: keep C,
    reduce Z/Y/X). Pad odd axes with edge values so 2x coarsening is
    well-defined on odd extents.
    """
    sz = list(vol.shape)
    out_shape = (sz[0], -(-sz[1] // 2), -(-sz[2] // 2), -(-sz[3] // 2))
    padded = vol
    if sz[1] % 2 == 1:
        padded = np.concatenate([padded, padded[:, -1:, :, :]], axis=1)
    if sz[2] % 2 == 1:
        padded = np.concatenate([padded, padded[:, :, -1:, :]], axis=2)
    if sz[3] % 2 == 1:
        padded = np.concatenate([padded, padded[:, :, :, -1:]], axis=3)
    ps = padded.shape
    p = padded.astype(np.float64)
    reshaped = p.reshape(ps[0], ps[1] // 2, 2, ps[2] // 2, 2, ps[3] // 2, 2)
    if reducer == "mean":
        agg = reshaped.mean(axis=(2, 4, 6))
    else:
        agg = reshaped.max(axis=(2, 4, 6))
    out = np.rint(agg).astype(np.uint16)
    return out[: out_shape[0], : out_shape[1], : out_shape[2], : out_shape[3]]


def _write_chunks(array_dir: Path, vol: np.ndarray, chunks: tuple[int, ...]) -> None:
    """Write ``vol`` under ``array_dir`` as uncompressed C-order chunk files.

    Uses the same ``<c>.<z>.<y>.<x>`` layout the MATLAB fixture writes.
    Uncompressed chunks are enough here because ``zarr.open`` reads them
    via the same code path as any other codec, and skipping Blosc keeps
    the test dependency-free (no zstd binary, no numcodecs.Blosc).
    """
    sz = vol.shape
    n_chunks = tuple(-(-sz[d] // chunks[d]) for d in range(len(sz)))
    dtype = vol.dtype
    for c in range(n_chunks[0]):
        for z in range(n_chunks[1]):
            for y in range(n_chunks[2]):
                for x in range(n_chunks[3]):
                    chunk = np.zeros(chunks, dtype=dtype)
                    src_start = np.array([c, z, y, x]) * np.array(chunks)
                    src_end = np.minimum(src_start + np.array(chunks), np.array(sz))
                    dst_end = src_end - src_start
                    chunk[: dst_end[0], : dst_end[1], : dst_end[2], : dst_end[3]] = vol[
                        src_start[0] : src_end[0],
                        src_start[1] : src_end[1],
                        src_start[2] : src_end[2],
                        src_start[3] : src_end[3],
                    ]
                    key = f"{c}.{z}.{y}.{x}"
                    (array_dir / key).write_bytes(chunk.tobytes(order="C"))


def _write_zarr_array(array_dir: Path, vol: np.ndarray, chunks: tuple[int, ...]) -> None:
    """Write ``vol`` as a zarr v2 array compressed with Blosc+Zstd, via zarr-python.

    Replaces the ``.zarray`` written by :func:`_write_zarray` with zarr-python's
    own, so the metadata and the chunks are both exactly what zarr-python
    produces. Same codec settings as ``makeExampleFixture.m``: Blosc container,
    Zstd, level 5, byte shuffle.
    """
    import zarr
    from numcodecs import Blosc

    kwargs = {
        "mode": "w",
        "shape": vol.shape,
        "chunks": chunks,
        "dtype": "<u2",
        "compressor": Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE),
        "fill_value": 0,
    }
    try:
        arr = zarr.open_array(str(array_dir), zarr_format=2, **kwargs)
    except TypeError:  # zarr 2.x: no zarr_format keyword, and v2 is the default
        arr = zarr.open_array(str(array_dir), **kwargs)
    arr[...] = vol


def make_example_fixture(
    parent_dir: str | Path,
    *,
    with_chunks: bool = False,
    seed: int = 20260906,
    codec: str = "none",
) -> tuple[Path, GroundTruth]:
    """Write a dual-pyramid OME-Zarr store and return its root and ground truth.

    ``codec`` is ``"none"`` (uncompressed chunks written by hand, the default)
    or ``"blosc-zstd"`` (arrays written by zarr-python with Blosc+Zstd). It
    only matters with ``with_chunks``.
    """
    if codec not in ("none", "blosc-zstd"):
        raise ValueError(f'codec must be "none" or "blosc-zstd", not {codec!r}.')
    parent = Path(parent_dir)
    parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = parent / "example.zarr"
    if fixture_dir.exists():
        import shutil

        shutil.rmtree(fixture_dir)
    fixture_dir.mkdir(parents=True)

    dtype = "<u2"

    if with_chunks:
        shape0: tuple[int, ...] = (1, 8, 8, 10)
        chunks0: tuple[int, ...] = (1, 4, 4, 4)
        shape1: tuple[int, ...] = (1, 4, 4, 5)
        chunks1: tuple[int, ...] = (1, 4, 4, 4)
        shape2: tuple[int, ...] = (1, 2, 2, 3)
        chunks2: tuple[int, ...] = (1, 4, 4, 4)
    else:
        shape0 = (1, 256, 256, 256)
        chunks0 = shape0
        shape1 = (1, 128, 128, 128)
        chunks1 = shape1
        shape2 = (1, 64, 64, 64)
        chunks2 = shape2

    _write_zgroup(fixture_dir)
    _write_zarray(fixture_dir / "0", shape0, chunks0, dtype)

    mean_dir = fixture_dir / "mean"
    mean_dir.mkdir()
    _write_zgroup(mean_dir)
    _write_zarray(mean_dir / "1", shape1, chunks1, dtype)
    _write_zarray(mean_dir / "2", shape2, chunks2, dtype)

    max_dir = fixture_dir / "max"
    max_dir.mkdir()
    _write_zgroup(max_dir)
    _write_zarray(max_dir / "1", shape1, chunks1, dtype)
    _write_zarray(max_dir / "2", shape2, chunks2, dtype)

    axes = [
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]

    mean_datasets = [
        _make_dataset("0", [1, 4, 4, 4]),
        _make_dataset("mean/1", [1, 8, 8, 8]),
        _make_dataset("mean/2", [1, 16, 16, 16]),
    ]
    max_datasets = [
        _make_dataset("0", [1, 4, 4, 4]),
        _make_dataset("max/1", [1, 8, 8, 8]),
        _make_dataset("max/2", [1, 16, 16, 16]),
    ]
    multiscales = [
        {"name": "mean", "type": "box", "axes": axes, "datasets": mean_datasets},
        {"name": "max", "type": "max", "axes": axes, "datasets": max_datasets},
    ]
    _write_json(fixture_dir / ".zattrs", {"multiscales": multiscales})

    gt = GroundTruth()
    if not with_chunks:
        return fixture_dir, gt

    rng = np.random.default_rng(seed)
    lvl0 = rng.integers(0, 65536, size=shape0, dtype=np.uint16)

    mean1 = _downsample_block(lvl0, "mean")
    max1 = _downsample_block(lvl0, "max")
    mean2 = _downsample_block(mean1, "mean")
    max2 = _downsample_block(max1, "max")

    write = _write_zarr_array if codec == "blosc-zstd" else _write_chunks
    write(fixture_dir / "0", lvl0, chunks0)
    write(fixture_dir / "mean" / "1", mean1, chunks1)
    write(fixture_dir / "max" / "1", max1, chunks1)
    write(fixture_dir / "mean" / "2", mean2, chunks2)
    write(fixture_dir / "max" / "2", max2, chunks2)

    gt.level0 = lvl0
    gt.mean_level1 = mean1
    gt.max_level1 = max1
    gt.mean_level2 = mean2
    gt.max_level2 = max2
    gt.shape0 = shape0
    gt.chunk_shape0 = chunks0
    gt.dtype = dtype

    return fixture_dir, gt
