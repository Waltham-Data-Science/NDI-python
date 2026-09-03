"""ndi.fun.probe.import.kiasort.meanwaveform - one unit's mean waveform.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/meanwaveform.m``
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["meanwaveform", "mean_waveform"]


def meanwaveform(uid: float, unit_stats: Any) -> np.ndarray | None:
    """The mean waveform of unit UID, ``nSamples x nChannels``, or None.

    KIASORT stores ``meanWaveforms`` as ``(nUnits, nSamples, nChannels)``
    indexed in parallel with ``unit_stats.label``, so the unit is found BY ITS
    LABEL rather than by position: the labels are unit ids, not row numbers,
    and a curated sort renumbers them. Taking row ``uid`` directly would hand
    back another unit's waveform.

    None -- MATLAB's ``[]`` -- when there are no statistics, no waveforms in
    them, or no row for this unit. The caller stores no waveform in that case
    rather than a zero one, which would claim a shape the sort never had.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.meanwaveform``.
    """
    if unit_stats is None:
        return None
    waveforms = getattr(unit_stats, "meanWaveforms", None)
    if waveforms is None or np.asarray(waveforms).size == 0:
        return None

    label = np.asarray(getattr(unit_stats, "label", []), dtype=float).ravel()
    rows = np.flatnonzero(label == float(uid))
    if rows.size == 0:
        return None
    row = int(rows[0])

    waveforms = np.asarray(waveforms, dtype=float)
    if row >= waveforms.shape[0]:
        return None

    waveform = np.squeeze(waveforms[row])
    if waveform.ndim <= 1:
        # A single-channel probe squeezes to a vector; the caller reads this
        # as nSamples x nChannels, so give it the second axis back.
        waveform = waveform.reshape(-1, 1)
    return waveform


#: The readable spelling beside MATLAB's.
mean_waveform = meanwaveform
