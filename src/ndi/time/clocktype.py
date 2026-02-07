"""
ndi.time.clocktype - Clock type enumeration for NDI framework.

This module provides the ClockType class for specifying clock types
used in time synchronization across epochs and devices.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .timemapping import TimeMapping


class ClockType(Enum):
    """
    Clock type enumeration for specifying timing precision and scope.

    Clock types define how time is kept and its precision:

    - UTC: Universal coordinated time (within 0.1ms)
    - APPROX_UTC: Universal coordinated time (within 5 seconds)
    - EXP_GLOBAL_TIME: Experiment global time (within 0.1ms)
    - APPROX_EXP_GLOBAL_TIME: Experiment global time (within 5s)
    - DEV_GLOBAL_TIME: Device keeps its own global time (within 0.1ms)
    - APPROX_DEV_GLOBAL_TIME: Device keeps its own global time (within 5s)
    - DEV_LOCAL_TIME: Device keeps local time only within epochs
    - NO_TIME: No timing information
    - INHERITED: Timing inherited from another device
    """

    UTC = 'utc'
    APPROX_UTC = 'approx_utc'
    EXP_GLOBAL_TIME = 'exp_global_time'
    APPROX_EXP_GLOBAL_TIME = 'approx_exp_global_time'
    DEV_GLOBAL_TIME = 'dev_global_time'
    APPROX_DEV_GLOBAL_TIME = 'approx_dev_global_time'
    DEV_LOCAL_TIME = 'dev_local_time'
    NO_TIME = 'no_time'
    INHERITED = 'inherited'

    @classmethod
    def from_string(cls, type_str: str) -> 'ClockType':
        """
        Create a ClockType from a string.

        Args:
            type_str: Clock type string (case-insensitive)

        Returns:
            ClockType enum value

        Raises:
            ValueError: If the type string is not recognized
        """
        type_lower = type_str.lower()
        for ct in cls:
            if ct.value == type_lower:
                return ct
        raise ValueError(f"Unknown clock type: {type_str}")

    def __str__(self) -> str:
        """Return the clock type as a string."""
        return self.value

    def needs_epoch(self) -> bool:
        """
        Check if this clock type needs an epoch for full description.

        Returns:
            True if clock type is DEV_LOCAL_TIME, False otherwise
        """
        return self == ClockType.DEV_LOCAL_TIME

    def is_global(self) -> bool:
        """
        Check if this is a global clock type.

        Global clock types maintain time across epochs.

        Returns:
            True if this is a global clock type
        """
        global_types = {
            ClockType.UTC,
            ClockType.APPROX_UTC,
            ClockType.EXP_GLOBAL_TIME,
            ClockType.APPROX_EXP_GLOBAL_TIME,
            ClockType.DEV_GLOBAL_TIME,
            ClockType.APPROX_DEV_GLOBAL_TIME,
        }
        return self in global_types

    @staticmethod
    def assert_global(clocktype: 'ClockType') -> None:
        """
        Assert that a clock type is global, raising an error if not.

        Args:
            clocktype: Clock type to check

        Raises:
            AssertionError: If clock type is not global
        """
        if not clocktype.is_global():
            valid_types = ', '.join([
                ClockType.UTC.value,
                ClockType.APPROX_UTC.value,
                ClockType.EXP_GLOBAL_TIME.value,
                ClockType.APPROX_EXP_GLOBAL_TIME.value,
                ClockType.DEV_GLOBAL_TIME.value,
                ClockType.APPROX_DEV_GLOBAL_TIME.value,
            ])
            raise AssertionError(
                f"Clock type must be one of: {valid_types}. Got: {clocktype.value}"
            )

    def epochgraph_edge(self, other: 'ClockType') -> Tuple[float, Optional['TimeMapping']]:
        """
        Provide epochgraph edge based purely on clock type.

        Determines if there's an automatic mapping between epochs with these
        clock types. The following types are linked with cost 100 and identity mapping:

        - utc -> utc
        - utc -> approx_utc
        - exp_global_time -> exp_global_time
        - exp_global_time -> approx_exp_global_time
        - dev_global_time -> dev_global_time
        - dev_global_time -> approx_dev_global_time

        Args:
            other: The destination clock type

        Returns:
            Tuple of (cost, mapping) where cost is float and mapping is
            a TimeMapping object or None if no mapping exists.
        """
        from .timemapping import TimeMapping

        # No mapping possible with no_time
        if self == ClockType.NO_TIME or other == ClockType.NO_TIME:
            return float('inf'), None

        # Define valid transitions
        valid_transitions = [
            (ClockType.UTC, ClockType.UTC),
            (ClockType.UTC, ClockType.APPROX_UTC),
            (ClockType.EXP_GLOBAL_TIME, ClockType.EXP_GLOBAL_TIME),
            (ClockType.EXP_GLOBAL_TIME, ClockType.APPROX_EXP_GLOBAL_TIME),
            (ClockType.DEV_GLOBAL_TIME, ClockType.DEV_GLOBAL_TIME),
            (ClockType.DEV_GLOBAL_TIME, ClockType.APPROX_DEV_GLOBAL_TIME),
        ]

        if (self, other) in valid_transitions:
            return 100.0, TimeMapping.identity()

        return float('inf'), None


# Convenience aliases for common clock types
UTC = ClockType.UTC
APPROX_UTC = ClockType.APPROX_UTC
EXP_GLOBAL_TIME = ClockType.EXP_GLOBAL_TIME
APPROX_EXP_GLOBAL_TIME = ClockType.APPROX_EXP_GLOBAL_TIME
DEV_GLOBAL_TIME = ClockType.DEV_GLOBAL_TIME
APPROX_DEV_GLOBAL_TIME = ClockType.APPROX_DEV_GLOBAL_TIME
DEV_LOCAL_TIME = ClockType.DEV_LOCAL_TIME
NO_TIME = ClockType.NO_TIME
INHERITED = ClockType.INHERITED
