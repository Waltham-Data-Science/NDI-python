"""
ndi.file.navigator.rhd_series_epochdir - Epochdir navigator for prefix-grouped .rhd recordings.

The epochdir-organized counterpart of ndi.file.navigator.rhd_series. Each
first-level subdirectory of the session is treated as a candidate epoch
container; within each subdirectory, .rhd files that share a common prefix
but differ in a trailing variable portion (typically a YYYYMMDDHHMMSS.msec
timestamp) are grouped, and only the lexicographically earliest member of
each group is returned (the Intan reader recovers the rest of the series
from that file). Ancillary files matched through the standard '#'
substitution syntax are searched for in the same subdirectory.

MATLAB equivalent: +ndi/+file/+navigator/rhd_series_epochdir.m
"""

from __future__ import annotations

import os
from pathlib import Path

from .epochdir import ndi_file_navigator_epochdir
from .rhd_series import ndi_file_navigator_rhd_series


class ndi_file_navigator_rhd_series_epochdir(ndi_file_navigator_epochdir):
    """
    Epochdir navigator for prefix-grouped .rhd recordings.

    FILEPARAMETERS
        The filematch list is interpreted exactly as in
        ndi.file.navigator.rhd_series; the only difference is that
        matching is performed independently in each first-level
        subdirectory of the session rather than in the session root.

        patterns[0] - Series pattern. Contains exactly one '#' capturing
            the per-epoch prefix; the remainder is a regular expression
            matching the variable part of the filename.

        patterns[1:] - Ancillary patterns. '#' is replaced by the literal
            (regex-escaped) prefix of the current epoch and the result
            is matched as a regular expression against filenames in the
            same subdirectory. The lexicographically earliest match per
            pattern is appended to the epoch's file list. If any
            ancillary pattern produces no match the epoch is skipped.

    The epoch identifier returned by epochid is the name of the
    subdirectory that contains the epoch's files, matching the
    convention of ndi.file.navigator.epochdir.

    Example:
        >>> nav = ndi_file_navigator_rhd_series_epochdir(
        ...     session,
        ...     [r'#_\\d{14}\\.\\d+\\.rhd\\>', r'#\\.epochprobemap\\.ndi\\>'],
        ... )
    """

    NDI_FILENAVIGATOR_CLASS = "ndi.file.navigator.rhd_series_epochdir"

    def epochid(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str:
        """
        Return the epoch identifier (subdirectory name).

        MATLAB equivalent: ndi.file.navigator.rhd_series_epochdir/epochid

        Returns the name of the subdirectory that contains the epoch's
        files. If the epoch's files are ingested, the inherited
        ingested-file identifier is returned instead.

        Args:
            epoch_number: epoch number (1-indexed)
            epochfiles: optional file list (fetched if not provided)

        Returns:
            Epoch identifier string (the subdirectory name).
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        if self.isingested(epochfiles):
            return self.ingestedfiles_epochid(epochfiles)

        return Path(epochfiles[0]).parent.name

    def selectfilegroups_disk(self) -> list[list[str]]:
        """
        Return groups of files that comprise epochs.

        MATLAB equivalent:
            ndi.file.navigator.rhd_series_epochdir/selectfilegroups_disk

        Walks the first-level subdirectories of the session and applies
        the rhd_series matching rules to each. Every prefix group found
        in a subdirectory contributes one epoch whose file list is the
        first .rhd of the group followed by any ancillary matches found
        in the same subdirectory.

        Returns:
            List of epoch file groups.
        """
        try:
            base_path = self.path()
        except ValueError:
            return []

        if not os.path.isdir(base_path):
            return []

        patterns = ndi_file_navigator_rhd_series._normalize_patterns(
            self._fileparameters.get("filematch", [])
        )
        if not patterns:
            return []

        epochfiles_disk: list[list[str]] = []
        try:
            entries = sorted(os.listdir(base_path))
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return []

        for name in entries:
            if name.startswith("."):
                continue
            epoch_path = os.path.join(base_path, name)
            if not os.path.isdir(epoch_path):
                continue
            groups = ndi_file_navigator_rhd_series._group_directory(
                epoch_path, patterns
            )
            for g in groups:
                epochfiles_disk.append(g)

        return epochfiles_disk

    def __repr__(self) -> str:
        n_patterns = len(self._fileparameters.get("filematch", []))
        return f"ndi_file_navigator_rhd_series_epochdir(patterns={n_patterns})"
