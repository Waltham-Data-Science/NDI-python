"""
ndi.file.type.mfdaq_epoch_channel - Channel metadata for MFDAQ epoch files.

Provides the ndi_file_type_mfdaq__epoch__channel dataclass describing channel information
for multi-function DAQ recordings.

MATLAB equivalent: src/ndi/+ndi/+file/+type/mfdaq_epoch_channel.m
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChannelInfo:
    """Information about a single channel in an MFDAQ recording."""

    name: str = ""
    type: str = ""
    time_channel: int = 1
    sample_rate: float = 0.0
    offset: float = 0.0
    scale: float = 1.0
    number: int = 0
    group: int = 0
    dataclass: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChannelInfo:
        return cls(
            name=d.get("name", ""),
            type=d.get("type", ""),
            time_channel=d.get("time_channel", 1),
            sample_rate=d.get("sample_rate", 0.0),
            offset=d.get("offset", 0.0),
            scale=d.get("scale", 1.0),
            number=d.get("number", 0),
            group=d.get("group", 0),
            dataclass=d.get("dataclass", ""),
        )


@dataclass
class ndi_file_type_mfdaq__epoch__channel:
    """
    Channel metadata for a multi-function DAQ epoch.

    Stores information about all channels available in an epoch,
    including type, sample rate, scale, and group assignments.

    Attributes:
        channel_information: List of ChannelInfo describing each channel

    Example:
        >>> ch = ChannelInfo(name='ai1', type='analog_in', sample_rate=30000.0, number=1)
        >>> mec = ndi_file_type_mfdaq__epoch__channel([ch])
        >>> mec.channels_of_type('analog_in')
        [ChannelInfo(name='ai1', ...)]
    """

    channel_information: list[ChannelInfo] = field(default_factory=list)

    def channels_of_type(self, channel_type: str) -> list[ChannelInfo]:
        """
        Get channels of a specific type.

        Args:
            channel_type: Channel type to filter by (e.g., 'analog_in', 'ai')

        Returns:
            List of matching ChannelInfo objects
        """
        return [ch for ch in self.channel_information if ch.type == channel_type]

    def channel_numbers(self, channel_type: str | None = None) -> list[int]:
        """
        Get channel numbers, optionally filtered by type.

        Args:
            channel_type: If specified, only return channels of this type

        Returns:
            List of channel numbers
        """
        if channel_type is None:
            return [ch.number for ch in self.channel_information]
        return [ch.number for ch in self.channel_information if ch.type == channel_type]

    def create_properties(
        self,
        channel_structure: list[dict[str, Any]] | list[ChannelInfo],
        **kwargs: Any,
    ) -> ndi_file_type_mfdaq__epoch__channel:
        """
        Create/set channel properties from a structure.

        MATLAB equivalent: ndi.file.type.mfdaq_epoch_channel/create_properties

        Args:
            channel_structure: List of channel dicts or ChannelInfo objects
            **kwargs: Additional keyword arguments (reserved for future use)

        Returns:
            Self for chaining
        """
        self.channel_information = []
        for item in channel_structure:
            if isinstance(item, ChannelInfo):
                self.channel_information.append(item)
            elif isinstance(item, dict):
                self.channel_information.append(ChannelInfo.from_dict(item))
        return self

    def readFromFile(self, filename: str) -> ndi_file_type_mfdaq__epoch__channel:
        """
        Read channel information from a file.

        MATLAB equivalent: ndi.file.type.mfdaq_epoch_channel/readFromFile

        Supports both JSON format (Python-generated) and the MATLAB
        tab-delimited format (read via ``vlt.file.loadStructArray``).

        Args:
            filename: Path to the channel list file

        Returns:
            Self for chaining
        """
        # Try JSON first (Python-generated files)
        try:
            with open(filename) as f:
                data = json.load(f)
            self.channel_information = []
            for ch_data in data.get("channel_information", []):
                self.channel_information.append(ChannelInfo.from_dict(ch_data))
            return self
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        # Fallback: vlt.file.loadStructArray (MATLAB tab-delimited format)
        from vlt.file import loadStructArray

        records = loadStructArray(filename)
        self.channel_information = []
        for rec in records:
            self.channel_information.append(
                ChannelInfo(
                    name=str(rec.get("name", "")),
                    type=str(rec.get("type", "")),
                    time_channel=int(rec.get("time_channel", 1)),
                    sample_rate=float(rec.get("sample_rate", 0.0)),
                    offset=float(rec.get("offset", 0.0)),
                    scale=float(rec.get("scale", 1.0)),
                    number=int(rec.get("number", 0)),
                    group=int(rec.get("group", 0)),
                    dataclass=str(rec.get("dataclass", "")),
                )
            )
        return self

    def writeToFile(self, filename: str) -> tuple[bool, str]:
        """
        Write channel information to a JSON file.

        MATLAB equivalent: ndi.file.type.mfdaq_epoch_channel/writeToFile

        Args:
            filename: Path to write

        Returns:
            Tuple of (success, error_message)
        """
        try:
            data = {"channel_information": [ch.to_dict() for ch in self.channel_information]}
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
            return True, ""
        except Exception as e:
            return False, str(e)

    @staticmethod
    def channelgroupdecoding(
        channel_info: list[ChannelInfo],
        channel_type: str,
        channels: list[int],
    ) -> tuple[list[int], list[list[int]], list[list[int]]]:
        """
        Decode channel group assignments.

        MATLAB equivalent: ndi.file.type.mfdaq_epoch_channel.channelgroupdecoding

        Given a list of requested channels, returns the corresponding
        group assignments and index mappings.

        Note:
            ``channel_indexes_in_groups`` contains 0-based indices into the
            segment data columns (within the subset of channels belonging to
            that group and type). In MATLAB these are 1-based.

        Args:
            channel_info: List of ChannelInfo
            channel_type: Type of channels to look up
            channels: Channel numbers to decode

        Returns:
            Tuple of (groups, channel_indexes_in_groups,
            channel_indexes_in_output):
            - groups: Unique group numbers for requested channels
            - channel_indexes_in_groups: For each group, 0-based column
              indices into the segment data for the requested channels
            - channel_indexes_in_output: For each group, 0-based indices
              into the output data array
        """
        from ..daq.mfdaq import standardize_channel_type

        ct_std = standardize_channel_type(channel_type)

        # Filter to channels matching the requested type
        ci_typed = [ch for ch in channel_info if standardize_channel_type(ch.type) == ct_std]

        groups: list[int] = []
        channel_indexes_in_groups: list[list[int]] = []
        channel_indexes_in_output: list[list[int]] = []

        for c_idx, ch_num in enumerate(channels):
            # Find this channel in the type-filtered list
            matches = [i for i, ci in enumerate(ci_typed) if ci.number == ch_num]
            if not matches:
                raise ValueError(f"Channel number {ch_num} not found in record.")
            if len(matches) > 1:
                raise ValueError(f"Channel number {ch_num} found multiple times in record.")

            ch_info = ci_typed[matches[0]]
            grp = ch_info.group

            # Find or create group entry
            if grp in groups:
                g_idx = groups.index(grp)
            else:
                groups.append(grp)
                g_idx = len(groups) - 1
                channel_indexes_in_groups.append([])
                channel_indexes_in_output.append([])

            # Find the 0-based index of this channel within its group
            subset_group = [ci for ci in ci_typed if ci.group == grp]
            chan_index_in_group = next(
                i for i, ci in enumerate(subset_group) if ci.number == ch_num
            )

            channel_indexes_in_groups[g_idx].append(chan_index_in_group)
            channel_indexes_in_output[g_idx].append(c_idx)

        return groups, channel_indexes_in_groups, channel_indexes_in_output

    def __len__(self) -> int:
        return len(self.channel_information)

    def __repr__(self) -> str:
        return f"ndi_file_type_mfdaq__epoch__channel(n_channels={len(self.channel_information)})"
