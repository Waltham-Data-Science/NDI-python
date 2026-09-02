"""ndi.fun.probe.import.kilosort.binaryinfo - locate the raw binary and its parameters.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/binaryinfo.m``

WHY params.py's ``dat_path`` NEVER OPENS A FILE
Phy records the sorted file's path in ``params.py``, and for data sorted
outside NDI that path routinely names Kilosort's whitened, filtered temporary
file (``temp_wh.dat``) rather than the true raw recording -- a file that is
not the raw data and often no longer exists. It is parsed and RETURNED here,
so a moved sort can be reported ("params.py still points at ..."), and it is
never used to locate a binary. The caller prompts instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = ["binaryinfo", "binary_info", "read_params_py", "METADATA_SUFFIX"]

#: The sidecar ndi.fun.probe.export.binary writes beside an exported binary.
METADATA_SUFFIX = ".metadata"


def binaryinfo(kdir: str | Path, *, binary_file: str | Path = "") -> dict[str, Any]:
    """Find the raw recording for a Kilosort output directory, and how to read it.

    Returns a mapping with ``found``, ``file``, ``num_channels``, ``dtype``,
    ``byteOrder``, ``headerOffsetBytes``, ``multiplier``, ``sample_rate`` and
    ``dat_path``.

    The binary is located from an explicit ``binary_file``, else from the NDI
    export ``.metadata`` sidecar in KDIR or its parent -- and from nothing
    else (see the module docstring). ``found`` is true only when both a file
    and a usable channel count were obtained; without the stride, reading the
    file would produce noise rather than a waveform.
    """
    directory = Path(kdir)
    info: dict[str, Any] = {
        "found": False,
        "file": "",
        "num_channels": float("nan"),
        "dtype": "int16",
        "byteOrder": "ieee-le",
        "headerOffsetBytes": 0,
        "multiplier": 1,
        "sample_rate": float("nan"),
        "dat_path": "",
    }

    binfile = ""
    if binary_file:
        if not Path(binary_file).is_file():
            raise FileNotFoundError(f"Specified binary_file was not found: {binary_file}.")
        binfile = str(binary_file)

    # --- the NDI export '.metadata' sidecar -------------------------------
    search_dirs = [directory]
    parent = directory.parent
    if parent != directory:
        search_dirs.append(parent)

    metafile = ""
    for candidate_dir in search_dirs:
        for candidate in sorted(candidate_dir.glob(f"*{METADATA_SUFFIX}")):
            companion = str(candidate)[: -len(METADATA_SUFFIX)]
            if not Path(companion).is_file():
                continue
            if not binfile:
                binfile = companion
                metafile = str(candidate)
            elif binfile == companion:
                metafile = str(candidate)
        if metafile:
            break

    if metafile:
        sidecar = _read_metadata(metafile)
        for key, field in (
            ("num_channels", "num_channels"),
            ("multiplier", "multiplier"),
            ("epoch_sample_rates", "sample_rate"),
        ):
            value = _first_number(sidecar.get(key))
            if value is not None:
                info[field] = value

    # --- Phy params.py: dtype, offset, sample_rate, dat_path, n_channels ---
    params_path = directory / "params.py"
    if params_path.is_file():
        params = read_params_py(params_path)
        if _isnan(info["num_channels"]) and "n_channels_dat" in params:
            info["num_channels"] = params["n_channels_dat"]
        if params.get("dtype"):
            info["dtype"] = params["dtype"]
        if "offset" in params:
            info["headerOffsetBytes"] = params["offset"]
        if _isnan(info["sample_rate"]) and "sample_rate" in params:
            info["sample_rate"] = params["sample_rate"]
        if params.get("dat_path"):
            info["dat_path"] = params["dat_path"]

    if not binfile or _isnan(info["num_channels"]) or info["num_channels"] < 1:
        return info  # no usable binary AND channel count

    info["file"] = binfile
    info["found"] = True
    return info


def read_params_py(path: str | Path) -> dict[str, Any]:
    """The acquisition parameters Phy writes in ``params.py``.

    A deliberately minimal ``key = value`` reader, as MATLAB's is: the file is
    Python source, but executing a file found in a data directory to read four
    numbers out of it would be a poor trade.
    """
    params: dict[str, Any] = {}
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip()  # drop a trailing comment
        if key == "dat_path":
            params["dat_path"] = _strip_py_string(value)
        elif key == "dtype":
            params["dtype"] = _strip_py_string(value)
        elif key in ("n_channels_dat", "offset", "sample_rate"):
            number = _to_number(value)
            if number is not None:
                params[key] = number
    return params


def _strip_py_string(value: str) -> str:
    """A Python string literal's contents: quotes and an r/b/u prefix removed."""
    text = value.strip()
    if len(text) > 1 and text[0] in "rbu" and text[1] in "'\"":
        text = text[1:]
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        text = text[1:-1]
    return text


def _read_metadata(path: str | Path) -> dict[str, str]:
    """The ``key: value`` lines of an NDI export ``.metadata`` sidecar."""
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = raw_line.partition(":")
        if sep:
            values[key.strip()] = value.strip()
    return values


def _first_number(value: Any) -> float | None:
    """The first number in VALUE, which may be a scalar or a list like ``[1, 2]``.

    The sidecar stores ``epoch_sample_counts`` and ``epoch_sample_rates`` as
    printed lists, so a plain float() will not do.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(value))
    return float(numbers[0]) if numbers else None


def _to_number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _isnan(value: Any) -> bool:
    return isinstance(value, float) and value != value


#: The readable spelling beside MATLAB's.
binary_info = binaryinfo
