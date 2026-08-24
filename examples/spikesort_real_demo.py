#!/usr/bin/env python3
"""
Interactive spike-sorter demo on REAL recorded data.

Loads the real Kilosort2.5/Phy export (a 10-second, 32-channel probe recording,
788 spikes sorted into 13 units) from ~/.cache/ndi/ks_phy_example_0 and opens the
NDI interactive spike-sorter GUI (ndi.app.spikesorter_gui.cluster_spikewaves_gui)
on the real, recorded waveforms.

Each spike's waveform is reconstructed from the real Kilosort template for its
unit, scaled by that spike's real per-spike amplitude, on the electrode channels
where the units actually sit, plus realistic recording noise. The real Kilosort
cluster assignments are pre-loaded, so the GUI opens on the actual 13-unit sort.

In the window you can:
  * zoom / pan every waveform-overlay panel and the feature scatter
    (mouse wheel = zoom, drag = pan, right-drag = box-zoom, 'A' = auto-range),
  * change the feature view (pca3 / 2points) and the scatter X/Y dims,
  * re-run the sort ("Cluster all" -> KMeans or KlustaKwik),
  * merge two clusters, lasso-select points in the feature view to split,
  * relabel each unit's quality and (n/a here, single epoch) its epoch presence,
  * DONE to return the curated (clusterids, clusterinfo), or Cancel.

Usage:
    python3 spikesort_real_demo.py            # open on the real 13-unit sort
    python3 spikesort_real_demo.py --fresh    # open unclustered; you run the sort
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

# The spike-sorter GUI now ships with this package (ndi.app.spikesorter_gui),
# so no sys.path surgery is needed (this file was relocated 2026-07-20 from the
# ndi-projects workspace root, where it prepended now-deleted worktree paths).
# ROOT is used only to locate optional web-app logo assets in the sibling
# ndi-projects workspace; override with NDI_PROJECTS_ROOT. Not required to run.
ROOT = Path(os.environ.get("NDI_PROJECTS_ROOT", os.path.expanduser("~/Documents/ndi-projects")))

PHY = Path(os.path.expanduser("~/.cache/ndi/ks_phy_example_0"))


def build_real_waveforms(noise_frac: float = 0.08, seed: int = 0, oversample: int = 4):
    """Reconstruct per-spike waveforms from the real Phy export.

    Returns (waves, clusterids, info) where waves is
    (NumSamples x NumChannels x NumSpikes), clusterids are 1-based per-spike unit
    ids, and info is a small dict for the banner.
    """
    if not PHY.exists():
        raise SystemExit(
            f"Real Kilosort export not found at {PHY}.\n"
            "Fetch it first (see tests/test_pr12_kilosort_real.py docstring)."
        )
    templates = np.load(PHY / "templates.npy")  # (nUnits, nSamples, nChannels)
    clusters = np.load(PHY / "spike_clusters.npy").ravel().astype(int)  # 0-based unit per spike
    amps = np.load(PHY / "amplitudes.npy").ravel().astype(float)  # per-spike scale

    n_units, n_samples, _n_chan_all = templates.shape

    # Channels that actually carry signal: each unit's peak channel (so every
    # unit shows a real waveform), sorted by electrode index.
    p2p = templates.max(axis=1) - templates.min(axis=1)  # (nUnits, nChannels)
    peak_chan = p2p.argmax(axis=1)
    channels = sorted({int(c) for c in peak_chan})

    n = clusters.size
    waves = np.zeros((n_samples, len(channels), n), dtype=float)
    for i in range(n):
        waves[:, :, i] = templates[clusters[i]][:, channels] * amps[i]

    # realistic additive recording noise (fixed sigma, a fraction of the signal scale)
    rng = np.random.default_rng(seed)
    sigma = noise_frac * float(np.abs(waves).max())
    waves += sigma * rng.standard_normal(waves.shape)

    # Cubic-spline OVERSAMPLE along the sample axis (like the real spike-sort's
    # interpolation step): the displayed waveforms become smooth, so zooming in
    # "sharpens" the spike into a clean curve instead of jagged sample-to-sample
    # segments. order=3 = cubic spline; mode='nearest' avoids edge dips.
    if oversample and oversample > 1:
        from scipy.ndimage import zoom

        waves = zoom(waves, (oversample, 1, 1), order=3, mode="nearest")
    n_samples = waves.shape[0]

    clusterids = (clusters + 1).astype(float)  # 1-based, as the GUI/MATLAB expect
    info = {
        "n_spikes": n,
        "n_units": n_units,
        "n_samples": n_samples,
        "channels": channels,
        "sample_rate": 32000.0,
        "oversample": oversample,
    }
    return waves, clusterids, info


def main() -> None:
    fresh = "--fresh" in sys.argv
    waves, clusterids, info = build_real_waveforms()

    print("=" * 70)
    print("NDI interactive spike sorter -- REAL Kilosort/Phy recording")
    print("=" * 70)
    print(f"  recording   : 10.0 s @ {info['sample_rate']:.0f} Hz, 32-channel probe")
    print(f"  spikes      : {info['n_spikes']}")
    print(f"  units       : {info['n_units']} (Kilosort)")
    print(f"  waveform    : {info['n_samples']} samples x {len(info['channels'])} channels")
    print(f"  channels    : {info['channels']}")
    print(
        f"  mode        : {'FRESH (unclustered -- click Cluster all)' if fresh else 'pre-loaded real 13-unit sort'}"
    )
    print("-" * 70)
    print("  zoom: mouse-wheel | pan: drag | box-zoom: right-drag | auto: 'A'")
    print("  try: Feature pca3<->2points, scatter X/Y dims, Cluster all,")
    print("       Merge two units, Other actions -> lasso split, set Quality, DONE")
    print("=" * 70)

    try:
        from ndi.app.spikesorter_gui import cluster_spikewaves_gui, gui_available
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            f"Could not import the spike-sorter GUI ({exc}).\n"
            "Install NDI-python with the GUI support and PyQt6+pyqtgraph "
            "(pip install PyQt6 pyqtgraph)."
        ) from exc
    if not gui_available():
        raise SystemExit("PyQt6/pyqtgraph not installed -- run: pip install PyQt6 pyqtgraph")

    # NDI logo for the header, if the web-app asset is present.
    logo = None
    for cand in (
        ROOT / "ndi-web-app/app/public/ndiLogoDark.svg",
        ROOT / "ndi-web-app-wds/app/public/ndiLogoDark.svg",
    ):
        if cand.exists():
            logo = str(cand)
            break
    subtitle = (
        f"Kilosort/Phy export · 32-ch probe · 10 s · "
        f"{info['n_spikes']} spikes · {info['n_units']} units"
    )

    clusterids_arg = None if fresh else clusterids
    ids, clusterinfo = cluster_spikewaves_gui(
        waves,
        waveparameters={"samplerate": info["sample_rate"], "S0": 0, "S1": info["n_samples"] - 1},
        clusterids=clusterids_arg,
        epoch_names=["epoch1"],
        epoch_start_samples=[1],
        figure_name="Spike Sorter",
        logo_path=logo,
        subtitle=subtitle,
        force_quality_assessment=False,  # let you DONE without labeling everything
        ask_before_done=True,
    )

    if ids is None:
        print("\nCancelled -- no curated result returned.")
        return
    finite = ids[~np.isnan(ids)]
    n_units = len({int(x) for x in finite})
    print(
        f"\nDONE -- curated into {n_units} unit(s); {int(np.isnan(ids).sum())} spike(s) left unclassified."
    )
    for ci in clusterinfo:
        print(
            f"  unit {ci['number']:>3}: N={ci['number_of_spikes']:>4}  quality={ci['qualitylabel']}"
        )


if __name__ == "__main__":
    main()
