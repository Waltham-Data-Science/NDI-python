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

    #: Serialized column order (MATLAB serialization_struct field order).
    _FIELDS = ("name", "reference", "type", "devicestring", "subjectstring")

    def _data_row(self) -> str:
        """This object's tab-joined data row (reference as an integer)."""
        return "\t".join(
            [self.name, str(self.reference), self.type, self.devicestring, self.subjectstring]
        )

    def serialize(self) -> str:
        """
        Serialize to a tab-delimited string with a header row.

        Matches MATLAB ``ndi.epoch.epochprobemap_daqsystem/serialize``: a header
        row of field names followed by one data row per object. (The previous
        Python output was a single header-less line, which crashed MATLAB's
        decode and could not represent an array — audit C10.)

        Returns:
            ``"name\\treference\\ttype\\tdevicestring\\tsubjectstring\\n<row>"``
        """
        return "\t".join(self._FIELDS) + "\n" + self._data_row()

    @classmethod
    def serialize_array(cls, objs: list[ndi_epoch_epochprobemap__daqsystem]) -> str:
        """Serialize a list of probe maps as one header row + one row per object."""
        rows = [o._data_row() for o in objs]
        return "\n".join(["\t".join(cls._FIELDS), *rows])

    @pydantic.validate_call
    def savetofile(self, filename: str) -> None:
        """
        Write this epoch probe map to a file (header row + one data row).

        Args:
            filename: Path to write to
        """
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w") as f:
            f.write(self.serialize() + "\n")

    @classmethod
    def save_array_to_file(
        cls, objs: list[ndi_epoch_epochprobemap__daqsystem], filename: str
    ) -> None:
        """Write a list of probe maps to a file (one header row + N data rows)."""
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w") as f:
            f.write(cls.serialize_array(objs) + "\n")

    @staticmethod
    def _is_header_row(parts: list[str]) -> bool:
        """A header row's ``reference`` column is the literal field name, not an int."""
        if len(parts) < 2:
            return False
        try:
            int(parts[1])
            return False
        except ValueError:
            return True

    @classmethod
    def _parse_rows(cls, s: str) -> list[ndi_epoch_epochprobemap__daqsystem]:
        """Parse a serialized string (with or without a header) into objects."""
        lines = [ln for ln in s.replace("\r\n", "\n").split("\n") if ln.strip()]
        if not lines:
            return []

        header = list(cls._FIELDS)
        first = lines[0].split("\t")
        if cls._is_header_row(first):
            header = first
            lines = lines[1:]

        results: list[ndi_epoch_epochprobemap__daqsystem] = []
        for line in lines:
            if line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < len(header):
                continue
            row = dict(zip(header, parts))
            results.append(
                cls(
                    name=row.get("name", ""),
                    reference=int(row["reference"]),
                    type=row.get("type", ""),
                    devicestring=row.get("devicestring", ""),
                    subjectstring=row.get("subjectstring", ""),
                )
            )
        return results

    @classmethod
    def decode(cls, s: str) -> ndi_epoch_epochprobemap__daqsystem:
        """
        Decode a single probe map from a serialized string (header skipped).

        Args:
            s: Serialized string (header row + data row, or a bare data row).

        Returns:
            The first ndi_epoch_epochprobemap__daqsystem in the string.

        Raises:
            ValueError: If no data row can be parsed.
        """
        objs = cls._parse_rows(s)
        if not objs:
            raise ValueError(f"No epochprobemap data row found in serialized string: '{s}'")
        return objs[0]

    @classmethod
    def decode_array(cls, s: str) -> list[ndi_epoch_epochprobemap__daqsystem]:
        """Decode all probe maps from a serialized string (header skipped)."""
        return cls._parse_rows(s)

    @classmethod
    def loadfromfile(cls, filename: str) -> list[ndi_epoch_epochprobemap__daqsystem]:
        """
        Load epoch probe maps from a file (header row skipped if present).

        Args:
            filename: Path to read from

        Returns:
            List of ndi_epoch_epochprobemap__daqsystem objects
        """
        with open(filename) as f:
            return cls._parse_rows(f.read())

    def __repr__(self) -> str:
        return (
            f"ndi_epoch_epochprobemap__daqsystem(name='{self.name}', "
            f"reference={self.reference}, type='{self.type}', "
            f"devicestring='{self.devicestring}')"
        )
