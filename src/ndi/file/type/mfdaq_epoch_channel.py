"""
ndi.file.type.mfdaq_epoch_channel - Channel metadata for MFDAQ epoch files.

Provides the MFDAQEpochChannel dataclass describing channel information
for multi-function DAQ recordings.

MATLAB equivalent: src/ndi/+ndi/+file/+type/mfdaq_epoch_channel.m
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ChannelInfo:
    """Information about a single channel in an MFDAQ recording."""

    name: str = ''
    type: str = ''
    time_channel: int = 1
    sample_rate: float = 0.0
    offset: float = 0.0
    scale: float = 1.0
    number: int = 0
    group: int = 0
    dataclass: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ChannelInfo':
        return cls(
            name=d.get('name', ''),
            type=d.get('type', ''),
            time_channel=d.get('time_channel', 1),
            sample_rate=d.get('sample_rate', 0.0),
            offset=d.get('offset', 0.0),
            scale=d.get('scale', 1.0),
            number=d.get('number', 0),
            group=d.get('group', 0),
            dataclass=d.get('dataclass', ''),
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

    channel_information: List[ChannelInfo] = field(default_factory=list)

    def channels_of_type(self, channel_type: str) -> List[ChannelInfo]:
        """
        Get channels of a specific type.

        Args:
            channel_type: Channel type to filter by (e.g., 'analog_in', 'ai')

        Returns:
            List of matching ChannelInfo objects
        """
        return [
            ch for ch in self.channel_information
            if ch.type == channel_type
        ]

    def channel_numbers(self, channel_type: Optional[str] = None) -> List[int]:
        """
        Get channel numbers, optionally filtered by type.

        Args:
            channel_type: If specified, only return channels of this type

        Returns:
            List of channel numbers
        """
        if channel_type is None:
            return [ch.number for ch in self.channel_information]
        return [
            ch.number for ch in self.channel_information
            if ch.type == channel_type
        ]

    def read_from_file(self, filename: str) -> None:
        """
        Read channel information from a JSON file.

        Args:
            filename: Path to the JSON file
        """
        with open(filename, 'r') as f:
            data = json.load(f)

        self.channel_information = []
        for ch_data in data.get('channel_information', []):
            self.channel_information.append(ChannelInfo.from_dict(ch_data))

    def write_to_file(self, filename: str) -> None:
        """
        Write channel information to a JSON file.

        Args:
            filename: Path to write
        """
        data = {
            'channel_information': [
                ch.to_dict() for ch in self.channel_information
            ]
        }
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def channel_group_decoding(
        channel_info: List[ChannelInfo],
        channel_type: str,
        channels: List[int],
    ) -> List[int]:
        """
        Decode channel group assignments.

        Given a list of requested channels, returns the corresponding
        group assignments from the channel information.

        Args:
            channel_info: List of ChannelInfo
            channel_type: Type of channels to look up
            channels: Channel numbers to decode

        Returns:
            List of group numbers for each requested channel
        """
        # Build lookup by (type, number) -> group
        lookup = {
            (ch.type, ch.number): ch.group
            for ch in channel_info
        }

        groups = []
        for ch_num in channels:
            group = lookup.get((channel_type, ch_num), 0)
            groups.append(group)

        return groups

    def __len__(self) -> int:
        return len(self.channel_information)

    def __repr__(self) -> str:
        return f"MFDAQEpochChannel(n_channels={len(self.channel_information)})"
