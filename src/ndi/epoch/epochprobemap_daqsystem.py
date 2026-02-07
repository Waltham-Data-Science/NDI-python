"""
ndi.epoch.epochprobemap_daqsystem - EpochProbeMap with DAQ system device strings.

Extends EpochProbeMap with structured device string parsing via DAQSystemString,
plus serialization and file I/O.

MATLAB equivalent: src/ndi/+ndi/+epoch/epochprobemap_daqsystem.m
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .epochprobemap import EpochProbeMap
from ..daq.daqsystemstring import DAQSystemString


@dataclass
class EpochProbeMapDAQSystem(EpochProbeMap):
    """
    Epoch probe map with DAQ system device string support.

    Extends EpochProbeMap with a structured DAQSystemString for the
    devicestring field, plus serialization and file I/O support.

    The devicestring is parsed into a DAQSystemString that provides
    access to device name, channel types, and channel lists.

    Example:
        >>> epm = EpochProbeMapDAQSystem(
        ...     name='electrode1',
        ...     reference=1,
        ...     type='n-trode',
        ...     devicestring='intan1:ai1-4',
        ...     subjectstring='mouse001',
        ... )
        >>> epm.daqsystemstring.channel_list('ai')
        [1, 2, 3, 4]
    """

    def __post_init__(self):
        """Validate fields and parse device string."""
        super().__post_init__()
        self._daqsystemstring: Optional[DAQSystemString] = None

    @property
    def daqsystemstring(self) -> DAQSystemString:
        """Get parsed DAQSystemString from devicestring."""
        if self._daqsystemstring is None:
            self._daqsystemstring = DAQSystemString.parse(self.devicestring)
        return self._daqsystemstring

    def serialization_struct(self) -> Dict[str, Any]:
        """
        Create a structure suitable for serialization.

        Returns:
            Dict with all fields
        """
        return {
            'name': self.name,
            'reference': self.reference,
            'type': self.type,
            'devicestring': self.devicestring,
            'subjectstring': self.subjectstring,
        }

    def serialize(self) -> str:
        """
        Serialize to a tab-delimited string.

        Returns:
            Tab-delimited string: name\\treference\\ttype\\tdevicestring\\tsubjectstring
        """
        return '\t'.join([
            self.name,
            str(self.reference),
            self.type,
            self.devicestring,
            self.subjectstring,
        ])

    def save_to_file(self, filename: str) -> None:
        """
        Write this epoch probe map to a file.

        Args:
            filename: Path to write to
        """
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, 'w') as f:
            f.write(self.serialize() + '\n')

    @classmethod
    def decode(cls, s: str) -> 'EpochProbeMapDAQSystem':
        """
        Decode from a serialized string.

        Args:
            s: Tab-delimited string

        Returns:
            EpochProbeMapDAQSystem object

        Raises:
            ValueError: If the string cannot be parsed
        """
        parts = s.strip().split('\t')
        if len(parts) < 5:
            raise ValueError(
                f"Expected 5 tab-separated fields, got {len(parts)}: '{s}'"
            )

        return cls(
            name=parts[0],
            reference=int(parts[1]),
            type=parts[2],
            devicestring=parts[3],
            subjectstring=parts[4],
        )

    @classmethod
    def load_from_file(cls, filename: str) -> List['EpochProbeMapDAQSystem']:
        """
        Load epoch probe maps from a file.

        Each line is one serialized EpochProbeMapDAQSystem.

        Args:
            filename: Path to read from

        Returns:
            List of EpochProbeMapDAQSystem objects
        """
        results = []
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    results.append(cls.decode(line))
        return results

    def __repr__(self) -> str:
        return (
            f"EpochProbeMapDAQSystem(name='{self.name}', "
            f"reference={self.reference}, type='{self.type}', "
            f"devicestring='{self.devicestring}')"
        )
