"""
ndi.epoch.epochset - Abstract base class for epoch management.

This module provides the EpochSet abstract base class that defines
the interface for objects that manage epochs (recording periods).
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import hashlib
import json

import numpy as np

if TYPE_CHECKING:
    from ..time import ClockType, TimeReference


class EpochSet(ABC):
    """
    Abstract base class for epoch management.

    EpochSet defines the interface for objects that manage epochs,
    providing methods for accessing epoch tables, clock types, and
    time ranges.

    Subclasses must implement:
        - buildepochtable(): Construct the epoch table
        - epochsetname(): Return the name of this epoch set
        - issyncgraphroot(): Control graph traversal behavior

    The epoch table is cached with a hash value to avoid recomputation.

    Attributes:
        _epochtable_cache: Cached epoch table
        _epochtable_hash: Hash of cached epoch table

    Example:
        >>> class MyEpochSet(EpochSet):
        ...     def buildepochtable(self):
        ...         return [{'epoch_number': 1, 'epoch_id': 'ep1', ...}]
        ...     def epochsetname(self):
        ...         return 'my_epochset'
        ...     def issyncgraphroot(self):
        ...         return True
    """

    def __init__(self):
        """Initialize epoch set with empty cache."""
        self._epochtable_cache: Optional[List[Dict[str, Any]]] = None
        self._epochtable_hash: Optional[str] = None

    @abstractmethod
    def buildepochtable(self) -> List[Dict[str, Any]]:
        """
        Build the epoch table for this epoch set.

        This method constructs the epoch table structure containing
        all epochs managed by this object.

        Returns:
            List of epoch entries, each with fields:
            - epoch_number: Integer position (1-indexed)
            - epoch_id: Unique identifier string
            - epoch_session_id: Session containing this epoch
            - epochprobemap: List of EpochProbeMap objects
            - epoch_clock: List of ClockType objects
            - t0_t1: List of (t0, t1) tuples per clock
            - underlying_epochs: Dict with underlying epoch info
        """
        pass

    @abstractmethod
    def epochsetname(self) -> str:
        """
        Return the name of this epoch set.

        Returns:
            Human-readable name for this epoch set
        """
        pass

    @abstractmethod
    def issyncgraphroot(self) -> bool:
        """
        Check if this epoch set is a sync graph root.

        Root epoch sets terminate graph traversal. Non-root epoch
        sets (like probes) continue traversal to underlying elements.

        Returns:
            True if this is a root (stop traversal),
            False to continue traversal
        """
        pass

    def epochtable(
        self,
        force_rebuild: bool = False,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Get the epoch table with caching.

        Returns the cached epoch table if valid, otherwise rebuilds
        it using buildepochtable().

        Args:
            force_rebuild: If True, ignore cache and rebuild

        Returns:
            Tuple of (epoch_table, hash_value)
        """
        if force_rebuild or self._epochtable_cache is None:
            self._epochtable_cache = self.buildepochtable()
            self._epochtable_hash = self._compute_hash(self._epochtable_cache)

        return self._epochtable_cache, self._epochtable_hash

    def _compute_hash(self, epochtable: List[Dict[str, Any]]) -> str:
        """Compute hash of epoch table for cache validation."""
        # Create a stable string representation
        def make_hashable(obj):
            if isinstance(obj, dict):
                return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
            elif isinstance(obj, list):
                return tuple(make_hashable(x) for x in obj)
            elif isinstance(obj, np.ndarray):
                return tuple(obj.flatten().tolist())
            elif hasattr(obj, 'to_dict'):
                return make_hashable(obj.to_dict())
            elif hasattr(obj, '__dict__'):
                return make_hashable(obj.__dict__)
            else:
                return obj

        hashable = make_hashable(epochtable)
        hash_str = hashlib.md5(str(hashable).encode()).hexdigest()
        return hash_str

    def numepochs(self) -> int:
        """
        Return the number of epochs.

        Returns:
            Number of epochs in the epoch table
        """
        et, _ = self.epochtable()
        return len(et)

    def epochclock(self, epoch_number: int) -> List['ClockType']:
        """
        Get clock types for an epoch.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            List of ClockType objects for this epoch

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number < 1 or epoch_number > len(et):
            raise IndexError(f"Epoch {epoch_number} out of range (1..{len(et)})")

        entry = et[epoch_number - 1]
        return entry.get('epoch_clock', [])

    def t0_t1(self, epoch_number: int) -> List[Tuple[float, float]]:
        """
        Get time range for an epoch.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            List of (t0, t1) tuples, one per clock type

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number < 1 or epoch_number > len(et):
            raise IndexError(f"Epoch {epoch_number} out of range (1..{len(et)})")

        entry = et[epoch_number - 1]
        return entry.get('t0_t1', [(np.nan, np.nan)])

    def epochid(self, epoch_number: int) -> str:
        """
        Get epoch ID for an epoch number.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            Epoch identifier string

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number < 1 or epoch_number > len(et):
            raise IndexError(f"Epoch {epoch_number} out of range (1..{len(et)})")

        return et[epoch_number - 1].get('epoch_id', '')

    def epochnumber(self, epoch_id: str) -> int:
        """
        Get epoch number for an epoch ID.

        Args:
            epoch_id: Epoch identifier string

        Returns:
            Epoch number (1-indexed)

        Raises:
            ValueError: If epoch_id not found
        """
        et, _ = self.epochtable()
        for i, entry in enumerate(et):
            if entry.get('epoch_id') == epoch_id:
                return i + 1

        raise ValueError(f"Epoch ID not found: {epoch_id}")

    def matchedepochtable(
        self,
        epoch_number: Optional[int] = None,
        epoch_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get epoch table entries matching criteria.

        Args:
            epoch_number: Match by epoch number (None = any)
            epoch_id: Match by epoch ID (None = any)

        Returns:
            List of matching epoch table entries
        """
        et, _ = self.epochtable()
        matches = []

        for entry in et:
            if epoch_number is not None and entry.get('epoch_number') != epoch_number:
                continue
            if epoch_id is not None and entry.get('epoch_id') != epoch_id:
                continue
            matches.append(entry)

        return matches

    def epochtableentry(self, epoch_number: int) -> Dict[str, Any]:
        """
        Get a single epoch table entry.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            Epoch table entry dict

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number < 1 or epoch_number > len(et):
            raise IndexError(f"Epoch {epoch_number} out of range (1..{len(et)})")

        return et[epoch_number - 1]

    def epochgraph(self) -> List[Dict[str, Any]]:
        """
        Build epoch graph nodes for time synchronization.

        Creates a list of graph nodes, one for each (epoch, clock) pair.
        This is used by SyncGraph for time conversion.

        Returns:
            List of epoch graph nodes with fields:
            - epoch_id: Epoch identifier
            - epochset: Reference to this EpochSet
            - clock: ClockType for this node
            - t0: Start time
            - t1: End time
        """
        et, _ = self.epochtable()
        nodes = []

        for entry in et:
            epoch_id = entry.get('epoch_id', '')
            clocks = entry.get('epoch_clock', [])
            t0t1_list = entry.get('t0_t1', [])

            # Create one node per clock type
            for i, clock in enumerate(clocks):
                t0, t1 = t0t1_list[i] if i < len(t0t1_list) else (np.nan, np.nan)
                nodes.append({
                    'epoch_id': epoch_id,
                    'epochset': self,
                    'clock': clock,
                    't0': t0,
                    't1': t1,
                })

        return nodes

    def clear_cache(self) -> None:
        """Clear the epoch table cache."""
        self._epochtable_cache = None
        self._epochtable_hash = None
