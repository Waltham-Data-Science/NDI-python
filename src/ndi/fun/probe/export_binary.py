"""
ndi.fun.probe.export_binary - the older names for the binary exporters.

MATLAB once had ``+ndi/+fun/+probe/export_binary.m`` and
``export_all_binary.m``; it has since moved both into the
``+ndi/+fun/+probe/+export/`` package as ``binary`` and ``all_binary``, and
grown ``autoMultiplier`` and ``oneProbe`` beside them. :mod:`ndi.fun.probe.export`
is the port of that package.

These two names stay, bound to those functions, so code written against the
earlier port keeps working; they are not a second implementation. New code
should call :func:`ndi.fun.probe.export.binary` and
:func:`ndi.fun.probe.export.all_binary`, which take the further arguments
(``noBinary``, ``progressfcn``, the output file name) that this shape cannot
express.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .export import INTAN_MULTIPLIER, all_binary, binary

__all__ = ["export_binary", "export_all_binary"]


def export_binary(
    probe: Any,
    outputfile: str | Path,
    *,
    multiplier: float = 1.0,
    verbose: bool = True,
    precision: str = "int16",
) -> None:
    """Export data from a probe to a binary file.

    The earlier name for :func:`ndi.fun.probe.export.binary`, which this
    calls; see it for what the multiplier means and what the ``.metadata``
    sidecar holds.
    """
    binary(
        probe,
        outputfile,
        multiplier=multiplier,
        verbose=verbose,
        precision=precision,
    )


def export_all_binary(
    session: Any,
    *,
    kilosort_dir: str = "kilosort",
    verbose: bool = True,
    multiplier: float = INTAN_MULTIPLIER,
) -> None:
    """Export all n-trode probes in a session to binary files.

    The earlier name for :func:`ndi.fun.probe.export.all_binary`, which this
    calls with ``binary_dir=kilosort_dir``.
    """
    all_binary(
        session,
        binary_dir=kilosort_dir,
        verbose=verbose,
        multiplier=multiplier,
    )
