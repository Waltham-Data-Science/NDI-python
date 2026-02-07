"""
ndi.cache - Cache class for NDI.

This module provides the Cache class for session-level caching
of computed results with memory limits and eviction policies.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import sys


@dataclass
class CacheEntry:
    """A single entry in the cache table."""
    key: str
    type: str
    timestamp: datetime
    priority: float
    bytes: int
    data: Any


class Cache:
    """
    Cache class for NDI session caching.

    Provides key-type based caching with memory limits and
    configurable eviction policies (FIFO, LIFO, or error).

    Attributes:
        max_memory: Maximum memory in bytes before eviction
        replacement_rule: Eviction policy ('fifo', 'lifo', 'error')

    Example:
        >>> cache = Cache(max_memory=1e9)
        >>> cache.add('element_123', 'epochtable', my_data)
        >>> entry = cache.lookup('element_123', 'epochtable')
        >>> if entry:
        ...     data = entry.data
    """

    VALID_RULES = ('fifo', 'lifo', 'error')

    def __init__(
        self,
        max_memory: float = 10e9,
        replacement_rule: str = 'fifo',
    ):
        """
        Create a new Cache.

        Args:
            max_memory: Maximum memory in bytes (default 10GB)
            replacement_rule: Eviction policy - 'fifo', 'lifo', or 'error'
        """
        self._max_memory = max_memory
        self._table: List[CacheEntry] = []
        self.set_replacement_rule(replacement_rule)

    @property
    def max_memory(self) -> float:
        """Get maximum memory limit."""
        return self._max_memory

    @property
    def replacement_rule(self) -> str:
        """Get current replacement rule."""
        return self._replacement_rule

    def set_replacement_rule(self, rule: str) -> 'Cache':
        """
        Set the replacement rule for cache eviction.

        Args:
            rule: One of 'fifo', 'lifo', or 'error'

        Returns:
            self for chaining

        Raises:
            ValueError: If rule is not valid
        """
        rule_lower = rule.lower()
        if rule_lower not in self.VALID_RULES:
            raise ValueError(
                f"Unknown replacement rule: {rule}. "
                f"Must be one of {self.VALID_RULES}"
            )
        self._replacement_rule = rule_lower
        return self

    def add(
        self,
        key: str,
        type: str,
        data: Any,
        priority: float = 0,
    ) -> 'Cache':
        """
        Add data to the cache.

        Args:
            key: Unique key for the data
            type: Type category for the data
            data: The data to cache
            priority: Higher priority items are evicted last

        Returns:
            self for chaining

        Raises:
            MemoryError: If data is larger than max_memory
            MemoryError: If cache is full and rule is 'error'
        """
        # Estimate size of data
        data_bytes = self._estimate_size(data)

        if data_bytes > self._max_memory:
            raise MemoryError(
                f"Data ({data_bytes} bytes) exceeds cache max_memory "
                f"({self._max_memory} bytes)"
            )

        # Create new entry
        new_entry = CacheEntry(
            key=key,
            type=type,
            timestamp=datetime.now(),
            priority=priority,
            bytes=data_bytes,
            data=data,
        )

        # Check if we need to evict
        total_memory = self.bytes() + data_bytes
        if total_memory > self._max_memory:
            if self._replacement_rule == 'error':
                raise MemoryError(
                    "Cache is full and replacement_rule is 'error'"
                )

            free_needed = total_memory - self._max_memory
            indices_to_remove, safe_to_add = self._evaluate_items_for_removal(
                free_needed, new_entry
            )

            if safe_to_add:
                self._remove_indices(indices_to_remove)
                self._table.append(new_entry)
        else:
            self._table.append(new_entry)

        return self

    def remove(
        self,
        key_or_index: Any,
        type: Optional[str] = None,
    ) -> 'Cache':
        """
        Remove data from the cache.

        Args:
            key_or_index: Either a string key (requires type) or int/list indices
            type: Required when key_or_index is a string key

        Returns:
            self for chaining
        """
        if isinstance(key_or_index, int):
            self._remove_indices([key_or_index])
        elif isinstance(key_or_index, (list, tuple)):
            self._remove_indices(list(key_or_index))
        else:
            # It's a key string
            if type is None:
                raise ValueError("type must be provided when removing by key")

            indices = [
                i for i, entry in enumerate(self._table)
                if entry.key == key_or_index and entry.type == type
            ]
            self._remove_indices(indices)

        return self

    def _remove_indices(self, indices: List[int]) -> None:
        """Remove entries at specified indices."""
        if not indices:
            return
        # Sort in reverse to remove from end first
        for i in sorted(indices, reverse=True):
            if 0 <= i < len(self._table):
                del self._table[i]

    def clear(self) -> 'Cache':
        """
        Clear all entries from the cache.

        Returns:
            self for chaining
        """
        self._table.clear()
        return self

    def lookup(self, key: str, type: str) -> Optional[CacheEntry]:
        """
        Look up a cache entry by key and type.

        Args:
            key: The key to look up
            type: The type to match

        Returns:
            CacheEntry if found, None otherwise
        """
        for entry in self._table:
            if entry.key == key and entry.type == type:
                return entry
        return None

    def bytes(self) -> int:
        """
        Get total memory used by cache entries.

        Returns:
            Total bytes used
        """
        return sum(entry.bytes for entry in self._table)

    def _estimate_size(self, data: Any) -> int:
        """Estimate the memory size of data in bytes."""
        try:
            return sys.getsizeof(data)
        except TypeError:
            # Fallback for objects that don't support getsizeof
            return 1000  # Default estimate

    def _evaluate_items_for_removal(
        self,
        free_bytes: int,
        new_item: Optional[CacheEntry] = None,
    ) -> Tuple[List[int], bool]:
        """
        Evaluate which items to remove to free memory.

        Items are removed by priority (lowest first), then by
        timestamp according to replacement_rule.

        Args:
            free_bytes: Bytes needed to free
            new_item: Optional new item being added

        Returns:
            Tuple of (indices to remove, is new item safe to add)
        """
        # Create combined list for evaluation
        if new_item:
            entries = self._table + [new_item]
        else:
            entries = self._table

        # Build sortable tuples: (priority, timestamp, index, bytes)
        # Lower priority evicted first, then by timestamp based on rule
        stats = [
            (
                entry.priority,
                entry.timestamp.timestamp(),
                i,
                entry.bytes,
            )
            for i, entry in enumerate(entries)
        ]

        # Sort by priority (ascending), then timestamp
        # FIFO: oldest first (ascending timestamp)
        # LIFO: newest first (descending timestamp)
        if self._replacement_rule == 'lifo':
            stats.sort(key=lambda x: (x[0], -x[1], -x[2]))
        else:  # fifo
            stats.sort(key=lambda x: (x[0], x[1], x[2]))

        # Find minimum items to remove
        cumulative = 0
        indices_to_remove = []
        for priority, ts, idx, size in stats:
            indices_to_remove.append(idx)
            cumulative += size
            if cumulative >= free_bytes:
                break

        # Check if new item would be removed
        new_item_idx = len(self._table) if new_item else -1
        is_safe = new_item_idx not in indices_to_remove

        # Only return indices that are in the actual table
        valid_indices = [i for i in indices_to_remove if i < len(self._table)]

        return valid_indices, is_safe

    def __len__(self) -> int:
        """Return number of entries in cache."""
        return len(self._table)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Cache(entries={len(self._table)}, "
            f"bytes={self.bytes()}, "
            f"max_memory={self._max_memory})"
        )
