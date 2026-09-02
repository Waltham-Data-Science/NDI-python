"""ndi.fun.probe.import.kilosort.session - import every n-trode probe in a session.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/session.m``

The import-side analog of ``ndi.fun.probe.export.all_binary``: it walks the
session's n-trode probes and imports whatever curated Kilosort output each one
has. A probe with no output is SKIPPED WITH A WARNING rather than failing the
run, because a session commonly has some probes sorted and some not, and the
sorted ones are still worth importing.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .get_info import DEFAULT_QUALITY_LABELS, kilosort_directory
from .probe import DEFAULT_QUALITY_VALUES
from .probe import probe as import_probe

__all__ = ["session", "NTRODE_TYPE"]

#: The probe type Kilosort output is expected for.
NTRODE_TYPE = "n-trode"


def session(
    S: Any,  # noqa: N803 - MATLAB's parameter name
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
    quality_values: Sequence[float] = DEFAULT_QUALITY_VALUES,
    verbose: bool = True,
    **options: Any,
) -> int:
    """Import curated Kilosort results for every n-trode probe in S.

    Returns the total number of neurons imported. Extra keyword arguments are
    passed through to :func:`ndi.fun.probe.import_.kilosort.probe.probe`, so
    the two take the same options.
    """
    if verbose:
        print(f"Looking for n-trode probes in {S.reference}...")
    probes = S.getprobes(type=NTRODE_TYPE) or []
    if verbose:
        print(f"Found {len(probes)} probe(s) of type '{NTRODE_TYPE}'.")

    total = 0
    for probe_obj in probes:
        kdir = Path(
            kilosort_directory(
                S, probe_obj, kilosort_dir=kilosort_dir, subdir=subdir, noSubFolder=noSubFolder
            )
        )
        if not kdir.is_dir() or not (kdir / "spike_times.npy").is_file():
            warnings.warn(
                f"Skipping probe {probe_obj.elementstring()}: no kilosort output found "
                f"in {kdir}.",
                stacklevel=2,
            )
            continue
        total += import_probe(
            S,
            probe_obj,
            kilosort_dir=kilosort_dir,
            subdir=subdir,
            noSubFolder=noSubFolder,
            quality_labels=quality_labels,
            quality_values=quality_values,
            verbose=verbose,
            **options,
        )

    if verbose:
        print(f"Done importing kilosort results for {S.reference}.")
    return total
