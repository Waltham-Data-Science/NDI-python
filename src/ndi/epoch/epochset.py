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
from ..time.timemapping import ndi_time_timemapping


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
        self._epochgraph_cache: (
            tuple[np.ndarray, list[list[ndi_time_timemapping | None]]] | None
        ) = None
        self._epochgraph_cache_hash: str | None = None

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

    @pydantic.validate_call
    def matchedepochtable(self, hashvalue: str) -> bool:
        """Check whether the cached epoch table's hash matches ``hashvalue``.

        MATLAB equivalent: ``ndi.epoch.epochset.matchedepochtable`` — a
        cache-validity predicate used by ``cached_epochgraph`` to detect a
        stale epoch graph. Returns False when nothing has been cached yet.
        """
        if self._epochtable_cache is None:
            return False
        return self._epochtable_hash == hashvalue

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

    def epochnodes(self) -> list[dict[str, Any]]:
        """Return one epoch node per (epoch, clocktype) pair.

        MATLAB equivalent: ``ndi.epoch.epochset.epochnodes``. An epoch node
        carries the same fields as an epoch table entry (minus
        ``epoch_number``) but pinned to a single ``epoch_clock`` and its
        matching ``t0_t1`` pair, with ``objectname``/``objectclass``
        identifying the owning epoch set. Subclasses (``ndi.daq.system``,
        ``ndi.file.navigator``) may override with a specialised builder;
        this abstract-class version is what ``buildepochgraph`` consumes.
        """
        et, _ = self.epochtable()
        nodes: list[dict[str, Any]] = []
        objectname = self.epochsetname()
        objectclass = type(self).__name__

        for entry in et:
            clocks = entry.get("epoch_clock", [])
            t0t1_list = entry.get("t0_t1", [])
            for i, clock in enumerate(clocks):
                t0_t1 = t0t1_list[i] if i < len(t0t1_list) else (np.nan, np.nan)
                node = {k: v for k, v in entry.items() if k != "epoch_number"}
                node["epoch_clock"] = clock
                node["t0_t1"] = t0_t1
                node["objectname"] = objectname
                node["objectclass"] = objectclass
                nodes.append(node)

        return nodes

    def epochgraph(
        self,
    ) -> tuple[np.ndarray, list[list[ndi_time_timemapping | None]]]:
        """Return the (cost, mapping) graph over this object's epoch nodes.

        MATLAB equivalent: ``ndi.epoch.epochset.epochgraph``. ``cost`` is an
        MxM matrix (M = number of epoch nodes) where ``cost[i, j]`` is the
        cost of mapping from node i's (epoch, clocktype) to node j's, and
        ``mapping[i][j]`` is the ``ndi_time_timemapping`` that performs the
        conversion (or None where no edge exists). Result is cached and
        invalidated by ``resetepochtable`` or by a changed epoch-table hash.
        """
        _, current_hash = self.epochtable()
        if self._epochgraph_cache is not None and self._epochgraph_cache_hash == current_hash:
            return self._epochgraph_cache

        self._epochgraph_cache = self.buildepochgraph()
        self._epochgraph_cache_hash = current_hash
        return self._epochgraph_cache

    def buildepochgraph(
        self,
    ) -> tuple[np.ndarray, list[list[ndi_time_timemapping | None]]]:
        """Compute the epoch graph from scratch.

        MATLAB equivalent: ``ndi.epoch.epochset.buildepochgraph``. Links
        nodes sharing (epoch_id, epoch_session_id) with the linear rescaling
        implied by their ``t0_t1`` ranges, and delegates cross-clock edges
        to ``ndi_time_clocktype.epochgraph_edge``. Subclasses that know
        richer inter-epoch relationships (e.g. ``ndi.daq.system``) may
        override, typically by calling ``super().buildepochgraph()`` first
        and layering additional edges on the returned matrices.
        """
        nodes = self.epochnodes()
        n = len(nodes)
        cost = np.full((n, n), np.inf)
        mapping: list[list[ndi_time_timemapping | None]] = [[None] * n for _ in range(n)]

        trivial = ndi_time_timemapping([1.0, 0.0])

        for i in range(n):
            for j in range(n):
                if i == j:
                    cost[i, j] = 1.0
                    mapping[i][j] = trivial
                    continue

                ni, nj = nodes[i], nodes[j]
                same_epoch = ni.get("epoch_id") == nj.get("epoch_id") and ni.get(
                    "epoch_session_id"
                ) == nj.get("epoch_session_id")
                if same_epoch:
                    ti0, ti1 = ni["t0_t1"]
                    tj0, tj1 = nj["t0_t1"]
                    di = ti1 - ti0
                    if di == 0:
                        continue
                    m = (tj1 - tj0) / di
                    b = tj0 - m * ti0
                    cost[i, j] = 1.0
                    mapping[i][j] = ndi_time_timemapping([m, b])
                else:
                    c, mp = ni["epoch_clock"].epochgraph_edge(nj["epoch_clock"])
                    if not np.isinf(c):
                        cost[i, j] = c
                        mapping[i][j] = mp

        return cost, mapping

    def resetepochtable(self) -> None:
        """Reset (clear) the epoch table and epoch graph caches.

        MATLAB equivalent: ndi.epoch.epochset.resetepochtable
        """
        self._epochtable_cache = None
        self._epochtable_hash = None
        self._epochgraph_cache = None
        self._epochgraph_cache_hash = None
