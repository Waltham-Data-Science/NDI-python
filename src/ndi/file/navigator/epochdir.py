"""
ndi.file.navigator.epochdir - Directory-based epoch navigator.

Navigates data organized as one subdirectory per epoch.

MATLAB equivalent: src/ndi/+ndi/+file/navigator_epochdir.m (conceptual)
"""

from __future__ import annotations

from pathlib import Path

from . import FileNavigator


class EpochDirNavigator(FileNavigator):
    """
    Navigator where each subdirectory is one epoch.

    Finds epochs by scanning subdirectories of the session path.
    Each subdirectory that contains files matching the file patterns
    constitutes one epoch.

    This is a common pattern for neurophysiology data where each
    recording session/trial is stored in its own directory.

    Example:
        >>> nav = EpochDirNavigator(session, '*.rhd')
        >>> # session_path/
        >>> #   trial_001/file.rhd  -> epoch 1
        >>> #   trial_002/file.rhd  -> epoch 2
    """

    def selectfilegroups_disk(self) -> list[list[str]]:
        """
        Select file groups from disk, one per subdirectory.

        Each subdirectory of the session path that contains matching
        files becomes one epoch (one file group).

        Returns:
            List of file groups (one per epoch directory)
        """
        try:
            base_path = self.path()
        except ValueError:
            return []

        patterns = self._fileparameters.get("filematch", [])
        if not patterns:
            return []

        base = Path(base_path)
        if not base.is_dir():
            return []

        groups = []

        # Sort directories for deterministic ordering
        subdirs = sorted([d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")])

        for subdir in subdirs:
            matched = self._match_files_in_dir(subdir, patterns)
            if matched:
                groups.append(sorted(matched))

        return groups

    def _match_files_in_dir(
        self,
        directory: Path,
        patterns: list[str],
    ) -> list[str]:
        """
        Find files matching patterns in a single directory.

        Args:
            directory: Directory to search
            patterns: File patterns to match

        Returns:
            List of matched file paths
        """
        import fnmatch
        import re

        matched = []
        try:
            files = [f for f in directory.iterdir() if f.is_file()]
        except PermissionError:
            return []

        for f in files:
            if f.name.startswith("."):
                continue
            for pattern in patterns:
                if fnmatch.fnmatch(f.name, pattern):
                    matched.append(str(f))
                    break
                try:
                    if re.search(pattern, f.name):
                        matched.append(str(f))
                        break
                except re.error:
                    pass

        return matched

    def __repr__(self) -> str:
        n_patterns = len(self._fileparameters.get("filematch", []))
        return f"EpochDirNavigator(patterns={n_patterns})"
