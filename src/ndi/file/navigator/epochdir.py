"""
ndi.file.navigator.epochdir - Directory-based epoch navigator.

Navigates data organized as one subdirectory per epoch.

MATLAB equivalent: +ndi/+file/+navigator/epochdir.m
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import ndi_file_navigator


class ndi_file_navigator_epochdir(ndi_file_navigator):
    """
    Navigator where each subdirectory is one epoch.

    Finds epochs by scanning subdirectories of the session path.
    Each subdirectory that contains files matching the file patterns
    constitutes one epoch.

    This is a common pattern for neurophysiology data where each
    recording session/trial is stored in its own directory.

    Example:
        >>> nav = ndi_file_navigator_epochdir(session, '*.rhd')
        >>> # session_path/
        >>> #   trial_001/file.rhd  -> epoch 1
        >>> #   trial_002/file.rhd  -> epoch 2
    """

    def epochid(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str:
        """
        Get the epoch ID for a directory-based epoch.

        MATLAB equivalent: ndi.file.navigator_epochdir/epochid

        Overrides the parent to generate deterministic IDs from the
        epoch directory name rather than creating random IDs.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)
            epochfiles: Optional file list (fetched if not provided)

        Returns:
            ndi_epoch_epoch identifier string based on directory name
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        # Check if ingested
        if self.isingested(epochfiles):
            return self.ingestedfiles_epochid(epochfiles)

        # Try to read from epoch ID file (parent behavior)
        eidfname = self.epochidfilename(epoch_number, epochfiles)
        if eidfname and Path(eidfname).is_file():
            with open(eidfname) as f:
                return f.read().strip()

        # Generate ID from directory name (epochdir-specific behavior)
        if epochfiles:
            epoch_dir = Path(epochfiles[0]).parent
            dir_name = epoch_dir.name
            # Create deterministic ID from directory name + filematch hash
            fmstr = self.filematch_hashstring()
            hash_input = f"{dir_name}_{fmstr}"
            epoch_hash = hashlib.md5(hash_input.encode()).hexdigest()[:16]
            new_id = f"epoch_{epoch_hash}"
        else:
            from ...ido import ndi_ido

            new_id = f"epoch_{ndi_ido().id}"

        # Save to file if possible
        if eidfname:
            Path(eidfname).parent.mkdir(parents=True, exist_ok=True)
            with open(eidfname, "w") as f:
                f.write(new_id)

        return new_id

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
        return f"ndi_file_navigator_epochdir(patterns={n_patterns})"
