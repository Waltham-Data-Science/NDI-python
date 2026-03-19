"""
ndi.daq.metadatareader.VHAudreyBPod - VH Lab Audrey BPod stimulus metadata reader.

Reads stimulus parameters from BPod behavioral task summary log JSON files
used in the VH Lab taste experiments.

MATLAB equivalent: src/ndi/+ndi/+daq/+metadatareader/VHAudreyBPod.m
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..metadatareader import ndi_daq_metadatareader


class ndi_daq_metadatareader_VHAudreyBPod(ndi_daq_metadatareader):
    """
    Metadata reader for VH Lab Audrey BPod stimulus systems.

    Reads stimulus parameters from JSON summary log files produced by
    BPod behavioral task systems.

    Example:
        >>> reader = ndi_daq_metadatareader_VHAudreyBPod()
        >>> params = reader.readmetadata(['triggers.tsv', 'summary_log.json'])
    """

    SUMMARY_FILE_PATTERN = r"_summary_log\.json$"

    def __init__(
        self,
        tsv_pattern: str = "",
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(
            tsv_pattern=tsv_pattern,
            identifier=identifier,
            session=session,
            document=document,
        )

    def readmetadata(
        self,
        epochfiles: list[str],
    ) -> list[dict[str, Any]]:
        """
        Read stimulus metadata from BPod summary log files.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of parameter dictionaries
        """
        # First try TSV-based reading from base class
        if self._tab_separated_file_parameter:
            try:
                return super().readmetadata(epochfiles)
            except (ValueError, FileNotFoundError):
                pass

        # Look for summary_log.json
        summary_file = self._find_summary_file(epochfiles)
        if summary_file is None:
            return []

        return self._read_summary_json(summary_file)

    def _find_summary_file(self, epochfiles: list[str]) -> str | None:
        """Find the BPod summary log JSON file in epoch files."""
        pattern = re.compile(self.SUMMARY_FILE_PATTERN, re.IGNORECASE)
        for f in epochfiles:
            if pattern.search(f):
                return f
        return None

    @staticmethod
    def _read_summary_json(filepath: str) -> list[dict[str, Any]]:
        """
        Read stimulus parameters from a BPod summary log JSON file.

        Args:
            filepath: Path to the summary_log.json file

        Returns:
            List of parameter dicts
        """
        if not Path(filepath).is_file():
            return []

        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    def __repr__(self) -> str:
        return f"ndi_daq_metadatareader_VHAudreyBPod(id='{self.id[:8]}...')"
