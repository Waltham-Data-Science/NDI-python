"""ndi.fun.probe.import.kilosort.waveformdata - load Kilosort template data.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/waveformdata.m``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["waveformdata", "waveform_data"]


def waveformdata(kdir: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """The Kilosort files needed to rebuild per-cluster mean waveforms.

    Returns ``(templates, spike_templates, amplitudes, winv)``:

    ``templates``
        nTemplates x nSamples x nChannels template shapes.
    ``spike_templates``
        The 0-based template id of every spike.
    ``amplitudes``
        Each spike's template scaling amplitude.
    ``winv``
        The inverse whitening matrix, or None when the sort has none. Present,
        it un-whitens the templates into approximately physical units.

    MATLAB reads these through ``ndi.util.readNPY``; numpy reads its own
    format, so :func:`numpy.load` stands in with nothing to port.
    """
    directory = Path(kdir)
    templates_file = directory / "templates.npy"
    spike_templates_file = directory / "spike_templates.npy"
    amplitudes_file = directory / "amplitudes.npy"

    missing = [
        f.name for f in (templates_file, spike_templates_file, amplitudes_file) if not f.is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "waveform_source 'templates' requires templates.npy, spike_templates.npy, "
            f"and amplitudes.npy in {directory}; missing {', '.join(missing)}. Use "
            "waveform_source='none' to skip waveforms."
        )

    templates = np.load(templates_file).astype(float)
    spike_templates = np.load(spike_templates_file).astype(float).ravel()
    amplitudes = np.load(amplitudes_file).astype(float).ravel()

    winv = None
    winv_file = directory / "whitening_mat_inv.npy"
    if winv_file.is_file():
        winv = np.load(winv_file).astype(float)

    return templates, spike_templates, amplitudes, winv


#: MATLAB's spelling is one word; this is the readable one.
waveform_data = waveformdata
