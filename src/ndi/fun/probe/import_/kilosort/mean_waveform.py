"""ndi.fun.probe.import.kilosort.meanwaveform - a cluster's template waveform.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/meanwaveform.m``
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["meanwaveform", "mean_waveform"]


def meanwaveform(
    cid: float,
    spike_clusters: Any,
    spike_templates: Any,
    amplitudes: Any,
    templates: Any,
    winv: Any = None,
) -> np.ndarray:
    """The amplitude-weighted mean waveform of cluster CID, nSamples x nChannels.

    A curated cluster may span several Kilosort templates once merges are
    applied, so the waveform is the AMPLITUDE-WEIGHTED average of every
    template that contributes spikes to the cluster: each contributing
    template is weighted by the summed spike amplitudes assigned to it within
    this cluster. The result is scaled by the cluster's mean spike amplitude
    so its magnitude means something, and un-whitened by WINV when one is
    supplied and conformable.

    A cluster with no spikes gets zeros, which is what MATLAB returns and what
    keeps the document's declared waveform size honest.
    """
    spike_clusters = np.asarray(spike_clusters, dtype=float).ravel()
    spike_templates = np.asarray(spike_templates, dtype=float).ravel()
    amplitudes = np.asarray(amplitudes, dtype=float).ravel()
    templates = np.asarray(templates, dtype=float)

    n_samples = templates.shape[1] if templates.ndim >= 2 else 0
    n_channels = templates.shape[2] if templates.ndim >= 3 else 0

    selected = np.flatnonzero(spike_clusters == cid)
    if selected.size == 0:
        return np.zeros((n_samples, n_channels))

    template_ids = spike_templates[selected]  # 0-based, as Kilosort writes them
    spike_amplitudes = amplitudes[selected]

    weighted = np.zeros((n_samples, n_channels))
    weight_total = 0.0
    for template_id in np.unique(template_ids):
        contributing = template_ids == template_id
        weight = float(np.sum(spike_amplitudes[contributing]))
        weighted = weighted + weight * templates[int(template_id), :, :]
        weight_total += weight

    result = weighted / weight_total if weight_total > 0 else weighted
    result = result * float(np.mean(spike_amplitudes))

    if winv is not None:
        winv = np.asarray(winv, dtype=float)
        if winv.ndim == 2 and winv.shape[0] == n_channels and winv.shape[1] == n_channels:
            result = result @ winv

    return result


#: The readable spelling beside MATLAB's.
mean_waveform = meanwaveform
