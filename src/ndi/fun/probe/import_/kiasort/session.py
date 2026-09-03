"""ndi.fun.probe.import.kiasort.session - import every n-trode probe in a session.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/session.m``

The import-side analog of ``ndi.fun.probe.export.all_binary``: it walks the
session's n-trode probes and imports whatever KIASORT output each one has. A
probe with no output is SKIPPED WITH A WARNING rather than failing the run,
because a session commonly has some probes sorted and some not, and the
sorted ones are still worth importing.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .get_info import DEFAULT_QUALITY_LABELS, kiasort_directory
from .probe import DEFAULT_QUALITY_VALUES
from .probe import probe as import_probe
from .results import RES_SORTED

__all__ = ["session", "NTRODE_TYPE"]

#: The probe type KIASORT output is expected for.
NTRODE_TYPE = "n-trode"


def session(
    S: Any,  # noqa: N803 - MATLAB's parameter name
    *,
    kiasort_dir: str = "kiasort",
    subdir: str = "kiasort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
    quality_values: Sequence[float] = DEFAULT_QUALITY_VALUES,
    verbose: bool = True,
    **options: Any,
) -> int:
    """Import KIASORT results for every n-trode probe in S; returns neurons imported.

    Further keyword arguments go to :func:`.probe.probe` unchanged
    (``curated``, ``waveform_source``, ``force``, ``dryRun``, ...).

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.session``.
    """
    if verbose:
        print(f"Looking for {NTRODE_TYPE} probes in {S.reference}...")
    probe_list = S.getprobes(type=NTRODE_TYPE) or []
    if verbose:
        print(f"Found {len(probe_list)} probe(s) of type '{NTRODE_TYPE}'.")

    total = 0
    for probe_obj in probe_list:
        kdir, element_string = kiasort_directory(
            S, probe_obj, kiasort_dir=kiasort_dir, subdir=subdir, noSubFolder=noSubFolder
        )
        if not (Path(kdir) / RES_SORTED).is_dir():
            warnings.warn(
                f"Skipping probe {element_string}: no KIASORT output found in "
                f"{Path(kdir) / RES_SORTED}.",
                stacklevel=2,
            )
            continue
        total += import_probe(
            S,
            probe_obj,
            kiasort_dir=kiasort_dir,
            subdir=subdir,
            noSubFolder=noSubFolder,
            quality_labels=quality_labels,
            quality_values=quality_values,
            verbose=verbose,
            **options,
        )

    if verbose:
        print(f"Done importing KIASORT results for {S.reference}.")
    return total
