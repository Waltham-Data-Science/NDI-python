"""ndi.fun.probe.import.kilosort - import curated Kilosort/Phy output into NDI.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+probe/+import/+kilosort/``

The subsystem that turns a curated spike sort on disk into NDI neurons:
:func:`probe` imports one probe's sort, :func:`session` sweeps a whole
session, and :func:`getInfo` reports what a sort holds without importing it.
The rest are the pieces those three are built from -- reading Phy's label
files and templates, locating the raw recording, and recalculating wide mean
waveforms from it.

The flat namespace MATLAB's package presents is reproduced here, so
``kilosort.probe(...)``, ``kilosort.getInfo(...)`` and
``kilosort.binaryinfo(...)`` all resolve, whichever module actually defines
them.
"""

from __future__ import annotations

from .binary_info import binary_info, binaryinfo, read_params_py
from .get_info import DEFAULT_QUALITY_LABELS, get_info, getInfo, kilosort_directory
from .labels import labels
from .mean_waveform import mean_waveform, meanwaveform
from .neuropixels_multiplier import neuropixels_multiplier, neuropixelsmultiplier
from .probe import DEFAULT_QUALITY_VALUES, app_provenance, probe
from .prompt_raw_binary import prompt_raw_binary, promptrawbinary
from .read_spikeglx_meta import read_spikeglx_meta, readspikeglxmeta
from .recalculate_mean_waveform import recalculate_mean_waveform, recalculatemeanwaveform
from .recalculate_mean_waveforms import recalculate_mean_waveforms, recalculatemeanwaveforms
from .remove_old import remove_old, removeold
from .session import session
from .waveform_data import waveform_data, waveformdata

__all__ = [
    "DEFAULT_QUALITY_LABELS",
    "DEFAULT_QUALITY_VALUES",
    "app_provenance",
    "binary_info",
    "binaryinfo",
    "getInfo",
    "get_info",
    "kilosort_directory",
    "labels",
    "mean_waveform",
    "meanwaveform",
    "neuropixels_multiplier",
    "neuropixelsmultiplier",
    "probe",
    "prompt_raw_binary",
    "promptrawbinary",
    "read_params_py",
    "read_spikeglx_meta",
    "readspikeglxmeta",
    "recalculate_mean_waveform",
    "recalculate_mean_waveforms",
    "recalculatemeanwaveform",
    "recalculatemeanwaveforms",
    "remove_old",
    "removeold",
    "session",
    "waveform_data",
    "waveformdata",
]
