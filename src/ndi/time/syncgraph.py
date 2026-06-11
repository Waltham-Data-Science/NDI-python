"""
ndi.time.syncgraph - Synchronization graph for time conversion.

This module provides the ndi_time_syncgraph class that manages time synchronization
across epochs and devices using a graph-based approach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

try:
    import networkx as nx

    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

from ..ido import ndi_ido
from ..util.classname import ndi_matlab_classname
from .clocktype import ndi_time_clocktype
from .syncrule_base import ndi_time_syncrule
from .timemapping import ndi_time_timemapping

if TYPE_CHECKING:
    from ..document import ndi_document
    from .timereference import ndi_time_timereference


@dataclass
class ndi_time_epochnode:
    """
    Represents a node in the epoch graph.

    An epoch node represents a specific epoch with its timing information.
    """

    epoch_id: str
    epoch_session_id: str
    epochprobemap: Any  # The probe map for this epoch
    epoch_clock: ndi_time_clocktype
    t0_t1: tuple[float, float]  # Start and end times
    underlying_epochs: dict[str, Any] | None = None
    objectname: str = ""
    objectclass: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "epoch_id": self.epoch_id,
            "epoch_session_id": self.epoch_session_id,
            "epochprobemap": self.epochprobemap,
            "epoch_clock": (
                self.epoch_clock.value
                if isinstance(self.epoch_clock, ndi_time_clocktype)
                else str(self.epoch_clock)
            ),
            "t0_t1": list(self.t0_t1) if self.t0_t1 else None,
            "underlying_epochs": self.underlying_epochs,
            "objectname": self.objectname,
            "objectclass": self.objectclass,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ndi_time_epochnode:
        """Create from dictionary."""
        epoch_clock = data.get("epoch_clock")
        if isinstance(epoch_clock, str):
            epoch_clock = ndi_time_clocktype.from_string(epoch_clock)

        t0_t1 = data.get("t0_t1")
        if isinstance(t0_t1, list):
            t0_t1 = tuple(t0_t1)

        return cls(
            epoch_id=data["epoch_id"],
            epoch_session_id=data["epoch_session_id"],
            epochprobemap=data.get("epochprobemap"),
            epoch_clock=epoch_clock,
            t0_t1=t0_t1,
            underlying_epochs=data.get("underlying_epochs"),
            objectname=data.get("objectname", ""),
            objectclass=data.get("objectclass", ""),
        )


@dataclass
class ndi_time_graphinfo:
    """
    Container for sync graph information.

    Attributes:
        nodes: List of ndi_time_epochnode objects
        G: Adjacency matrix (cost matrix) - G[i,j] is cost from node i to j
        mapping: Matrix of ndi_time_timemapping objects - mapping[i,j] maps time from i to j
        diG: NetworkX DiGraph for path finding
        syncrule_ids: List of sync rule document IDs
        syncrule_G: Matrix indicating which sync rule created each edge
    """

    nodes: list[ndi_time_epochnode] = field(default_factory=list)
    G: np.ndarray | None = None  # Cost matrix
    mapping: list[list[ndi_time_timemapping | None]] | None = None
    diG: Any = None  # NetworkX DiGraph
    syncrule_ids: list[str] = field(default_factory=list)
    syncrule_G: np.ndarray | None = None  # Sync rule index matrix


class ndi_time_syncgraph(ndi_ido):
    """
    Synchronization graph for managing time conversion across epochs.

    ndi_time_syncgraph builds a graph where nodes are epochs and edges represent
    time mappings between them. It uses NetworkX to find shortest paths
    for time conversion.

    Example:
        >>> sg = ndi_time_syncgraph(session)
        >>> sg.add_rule(ndi_time_syncrule_filematch())
        >>> t_out, ref_out, msg = sg.time_convert(
        ...     timeref_in, t_in, referent_out, clocktype_out
        ... )
    """

    def __init__(
        self,
        session: Any = None,
        document: ndi_document | None = None,
        identifier: str | None = None,
    ):
        """
        Create a new ndi_time_syncgraph.

        Args:
            session: The NDI session object
            document: Optional document to load from
            identifier: Optional identifier
        """
        if not HAS_NETWORKX:
            raise ImportError(
                "networkx is required for ndi_time_syncgraph. Install with: pip install networkx"
            )

        super().__init__(identifier)

        self._session = session
        self._rules: list[ndi_time_syncrule] = []
        self._cached_ginfo: ndi_time_graphinfo | None = None

        # Load from document if provided
        if document is not None and session is not None:
            self._load_from_document(session, document)

    def _load_from_document(self, session: Any, document: ndi_document) -> None:
        """Load syncgraph state from a document."""
        self._identifier = document.id

        # Load sync rules from document dependencies
        syncrule_ids = document.dependency_value_n("syncrule_id", error_if_not_found=False)
        if syncrule_ids:
            for rule_id in syncrule_ids:
                # Find and load the sync rule document
                from ..query import ndi_query

                q = ndi_query("base.id") == rule_id
                docs = session.database_search(q)
                if docs:
                    rule = ndi_time_syncrule.from_document(session, docs[0])
                    self._rules.append(rule)

    @property
    def session(self) -> Any:
        """Get the session."""
        return self._session

    @property
    def rules(self) -> list[ndi_time_syncrule]:
        """Get the sync rules."""
        return self._rules.copy()

    def add_rule(self, rule: ndi_time_syncrule) -> ndi_time_syncgraph:
        """
        Add a sync rule to the graph.

        Args:
            rule: ndi_time_syncrule to add

        Returns:
            self for chaining
        """
        if not isinstance(rule, ndi_time_syncrule):
            raise TypeError("rule must be a ndi_time_syncrule instance")

        # Check for duplicates
        for existing in self._rules:
            if existing == rule:
                return self

        self._rules.append(rule)
        self._remove_cached_graphinfo()
        return self

    def remove_rule(self, index: int) -> ndi_time_syncgraph:
        """
        Remove a sync rule by index.

        Args:
            index: Index of rule to remove

        Returns:
            self for chaining
        """
        if 0 <= index < len(self._rules):
            del self._rules[index]
            self._remove_cached_graphinfo()
        return self

    def graphinfo(self) -> ndi_time_graphinfo:
        """
        Get the graph information, building if necessary.

        Returns:
            ndi_time_graphinfo object with nodes, cost matrix, mappings, etc.
        """
        if self._cached_ginfo is None:
            self._cached_ginfo = self._build_graphinfo()
        return self._cached_ginfo

    def _build_graphinfo(self) -> ndi_time_graphinfo:
        """
        Build the sync graph from scratch.

        Returns:
            ndi_time_graphinfo with all epoch nodes and mappings
        """
        ginfo = ndi_time_graphinfo()
        ginfo.syncrule_ids = [rule.id for rule in self._rules]

        # Load all DAQ systems from session
        if self._session is None:
            return ginfo

        # Get all DAQ systems
        daqsystems = []
        if hasattr(self._session, "daqsystem_load"):
            daqsystems = self._session.daqsystem_load(name="(.*)")
            if not isinstance(daqsystems, list):
                daqsystems = [daqsystems] if daqsystems else []

        # Add each DAQ system's epochs to the graph
        for daq in daqsystems:
            ginfo = self._add_epoch(daq, ginfo)

        return ginfo

    def _add_epoch(self, daqsystem: Any, ginfo: ndi_time_graphinfo) -> ndi_time_graphinfo:
        """
        Add a DAQ system's epochs to the graph.

        Args:
            daqsystem: The DAQ system to add
            ginfo: Current graph info

        Returns:
            Updated ndi_time_graphinfo
        """
        # Get epoch nodes from the DAQ system
        if hasattr(daqsystem, "epochnodes"):
            newnodes_data = daqsystem.epochnodes()
            newnodes = [
                ndi_time_epochnode.from_dict(n) if isinstance(n, dict) else n for n in newnodes_data
            ]
        else:
            newnodes = []

        if not newnodes:
            return ginfo

        # Get the DAQ system's internal graph
        if hasattr(daqsystem, "epochgraph"):
            newcost, newmapping = daqsystem.epochgraph()
        else:
            n = len(newnodes)
            newcost = np.full((n, n), np.inf)
            newmapping = [[None] * n for _ in range(n)]

        oldn = len(ginfo.nodes)
        newn = len(newnodes)

        # Extend the graph
        ginfo.nodes.extend(newnodes)

        # Extend cost matrix
        if ginfo.G is None:
            ginfo.G = newcost
        else:
            # Expand existing matrix
            new_G = np.full((oldn + newn, oldn + newn), np.inf)
            new_G[:oldn, :oldn] = ginfo.G
            new_G[oldn:, oldn:] = newcost
            ginfo.G = new_G

        # Extend mapping matrix
        if ginfo.mapping is None:
            ginfo.mapping = newmapping
        else:
            # Expand existing mapping
            new_mapping = [[None] * (oldn + newn) for _ in range(oldn + newn)]
            for i in range(oldn):
                for j in range(oldn):
                    new_mapping[i][j] = ginfo.mapping[i][j]
            for i in range(newn):
                for j in range(newn):
                    new_mapping[oldn + i][oldn + j] = newmapping[i][j]
            ginfo.mapping = new_mapping

        # Extend syncrule_G matrix
        if ginfo.syncrule_G is None:
            ginfo.syncrule_G = np.zeros((oldn + newn, oldn + newn), dtype=int)
        else:
            new_srG = np.zeros((oldn + newn, oldn + newn), dtype=int)
            new_srG[:oldn, :oldn] = ginfo.syncrule_G
            ginfo.syncrule_G = new_srG

        # Add clock-based edges (utc->utc, etc.)
        for i in range(oldn):
            for j in range(oldn, oldn + newn):
                # Check both directions
                cost_ij, map_ij = ginfo.nodes[i].epoch_clock.epochgraph_edge(
                    ginfo.nodes[j].epoch_clock
                )
                if not np.isinf(cost_ij):
                    ginfo.G[i, j] = cost_ij
                    ginfo.mapping[i][j] = map_ij

                cost_ji, map_ji = ginfo.nodes[j].epoch_clock.epochgraph_edge(
                    ginfo.nodes[i].epoch_clock
                )
                if not np.isinf(cost_ji):
                    ginfo.G[j, i] = cost_ji
                    ginfo.mapping[j][i] = map_ji

        # Apply sync rules (the daqsystem is required by trigger-based rules to
        # read their trigger trains; without it they early-return — audit C7)
        for i in range(oldn):
            for j in range(oldn, oldn + newn):
                self._apply_rules_to_edge(ginfo, i, j, daqsystem)
                self._apply_rules_to_edge(ginfo, j, i, daqsystem)

        # Build NetworkX graph
        ginfo.diG = self._build_digraph(ginfo.G)

        return ginfo

    def _apply_rules_to_edge(
        self, ginfo: ndi_time_graphinfo, i: int, j: int, daqsystem: Any = None
    ) -> None:
        """Apply sync rules to find the best edge between nodes i and j.

        *daqsystem* is threaded through to ``rule.apply`` so that trigger-based
        rules (commonTriggersOverlappingEpochs, randomPulses) can read their
        trigger trains; MATLAB passes it as the 4th argument to apply (audit C7).
        """
        best_cost = np.inf
        best_mapping = None
        best_rule_idx = 0

        node_i = ginfo.nodes[i].to_dict()
        node_j = ginfo.nodes[j].to_dict()

        for k, rule in enumerate(self._rules):
            cost, mapping = rule.apply(node_i, node_j, daqsystem)
            if cost is not None and cost < best_cost:
                best_cost = cost
                best_mapping = mapping
                best_rule_idx = k + 1  # 1-indexed

        if best_mapping is not None:
            ginfo.G[i, j] = best_cost
            ginfo.mapping[i][j] = best_mapping
            ginfo.syncrule_G[i, j] = best_rule_idx

    @staticmethod
    def _build_digraph(G: np.ndarray) -> Any:
        """Build a NetworkX DiGraph from the cost matrix."""
        if not HAS_NETWORKX:
            return None

        # Replace inf with 0 for graph construction (no edge)
        G_table = G.copy()
        G_table[np.isinf(G_table)] = 0

        return nx.DiGraph(G_table)

    def _remove_cached_graphinfo(self) -> None:
        """Clear the cached graph info."""
        self._cached_ginfo = None

    def time_convert(
        self,
        timeref_in: ndi_time_timereference,
        t_in: float,
        referent_out: Any,
        clocktype_out: ndi_time_clocktype,
    ) -> tuple[float | None, ndi_time_timereference | None, str]:
        """
        Convert time from one reference to another.

        Args:
            timeref_in: Input time reference
            t_in: Input time value
            referent_out: Target referent object
            clocktype_out: Target clock type

        Returns:
            Tuple of (t_out, timeref_out, message) where:
            - t_out is the converted time (or None if failed)
            - timeref_out is the output ndi_time_timereference (or None if failed)
            - message describes any error
        """
        from .timereference import ndi_time_timereference

        # --- C5 branch 1: resolve the input epoch id (empty -> global lookup) --
        try:
            in_epochid = self._resolve_in_epochid(timeref_in, t_in)
        except ValueError as exc:
            return None, None, str(exc)

        # --- C5 branch 2: same-referent shortcut (bypass the syncgraph) -------
        if self._same_referent(timeref_in.referent, referent_out):
            return self._same_referent_convert(
                timeref_in, t_in, referent_out, clocktype_out, in_epochid
            )

        # Get graph info. An empty graph is not fatal here: the source/dest may
        # be an element/probe whose epochs are injected lazily below (audit C6).
        ginfo = self.graphinfo()

        # Find source node
        source_idx = self._find_epoch_node(
            ginfo.nodes,
            timeref_in.referent,
            timeref_in.clocktype,
            in_epochid,
        )

        if source_idx is None:
            # audit C6: the source epoch isn't a DAQ-system node yet. Inject the
            # referent's underlying epochs (element/probe -> ... -> DAQ) into the
            # graph and try once more (MATLAB syncgraph.m:716-735).
            ginfo = self._add_underlying_epochs(timeref_in.referent, ginfo)
            source_idx = self._find_epoch_node(
                ginfo.nodes,
                timeref_in.referent,
                timeref_in.clocktype,
                in_epochid,
            )
            if source_idx is None:
                return None, None, "Could not find source node"

        # --- C5 branch 3: when both clocks are global, narrow the destination
        # candidates to the epoch whose t0_t1 window contains the absolute time
        # (syncgraph.m:744-746) ------------------------------------------------
        dest_time = None
        if clocktype_out.is_global() and timeref_in.clocktype.is_global():
            dest_time = (timeref_in.time or 0) + t_in

        # Find destination node(s)
        dest_indices = self._find_destination_nodes(
            ginfo.nodes,
            referent_out,
            clocktype_out,
            dest_time,
        )

        if not dest_indices:
            # audit C6: if no node from referent_out exists at all, inject its
            # underlying epochs and retry once (MATLAB syncgraph.m:751-762).
            any_referent = self._find_destination_nodes(ginfo.nodes, referent_out, None, None)
            if not any_referent:
                before = len(ginfo.nodes)
                ginfo = self._add_underlying_epochs(referent_out, ginfo)
                if len(ginfo.nodes) != before:
                    dest_indices = self._find_destination_nodes(
                        ginfo.nodes, referent_out, clocktype_out, dest_time
                    )
            if not dest_indices:
                return None, None, "Could not find destination node"

        # Find shortest path
        if ginfo.diG is None:
            return None, None, "Graph not built"

        # Distances from source to every reachable destination candidate.
        reachable: list[tuple[int, float, list[int]]] = []
        for dest_idx in dest_indices:
            try:
                dist = nx.shortest_path_length(ginfo.diG, source_idx, dest_idx, weight="weight")
                path = nx.shortest_path(ginfo.diG, source_idx, dest_idx, weight="weight")
                reachable.append((dest_idx, dist, path))
            except nx.NetworkXNoPath:
                continue

        if not reachable:
            return None, None, "No path found between nodes"

        # --- C5 branch 4: equal-cost tie-breaking ----------------------------
        min_dist = min(r[1] for r in reachable)
        min_cands = [r for r in reachable if r[1] == min_dist]
        if len(min_cands) == 1:
            best_path = min_cands[0][2]
        else:
            # Multiple equal-cost destinations: sort by epoch_id and break the
            # tie on t_in (+Inf->last, -Inf/0->first), else it is ambiguous.
            ordered = sorted(min_cands, key=lambda r: ginfo.nodes[r[0]].epoch_id)
            if t_in == np.inf:
                best_path = ordered[-1][2]
            elif t_in == -np.inf or t_in == 0:
                best_path = ordered[0][2]
            else:
                return None, None, "Too many paths; ambiguous destination epoch for the given time"

        # Apply mappings along path
        t_out = t_in - (timeref_in.time or 0)
        for i in range(len(best_path) - 1):
            mapping = ginfo.mapping[best_path[i]][best_path[i + 1]]
            if mapping is not None:
                t_out = mapping.map(t_out)

        # Create output time reference
        dest_node = ginfo.nodes[best_path[-1]]
        timeref_out = ndi_time_timereference(
            referent=referent_out,
            clocktype=dest_node.epoch_clock,
            epoch=dest_node.epoch_id,
            time=0,
        )

        return t_out, timeref_out, ""

    @staticmethod
    def _referent_epochtable(referent: Any) -> list[dict[str, Any]]:
        """Return a referent's epoch table as a list of entry dicts."""
        if not hasattr(referent, "epochtable"):
            return []
        et = referent.epochtable()
        if isinstance(et, tuple):
            et = et[0]
        return list(et) if et else []

    @staticmethod
    def _same_referent(ref_a: Any, ref_b: Any) -> bool:
        """True if two referents are the same object (by identity or id())."""
        if ref_a is ref_b:
            return True
        try:
            ida = ref_a.id() if callable(getattr(ref_a, "id", None)) else getattr(ref_a, "id", None)
            idb = ref_b.id() if callable(getattr(ref_b, "id", None)) else getattr(ref_b, "id", None)
            if ida is not None and ida == idb:
                # Same object id AND same epochsetname (a referent is identified
                # by both — distinct elements can share an underlying id).
                na = ref_a.epochsetname() if hasattr(ref_a, "epochsetname") else None
                nb = ref_b.epochsetname() if hasattr(ref_b, "epochsetname") else None
                return na == nb
        except Exception:
            pass
        return False

    @staticmethod
    def _rescale(t: float, from_range: tuple[float, float], to_range: tuple[float, float]) -> float:
        """Linearly remap *t* from *from_range* onto *to_range* (no clipping)."""
        f0, f1 = from_range
        d0, d1 = to_range
        if f1 == f0:
            return d0
        return d0 + (t - f0) * (d1 - d0) / (f1 - f0)

    def _resolve_in_epochid(self, timeref_in: Any, t_in: float) -> str:
        """Resolve the input epoch id (audit C5 branch 1).

        If ``timeref_in.epoch`` is set, use it (resolving a numeric epoch index
        against the referent's epoch table). If empty, the clock must be global;
        scan the referent's epoch table for the epoch whose ``t0_t1`` window
        (for that clock) contains ``timeref_in.time + t_in``.
        """
        epoch = timeref_in.epoch
        if epoch not in (None, ""):
            if isinstance(epoch, int):
                et = self._referent_epochtable(timeref_in.referent)
                if 0 < epoch <= len(et):
                    return et[epoch - 1].get("epoch_id", "")
                return ""
            return epoch

        if not timeref_in.clocktype.is_global():
            raise ValueError("A timeref with an empty epoch requires a global clock type")

        target = (timeref_in.time or 0) + t_in
        for entry in self._referent_epochtable(timeref_in.referent):
            clocks = entry.get("epoch_clock", [])
            t0_t1 = entry.get("t0_t1", [])
            for idx, clk in enumerate(clocks):
                if clk == timeref_in.clocktype and idx < len(t0_t1):
                    lo, hi = t0_t1[idx][0], t0_t1[idx][1]
                    if lo <= target <= hi:
                        return entry.get("epoch_id", "")
        raise ValueError("Did not find parent epoch for timeref.")

    def _same_referent_convert(
        self,
        timeref_in: Any,
        t_in: float,
        referent_out: Any,
        clocktype_out: ndi_time_clocktype,
        in_epochid: str,
    ) -> tuple[float | None, Any, str]:
        """Convert time when source and destination referents are the same
        object, without consulting the syncgraph (audit C5 branch 2)."""
        from .timereference import ndi_time_timereference

        if timeref_in.clocktype == clocktype_out:
            return (
                t_in,
                ndi_time_timereference(referent_out, clocktype_out, in_epochid, timeref_in.time),
                "",
            )

        # Different clock on the same referent: rescale t_in from the source
        # clock's window (shifted by -timeref_in.time) onto the dest window.
        et = self._referent_epochtable(referent_out)
        match = next((e for e in et if e.get("epoch_id") == in_epochid), None)
        if match is None:
            return None, None, "No matching epoch on the requested referent"
        clocks = match.get("epoch_clock", [])
        t0_t1 = match.get("t0_t1", [])
        j1 = next((i for i, c in enumerate(clocks) if c == timeref_in.clocktype), None)
        j2 = next((i for i, c in enumerate(clocks) if c == clocktype_out), None)
        if j2 is None or j1 is None or j1 >= len(t0_t1) or j2 >= len(t0_t1):
            return None, None, "No clock type match for the requested referent"
        shift = timeref_in.time or 0
        corrected = (t0_t1[j1][0] - shift, t0_t1[j1][1] - shift)
        t_out = self._rescale(t_in, corrected, (t0_t1[j2][0], t0_t1[j2][1]))
        return t_out, ndi_time_timereference(referent_out, clocktype_out, in_epochid, 0), ""

    def _add_underlying_epochs(
        self, epochset: Any, ginfo: ndi_time_graphinfo
    ) -> ndi_time_graphinfo:
        """Inject an element/probe epochset's epochs into the graph (audit C6).

        Port of MATLAB ``ndi.time.syncgraph/addunderlyingepochs``
        (syncgraph.m:461-550). For every epoch node of *epochset* not already in
        the graph, fetch its underlying-epoch sub-graph
        (``underlyingepochnodes``) and overlay it onto the main graph, reusing
        any underlying node (e.g. the DAQ-system epoch) that is already present.
        Finally connect all nodes that share an equivalence global clock with a
        fallback identity edge, and rebuild the directed graph + cache.

        *epochset* must expose ``epochnodes()`` and ``underlyingepochnodes()``
        (every ``ndi.epoch.epochset`` does). Anything else is a no-op so callers
        with bare/fake referents degrade gracefully.
        """
        if not (hasattr(epochset, "epochnodes") and hasattr(epochset, "underlyingepochnodes")):
            return ginfo
        try:
            enodes = epochset.epochnodes()
        except Exception:
            return ginfo

        if ginfo.G is None:
            ginfo.G = np.zeros((0, 0))
        if ginfo.mapping is None:
            ginfo.mapping = []
        if ginfo.syncrule_G is None:
            ginfo.syncrule_G = np.zeros((0, 0), dtype=int)

        for enode in enodes:
            if self._find_node_index(ginfo.nodes, enode) is not None:
                continue  # already in the graph
            try:
                u_nodes, u_cost, u_mapping = epochset.underlyingepochnodes(enode)
            except Exception:
                continue

            # Map each underlying node to a main-graph index: reuse the index of
            # any node already present, allocate a fresh index for the rest.
            n_existing = len(ginfo.nodes)
            main_index: list[int] = []
            new_nodes: list[Any] = []
            for un in u_nodes:
                idx = self._find_node_index(ginfo.nodes, un)
                if idx is not None:
                    main_index.append(idx)
                else:
                    main_index.append(n_existing + len(new_nodes))
                    new_nodes.append(un)

            if new_nodes:
                self._grow_ginfo(ginfo, len(new_nodes))
                for un in new_nodes:
                    ginfo.nodes.append(
                        ndi_time_epochnode.from_dict(un) if isinstance(un, dict) else un
                    )

            # Overlay the sub-graph onto the new-node blocks. Existing<->existing
            # edges are left untouched (this is exactly the result of MATLAB's
            # vlt.graph.mergegraph, which only fills the upper-right / lower-left
            # / lower-right panels), expressed directly via node indices.
            k = len(u_nodes)
            for a in range(k):
                ia = main_index[a]
                for b in range(k):
                    ib = main_index[b]
                    if ia < n_existing and ib < n_existing:
                        continue
                    c = u_cost[a][b]
                    if not np.isinf(c):
                        ginfo.G[ia, ib] = c
                        ginfo.mapping[ia][ib] = u_mapping[a][b]

        self._add_equivalence_edges(ginfo)
        ginfo.diG = self._build_digraph(ginfo.G)
        self._cached_ginfo = ginfo
        return ginfo

    @staticmethod
    def _grow_ginfo(ginfo: ndi_time_graphinfo, n_add: int) -> None:
        """Grow ginfo's cost/mapping/syncrule matrices by *n_add* nodes (inf/None/0)."""
        old = ginfo.G.shape[0] if ginfo.G is not None and ginfo.G.size else len(ginfo.nodes)
        new_n = old + n_add

        new_G = np.full((new_n, new_n), np.inf)
        if ginfo.G is not None and ginfo.G.size:
            new_G[:old, :old] = ginfo.G
        ginfo.G = new_G

        new_map: list[list[Any]] = [[None] * new_n for _ in range(new_n)]
        if ginfo.mapping:
            for i in range(min(old, len(ginfo.mapping))):
                for j in range(min(old, len(ginfo.mapping[i]))):
                    new_map[i][j] = ginfo.mapping[i][j]
        ginfo.mapping = new_map

        new_sr = np.zeros((new_n, new_n), dtype=int)
        if ginfo.syncrule_G is not None and ginfo.syncrule_G.size:
            new_sr[:old, :old] = ginfo.syncrule_G
        ginfo.syncrule_G = new_sr

    @staticmethod
    def _add_equivalence_edges(ginfo: ndi_time_graphinfo) -> None:
        """Connect nodes that share an equivalence global clock (audit C6).

        MATLAB (syncgraph.m:526-543) gives every pair of nodes whose clock is
        ``utc`` (or every pair whose clock is ``exp_global_time``) a cost-77
        identity edge so global clocks remain mutually reachable. NOTE: the
        MATLAB ``strcmp(ginfo.nodes(matches(i))...)`` guard at syncgraph.m:534
        indexes ``matches`` with the outer clock-loop counter ``i`` (1 or 2)
        rather than the node-pair counters ``j``/``k`` — a latent bug that makes
        the guard depend on node ordering. We port the documented intent ("make
        sure all utc and exp_global_time clocks map onto one another") and only
        fill a pair that has no cheaper edge, so genuine cost-1 self/direct edges
        are preserved ("self is still 1, and across-object maps are still 1").
        """
        if ginfo.G is None or ginfo.G.size == 0:
            return
        identity = ndi_time_timemapping([1, 0])
        for clock in (ndi_time_clocktype.UTC, ndi_time_clocktype.EXP_GLOBAL_TIME):
            matches = [i for i, node in enumerate(ginfo.nodes) if node.epoch_clock == clock]
            for a in matches:
                for b in matches:
                    if a != b and ginfo.G[a, b] > 77:
                        ginfo.G[a, b] = 77
                        ginfo.mapping[a][b] = identity

    @staticmethod
    def _find_node_index(nodes: list[ndi_time_epochnode], node: Any) -> int | None:
        """Return the index of the graph node identical to *node* (or None).

        Identity is the MATLAB ``ndi.epoch.findepochnode`` exact-match key:
        objectname, objectclass, epoch_id, epoch_session_id and epoch_clock.
        *node* may be a dict (from ``epochnodes()``) or an ``ndi_time_epochnode``.
        """

        def get(obj: Any, key: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        objectname = get(node, "objectname")
        objectclass = get(node, "objectclass")
        epoch_id = get(node, "epoch_id")
        epoch_session_id = get(node, "epoch_session_id")
        epoch_clock = get(node, "epoch_clock")

        for i, existing in enumerate(nodes):
            if existing.objectname != objectname:
                continue
            if existing.objectclass != objectclass:
                continue
            if existing.epoch_id != epoch_id:
                continue
            if existing.epoch_session_id != epoch_session_id:
                continue
            if existing.epoch_clock != epoch_clock:
                continue
            return i
        return None

    def _find_epoch_node(
        self,
        nodes: list[ndi_time_epochnode],
        referent: Any,
        clocktype: ndi_time_clocktype,
        epoch_id: str | None,
    ) -> int | None:
        """Find the index of a matching epoch node."""
        # Get referent name
        if hasattr(referent, "epochsetname"):
            ref_name = (
                referent.epochsetname()
                if callable(referent.epochsetname)
                else referent.epochsetname
            )
        elif hasattr(referent, "name"):
            ref_name = referent.name
        else:
            ref_name = str(referent)

        for i, node in enumerate(nodes):
            if node.objectname != ref_name:
                continue
            if node.epoch_clock != clocktype:
                continue
            if epoch_id is not None and node.epoch_id != epoch_id:
                continue
            return i

        return None

    def _find_destination_nodes(
        self,
        nodes: list[ndi_time_epochnode],
        referent: Any,
        clocktype: ndi_time_clocktype | None,
        time_value: float | None = None,
    ) -> list[int]:
        """Find indices of all nodes matching the destination criteria.

        Matches on ``objectname``; when *clocktype* is given, also on the clock;
        when *time_value* is given (audit C5 branch 3, both clocks global), keeps
        only candidates whose ``t0_t1`` window contains the value.
        """
        # Get referent name
        if hasattr(referent, "epochsetname"):
            ref_name = (
                referent.epochsetname()
                if callable(referent.epochsetname)
                else referent.epochsetname
            )
        elif hasattr(referent, "name"):
            ref_name = referent.name
        else:
            ref_name = str(referent)

        indices = []
        for i, node in enumerate(nodes):
            if node.objectname != ref_name:
                continue
            if clocktype is not None and node.epoch_clock != clocktype:
                continue
            if time_value is not None:
                t0_t1 = node.t0_t1
                if not t0_t1 or len(t0_t1) < 2:
                    continue
                t0, t1 = t0_t1[0], t0_t1[1]
                if not (t0 <= time_value <= t1):
                    continue
            indices.append(i)

        return indices

    def __eq__(self, other: object) -> bool:
        """Check equality of two sync graphs."""
        if not isinstance(other, ndi_time_syncgraph):
            return NotImplemented

        if self._session != other._session:
            return False

        if len(self._rules) != len(other._rules):
            return False

        for r1, r2 in zip(self._rules, other._rules):
            if r1 != r2:
                return False

        return True

    def new_document(self) -> list[ndi_document]:
        """
        Create documents for this sync graph and its rules.

        Returns:
            List of ndi_document objects
        """
        from ..document import ndi_document

        docs = []

        # Create syncgraph document
        sg_doc = ndi_document(
            document_type="daq/syncgraph",
            **{
                "syncgraph.ndi_syncgraph_class": ndi_matlab_classname(self),
                "base.id": self.id,
                "base.session_id": self._session.id() if self._session else "",
            },
        )

        # Add rule dependencies
        for rule in self._rules:
            rule_doc = rule.new_document()
            docs.append(rule_doc)
            sg_doc = sg_doc.add_dependency_value_n("syncrule_id", rule.id)

        docs.insert(0, sg_doc)
        return docs

    def search_query(self) -> Any:
        """Create a search query for this sync graph."""
        from ..query import ndi_query

        return (ndi_query("base.id") == self.id) & (
            ndi_query("base.session_id") == (self._session.id() if self._session else "")
        )
