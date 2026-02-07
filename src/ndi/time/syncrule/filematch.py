"""
ndi.time.syncrule.filematch - File match synchronization rule.

This module provides the FileMatch sync rule that synchronizes epochs
based on shared underlying files.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from ..syncrule_base import SyncRule
from ..timemapping import TimeMapping


class FileMatch(SyncRule):
    """
    Synchronization rule based on matching underlying files.

    FileMatch identifies epochs that share underlying files and creates
    a synchronization mapping between them. This is useful when multiple
    DAQ systems record to a shared file system.

    Parameters:
        number_fullpath_matches (int): The number of full path matches of
            underlying filenames that must match for epochs to be synchronized.
            Default is 2.

    Example:
        >>> rule = FileMatch()  # Default: require 2 matching files
        >>> rule = FileMatch({'number_fullpath_matches': 3})  # Require 3 matches
    """

    def __init__(
        self,
        parameters: Optional[Dict[str, Any]] = None,
        identifier: Optional[str] = None,
    ):
        """
        Create a new FileMatch sync rule.

        Args:
            parameters: Dict with 'number_fullpath_matches' key (default 2)
            identifier: Optional identifier
        """
        if parameters is None:
            parameters = {'number_fullpath_matches': 2}

        super().__init__(parameters, identifier)

    def is_valid_parameters(self, parameters: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate parameters for FileMatch.

        Args:
            parameters: Dict to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(parameters, dict):
            return False, "Parameters must be a dictionary"

        if 'number_fullpath_matches' not in parameters:
            return False, "Missing required field: number_fullpath_matches"

        n = parameters['number_fullpath_matches']
        if not isinstance(n, (int, float)):
            return False, "number_fullpath_matches must be a number"

        if n < 1:
            return False, "number_fullpath_matches must be at least 1"

        return True, ""

    def eligible_epochsets(self) -> List[str]:
        """Return eligible epochset class names."""
        return ['ndi.daq.system', 'DAQSystem']

    def ineligible_epochsets(self) -> List[str]:
        """Return ineligible epochset class names."""
        base_ineligible = super().ineligible_epochsets()
        return base_ineligible + [
            'ndi.epoch.epochset',
            'ndi.epoch.epochset.param',
            'ndi.file.navigator',
        ]

    def apply(
        self,
        epochnode_a: Dict[str, Any],
        epochnode_b: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[TimeMapping]]:
        """
        Apply FileMatch rule to determine if epochs can be synchronized.

        Checks if the epochs share enough underlying files to establish
        a synchronization. If they do, returns cost=1 and identity mapping.

        Args:
            epochnode_a: First epoch node
            epochnode_b: Second epoch node

        Returns:
            Tuple of (cost, mapping) or (None, None) if no sync possible
        """
        # Quick content checks
        class_a = epochnode_a.get('objectclass', '')
        class_b = epochnode_b.get('objectclass', '')

        # Must be DAQ systems
        if not self._is_daq_system(class_a) or not self._is_daq_system(class_b):
            return None, None

        # Check for underlying epochs
        underlying_a = epochnode_a.get('underlying_epochs')
        underlying_b = epochnode_b.get('underlying_epochs')

        if not underlying_a or not underlying_b:
            return None, None

        # Get underlying files
        files_a = self._get_underlying_files(underlying_a)
        files_b = self._get_underlying_files(underlying_b)

        if not files_a or not files_b:
            return None, None

        # Find common files
        common = set(files_a) & set(files_b)

        required_matches = self._parameters.get('number_fullpath_matches', 2)
        if len(common) >= required_matches:
            # Epochs match - return cost=1 and identity mapping
            return 1.0, TimeMapping.identity()

        return None, None

    @staticmethod
    def _is_daq_system(classname: str) -> bool:
        """Check if a classname represents a DAQ system."""
        daq_classes = [
            'ndi.daq.system',
            'DAQSystem',
            'daq.system',
        ]
        return any(c in classname for c in daq_classes)

    @staticmethod
    def _get_underlying_files(underlying_epochs: Any) -> List[str]:
        """
        Extract underlying file paths from underlying_epochs structure.

        Args:
            underlying_epochs: Dict or object with underlying file info

        Returns:
            List of file paths
        """
        if isinstance(underlying_epochs, dict):
            underlying = underlying_epochs.get('underlying', [])
        elif hasattr(underlying_epochs, 'underlying'):
            underlying = underlying_epochs.underlying
        else:
            return []

        if isinstance(underlying, list):
            return [str(f) for f in underlying]
        return []
