"""
ndi.fun.probe.import_.kilosort.meanwaveform - amplitude-weighted mean waveform for a cluster.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/meanwaveform.m

NAMING DIVERGENCE: ``import`` is a reserved word in Python, so the subpackage
directory is named ``import_`` (see this package's ``__init__``).
"""

from __future__ import annotations

import numpy as np


def meanwaveform(
    cid: int,
    spike_clusters: np.ndarray,
    spike_templates: np.ndarray,
    amplitudes: np.ndarray,
    templates: np.ndarray,
    winv: np.ndarray | None,
) -> np.ndarray:
    """Compute the amplitude-weighted mean waveform (nSamples x nChannels) for a cluster.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.meanwaveform``

    Because a curated cluster may span several kilosort templates (after
    merges), the waveform is computed as the AMPLITUDE-WEIGHTED AVERAGE of every
    template that contributes spikes to the cluster: each contributing template
    is weighted by the sum of the spike amplitudes assigned to it within this
    cluster. The result is then scaled by the cluster's mean spike amplitude so
    the waveform has a meaningful magnitude, and, if an inverse whitening matrix
    *winv* is provided, un-whitened into (approximately) physical units.

    Indexing note (MATLAB->Python parity): ``spike_templates`` holds 0-based
    template ids. MATLAB indexes ``templates(ut(k)+1, :, :)`` (converting the
    0-based id to a 1-based MATLAB row). In Python the 0-based id indexes
    ``templates[ut[k], :, :]`` directly, with no +1 offset.

    Args:
        cid: The cluster id to compute.
        spike_clusters: Cluster id of every spike.
        spike_templates: Template id (0-based) of every spike.
        amplitudes: Amplitude of every spike.
        templates: ``nTemplates x nSamples x nChannels`` template shapes.
        winv: Inverse whitening matrix (``nChannels x nChannels``) or ``None``.

    Returns:
        The mean waveform as a ``(nSamples, nChannels)`` numpy array.
    """
    spike_clusters = np.asarray(spike_clusters)
    spike_templates = np.asarray(spike_templates)
    amplitudes = np.asarray(amplitudes, dtype=np.float64)
    templates = np.asarray(templates, dtype=np.float64)

    n_samples = templates.shape[1]
    n_channels = templates.shape[2]

    idx = np.flatnonzero(spike_clusters == cid)
    if idx.size == 0:
        return np.zeros((n_samples, n_channels))

    tmpl = spike_templates[idx].astype(int)  # 0-based template ids
    amp = amplitudes[idx]

    unique_templates = np.unique(tmpl)
    weighted = np.zeros((n_samples, n_channels))
    wsum = 0.0
    for t in unique_templates:
        sel = tmpl == t
        w = float(np.sum(amp[sel]))  # total amplitude contributed by this template
        # 0-based template id -> direct numpy index (MATLAB used t+1 for 1-based).
        weighted += w * templates[int(t), :, :]
        wsum += w

    mean_wf = weighted / wsum if wsum > 0 else weighted

    # scale to physical-ish amplitude using the cluster's mean spike amplitude
    mean_wf = mean_wf * float(np.mean(amp))

    # un-whiten if the inverse whitening matrix is available and conformable
    if winv is not None:
        winv = np.asarray(winv, dtype=np.float64)
        if winv.shape[0] == n_channels and winv.shape[1] == n_channels:
            mean_wf = mean_wf @ winv

    return mean_wf
