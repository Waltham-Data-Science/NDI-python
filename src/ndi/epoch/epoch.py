"""
ndi.epoch.epoch - Immutable epoch data class.

This module provides the Epoch class that represents a single
recording epoch with all its metadata.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .epochprobemap import EpochProbeMap
    from .epochset import EpochSet
    from ..time import ClockType


@dataclass(frozen=True)
class Epoch:
    """
    Immutable data class representing a single epoch.

    An epoch represents a contiguous recording period with associated
    metadata including timing, probe mappings, and relationships to
    underlying epochs.

    This class is immutable (frozen=True) - properties cannot be
    changed after construction.

    Attributes:
        epoch_number: Position in epoch table (0 = unknown)
        epoch_id: Unique identifier string (never changes)
        epoch_session_id: ID of session containing this epoch
        epochprobemap: List of probe-device mappings
        epoch_clock: List of clock types for this epoch
        t0_t1: List of (t0, t1) time ranges per clock
        epochset_object: Reference to containing EpochSet
        underlying_epochs: List of underlying epoch references
        underlying_files: List of associated file paths

    Example:
        >>> from ndi.epoch import Epoch, EpochProbeMap
        >>> from ndi.time import DEV_LOCAL_TIME
        >>>
        >>> epoch = Epoch(
        ...     epoch_number=1,
        ...     epoch_id='ep_abc123',
        ...     epoch_session_id='sess_xyz',
        ...     epochprobemap=[EpochProbeMap('elec1', 1, 'n-trode', 'intan1::', '')],
        ...     epoch_clock=[DEV_LOCAL_TIME],
        ...     t0_t1=[(0.0, 100.0)],
        ... )
    """

    epoch_number: int = 0
    epoch_id: str = ''
    epoch_session_id: str = ''
    epochprobemap: Tuple['EpochProbeMap', ...] = field(default_factory=tuple)
    epoch_clock: Tuple['ClockType', ...] = field(default_factory=tuple)
    t0_t1: Tuple[Tuple[float, float], ...] = field(default_factory=tuple)
    epochset_object: Optional['EpochSet'] = None
    underlying_epochs: Tuple['Epoch', ...] = field(default_factory=tuple)
    underlying_files: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        """Convert lists to tuples for immutability."""
        # Note: frozen=True prevents direct assignment, so we use object.__setattr__
        if isinstance(self.epochprobemap, list):
            object.__setattr__(self, 'epochprobemap', tuple(self.epochprobemap))
        if isinstance(self.epoch_clock, list):
            object.__setattr__(self, 'epoch_clock', tuple(self.epoch_clock))
        if isinstance(self.t0_t1, list):
            object.__setattr__(self, 't0_t1', tuple(tuple(x) if isinstance(x, list) else x for x in self.t0_t1))
        if isinstance(self.underlying_epochs, list):
            object.__setattr__(self, 'underlying_epochs', tuple(self.underlying_epochs))
        if isinstance(self.underlying_files, list):
            object.__setattr__(self, 'underlying_files', tuple(self.underlying_files))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Epoch':
        """
        Create an Epoch from a dictionary.

        Args:
            data: Dictionary with epoch fields

        Returns:
            New Epoch instance
        """
        from .epochprobemap import EpochProbeMap
        from ..time import ClockType

        # Parse epochprobemap
        epm_raw = data.get('epochprobemap', [])
        epochprobemap = []
        for epm in epm_raw:
            if isinstance(epm, EpochProbeMap):
                epochprobemap.append(epm)
            elif isinstance(epm, dict):
                epochprobemap.append(EpochProbeMap.from_dict(epm))

        # Parse epoch_clock
        clock_raw = data.get('epoch_clock', [])
        epoch_clock = []
        for clock in clock_raw:
            if isinstance(clock, ClockType):
                epoch_clock.append(clock)
            elif isinstance(clock, str):
                epoch_clock.append(ClockType(clock))

        # Parse t0_t1
        t0t1_raw = data.get('t0_t1', [])
        t0_t1 = []
        for t in t0t1_raw:
            if isinstance(t, (list, tuple)) and len(t) >= 2:
                t0_t1.append((float(t[0]), float(t[1])))

        # Parse underlying_epochs recursively
        underlying_raw = data.get('underlying_epochs', [])
        underlying_epochs = []
        for ue in underlying_raw:
            if isinstance(ue, Epoch):
                underlying_epochs.append(ue)
            elif isinstance(ue, dict):
                underlying_epochs.append(cls.from_dict(ue))

        return cls(
            epoch_number=data.get('epoch_number', 0),
            epoch_id=data.get('epoch_id', ''),
            epoch_session_id=data.get('epoch_session_id', ''),
            epochprobemap=tuple(epochprobemap),
            epoch_clock=tuple(epoch_clock),
            t0_t1=tuple(t0_t1),
            epochset_object=data.get('epochset_object'),
            underlying_epochs=tuple(underlying_epochs),
            underlying_files=tuple(data.get('underlying_files', [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.

        Note: epochset_object is not serialized (would create circular ref).

        Returns:
            Dictionary with epoch fields
        """
        return {
            'epoch_number': self.epoch_number,
            'epoch_id': self.epoch_id,
            'epoch_session_id': self.epoch_session_id,
            'epochprobemap': [epm.to_dict() for epm in self.epochprobemap],
            'epoch_clock': [str(c) for c in self.epoch_clock],
            't0_t1': list(self.t0_t1),
            'underlying_epochs': [ue.to_dict() for ue in self.underlying_epochs],
            'underlying_files': list(self.underlying_files),
        }

    def has_clock(self, clock: 'ClockType') -> bool:
        """
        Check if this epoch has a specific clock type.

        Args:
            clock: ClockType to check for

        Returns:
            True if the clock type is present
        """
        return clock in self.epoch_clock

    def time_range(self, clock: 'ClockType') -> Optional[Tuple[float, float]]:
        """
        Get time range for a specific clock type.

        Args:
            clock: ClockType to get range for

        Returns:
            (t0, t1) tuple or None if clock not present
        """
        for i, c in enumerate(self.epoch_clock):
            if c == clock:
                if i < len(self.t0_t1):
                    return self.t0_t1[i]
        return None

    def matches_probe(
        self,
        name: str,
        reference: int,
        type: str,
    ) -> bool:
        """
        Check if any epochprobemap matches the probe criteria.

        Args:
            name: Probe name
            reference: Reference number
            type: Probe type

        Returns:
            True if any epochprobemap matches
        """
        for epm in self.epochprobemap:
            if epm.matches(name, reference, type):
                return True
        return False


def is_epoch_or_empty(value: Any) -> bool:
    """
    Validate that a value is an Epoch or empty.

    Args:
        value: Value to check

    Returns:
        True if value is Epoch, None, or empty
    """
    if value is None:
        return True
    if isinstance(value, Epoch):
        return True
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return True
    if isinstance(value, (list, tuple)) and all(isinstance(x, Epoch) for x in value):
        return True
    return False
