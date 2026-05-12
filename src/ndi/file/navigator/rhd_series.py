"""
ndi.file.navigator.rhd_series - File navigator for prefix-grouped .rhd recordings.

Groups .rhd files that share a common prefix but differ in a trailing variable
portion (typically a YYYYMMDDHHMMSS.msec timestamp) into a single epoch.
Because the Intan reader can discover the remaining files in a series from
the first file alone, only the lexicographically earliest match in each
prefix group is returned. Ancillary files (e.g. an epochprobemap) that
share the same prefix are matched through the standard '#' substitution
syntax used by ndi.file.navigator.

This navigator is for "flat" sessions in which all .rhd files of all epochs
live directly in the session directory. Use
ndi.file.navigator.rhd_series_epochdir for sessions in which each epoch
lives in its own subdirectory.

MATLAB equivalent: +ndi/+file/+navigator/rhd_series.m
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ...util.matlab_regex import matlab_to_python_regex
from . import ndi_file_navigator


class ndi_file_navigator_rhd_series(ndi_file_navigator):
    """
    Navigator for prefix-grouped .rhd recordings in a flat session directory.

    FILEPARAMETERS
        The filematch list is interpreted as follows:

        patterns[0] - Series pattern. Must contain exactly one '#'.
            The '#' captures the per-epoch prefix; the rest of the pattern
            is a regular expression matching the variable portion of the
            filename. Files matching this pattern are grouped by the
            captured prefix and each unique prefix becomes one epoch.
            Within a group only the lexicographically earliest filename
            is kept (which is the chronologically earliest when
            timestamps are zero-padded).

        patterns[1:] - Ancillary patterns. In each pattern '#' is replaced
            by the literal (regex-escaped) prefix of the current epoch
            and the result is matched as a regular expression against the
            filenames in the session directory. The lexicographically
            earliest match is appended to the epoch's file list. If any
            ancillary pattern produces no match the epoch is skipped.

    The epoch identifier returned by epochid is the prefix captured by
    the series pattern.

    Example:
        >>> nav = ndi_file_navigator_rhd_series(
        ...     session,
        ...     [r'#_\\d{14}\\.\\d+\\.rhd\\>', r'#\\.epochprobemap\\.ndi\\>'],
        ... )
    """

    NDI_FILENAVIGATOR_CLASS = "ndi.file.navigator.rhd_series"

    def epochid(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str:
        """
        Return the epoch identifier for an epoch.

        MATLAB equivalent: ndi.file.navigator.rhd_series/epochid

        Returns the prefix captured by the series pattern from the first
        file of the epoch. If the epoch's files are ingested, the
        inherited ingested-file identifier is returned instead.

        Args:
            epoch_number: epoch number (1-indexed)
            epochfiles: optional file list (fetched if not provided)

        Returns:
            Epoch identifier string.
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        if self.isingested(epochfiles):
            return self.ingestedfiles_epochid(epochfiles)

        patterns = self._normalize_patterns(self._fileparameters.get("filematch", []))
        basename = os.path.basename(epochfiles[0])
        eid = self._extract_prefix(basename, patterns[0]) if patterns else ""
        if not eid:
            # Fall back to the file stem (no extension), matching MATLAB
            # fileparts behavior.
            eid = Path(basename).stem
        return eid

    def selectfilegroups_disk(self) -> list[list[str]]:
        """
        Return groups of files that comprise epochs.

        MATLAB equivalent: ndi.file.navigator.rhd_series/selectfilegroups_disk

        Inspects the session directory and returns one list per epoch,
        each containing the absolute path of the first .rhd file in the
        prefix group followed by any ancillary files matched by the
        remaining filematch patterns.

        Returns:
            List of epoch file groups.
        """
        try:
            base_path = self.path()
        except ValueError:
            return []

        if not os.path.isdir(base_path):
            return []

        patterns = self._normalize_patterns(self._fileparameters.get("filematch", []))
        if not patterns:
            return []

        return self._group_directory(base_path, patterns)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_patterns(filematch: str | list[str]) -> list[str]:
        """Coerce filematch into a list of pattern strings.

        MATLAB equivalent: ndi.file.navigator.rhd_series.normalizePatterns
        """
        if isinstance(filematch, str):
            return [filematch]
        return list(filematch)

    @staticmethod
    def _extract_prefix(filename: str, series_pattern: str) -> str:
        """Return the substring captured by '#' in series_pattern.

        MATLAB equivalent: ndi.file.navigator.rhd_series.extractPrefix

        Replaces the '#' in series_pattern with a non-greedy capture
        group, anchors the result, and returns the captured substring
        or '' if the filename does not match.
        """
        rx = "^" + matlab_to_python_regex(series_pattern).replace("#", "(.+?)") + "$"
        m = re.match(rx, filename)
        if not m:
            return ""
        return m.group(1)

    @staticmethod
    def _group_directory(
        directory: str,
        patterns: list[str],
    ) -> list[list[str]]:
        """Build epoch file groups from one directory.

        MATLAB equivalent: ndi.file.navigator.rhd_series.groupDirectory

        Applies the rhd_series matching rules to the files in directory
        and returns a list of epoch file lists. patterns[0] is the
        series pattern and patterns[1:] are ancillary patterns.

        Files whose basename begins with '.' (e.g. macOS resource forks
        like '._foo.rhd' or '.DS_Store') are ignored, matching the
        convention used by the base ndi.file.navigator.
        """
        groups: list[list[str]] = []
        try:
            entries = os.listdir(directory)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return groups

        names = [
            n
            for n in entries
            if not n.startswith(".") and os.path.isfile(os.path.join(directory, n))
        ]
        if not names:
            return groups

        series_regex = "^" + matlab_to_python_regex(patterns[0]).replace("#", "(.+?)") + "$"
        series_re = re.compile(series_regex)

        # Tokenize: keep names that match and capture their prefix; preserve
        # order of first occurrence for stable group iteration ('stable'
        # in MATLAB's unique).
        series_names: list[str] = []
        prefixes: list[str] = []
        unique_prefixes: list[str] = []
        prefix_to_indices: dict[str, list[int]] = {}
        for name in names:
            m = series_re.match(name)
            if not m:
                continue
            p = m.group(1)
            idx = len(series_names)
            series_names.append(name)
            prefixes.append(p)
            if p not in prefix_to_indices:
                prefix_to_indices[p] = []
                unique_prefixes.append(p)
            prefix_to_indices[p].append(idx)

        if not series_names:
            return groups

        for p in unique_prefixes:
            sorted_series = sorted(series_names[i] for i in prefix_to_indices[p])
            epoch = [os.path.join(directory, sorted_series[0])]

            ok = True
            for ancillary in patterns[1:]:
                rx = "^" + matlab_to_python_regex(ancillary).replace("#", re.escape(p)) + "$"
                try:
                    anc_re = re.compile(rx)
                except re.error:
                    ok = False
                    break
                matched = sorted(n for n in names if anc_re.match(n))
                if not matched:
                    ok = False
                    break
                epoch.append(os.path.join(directory, matched[0]))

            if ok:
                groups.append(epoch)

        return groups

    def __repr__(self) -> str:
        n_patterns = len(self._fileparameters.get("filematch", []))
        return f"ndi_file_navigator_rhd_series(patterns={n_patterns})"
