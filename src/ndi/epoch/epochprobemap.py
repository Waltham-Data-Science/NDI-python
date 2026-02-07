"""
ndi.epoch.epochprobemap - Probe-device mapping for epochs.

This module provides the EpochProbeMap class that describes how
probes (logical measurement devices) map to physical DAQ channels
during an epoch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EpochProbeMap:
    """
    Mapping between a probe and a device for an epoch.

    EpochProbeMap describes how a logical probe (e.g., an electrode)
    maps to physical channels on a data acquisition device during
    a specific epoch.

    Attributes:
        name: Probe name (no whitespace allowed)
        reference: Reference number (non-negative integer)
        type: Probe type identifier (no whitespace)
        devicestring: Device identifier string (format: "devicename:class:details")
        subjectstring: Subject identifier string

    Example:
        >>> epm = EpochProbeMap(
        ...     name='electrode1',
        ...     reference=1,
        ...     type='n-trode',
        ...     devicestring='intan1:SpikeInterfaceReader:',
        ...     subjectstring='mouse001',
        ... )
    """

    name: str
    reference: int
    type: str
    devicestring: str = ""
    subjectstring: str = ""

    def __post_init__(self):
        """Validate fields after initialization."""
        # Validate no whitespace in name
        if " " in self.name or "\t" in self.name:
            raise ValueError(f"name cannot contain whitespace: '{self.name}'")

        # Validate no whitespace in type
        if " " in self.type or "\t" in self.type:
            raise ValueError(f"type cannot contain whitespace: '{self.type}'")

        # Validate reference is non-negative
        if self.reference < 0:
            raise ValueError(f"reference must be non-negative: {self.reference}")

    @property
    def devicename(self) -> str:
        """Extract device name from devicestring."""
        if not self.devicestring:
            return ""
        parts = self.devicestring.split(":")
        return parts[0] if parts else ""

    @property
    def deviceclass(self) -> str:
        """Extract device class from devicestring."""
        if not self.devicestring:
            return ""
        parts = self.devicestring.split(":")
        return parts[1] if len(parts) > 1 else ""

    def matches(
        self,
        name: str | None = None,
        reference: int | None = None,
        type: str | None = None,
    ) -> bool:
        """
        Check if this probe map matches the given criteria.

        Args:
            name: Probe name to match (None = any)
            reference: Reference number to match (None = any)
            type: Probe type to match (None = any)

        Returns:
            True if all specified criteria match
        """
        if name is not None and self.name != name:
            return False
        if reference is not None and self.reference != reference:
            return False
        if type is not None and self.type != type:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "reference": self.reference,
            "type": self.type,
            "devicestring": self.devicestring,
            "subjectstring": self.subjectstring,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EpochProbeMap:
        """Create from dictionary representation."""
        return cls(
            name=data.get("name", ""),
            reference=data.get("reference", 0),
            type=data.get("type", ""),
            devicestring=data.get("devicestring", ""),
            subjectstring=data.get("subjectstring", ""),
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"{self.name}|{self.reference}|{self.type}"

    def __eq__(self, other: Any) -> bool:
        """Test equality by all fields."""
        if not isinstance(other, EpochProbeMap):
            return False
        return (
            self.name == other.name
            and self.reference == other.reference
            and self.type == other.type
            and self.devicestring == other.devicestring
            and self.subjectstring == other.subjectstring
        )

    def __hash__(self) -> int:
        """Hash by name, reference, type."""
        return hash((self.name, self.reference, self.type))


def parse_devicestring(devicestring: str) -> dict[str, str]:
    """
    Parse a device string into components.

    Device strings have format: "devicename:deviceclass:details"

    Args:
        devicestring: The device string to parse

    Returns:
        Dict with 'name', 'class', 'details' keys
    """
    parts = devicestring.split(":")
    return {
        "name": parts[0] if len(parts) > 0 else "",
        "class": parts[1] if len(parts) > 1 else "",
        "details": ":".join(parts[2:]) if len(parts) > 2 else "",
    }


def build_devicestring(
    name: str,
    deviceclass: str = "",
    details: str = "",
) -> str:
    """
    Build a device string from components.

    Args:
        name: Device name
        deviceclass: Device class
        details: Additional details

    Returns:
        Formatted device string
    """
    if details:
        return f"{name}:{deviceclass}:{details}"
    elif deviceclass:
        return f"{name}:{deviceclass}:"
    else:
        return name
