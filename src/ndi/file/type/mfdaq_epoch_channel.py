"""
ndi.file.type.mfdaq_epoch_channel - Channel metadata for MFDAQ epoch files.

Provides the MFDAQEpochChannel dataclass describing channel information
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
class MFDAQEpochChannel:
    """
    Channel metadata for a multi-function DAQ epoch.

    Stores information about all channels available in an epoch,
    including type, sample rate, scale, and group assignments.

    Attributes:
        channel_information: List of ChannelInfo describing each channel

    Example:
        >>> ch = ChannelInfo(name='ai1', type='analog_in', sample_rate=30000.0, number=1)
        >>> mec = MFDAQEpochChannel([ch])
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
    ) -> MFDAQEpochChannel:
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

    def readFromFile(self, filename: str) -> MFDAQEpochChannel:
        """
        Read channel information from a JSON file.

        MATLAB equivalent: ndi.file.type.mfdaq_epoch_channel/readFromFile

        Args:
            filename: Path to the JSON file

        Returns:
            Self for chaining
        """
        with open(filename) as f:
            data = json.load(f)

        self.channel_information = []
        for ch_data in data.get("channel_information", []):
            self.channel_information.append(ChannelInfo.from_dict(ch_data))
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

        Args:
            channel_info: List of ChannelInfo
            channel_type: Type of channels to look up
            channels: Channel numbers to decode

        Returns:
            Tuple of (groups, channel_indexes_in_groups,
            channel_indexes_in_output):
            - groups: Unique group numbers for requested channels
            - channel_indexes_in_groups: For each group, the channel
              numbers that belong to it
            - channel_indexes_in_output: For each group, the indexes
              into the output data corresponding to those channels
        """
        # Build lookup by (type, number) -> (group, index in channel_info)
        lookup: dict[tuple[str, int], int] = {}
        for ch in channel_info:
            lookup[(ch.type, ch.number)] = ch.group

        # Get group assignment for each requested channel
        channel_groups = []
        for ch_num in channels:
            group = lookup.get((channel_type, ch_num), 0)
            channel_groups.append(group)

        # Find unique groups (preserving order)
        seen: set[int] = set()
        groups: list[int] = []
        for g in channel_groups:
            if g not in seen:
                seen.add(g)
                groups.append(g)

        # Build index mappings for each group
        channel_indexes_in_groups: list[list[int]] = []
        channel_indexes_in_output: list[list[int]] = []

        for g in groups:
            # Channel numbers belonging to this group
            ch_in_group = [channels[i] for i in range(len(channels)) if channel_groups[i] == g]
            # Indexes into the output array for this group
            idx_in_output = [i for i in range(len(channels)) if channel_groups[i] == g]
            channel_indexes_in_groups.append(ch_in_group)
            channel_indexes_in_output.append(idx_in_output)

        return groups, channel_indexes_in_groups, channel_indexes_in_output

    def __len__(self) -> int:
        return len(self.channel_information)

    def __repr__(self) -> str:
        return f"MFDAQEpochChannel(n_channels={len(self.channel_information)})"
