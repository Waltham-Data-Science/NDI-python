"""ndi.fun.probe.import.kilosort.getInfo - summarize a sort without importing it.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/getInfo.m``
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .binary_info import binaryinfo
from .labels import labels as read_labels

__all__ = ["getInfo", "get_info", "kilosort_directory", "DEFAULT_QUALITY_LABELS"]

#: The curation tags the importer keeps by default.
DEFAULT_QUALITY_LABELS = ("good", "mua")


def kilosort_directory(
    session: Any,
    probe: Any,
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
) -> str:
    """Where a probe's curated Kilosort output lives.

    ``[session.path]/[kilosort_dir]/[probe_directory]/[subdir]`` -- the layout
    ``ndi.fun.probe.export.all_binary`` writes to, so an import reads back
    from where the export put things. The probe folder name comes from
    ``ndi.fun.file.elementDirectory``, which also finds folders written under
    the older ``|`` separator.

    Shared by :func:`getInfo` and the importer so the two can never disagree
    about which directory they are talking about.
    """
    from ....file import elementDirectory

    probe_dir, _, _ = elementDirectory(Path(_session_path(session)) / kilosort_dir, probe)
    if noSubFolder:
        subdir = ""
    return str(Path(probe_dir) / subdir) if subdir else str(probe_dir)


def getInfo(  # noqa: N802 - MATLAB's function name
    session: Any,
    probe: Any,
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
    binary_file: str = "",
) -> tuple[dict[str, Any], str]:
    """What is in a probe's Kilosort/Phy output, without touching the database.

    Returns ``(info, summary)``. INFO describes the clusters, their tags and
    spike counts, which of them the quality filter would import, the template
    dimensions, and whether the raw binary the importer would read can be
    located. SUMMARY is the same thing as text.

    This is what the spikeSorterImporter's right-hand pane shows, and what
    lets someone inspect a sort before committing it.
    """
    kdir = kilosort_directory(
        session, probe, kilosort_dir=kilosort_dir, subdir=subdir, noSubFolder=noSubFolder
    )
    directory = Path(kdir)
    if not directory.is_dir():
        raise FileNotFoundError(f"Kilosort directory not found: {kdir}.")

    spike_times_file = directory / "spike_times.npy"
    spike_clusters_file = directory / "spike_clusters.npy"
    if not spike_times_file.is_file() or not spike_clusters_file.is_file():
        raise FileNotFoundError(
            f"Expected curated files spike_times.npy and spike_clusters.npy in {kdir}."
        )

    spike_clusters = np.load(spike_clusters_file).astype(float).ravel()
    cluster_ids, cluster_labels = read_labels(directory)

    n_clusters = int(cluster_ids.size)
    num_spikes = np.array([int(np.sum(spike_clusters == cid)) for cid in cluster_ids], dtype=int)

    unique_tags = sorted(set(cluster_labels))
    tag_counts = [cluster_labels.count(tag) for tag in unique_tags]

    wanted = {str(label).lower() for label in quality_labels}
    would_import = np.array([str(label).lower() in wanted for label in cluster_labels], dtype=bool)

    num_templates = float("nan")
    num_channels = float("nan")
    samples_per_template = float("nan")
    templates_file = directory / "templates.npy"
    if templates_file.is_file():
        shape = np.load(templates_file, mmap_mode="r").shape
        num_templates = shape[0]
        if len(shape) >= 2:
            samples_per_template = shape[1]
        if len(shape) >= 3:
            num_channels = shape[2]

    bininfo = binaryinfo(directory, binary_file=binary_file)

    info: dict[str, Any] = {
        "directory": kdir,
        "num_clusters": n_clusters,
        "cluster_ids": cluster_ids,
        "cluster_labels": cluster_labels,
        "unique_tags": unique_tags,
        "tag_counts": tag_counts,
        "num_spikes_total": int(num_spikes.sum()) if num_spikes.size else 0,
        "num_spikes": num_spikes,
        "would_import": would_import,
        "num_would_import": int(would_import.sum()),
        "num_templates": num_templates,
        "num_channels": num_channels,
        "samples_per_template": samples_per_template,
        "binary_found": bininfo["found"],
        "binary_file": bininfo["file"],
        "binary_dat_path": bininfo["dat_path"],
        "binary_num_channels": bininfo["num_channels"],
    }
    return info, summarize(info, probe, quality_labels)


def summarize(
    info: dict[str, Any], probe: Any, quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS
) -> str:
    """INFO as the multiline text MATLAB's second output returns."""
    num_spikes = np.asarray(info["num_spikes"])
    lines = [
        f"Kilosort/Phy summary for probe '{probe.elementstring()}'",
        f"  Directory:        {info['directory']}",
        f"  Clusters:         {info['num_clusters']}",
        f"  Total spikes:     {info['num_spikes_total']}",
    ]
    if info["num_clusters"] > 0:
        lines.append(
            f"  Spikes/cluster:   min {int(num_spikes.min())}, "
            f"median {int(round(float(np.median(num_spikes))))}, max {int(num_spikes.max())}"
        )
    lines.append("  Tags:")
    for tag, count in zip(info["unique_tags"], info["tag_counts"]):
        lines.append(f"     {tag}: {count} cluster(s)")
    lines.append(
        f"  Would import ({', '.join(str(x) for x in quality_labels)}): "
        f"{info['num_would_import']} of {info['num_clusters']} cluster(s)"
    )
    if info["num_templates"] == info["num_templates"]:  # not NaN
        lines.append(
            f"  Templates:        {info['num_templates']} templates, "
            f"{info['num_channels']} channels, {info['samples_per_template']} samples each"
        )
    else:
        lines.append("  Templates:        (templates.npy not present)")

    if info["binary_found"]:
        channels = info["binary_num_channels"]
        suffix = f" ({channels:g} channels)" if channels == channels else ""
        lines.append(f"  Raw binary:       found: {info['binary_file']}{suffix}")
    else:
        lines.append("  Raw binary:       NOT FOUND automatically (no .metadata sidecar).")
        lines.append("                      The importer will PROMPT for the raw recording and")
        lines.append("                      its Neuropixels generation, then high-pass filter it")
        lines.append("                      to recalculate wide mean waveforms. Pass binary_file /")
        lines.append("                      RawFile to skip the prompt.")
        if info["binary_dat_path"]:
            lines.append(
                f"                      (params.py dat_path names {info['binary_dat_path']} "
                "- not used; it often names a"
            )
            lines.append("                       whitened/filtered temp file.)")
    return "\n".join(lines)


def _session_path(session: Any) -> str:
    """SESSION's directory, however it reports one."""
    getpath = getattr(session, "getpath", None)
    if callable(getpath):
        return str(getpath())
    return str(getattr(session, "path", ""))


#: The readable spelling beside MATLAB's.
get_info = getInfo
