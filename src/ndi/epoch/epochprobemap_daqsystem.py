"""
ndi.epoch.epochprobemap_daqsystem - ndi_epoch_epochprobemap with DAQ system device strings.

Extends ndi_epoch_epochprobemap with structured device string parsing via ndi_daq_daqsystemstring,
plus serialization and file I/O.

MATLAB equivalent: src/ndi/+ndi/+epoch/epochprobemap_daqsystem.m
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic

from ..daq.daqsystemstring import ndi_daq_daqsystemstring
from .epochprobemap import ndi_epoch_epochprobemap


@dataclass
class ndi_epoch_epochprobemap__daqsystem(ndi_epoch_epochprobemap):
    """
    ndi_epoch_epoch probe map with DAQ system device string support.

    Extends ndi_epoch_epochprobemap with a structured ndi_daq_daqsystemstring for the
    devicestring field, plus serialization and file I/O support.

    The devicestring is parsed into a ndi_daq_daqsystemstring that provides
    access to device name, channel types, and channel lists.

    Example:
        >>> epm = ndi_epoch_epochprobemap__daqsystem(
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
        self._daqsystemstring: ndi_daq_daqsystemstring | None = None

    @property
    def daqsystemstring(self) -> ndi_daq_daqsystemstring:
        """Get parsed ndi_daq_daqsystemstring from devicestring."""
        if self._daqsystemstring is None:
            self._daqsystemstring = ndi_daq_daqsystemstring.parse(self.devicestring)
        return self._daqsystemstring

    def serialization_struct(self) -> dict[str, Any]:
        """
        Create a structure suitable for serialization.

        Returns:
            Dict with all fields
        """
        return {
            "name": self.name,
            "reference": self.reference,
            "type": self.type,
            "devicestring": self.devicestring,
            "subjectstring": self.subjectstring,
        }

    def serialize(self) -> str:
        """
        Serialize to a tab-delimited string.

        Returns:
            Tab-delimited string: name\\treference\\ttype\\tdevicestring\\tsubjectstring
        """
        return "\t".join(
            [
                self.name,
                str(self.reference),
                self.type,
                self.devicestring,
                self.subjectstring,
            ]
        )

    @pydantic.validate_call
    def savetofile(self, filename: str) -> None:
        """
        Write this epoch probe map to a file.

        Args:
            filename: Path to write to
        """
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w") as f:
            f.write(self.serialize() + "\n")

    @classmethod
    def decode(cls, s: str) -> ndi_epoch_epochprobemap__daqsystem:
        """
        Decode from a serialized string.

        Args:
            s: Tab-delimited string

        Returns:
            ndi_epoch_epochprobemap__daqsystem object

        Raises:
            ValueError: If the string cannot be parsed
        """
        parts = s.strip().split("\t")
        if len(parts) < 5:
            raise ValueError(f"Expected 5 tab-separated fields, got {len(parts)}: '{s}'")

        return cls(
            name=parts[0],
            reference=int(parts[1]),
            type=parts[2],
            devicestring=parts[3],
            subjectstring=parts[4],
        )

    @classmethod
    def loadfromfile(cls, filename: str) -> list[ndi_epoch_epochprobemap__daqsystem]:
        """
        Load epoch probe maps from a file.

        Each line is one serialized ndi_epoch_epochprobemap__daqsystem.

        Args:
            filename: Path to read from

        Returns:
            List of ndi_epoch_epochprobemap__daqsystem objects
        """
        results = []
        with open(filename) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    results.append(cls.decode(line))
        return results

    def __repr__(self) -> str:
        return (
            f"ndi_epoch_epochprobemap__daqsystem(name='{self.name}', "
            f"reference={self.reference}, type='{self.type}', "
            f"devicestring='{self.devicestring}')"
        )
