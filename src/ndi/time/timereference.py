"""
ndi.time.timereference - Time reference class for NDI framework.

This module provides the TimeReference class for specifying time
relative to an NDI clock type within a specific epoch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .clocktype import ClockType

if TYPE_CHECKING:
    pass  # Future imports for type checking


@dataclass
class TimeReferenceStruct:
    """
    Structure representation of a TimeReference without live objects.

    Used for serialization and database storage.
    """

    referent_epochsetname: str
    referent_classname: str
    clocktypestring: str
    epoch: str | None
    session_id: str
    time: float | None


class TimeReference:
    """
    A class for specifying time relative to an NDI clock.

    TimeReference describes a specific time point in the context of:
    - A referent (the object keeping time, e.g., DAQ system, element)
    - A clock type (utc, exp_global_time, dev_local_time, etc.)
    - An epoch (required for dev_local_time)
    - A time value

    Example:
        >>> # Create a time reference for UTC time
        >>> tr = TimeReference(
        ...     referent=my_daq_system,
        ...     clocktype=ClockType.UTC,
        ...     epoch=None,
        ...     time=1234567890.0
        ... )

        >>> # Create a local time reference (requires epoch)
        >>> tr = TimeReference(
        ...     referent=my_daq_system,
        ...     clocktype=ClockType.DEV_LOCAL_TIME,
        ...     epoch="epoch_001",
        ...     time=0.5
        ... )
    """

    def __init__(
        self,
        referent: Any,
        clocktype: ClockType | str,
        epoch: str | None = None,
        time: float | None = None,
        session_id: str | None = None,
    ):
        """
        Create a new time reference object.

        Args:
            referent: The object that serves as the time reference source.
                     Must have a 'session' property with a valid id.
            clocktype: The clock type (ClockType enum or string)
            epoch: The epoch identifier (required if clocktype is DEV_LOCAL_TIME)
            time: The time value at the reference point
            session_id: Optional session ID (extracted from referent if not provided)

        Raises:
            TypeError: If clocktype is not a ClockType
            ValueError: If epoch is required but not provided
        """
        # Handle clocktype as string or enum
        if isinstance(clocktype, str):
            clocktype = ClockType.from_string(clocktype)

        if not isinstance(clocktype, ClockType):
            raise TypeError("clocktype must be a ClockType instance or valid string")

        # Validate epoch requirement
        if clocktype.needs_epoch() and epoch is None:
            raise ValueError(f"Clock type '{clocktype.value}' requires an epoch to be specified")

        # Extract session_id from referent if not provided
        if session_id is None:
            session_id = self._extract_session_id(referent)

        self._referent = referent
        self._clocktype = clocktype
        self._epoch = epoch
        self._time = time
        self._session_id = session_id

    @staticmethod
    def _extract_session_id(referent: Any) -> str:
        """
        Extract session ID from a referent object.

        Args:
            referent: Object with session property

        Returns:
            Session ID string

        Raises:
            ValueError: If session ID cannot be extracted
        """
        # Handle different types of referent objects
        if hasattr(referent, "session"):
            session = referent.session
            if hasattr(session, "id"):
                if callable(session.id):
                    return session.id()
                return session.id
            raise ValueError("Referent's session does not have a valid id")
        elif hasattr(referent, "session_id"):
            return referent.session_id
        elif isinstance(referent, dict) and "session_id" in referent:
            return referent["session_id"]
        else:
            raise ValueError("Referent must have a session property with a valid id")

    @property
    def referent(self) -> Any:
        """Get the referent object."""
        return self._referent

    @property
    def clocktype(self) -> ClockType:
        """Get the clock type."""
        return self._clocktype

    @property
    def epoch(self) -> str | None:
        """Get the epoch identifier."""
        return self._epoch

    @property
    def time(self) -> float | None:
        """Get the time value."""
        return self._time

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._session_id

    def to_struct(self) -> TimeReferenceStruct:
        """
        Convert to a structure that lacks live Matlab/Python objects.

        Useful for serialization and database storage.

        Returns:
            TimeReferenceStruct with string-based representation
        """
        # Get epochsetname
        if hasattr(self._referent, "epochsetname"):
            if callable(self._referent.epochsetname):
                epochsetname = self._referent.epochsetname()
            else:
                epochsetname = self._referent.epochsetname
        elif hasattr(self._referent, "name"):
            epochsetname = self._referent.name
        else:
            epochsetname = str(self._referent)

        # Get class name
        referent_classname = type(self._referent).__name__

        return TimeReferenceStruct(
            referent_epochsetname=epochsetname,
            referent_classname=referent_classname,
            clocktypestring=self._clocktype.value,
            epoch=self._epoch,
            session_id=self._session_id,
            time=self._time,
        )

    @classmethod
    def from_struct(
        cls,
        session: Any,
        struct: TimeReferenceStruct,
    ) -> TimeReference:
        """
        Create a TimeReference from a struct and session.

        Args:
            session: The session object to search for the referent
            struct: TimeReferenceStruct with serialized data

        Returns:
            TimeReference with live referent object

        Raises:
            ValueError: If referent cannot be found in session
        """
        # Find the referent in the session
        if hasattr(session, "findexpobj"):
            referent = session.findexpobj(struct.referent_epochsetname, struct.referent_classname)
        else:
            raise ValueError("Session does not support finding experiment objects")

        clocktype = ClockType.from_string(struct.clocktypestring)

        return cls(
            referent=referent,
            clocktype=clocktype,
            epoch=struct.epoch,
            time=struct.time,
            session_id=struct.session_id,
        )

    def to_dict(self) -> dict:
        """
        Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation
        """
        struct = self.to_struct()
        return {
            "referent_epochsetname": struct.referent_epochsetname,
            "referent_classname": struct.referent_classname,
            "clocktypestring": struct.clocktypestring,
            "epoch": struct.epoch,
            "session_id": struct.session_id,
            "time": struct.time,
        }

    def __eq__(self, other: object) -> bool:
        """Check equality of time references."""
        if not isinstance(other, TimeReference):
            return NotImplemented

        return (
            self._session_id == other._session_id
            and self._clocktype == other._clocktype
            and self._epoch == other._epoch
            and self._time == other._time
            # Note: referent comparison is intentionally omitted as it may be complex
        )

    def __repr__(self) -> str:
        """Return string representation."""
        parts = [
            f"clocktype={self._clocktype.value}",
            f"epoch={self._epoch!r}",
            f"time={self._time}",
        ]
        return f"TimeReference({', '.join(parts)})"
