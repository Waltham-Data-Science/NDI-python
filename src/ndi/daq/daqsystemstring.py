"""
ndi.daq.daqsystemstring - Parse device-channel specification strings.

Parses device strings like 'mydevice:ai1-5,7;di1-3' into structured
representations of device names, channel types, and channel numbers.

MATLAB equivalent: src/ndi/+ndi/+daq/daqsystemstring.m
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class DAQSystemString:
    """
    Describes a device and its channels.

    Parses and generates device strings in the format:
        DEVICENAME:CHANNELTYPE#,#-#;CHANNELTYPE#,#

    Examples:
        'mydevice:ai1-5,7,23'  -> device='mydevice', channels=[('ai', [1,2,3,4,5,7,23])]
        'mydevice:ai1-5;di1'   -> two channel groups

    Attributes:
        devicename: Name of the device
        channels: List of (channeltype, channellist) tuples
    """

    devicename: str = ''
    channels: List[Tuple[str, List[int]]] = field(default_factory=list)

    @classmethod
    def parse(cls, devstr: str) -> 'DAQSystemString':
        """
        Parse a device string into a DAQSystemString.

        Args:
            devstr: Device string like 'mydevice:ai1-5,7;di1'

        Returns:
            Parsed DAQSystemString

        Raises:
            ValueError: If the string format is invalid
        """
        if not devstr or ':' not in devstr:
            if devstr:
                return cls(devicename=devstr, channels=[])
            return cls()

        colon_idx = devstr.index(':')
        devicename = devstr[:colon_idx]
        channel_str = devstr[colon_idx + 1:]

        if not channel_str:
            return cls(devicename=devicename, channels=[])

        channels = []
        # Split by semicolons for multiple channel groups
        groups = channel_str.split(';')

        for group in groups:
            group = group.strip()
            if not group:
                continue

            # Extract channel type prefix (letters) and number spec
            match = re.match(r'^([a-zA-Z_]+)(.*)', group)
            if not match:
                raise ValueError(f"Invalid channel group: '{group}'")

            channeltype = match.group(1)
            numspec = match.group(2)

            channellist = _parse_channel_numbers(numspec)
            channels.append((channeltype, channellist))

        return cls(devicename=devicename, channels=channels)

    def devicestring(self) -> str:
        """
        Generate a device string from this object.

        Returns:
            Formatted device string like 'mydevice:ai1-5;di1'
        """
        if not self.channels:
            return self.devicename

        parts = []
        for channeltype, channellist in self.channels:
            if not channellist:
                parts.append(channeltype)
            else:
                numstr = _format_channel_numbers(channellist)
                parts.append(f"{channeltype}{numstr}")

        return f"{self.devicename}:{';'.join(parts)}"

    def channel_types(self) -> List[str]:
        """Get list of unique channel types."""
        return [ct for ct, _ in self.channels]

    def channel_list(self, channeltype: Optional[str] = None) -> List[int]:
        """
        Get channel numbers, optionally filtered by type.

        Args:
            channeltype: If specified, only return channels of this type

        Returns:
            List of channel numbers
        """
        if channeltype is None:
            result = []
            for _, cl in self.channels:
                result.extend(cl)
            return result

        for ct, cl in self.channels:
            if ct == channeltype:
                return list(cl)
        return []

    def __str__(self) -> str:
        return self.devicestring()

    def __repr__(self) -> str:
        return f"DAQSystemString('{self.devicestring()}')"

    def __eq__(self, other) -> bool:
        if not isinstance(other, DAQSystemString):
            return False
        return self.devicename == other.devicename and self.channels == other.channels


def _parse_channel_numbers(spec: str) -> List[int]:
    """
    Parse a channel number specification.

    Args:
        spec: String like '1-5,7,23' or '1,2,3'

    Returns:
        Sorted list of channel numbers
    """
    if not spec:
        return []

    numbers = set()
    parts = spec.split(',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            # Range like '1-5'
            range_parts = part.split('-')
            if len(range_parts) == 2:
                try:
                    start = int(range_parts[0])
                    end = int(range_parts[1])
                    numbers.update(range(start, end + 1))
                except ValueError:
                    raise ValueError(f"Invalid range: '{part}'")
        else:
            try:
                numbers.add(int(part))
            except ValueError:
                raise ValueError(f"Invalid channel number: '{part}'")

    return sorted(numbers)


def _format_channel_numbers(channels: List[int]) -> str:
    """
    Format channel numbers into compact string.

    Args:
        channels: List of channel numbers

    Returns:
        Compact string like '1-5,7,23'
    """
    if not channels:
        return ''

    sorted_ch = sorted(set(channels))
    parts = []
    i = 0

    while i < len(sorted_ch):
        start = sorted_ch[i]
        end = start

        # Find consecutive range
        while i + 1 < len(sorted_ch) and sorted_ch[i + 1] == end + 1:
            end = sorted_ch[i + 1]
            i += 1

        if end > start:
            parts.append(f"{start}-{end}")
        else:
            parts.append(str(start))
        i += 1

    return ','.join(parts)
