"""
ndi.fun.probe.import_.kilosort.waveformdata - load kilosort template waveform data.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/waveformdata.m

NAMING DIVERGENCE: ``import`` is a reserved word in Python, so the subpackage
directory is named ``import_`` (see this package's ``__init__``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def waveformdata(
    kdir: str | Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Load the kilosort files needed to reconstruct per-cluster mean waveforms.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.waveformdata``

    Args:
        kdir: The kilosort output directory.

    Returns:
        Tuple ``(templates, spike_templates, amplitudes, winv)``:

        * ``templates``       - ``nTemplates x nSamples x nChannels`` template
          shapes (``templates.npy``).
        * ``spike_templates`` - template id (0-based) of each spike
          (``spike_templates.npy``).
        * ``amplitudes``      - per-spike template scaling amplitude
          (``amplitudes.npy``).
        * ``winv``            - the inverse whitening matrix
          (``whitening_mat_inv.npy``) if present, otherwise ``None``. When
          present it is used to un-whiten the templates so the waveforms are in
          (approximately) physical units.

    Raises:
        FileNotFoundError: If any of ``templates.npy``, ``spike_templates.npy``,
            or ``amplitudes.npy`` are missing.
    """
    kdir = Path(kdir)

    tfile = kdir / "templates.npy"
    stfile = kdir / "spike_templates.npy"
    afile = kdir / "amplitudes.npy"

    if not (tfile.is_file() and stfile.is_file() and afile.is_file()):
        raise FileNotFoundError(
            "waveform_source 'templates' requires templates.npy, "
            f"spike_templates.npy, and amplitudes.npy in {kdir}. Use "
            "waveform_source='none' to skip waveforms."
        )

    # readNPY -> numpy.load (Kilosort .npy files are standard numpy arrays).
    templates = np.load(tfile).astype(np.float64)
    spike_templates = np.load(stfile).astype(np.float64).ravel()
    amplitudes = np.load(afile).astype(np.float64).ravel()

    winv: np.ndarray | None = None
    wfile = kdir / "whitening_mat_inv.npy"
    if wfile.is_file():
        winv = np.load(wfile).astype(np.float64)

    return templates, spike_templates, amplitudes, winv
