"""
ndi.time.syncrule.filefind - File find synchronization rule.

This module provides the ndi_time_syncrule_filefind sync rule that synchronizes epochs
based on a synchronization text file shared between two named DAQ systems.

The sync file contains two numbers (shift and scale) defining:
    TimeOnDaqSystem2 = shift + scale * TimeOnDaqSystem1

MATLAB equivalent: src/ndi/+ndi/+time/+syncrule/filefind.m
"""

from __future__ import annotations

import os
from typing import Any

from ..syncrule_base import ndi_time_syncrule
from ..timemapping import ndi_time_timemapping


class ndi_time_syncrule_filefind(ndi_time_syncrule):
    """
    Synchronization rule based on finding a sync file between two DAQ systems.

    ndi_time_syncrule_filefind looks for a specific synchronization text file in the epoch's
    underlying files. The file should contain two numbers: a shift and a scale,
    defining the time relationship between two named DAQ systems:

        TimeOnDaqSystem2 = shift + scale * TimeOnDaqSystem1

    Parameters:
        number_fullpath_matches (int): Number of full path matches of
            underlying filenames required for epochs to match. Default: 1.
        syncfilename (str): Name of the sync text file. Default: 'syncfile.txt'.
        daqsystem1 (str): Name of the first DAQ system. Default: 'mydaq1'.
        daqsystem2 (str): Name of the second DAQ system. Default: 'mydaq2'.

    Example:
        >>> rule = ndi_time_syncrule_filefind({
        ...     'number_fullpath_matches': 1,
        ...     'syncfilename': 'syncfile.txt',
        ...     'daqsystem1': 'daq_vis',
        ...     'daqsystem2': 'daq_ephys',
        ... })
    """

    def __init__(
        self,
        parameters: dict[str, Any] | None = None,
        identifier: str | None = None,
    ):
        """
        Create a new ndi_time_syncrule_filefind sync rule.

        Args:
            parameters: Dict with sync file matching parameters
            identifier: Optional identifier
        """
        if parameters is None:
            parameters = {
                "number_fullpath_matches": 1,
                "syncfilename": "syncfile.txt",
                "daqsystem1": "mydaq1",
                "daqsystem2": "mydaq2",
            }

        super().__init__(parameters, identifier)

    def is_valid_parameters(self, parameters: dict[str, Any]) -> tuple[bool, str]:
        """
        Validate parameters for ndi_time_syncrule_filefind.

        Args:
            parameters: Dict to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(parameters, dict):
            return False, "Parameters must be a dictionary"

        required = ["number_fullpath_matches", "syncfilename", "daqsystem1", "daqsystem2"]
        for field in required:
            if field not in parameters:
                return False, f"Missing required field: {field}"

        if not isinstance(parameters["number_fullpath_matches"], (int, float)):
            return False, "number_fullpath_matches must be a number"

        if not isinstance(parameters["syncfilename"], str):
            return False, "syncfilename must be a string"

        if not isinstance(parameters["daqsystem1"], str):
            return False, "daqsystem1 must be a string"

        if not isinstance(parameters["daqsystem2"], str):
            return False, "daqsystem2 must be a string"

        return True, ""

    def eligible_epochsets(self) -> list[str]:
        """Return eligible epochset class names."""
        return ["ndi.daq.system"]

    def ineligible_epochsets(self) -> list[str]:
        """Return ineligible epochset class names."""
        base = super().ineligible_epochsets()
        return base + ["ndi.epoch.epochset", "ndi.epoch.epochset.param", "ndi.file.navigator"]

    def apply(
        self,
        epochnode_a: dict[str, Any],
        epochnode_b: dict[str, Any],
        daqsystem1: Any = None,
    ) -> tuple[float | None, ndi_time_timemapping | None]:
        """
        Apply ndi_time_syncrule_filefind rule to determine if epochs can be synchronized.

        Checks if the two epoch nodes come from the configured DAQ systems,
        share enough underlying files, and contain the sync file. If so,
        reads shift and scale from the sync file and returns a ndi_time_timemapping.

        Args:
            epochnode_a: First epoch node
            epochnode_b: Second epoch node
            daqsystem1: The DAQ system object corresponding to epochnode_a

        Returns:
            Tuple of (cost, mapping) or (None, None) if no sync possible
        """
        params = self._parameters

        # Get object names from epoch nodes
        name_a = _get_objectname(epochnode_a)
        name_b = _get_objectname(epochnode_b)

        # Check if these epoch nodes come from our configured DAQ systems
        forward = (name_a == params["daqsystem1"]) and (name_b == params["daqsystem2"])
        backward = (name_b == params["daqsystem1"]) and (name_a == params["daqsystem2"])

        if not forward and not backward:
            return None, None

        # Get underlying files from both epoch nodes
        files_a = _get_underlying_files(epochnode_a)
        files_b = _get_underlying_files(epochnode_b)

        if not files_a or not files_b:
            return None, None

        # Check for sufficient common files
        common = set(files_a) & set(files_b)
        if len(common) < int(params["number_fullpath_matches"]):
            return None, None

        # We have enough common files; now find the sync file
        syncfilename = params["syncfilename"]

        if forward:
            # Look for sync file in epochnode_a's files
            syncdata = _find_and_read_syncfile(files_a, syncfilename)
            if syncdata is None:
                raise FileNotFoundError(f"No file matched {syncfilename}.")
            shift, scale = syncdata
            return 1.0, ndi_time_timemapping([scale, shift])

        if backward:
            # Look for sync file in epochnode_b's files
            syncdata = _find_and_read_syncfile(files_b, syncfilename)
            if syncdata is None:
                raise FileNotFoundError(f"No file matched {syncfilename}.")
            shift, scale = syncdata
            # Reverse the mapping: if T2 = shift + scale*T1,
            # then T1 = -shift/scale + (1/scale)*T2
            scale_reverse = 1.0 / scale
            shift_reverse = -shift / scale
            return 1.0, ndi_time_timemapping([scale_reverse, shift_reverse])

        return None, None


def _get_objectname(epochnode: dict[str, Any]) -> str:
    """Extract the object name from an epoch node."""
    if isinstance(epochnode, dict):
        return epochnode.get("objectname", "")
    if hasattr(epochnode, "objectname"):
        return epochnode.objectname
    return ""


def _get_underlying_files(epochnode: dict[str, Any]) -> list[str]:
    """Extract underlying file paths from an epoch node."""
    underlying = None
    if isinstance(epochnode, dict):
        ue = epochnode.get("underlying_epochs")
        if isinstance(ue, dict):
            underlying = ue.get("underlying", [])
        elif hasattr(ue, "underlying"):
            underlying = ue.underlying
    elif hasattr(epochnode, "underlying_epochs"):
        ue = epochnode.underlying_epochs
        if isinstance(ue, dict):
            underlying = ue.get("underlying", [])
        elif hasattr(ue, "underlying"):
            underlying = ue.underlying

    if underlying is None:
        return []

    if isinstance(underlying, list):
        return [str(f) for f in underlying]

    return []


def _find_and_read_syncfile(files: list[str], syncfilename: str) -> tuple[float, float] | None:
    """
    Find and read a sync file from a list of file paths.

    The sync file should contain two numbers: shift and scale.

    Args:
        files: List of file paths to search
        syncfilename: Filename to match (compared against basename)

    Returns:
        Tuple of (shift, scale) or None if not found
    """
    for filepath in files:
        basename = os.path.basename(filepath)
        if basename == syncfilename:
            try:
                with open(filepath) as f:
                    content = f.read().strip()
                values = [float(v) for v in content.split()]
                if len(values) >= 2:
                    return values[0], values[1]  # shift, scale
            except (OSError, ValueError):
                continue
    return None
