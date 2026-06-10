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
    def read_audrey_bpod_json(s: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert a VHAudreyBPod config dict to a 7-stimulus parameter list.

        Port of MATLAB ``ndi.daq.metadatareader.VHAudreyBPod.readAudreyBPodJson``:
        entries 1-6 describe Solenoids 1-6, entry 7 the Wash/Water stimulus. Each
        entry carries ``stimid``, ``isUsed``, ``solenoidValve``, ``tastant``,
        ``solenoidOpenDuration``, ``DelayBeforeNextStim``, ``WashDuration``,
        ``InterStimulusTime`` and ``isblank`` (1 when the tastant is water).

        Args:
            s: the parsed BPod config dict (fields ``DelayB4NextStim``,
                ``WashDuration``, ``InterStimTime``, ``WaterSolenoidNum``,
                ``Sol{k}``, ``Sol{k}Valve``, ``Sol{k}_Tastant``,
                ``Stim{k}OpenDuration``).

        Returns:
            A list of 7 stimulus parameter dicts.
        """
        delay = s["DelayB4NextStim"]
        wash = s["WashDuration"]
        inter = s["InterStimTime"]

        parameters: list[dict[str, Any]] = []
        for k in range(1, 7):
            tastant = s[f"Sol{k}_Tastant"]
            parameters.append(
                {
                    "stimid": k,
                    "isUsed": s[f"Sol{k}"],
                    "solenoidValve": s[f"Sol{k}Valve"],
                    "tastant": tastant,
                    "solenoidOpenDuration": s[f"Stim{k}OpenDuration"],
                    "DelayBeforeNextStim": delay,
                    "WashDuration": wash,
                    "InterStimulusTime": inter,
                    "isblank": 1 if str(tastant).lower() == "water" else 0,
                }
            )

        parameters.append(
            {
                "stimid": 7,
                "isUsed": 1,
                "solenoidValve": s["WaterSolenoidNum"],
                "tastant": "Water",
                "solenoidOpenDuration": wash,
                "DelayBeforeNextStim": delay,
                "WashDuration": wash,
                "InterStimulusTime": inter,
                "isblank": 0,
            }
        )
        return parameters

    @classmethod
    def _read_summary_json(cls, filepath: str) -> list[dict[str, Any]]:
        """
        Read stimulus parameters from a BPod summary log JSON file.

        If the JSON is a VHAudreyBPod config (has the BPod parameter fields), it
        is transformed into the 7-stimulus parameter list via
        :meth:`read_audrey_bpod_json`; otherwise the raw content is returned (a
        list as-is, a dict wrapped in a list) for backward compatibility.

        Args:
            filepath: Path to the summary_log.json file

        Returns:
            List of parameter dicts
        """
        if not Path(filepath).is_file():
            return []

        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            if "DelayB4NextStim" in data and "WashDuration" in data:
                return cls.read_audrey_bpod_json(data)
            return [data]
        if isinstance(data, list):
            return data
        return []

    def __repr__(self) -> str:
        return f"ndi_daq_metadatareader_VHAudreyBPod(id='{self.id[:8]}...')"
