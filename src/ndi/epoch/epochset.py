"""
ndi.epoch.epochset - Abstract base class for epoch management.

This module provides the ndi_epoch_epochset abstract base class that defines
the interface for objects that manage epochs (recording periods).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Annotated, Any

import numpy as np
import pydantic
from pydantic import Field

from ..time import ndi_time_clocktype


class ndi_epoch_epochset(ABC):
    """
    Abstract base class for epoch management.

    ndi_epoch_epochset defines the interface for objects that manage epochs,
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
        >>> class MyEpochSet(ndi_epoch_epochset):
        ...     def buildepochtable(self):
        ...         return [{'epoch_number': 1, 'epoch_id': 'ep1', ...}]
        ...     def epochsetname(self):
        ...         return 'my_epochset'
        ...     def issyncgraphroot(self):
        ...         return True
    """

    def __init__(self):
        """Initialize epoch set with empty cache."""
        self._epochtable_cache: list[dict[str, Any]] | None = None
        self._epochtable_hash: str | None = None

    @abstractmethod
    def buildepochtable(self) -> list[dict[str, Any]]:
        """
        Build the epoch table for this epoch set.

        This method constructs the epoch table structure containing
        all epochs managed by this object.

        Returns:
            List of epoch entries, each with fields:
            - epoch_number: Integer position (1-indexed)
            - epoch_id: Unique identifier string
            - epoch_session_id: ndi_session containing this epoch
            - epochprobemap: List of ndi_epoch_epochprobemap objects
            - epoch_clock: List of ndi_time_clocktype objects
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
    ) -> tuple[list[dict[str, Any]], str]:
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

    def _compute_hash(self, epochtable: list[dict[str, Any]]) -> str:
        """Compute hash of epoch table for cache validation."""

        # Create a stable string representation.  Objects with to_dict()
        # (like ndi_epoch_epoch) already exclude circular back-references,
        # so we prefer that.  For anything else, fall back to repr()
        # rather than blindly walking __dict__, which can hit cycles
        # (e.g. epoch -> epochset_object -> epoch table -> epoch).
        def make_hashable(obj):
            if isinstance(obj, dict):
                return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
            elif isinstance(obj, (list, tuple)):
                return tuple(make_hashable(x) for x in obj)
            elif isinstance(obj, np.ndarray):
                return tuple(obj.flatten().tolist())
            elif hasattr(obj, "to_dict"):
                return make_hashable(obj.to_dict())
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

    @pydantic.validate_call
    def epochclock(self, epoch_number: Annotated[int, Field(ge=1)]) -> list[ndi_time_clocktype]:
        """
        Get clock types for an epoch.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)

        Returns:
            List of ndi_time_clocktype objects for this epoch

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number > len(et):
            raise IndexError(f"ndi_epoch_epoch {epoch_number} out of range (1..{len(et)})")

        entry = et[epoch_number - 1]
        return entry.get("epoch_clock", [])

    @pydantic.validate_call
    def t0_t1(self, epoch_number: Annotated[int, Field(ge=1)]) -> list[tuple[float, float]]:
        """
        Get time range for an epoch.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)

        Returns:
            List of (t0, t1) tuples, one per clock type

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number > len(et):
            raise IndexError(f"ndi_epoch_epoch {epoch_number} out of range (1..{len(et)})")

        entry = et[epoch_number - 1]
        return entry.get("t0_t1", [(np.nan, np.nan)])

    @pydantic.validate_call
    def epochid(self, epoch_number: Annotated[int, Field(ge=1)]) -> str:
        """
        Get epoch ID for an epoch number.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)

        Returns:
            ndi_epoch_epoch identifier string

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number > len(et):
            raise IndexError(f"ndi_epoch_epoch {epoch_number} out of range (1..{len(et)})")

        return et[epoch_number - 1].get("epoch_id", "")

    @pydantic.validate_call
    def epochnumber(self, epoch_id: str) -> int:
        """
        Get epoch number for an epoch ID.

        Args:
            epoch_id: ndi_epoch_epoch identifier string

        Returns:
            ndi_epoch_epoch number (1-indexed)

        Raises:
            ValueError: If epoch_id not found
        """
        et, _ = self.epochtable()
        for i, entry in enumerate(et):
            if entry.get("epoch_id") == epoch_id:
                return i + 1

        raise ValueError(f"ndi_epoch_epoch ID not found: {epoch_id}")

    def matchedepochtable(self, hashvalue: str) -> bool:
        """
        Check whether *hashvalue* matches the current cached epoch-table hash.

        MATLAB equivalent: ``ndi.epoch.epochset/matchedepochtable`` — returns True
        only if a cached epoch table exists and its hash equals *hashvalue*.
        (The previous Python method of this name was an entry-lookup filter with a
        different signature and no callers; audit §3.4-6 realigns it to the
        MATLAB boolean-hash semantics.)

        Args:
            hashvalue: A hash value previously obtained from ``epochtable()``.

        Returns:
            True if the cached epoch table's hash equals *hashvalue*.
        """
        if self._epochtable_cache is None:
            return False
        return hashvalue == self._epochtable_hash

    @pydantic.validate_call
    def epochtableentry(self, epoch_number: Annotated[int, Field(ge=1)]) -> dict[str, Any]:
        """
        Get a single epoch table entry.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)

        Returns:
            ndi_epoch_epoch table entry dict

        Raises:
            IndexError: If epoch_number is out of range
        """
        et, _ = self.epochtable()
        if epoch_number > len(et):
            raise IndexError(f"ndi_epoch_epoch {epoch_number} out of range (1..{len(et)})")

        return et[epoch_number - 1]

    def _epochgraph_nodes(self) -> list[dict[str, Any]]:
        """Enumerate one node per (epoch, clock) pair from the epoch table.

        Each node carries ``epoch_id``, ``epoch_session_id``, ``epoch_clock`` and
        ``t0_t1`` — the fields ``buildepochgraph`` needs to compute the cost and
        time-mapping matrices.
        """
        et, _ = self.epochtable()
        nodes: list[dict[str, Any]] = []
        for entry in et:
            clocks = entry.get("epoch_clock", []) or []
            t0t1_list = entry.get("t0_t1", []) or []
            for i, clock in enumerate(clocks):
                t = t0t1_list[i] if i < len(t0t1_list) else (np.nan, np.nan)
                nodes.append(
                    {
                        "epoch_id": entry.get("epoch_id", ""),
                        "epoch_session_id": entry.get("epoch_session_id", ""),
                        "epoch_clock": clock,
                        "t0_t1": tuple(t),
                    }
                )
        return nodes

    def buildepochgraph(self) -> tuple[np.ndarray, list[list[Any]]]:
        """Compute the cost and time-mapping matrices among this set's epochs.

        Port of MATLAB ``ndi.epoch.epochset/buildepochgraph`` (epochset.m:538-597).
        For M epoch nodes (one per epoch/clock pair) returns:

        - ``cost``: an MxM ``np.ndarray`` where ``cost[i, j]`` is the cost of
          converting node i -> j (1 for a direct mapping, ``inf`` if none).
        - ``mapping``: an MxM list-of-lists of ``ndi_time_timemapping`` / ``None``.

        Same epoch + same session across clocks rescales ``t0_t1``; otherwise the
        clock types' ``epochgraph_edge`` determines the link.
        """
        from ..time.timemapping import ndi_time_timemapping

        trivial = ndi_time_timemapping([1, 0])
        nodes = self._epochgraph_nodes()
        m = len(nodes)

        cost = np.full((m, m), np.inf)
        mapping: list[list[Any]] = [[None] * m for _ in range(m)]

        for i in range(m):
            for j in range(m):
                if i == j:
                    cost[i, j] = 1
                    mapping[i][j] = trivial
                elif (
                    nodes[i]["epoch_id"] == nodes[j]["epoch_id"]
                    and nodes[i]["epoch_session_id"] == nodes[j]["epoch_session_id"]
                ):
                    ti0, ti1 = nodes[i]["t0_t1"]
                    tj0, tj1 = nodes[j]["t0_t1"]
                    di = ti1 - ti0
                    scale = (tj1 - tj0) / di if di != 0 else 0.0
                    shift = tj0 - scale * ti0
                    cost[i, j] = 1
                    mapping[i][j] = ndi_time_timemapping([scale, shift])
                else:
                    c, mp = nodes[i]["epoch_clock"].epochgraph_edge(nodes[j]["epoch_clock"])
                    cost[i, j] = c
                    mapping[i][j] = mp
        return cost, mapping

    def epochgraph(self) -> tuple[np.ndarray, list[list[Any]]]:
        """Return the (cost, mapping) epoch graph for this epoch set.

        MATLAB equivalent: ``ndi.epoch.epochset/epochgraph`` — returns the
        ``(cost, mapping)`` matrices (see :meth:`buildepochgraph`). The previous
        Python implementation returned a list of node dicts, which did not match
        the MATLAB contract that ``ndi.time.syncgraph`` expects (audit §3.4-6).
        """
        return self.buildepochgraph()

    def resetepochtable(self) -> None:
        """Reset (clear) the epoch table cache.

        MATLAB equivalent: ndi.epoch.epochset.resetepochtable
        """
        self._epochtable_cache = None
        self._epochtable_hash = None
