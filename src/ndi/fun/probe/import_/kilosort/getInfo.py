"""
ndi.fun.probe.import_.kilosort.getInfo - summarize the kilosort/phy output for a probe.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/getInfo.m

NAMING DIVERGENCE: ``import`` is a reserved word in Python, so the subpackage
directory is named ``import_`` (see this package's ``__init__``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ndi.fun.file import elementDirectory

from .labels import labels


def getInfo(
    session: Any,
    probe: Any,
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,
    quality_labels: list[str] | tuple[str, ...] = ("good", "mua"),
) -> tuple[dict[str, Any], str]:
    """Summarize the curated Kilosort/Phy output directory for a probe.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.getInfo``

    Reads the curated Kilosort/Phy output directory for *probe* in the session
    *session* and returns a summary of what is there (without importing anything
    or touching the database). The directory is located the same way as the
    importer: ``[session.path]/[kilosort_dir]/[probe_directory]/[subdir]/``.

    The ``[probe_directory]`` name comes from
    :func:`ndi.fun.file.elementDirectoryName`; for a probe named ``'ctx'`` with
    reference 1 it is ``'ctx_-_1'``. Folders written by older versions of NDI,
    which used a ``'|'`` separator (``'ctx_|_1'``), are still found and used if
    they are present.

    Args:
        session: The ndi.session.
        probe: The ndi.probe / ndi.element to inspect.
        kilosort_dir: Name of the directory holding the kilosort output.
        subdir: Subfolder within the probe's directory holding the curated files.
        noSubFolder: If ``True``, read directly from the probe's directory.
        quality_labels: Labels that would be imported (drives ``would_import``).

    Returns:
        Tuple ``(info, summary)``. ``info`` is a dict with keys ``directory``,
        ``num_clusters``, ``cluster_ids``, ``cluster_labels``, ``unique_tags``,
        ``tag_counts``, ``num_spikes_total``, ``num_spikes``, ``would_import``,
        ``num_would_import``, ``num_templates``, ``num_channels``, and
        ``samples_per_template``. ``num_templates`` / ``num_channels`` /
        ``samples_per_template`` are ``None`` (MATLAB NaN) when ``templates.npy``
        is absent. ``summary`` is a multiline human-readable string.

    Raises:
        FileNotFoundError: If the kilosort directory or the required curated
            files (``spike_times.npy`` and ``spike_clusters.npy``) are missing.
    """
    # Step 1: locate the kilosort output directory (same logic as the importer)
    probedir, _elestr, _is_legacy = elementDirectory(Path(session.path) / kilosort_dir, probe)
    eff_subdir = "" if noSubFolder else subdir
    kdir = probedir / eff_subdir

    if not kdir.is_dir():
        raise FileNotFoundError(f"Kilosort directory not found: {kdir}.")

    spike_times_file = kdir / "spike_times.npy"
    spike_clusters_file = kdir / "spike_clusters.npy"
    if not spike_times_file.is_file() or not spike_clusters_file.is_file():
        raise FileNotFoundError(
            f"Expected curated files spike_times.npy and spike_clusters.npy in {kdir}."
        )

    # Step 2: read the curated output (readNPY -> numpy.load)
    spike_clusters = np.load(spike_clusters_file).astype(np.float64).ravel()
    cluster_ids, cluster_labels = labels(kdir)
    n_clusters = len(cluster_ids)

    # Step 3: spike counts per cluster
    num_spikes = [int(np.sum(spike_clusters == cid)) for cid in cluster_ids]

    # Step 4: unique tags and their cluster counts (sorted, mirroring MATLAB unique)
    unique_tags = sorted(set(cluster_labels))
    tag_counts = [cluster_labels.count(tag) for tag in unique_tags]

    # Step 5: which clusters would be imported under the quality filter
    want = {str(s).lower() for s in quality_labels}
    would_import = [str(lbl).lower() in want for lbl in cluster_labels]

    # Step 6: template dimensions, if templates are present
    num_templates: int | None = None
    num_channels: int | None = None
    samples_per_template: int | None = None
    tfile = kdir / "templates.npy"
    if tfile.is_file():
        templates = np.load(tfile)
        sz = templates.shape
        num_templates = int(sz[0])
        if len(sz) >= 2:
            samples_per_template = int(sz[1])
        if len(sz) >= 3:
            num_channels = int(sz[2])

    # Step 7: assemble the info structure
    info: dict[str, Any] = {
        "directory": str(kdir),
        "num_clusters": n_clusters,
        "cluster_ids": list(cluster_ids),
        "cluster_labels": list(cluster_labels),
        "unique_tags": unique_tags,
        "tag_counts": tag_counts,
        "num_spikes_total": int(sum(num_spikes)),
        "num_spikes": num_spikes,
        "would_import": would_import,
        "num_would_import": int(sum(would_import)),
        "num_templates": num_templates,
        "num_channels": num_channels,
        "samples_per_template": samples_per_template,
    }

    # Step 8: build the multiline summary
    lines: list[str] = []
    lines.append(f"Kilosort/Phy summary for probe '{probe.elementstring()}'")
    lines.append(f"  Directory:        {kdir}")
    lines.append(f"  Clusters:         {n_clusters}")
    lines.append(f"  Total spikes:     {info['num_spikes_total']}")
    if n_clusters > 0:
        lines.append(
            f"  Spikes/cluster:   min {min(num_spikes)}, "
            f"median {int(round(float(np.median(num_spikes))))}, "
            f"max {max(num_spikes)}"
        )
    lines.append("  Tags:")
    for tag, count in zip(unique_tags, tag_counts):
        lines.append(f"     {tag}: {count} cluster(s)")
    lines.append(
        f"  Would import ({', '.join(quality_labels)}): "
        f"{info['num_would_import']} of {n_clusters} cluster(s)"
    )
    if num_templates is not None:
        lines.append(
            f"  Templates:        {num_templates} templates, "
            f"{num_channels} channels, {samples_per_template} samples each"
        )
    else:
        lines.append("  Templates:        (templates.npy not present)")

    summary = "\n".join(lines)

    return info, summary
