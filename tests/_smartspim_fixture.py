"""Programmatic SmartSPIM fixture (copied from NDR-python tests/_smartspim_fixture.py).

Python mirror of ``+ndr/+test/+format/+smartspim/makeExampleFixture.m``.

Builds a synthetic LifeCanvas SmartSPIM acquisition directory on disk:
one root directory holding ``metadata.json``, ``sequence.json``, and one
``"Ex_<laser>_Em_<filter>_Ch<n>"`` channel directory per channel. Each
channel folder holds ``xml_import.xml``, ``xml_merging.xml``, and one
tile directory per stack; each tile directory holds a small stack of
zero-padded 2D TIFF z-slices with pixel_value = 100*channelIndex + z.

With ``all_channels=True`` it also writes an ``All_Channels`` folder
shaped like SmartSPIM AutoStitch's stitched output: one LZW-compressed
106x13 uint16 TIFF per (z, channel) named
``200000_100000_<z*10>_ch<k>.tiff`` plus ``ImageList.txt``, with
pixel_value = 1000*(k + 1) + z. No ``_MIP_stitched`` folders are written,
so ``k`` follows the filter-channel rank (Ch2 -> ch0, Ch3 -> ch1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

_NUM_SLICES = 4
_HEIGHT = 8
_WIDTH = 10
_VOXEL_V = 4
_VOXEL_H = 4
_VOXEL_D = 1

_CHANNELS = [
    {
        "name": "Ex_561_Em_561F_Ch2",
        "laser": 561,
        "filter": "561F",
        "chNum": 2,
        "left": 45,
        "right": 45,
    },
    {
        "name": "Ex_640_Em_640F_Ch3",
        "laser": 640,
        "filter": "640F",
        "chNum": 3,
        "left": 40,
        "right": 40,
    },
]

_STACKS_IMPORT = [
    {"row": 0, "col": 0, "absV": 0, "absH": 0, "absD": 0, "dirName": "100000/100000_200000"},
    {"row": 1, "col": 0, "absV": 100, "absH": 0, "absD": 0, "dirName": "100000/100000_300000"},
]
_STACKS_MERGING = [
    {"row": 0, "col": 0, "absV": 2, "absH": 1, "absD": 0, "dirName": "100000/100000_200000"},
    {"row": 1, "col": 0, "absV": 98, "absH": 3, "absD": 0, "dirName": "100000/100000_300000"},
]


def _stitcher_xml(stacks: list[dict[str, Any]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8" ?>']
    lines.append('<!DOCTYPE TeraStitcher SYSTEM "TeraStitcher.DTD">')
    lines.append('<TeraStitcher volume_format="TiledXY|2Dseries" input_plugin="tiff2D">')
    lines.append('    <stacks_dir value="." />')
    lines.append('    <mdata_bin value="./mdata.bin" />')
    lines.append('    <ref_sys ref1="2" ref2="1" ref3="3" />')
    lines.append(f'    <voxel_dims V="{_VOXEL_V}" H="{_VOXEL_H}" D="{_VOXEL_D}" />')
    lines.append('    <origin V="0" H="0" D="0" />')
    lines.append('    <mechanical_displacements V="100" H="100" />')
    lines.append(
        f'    <dimensions stack_rows="{len(stacks)}" stack_columns="1" '
        f'stack_slices="{_NUM_SLICES}" />'
    )
    lines.append("    <STACKS>")
    for s in stacks:
        lines.append(
            f'        <Stack N_CHANS="1" N_BYTESxCHAN="2" ROW="{s["row"]}" COL="{s["col"]}" '
            f'ABS_V="{s["absV"]}" ABS_H="{s["absH"]}" ABS_D="{s["absD"]}" STITCHABLE="no" '
            f'DIR_NAME="{s["dirName"]}" Z_RANGES="[0,{_NUM_SLICES})" IMG_REGEX="">'
        )
        lines.append("            <NORTH_displacements />")
        lines.append("            <EAST_displacements />")
        lines.append("            <SOUTH_displacements />")
        lines.append("            <WEST_displacements />")
        lines.append("        </Stack>")
    lines.append("    </STACKS>")
    lines.append("</TeraStitcher>")
    return "\n".join(lines)


def _extract_y(second: str, x_str: str) -> str:
    prefix = x_str + "_"
    if second.startswith(prefix):
        return second[len(prefix) :]
    parts = second.split("_")
    return parts[-1]


def _metadata(channels: list[dict[str, Any]], stacks: list[dict[str, Any]]) -> dict[str, Any]:
    laser_power = [
        {"wavelength": c["laser"], "left___": c["left"], "right___": c["right"]} for c in channels
    ]
    tiles = []
    for c in channels:
        for s in stacks:
            parts = s["dirName"].split("/")
            x_str = parts[0]
            y_str = _extract_y(parts[1], x_str)
            tiles.append(
                {
                    "X": x_str,
                    "Y": y_str,
                    "Z": "-1000",
                    "Laser": str(c["laser"]),
                    "Side": str(0 if s["row"] % 2 == 0 else 1),
                    "Exposure": "2",
                    "Acquire": "1",
                    "Filter": c["filter"],
                    "FilterChannel": str(c["chNum"]),
                    "NumImages": str(_NUM_SLICES),
                }
            )
    sample_metadata = {
        "acquisition_ID": "test_acquisition_001",
        "objective": "LCT 1.625x",
        "um_per_pix": 4,
        "z_step_um": 4,
        "horizontal_resolution": _WIDTH,
        "vertical_resolution": _HEIGHT,
        "z_range": -100.0,
        "scanning": "FAST",
        "destripe": "256/0",
        "destripe_status": "done",
        "laser_power": laser_power,
    }
    return {"sample_metadata": sample_metadata, "tiles": tiles}


def _sequence(channels: list[dict[str, Any]]) -> dict[str, Any]:
    laser_power = [
        {"wavelength": c["laser"], "left___": c["left"], "right___": c["right"]} for c in channels
    ]
    imaging_steps = [{"laser": c["laser"], "filter": c["filter"]} for c in channels]
    z_section = {
        "step_size__um_": 4,
        "top__um_": -100.0,
        "bottom__um_": 100.0,
        "default_step_size": True,
    }
    tile_boundary = {
        "top__pix_": 10.0,
        "left__pix_": 5.0,
        "bottom__pix_": 90.0,
        "right__pix_": 95.0,
        "left_right_split__pix_": 50.0,
    }
    focus_points = [
        {
            "objective": "LCT 1.625x",
            "wavelength": 561,
            "z_position": [-50, 50],
            "focus_position": [-10, -12],
        }
    ]
    step = {
        "GUID": "TEST-GUID-0001",
        "name": "test_acquisition",
        "disabled": False,
        "destripe": True,
        "z": z_section,
        "imaging_steps": imaging_steps,
        "laser_power": laser_power,
        "tile_boundary": tile_boundary,
        "focus_points": focus_points,
    }
    return {"objective": "LCT 1.625x", "immersion": "1.52+", "steps": [step]}


_STITCHED_HEIGHT = 106  # xml_merging.xml mosaic of the two tiles: 98 + 8 rows
_STITCHED_WIDTH = 13  # and 3 + 10 columns


def _write_all_channels(fixture_dir: Path, num_channels: int) -> None:
    import tifffile

    all_dir = fixture_dir / "All_Channels"
    all_dir.mkdir()
    names = []
    for k in range(num_channels):
        for z in range(_NUM_SLICES):
            img = np.full((_STITCHED_HEIGHT, _STITCHED_WIDTH), 1000 * (k + 1) + z, dtype=np.uint16)
            name = f"200000_100000_{z * 10:06d}_ch{k}.tiff"
            tifffile.imwrite(all_dir / name, img, compression="lzw")
            names.append(name)
    (all_dir / "ImageList.txt").write_text("\n".join(names))


def make_example_fixture(parent_dir: str | Path, *, all_channels: bool = False) -> Path:
    """Write a synthetic SmartSPIM directory and return its root path.

    Pixel values encode ``(channelIndex, z)`` so tests can verify a read
    hits the right slice: ``pixel_value(channelIndex, z) = 100 *
    channelIndex + z``, where ``channelIndex`` is 1-based (matching MATLAB).
    """
    try:
        import tifffile
    except ImportError as err:  # pragma: no cover
        raise ImportError("tifffile is required for the smartspim fixture") from err

    parent = Path(parent_dir)
    parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = parent / "BOTTOM"
    if fixture_dir.exists():
        import shutil

        shutil.rmtree(fixture_dir)
    fixture_dir.mkdir(parents=True)

    import_xml = _stitcher_xml(_STACKS_IMPORT)
    merging_xml = _stitcher_xml(_STACKS_MERGING)

    for ci, c in enumerate(_CHANNELS, start=1):
        ch_dir = fixture_dir / c["name"]
        ch_dir.mkdir()
        (ch_dir / "xml_import.xml").write_text(import_xml)
        (ch_dir / "xml_merging.xml").write_text(merging_xml)
        for s in _STACKS_IMPORT:
            tile_dir = ch_dir
            for part in [p for p in s["dirName"].split("/") if p]:
                tile_dir = tile_dir / part
            tile_dir.mkdir(parents=True, exist_ok=True)
            for z in range(_NUM_SLICES):
                img = np.full((_HEIGHT, _WIDTH), 100 * ci + z, dtype=np.uint16)
                tifffile.imwrite(tile_dir / f"{z:06d}.tiff", img)

    (fixture_dir / "metadata.json").write_text(json.dumps(_metadata(_CHANNELS, _STACKS_IMPORT)))
    (fixture_dir / "sequence.json").write_text(json.dumps(_sequence(_CHANNELS)))

    if all_channels:
        _write_all_channels(fixture_dir, len(_CHANNELS))

    return fixture_dir
