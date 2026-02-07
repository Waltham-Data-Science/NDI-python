"""
ndi.time.syncrule.filefind - File find synchronization rule.

This module provides the FileFind sync rule that synchronizes epochs
based on explicit file path matching.
"""

from __future__ import annotations

from typing import Any

from ..syncrule_base import SyncRule
from ..timemapping import TimeMapping


class FileFind(SyncRule):
    """
    Synchronization rule based on finding specific files.

    FileFind uses explicit file patterns to identify epochs that should
    be synchronized. Unlike FileMatch which looks for any shared files,
    FileFind looks for specific file patterns.

    Parameters:
        file_patterns (List[str]): List of file patterns to match
        match_type (str): How to match - 'exact', 'contains', or 'regex'

    Example:
        >>> rule = FileFind({
        ...     'file_patterns': ['sync_*.txt'],
        ...     'match_type': 'glob'
        ... })
    """

    def __init__(
        self,
        parameters: dict[str, Any] | None = None,
        identifier: str | None = None,
    ):
        """
        Create a new FileFind sync rule.

        Args:
            parameters: Dict with file matching parameters
            identifier: Optional identifier
        """
        if parameters is None:
            parameters = {
                "file_patterns": [],
                "match_type": "exact",
            }

        super().__init__(parameters, identifier)

    def is_valid_parameters(self, parameters: dict[str, Any]) -> tuple[bool, str]:
        """
        Validate parameters for FileFind.

        Args:
            parameters: Dict to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(parameters, dict):
            return False, "Parameters must be a dictionary"

        if "file_patterns" not in parameters:
            return False, "Missing required field: file_patterns"

        patterns = parameters["file_patterns"]
        if not isinstance(patterns, list):
            return False, "file_patterns must be a list"

        match_type = parameters.get("match_type", "exact")
        valid_types = ["exact", "contains", "regex", "glob"]
        if match_type not in valid_types:
            return False, f"match_type must be one of: {valid_types}"

        return True, ""

    def eligible_epochsets(self) -> list[str]:
        """Return eligible epochset class names."""
        return ["ndi.daq.system", "DAQSystem"]

    def apply(
        self,
        epochnode_a: dict[str, Any],
        epochnode_b: dict[str, Any],
    ) -> tuple[float | None, TimeMapping | None]:
        """
        Apply FileFind rule to determine if epochs can be synchronized.

        Checks if both epochs contain files matching the specified patterns.

        Args:
            epochnode_a: First epoch node
            epochnode_b: Second epoch node

        Returns:
            Tuple of (cost, mapping) or (None, None) if no sync possible
        """
        import fnmatch
        import re

        # Get file patterns
        patterns = self._parameters.get("file_patterns", [])
        match_type = self._parameters.get("match_type", "exact")

        if not patterns:
            return None, None

        # Get underlying files from both epochs
        files_a = self._get_epoch_files(epochnode_a)
        files_b = self._get_epoch_files(epochnode_b)

        if not files_a or not files_b:
            return None, None

        # Check if patterns match in both epochs
        def matches_pattern(files: list[str], pattern: str) -> bool:
            for f in files:
                if match_type == "exact":
                    if f == pattern or f.endswith("/" + pattern):
                        return True
                elif match_type == "contains":
                    if pattern in f:
                        return True
                elif match_type == "glob":
                    if fnmatch.fnmatch(f, pattern):
                        return True
                elif match_type == "regex":
                    if re.search(pattern, f):
                        return True
            return False

        # All patterns must match in both epochs
        for pattern in patterns:
            if not matches_pattern(files_a, pattern):
                return None, None
            if not matches_pattern(files_b, pattern):
                return None, None

        # All patterns matched in both epochs
        return 1.0, TimeMapping.identity()

    @staticmethod
    def _get_epoch_files(epochnode: dict[str, Any]) -> list[str]:
        """
        Extract file paths from an epoch node.

        Args:
            epochnode: Epoch node dictionary

        Returns:
            List of file paths
        """
        files = []

        # Try underlying_epochs
        underlying = epochnode.get("underlying_epochs")
        if underlying:
            if isinstance(underlying, dict):
                underlying_files = underlying.get("underlying", [])
            elif hasattr(underlying, "underlying"):
                underlying_files = underlying.underlying
            else:
                underlying_files = []

            if isinstance(underlying_files, list):
                files.extend(str(f) for f in underlying_files)

        return files
