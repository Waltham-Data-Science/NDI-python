"""
ndi.time.syncrule - Synchronization rule implementations.

This module provides concrete implementations of ndi_time_syncrule for
different synchronization strategies.
"""

from ...util.classname import ndi_matlab_classname
from ..syncrule_base import ndi_time_syncrule
from .common_triggers_overlapping_epochs import ndi_time_syncrule_commonTriggersOverlappingEpochs
from .filefind import ndi_time_syncrule_filefind
from .filematch import ndi_time_syncrule_filematch
from .random_pulses import ndi_time_syncrule_randomPulses

__all__ = [
    "ndi_time_syncrule_commonTriggersOverlappingEpochs",
    "ndi_time_syncrule_filefind",
    "ndi_time_syncrule_filematch",
    "ndi_time_syncrule_randomPulses",
    "resolve_syncrule_class",
]


_CONCRETE_CLASSES: tuple[type[ndi_time_syncrule], ...] = (
    ndi_time_syncrule_filematch,
    ndi_time_syncrule_filefind,
    ndi_time_syncrule_commonTriggersOverlappingEpochs,
    ndi_time_syncrule_randomPulses,
)

_PYTHON_TO_CLASS: dict[str, type[ndi_time_syncrule]] = {
    cls.__name__: cls for cls in _CONCRETE_CLASSES
}
_MATLAB_TO_CLASS: dict[str, type[ndi_time_syncrule]] = {
    ndi_matlab_classname(cls.__name__): cls for cls in _CONCRETE_CLASSES
}


def resolve_syncrule_class(name: str) -> type[ndi_time_syncrule]:
    """Resolve a syncrule class name to its concrete Python class.

    Accepts either the MATLAB dotted form (``"ndi.time.syncrule.filematch"``)
    or the Python underscore form (``"ndi_time_syncrule_filematch"``).

    Raises ``ValueError`` on an unknown name, and never falls back to the
    abstract ``ndi_time_syncrule`` base.
    """
    if name in _PYTHON_TO_CLASS:
        return _PYTHON_TO_CLASS[name]
    if name in _MATLAB_TO_CLASS:
        return _MATLAB_TO_CLASS[name]
    known = sorted(_MATLAB_TO_CLASS)
    raise ValueError(f"Unknown syncrule class {name!r}; expected one of {known}")
