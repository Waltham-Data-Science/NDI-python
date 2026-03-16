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

        # Apply sync rules
        for i in range(oldn):
            for j in range(oldn, oldn + newn):
                self._apply_rules_to_edge(ginfo, i, j)
                self._apply_rules_to_edge(ginfo, j, i)

        # Build NetworkX graph
        ginfo.diG = self._build_digraph(ginfo.G)

        return ginfo

    def _apply_rules_to_edge(self, ginfo: ndi_time_graphinfo, i: int, j: int) -> None:
        """Apply sync rules to find the best edge between nodes i and j."""
        best_cost = np.inf
        best_mapping = None
        best_rule_idx = 0

        node_i = ginfo.nodes[i].to_dict()
        node_j = ginfo.nodes[j].to_dict()

        for k, rule in enumerate(self._rules):
            cost, mapping = rule.apply(node_i, node_j)
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

        # Get graph info
        ginfo = self.graphinfo()

        if not ginfo.nodes:
            return None, None, "Graph has no nodes"

        # Find source node
        source_idx = self._find_epoch_node(
            ginfo.nodes,
            timeref_in.referent,
            timeref_in.clocktype,
            timeref_in.epoch,
        )

        if source_idx is None:
            return None, None, "Could not find source node"

        # Find destination node(s)
        dest_indices = self._find_destination_nodes(
            ginfo.nodes,
            referent_out,
            clocktype_out,
        )

        if not dest_indices:
            return None, None, "Could not find destination node"

        # Find shortest path
        if ginfo.diG is None:
            return None, None, "Graph not built"

        best_path = None
        best_dist = np.inf

        for dest_idx in dest_indices:
            try:
                dist = nx.shortest_path_length(ginfo.diG, source_idx, dest_idx, weight="weight")
                if dist < best_dist:
                    best_dist = dist
                    best_path = nx.shortest_path(ginfo.diG, source_idx, dest_idx, weight="weight")
            except nx.NetworkXNoPath:
                continue

        if best_path is None:
            return None, None, "No path found between nodes"

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
        clocktype: ndi_time_clocktype,
    ) -> list[int]:
        """Find indices of all nodes matching the destination criteria."""
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
            if node.epoch_clock != clocktype:
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
                "syncgraph.ndi_syncgraph_class": type(self).__name__,
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
