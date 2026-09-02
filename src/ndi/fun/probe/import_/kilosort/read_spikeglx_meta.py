"""ndi.fun.probe.import.kilosort.readspikeglxmeta - read a SpikeGLX .meta sidecar.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/readspikeglxmeta.m``
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = ["readspikeglxmeta", "read_spikeglx_meta"]


def readspikeglxmeta(binfile: str | Path) -> tuple[dict[str, Any] | None, str]:
    """Parse the ``.meta`` file beside a raw SpikeGLX recording.

    Returns ``(meta, metafile)``, or ``(None, "")`` when there is no sidecar.
    SpikeGLX writes newline-delimited ``key=value`` text; a value that parses
    whole as a number comes back numeric and everything else as a string. The
    channel count of the raw file is ``nSavedChans``.

    This is how :func:`prompt_raw_binary` learns the READ STRIDE of a
    hand-selected recording, which differs from the channel count of an NDI
    export: a Neuropixels AP band saves 385 channels (384 electrodes plus one
    sync), an NDI export only the electrodes.
    """
    path = Path(binfile)
    metafile = path.with_suffix(".meta")
    if not metafile.is_file():
        return None, ""

    meta: dict[str, Any] = {}
    for raw_line in metafile.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # SpikeGLX prefixes multi-valued keys with '~'; MATLAB strips it to
        # make a valid field name and so do we, so both find 'imroTbl'.
        meta[_valid_name(re.sub(r"^~", "", key.strip()))] = _numeric_or_text(value.strip())

    return meta, str(metafile)


def _valid_name(key: str) -> str:
    """MATLAB's makeValidName, as far as this file needs it."""
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", key)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"x{cleaned}"
    return cleaned


def _numeric_or_text(value: str) -> Any:
    try:
        return float(value)
    except ValueError:
        return value


#: The readable spelling beside MATLAB's.
read_spikeglx_meta = readspikeglxmeta
