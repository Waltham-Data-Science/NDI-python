"""
ndi.fun.probe.import_.kilosort.session - import curated Kilosort results for all probes.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/session.m

NAMING DIVERGENCE: the MATLAB package is ``+ndi/+fun/+probe/+import/+kilosort``.
``import`` is a reserved word in Python, so the subpackage directory is named
``import_`` and the importable path is ``ndi.fun.probe.import_.kilosort.session``.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from .probe import probe as import_probe


def session(
    session: Any,
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,
    quality_labels: list[str] | tuple[str, ...] = ("good", "mua"),
    quality_values: list[float] | tuple[float, ...] = (1, 4),
    waveform_source: str = "templates",
    force: bool = False,
    dryRun: bool = False,
    verbose: bool = True,
) -> None:
    """Import curated Kilosort results for every n-trode probe in a session.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.session``

    For each ``'n-trode'`` probe in *session*, imports the curated Kilosort spike
    sorting results by calling :func:`ndi.fun.probe.import_.kilosort.probe`. This
    is the import-side analog of ``ndi.fun.probe.export.all_binary``.

    The Kilosort output for each probe is expected in
    ``[session.path]/[kilosort_dir]/[probe_elementstring]/[subdir]/`` (the same
    layout produced by the binary export). Probes whose kilosort directory or
    curated files are missing are skipped with a warning.

    Takes the same keyword arguments as
    :func:`ndi.fun.probe.import_.kilosort.probe`.

    Args:
        session: The ndi.session.
        kilosort_dir: Name of the directory holding the kilosort output.
        subdir: Subfolder within each probe's directory holding the curated files.
        noSubFolder: If ``True``, ignore *subdir* and read directly from the
            probe's directory.
        quality_labels: Curation labels to import.
        quality_values: ``quality_number`` for each label (parallel array).
        waveform_source: ``'templates'`` or ``'none'``.
        force: Re-import even if the checksum is unchanged.
        dryRun: Report what would be imported without changing the database.
        verbose: ``True``/``False`` should we be verbose.
    """
    sess = session  # local alias; the parameter shadows the module name

    if verbose:
        print(f"Looking for n-trode probes in {sess.reference}...")
    probe_list = sess.getprobes(type="n-trode")
    if verbose:
        print(f"Found {len(probe_list)} probe(s) of type 'n-trode'.")

    eff_subdir = "" if noSubFolder else subdir

    for p in probe_list:
        elestr = p.elementstring().replace(" ", "_")
        kdir = Path(sess.path) / kilosort_dir / elestr / eff_subdir
        if not kdir.is_dir() or not (kdir / "spike_times.npy").is_file():
            warnings.warn(
                f"Skipping probe {elestr}: no kilosort output found in {kdir}.",
                stacklevel=2,
            )
            continue
        import_probe(
            sess,
            p,
            kilosort_dir=kilosort_dir,
            subdir=subdir,
            noSubFolder=noSubFolder,
            quality_labels=quality_labels,
            quality_values=quality_values,
            waveform_source=waveform_source,
            force=force,
            dryRun=dryRun,
            verbose=verbose,
        )

    if verbose:
        print(f"Done importing kilosort results for {sess.reference}.")
