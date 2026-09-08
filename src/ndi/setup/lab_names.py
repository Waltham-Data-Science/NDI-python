"""ndi.setup.labNames - the lab names ndi.setup.lab knows about.

MATLAB equivalent: ``src/ndi/+ndi/+setup/labNames.m``. There was no Python
counterpart, so there was no way to ask which labs are installed -- a
caller had to know the directory layout of ``ndi_common/daq_systems``.
"""

from __future__ import annotations


def labNames() -> list[str]:
    """List the lab names that can be passed to :func:`ndi.setup.lab`.

    MATLAB equivalent: ``ndi.setup.labNames``.

    A lab is "known" if it has a directory of DAQ system configuration
    files under ``ndi_common/daq_systems/<labName>``.

    Returns:
        The names, sorted alphabetically. An empty list when no DAQ system
        configurations are installed, as MATLAB returns an empty cell array.
    """
    from ..common import ndi_common_PathConstants

    daq_systems = ndi_common_PathConstants.COMMON_FOLDER / "daq_systems"
    if not daq_systems.is_dir():
        return []

    return sorted(
        entry.name
        for entry in daq_systems.iterdir()
        # MATLAB drops '.', '..' and any hidden directory.
        if entry.is_dir() and not entry.name.startswith(".")
    )


#: Snake-case alias for MATLAB's name; one function under two names.
lab_names = labNames
