"""ndi.fun.probe.import.kiasort - import a KIASORT sort into NDI.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+probe/+import/+kiasort/``

:func:`probe` imports one probe's sort, :func:`session` sweeps a whole
session, :func:`getInfo` reports what a sort holds without importing it, and
:func:`status` says where a probe stands in the pipeline. The rest are the
pieces those are built from -- reading KIASORT's HDF5 output and the ``.mat``
holding its per-unit statistics.

WHAT IS HERE AND WHAT IS NOT
MATLAB's package also holds ``run``, ``run_stages_with_progress`` and
``curate``, which drive the KIASORT toolbox itself: they call
``run_kiasort_nogui``, ``kiaSort_main_*`` and ``kiaSort_curate_results``.
KIASORT is MATLAB, so those cannot run from Python and are NOT ported --
:func:`run` and :func:`curate` are here only to say so clearly, rather than
letting a caller find out through an AttributeError. Sort in MATLAB (or take
a collaborator's output) and import it here; that path works end to end.

This mirrors ``ndi.fun.probe.import.kilosort``, which is likewise
import-only in both languages.

The flat namespace MATLAB's package presents is reproduced here, so
``kiasort.probe(...)``, ``kiasort.getInfo(...)`` and ``kiasort.results(...)``
all resolve, whichever module defines them.
"""

from __future__ import annotations

from typing import Any, NoReturn

from .get_info import DEFAULT_QUALITY_LABELS, SortInfo, get_info, getInfo, kiasort_directory
from .labels import DEFAULT_LABEL, labels
from .mean_waveform import mean_waveform, meanwaveform
from .probe import DEFAULT_QUALITY_VALUES, WAVEFORM_SOURCES, app_provenance, probe
from .remove_old import remove_old, removeold
from .results import RES_SORTED, Results, results
from .session import NTRODE_TYPE, session
from .status import Status, status
from .unit_stats import CURATED_SUFFIX, UnitStats, unit_stats, unitstats

__all__ = [
    "CURATED_SUFFIX",
    "DEFAULT_LABEL",
    "DEFAULT_QUALITY_LABELS",
    "DEFAULT_QUALITY_VALUES",
    "NTRODE_TYPE",
    "RES_SORTED",
    "Results",
    "SortInfo",
    "Status",
    "UnitStats",
    "WAVEFORM_SOURCES",
    "app_provenance",
    "curate",
    "getInfo",
    "get_info",
    "kiasort_directory",
    "labels",
    "mean_waveform",
    "meanwaveform",
    "probe",
    "remove_old",
    "removeold",
    "results",
    "run",
    "session",
    "status",
    "unit_stats",
    "unitstats",
]

#: What both unported entry points say. One message, because the reason and
#: the way forward are the same for each.
_MATLAB_ONLY = (
    "{name} drives the KIASORT toolbox, which is MATLAB. It cannot run from "
    "Python and is not ported. Sort and curate in MATLAB with "
    "ndi.fun.probe.import.kiasort.{matlab_name}, then import the result here "
    "with ndi.fun.probe.import.kiasort.probe -- that path is fully ported. "
    "See Waltham-Data-Science/NDI-python#122."
)


def run(*_args: Any, **_options: Any) -> NoReturn:
    """NOT PORTED: running KIASORT needs the MATLAB toolbox.

    Present so the failure is this sentence rather than an AttributeError
    from a caller who reasonably expected MATLAB's package shape.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.run``.
    """
    raise NotImplementedError(
        _MATLAB_ONLY.format(name="ndi.fun.probe.import.kiasort.run", matlab_name="run")
    )


def curate(*_args: Any, **_options: Any) -> NoReturn:
    """NOT PORTED: KIASORT's curation UI is a MATLAB app.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.curate``.
    """
    raise NotImplementedError(
        _MATLAB_ONLY.format(name="ndi.fun.probe.import.kiasort.curate", matlab_name="curate")
    )
