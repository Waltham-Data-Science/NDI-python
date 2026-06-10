"""Tests for syncgraph addunderlyingepochs / lazy graph injection (audit C6).

Before this, the syncgraph only ever held DAQ-system epoch nodes; an
element/probe whose epoch was not a directly-resolvable DAQ epoch returned
"Could not find source node" from ``time_convert``. C6 ports MATLAB's
``addunderlyingepochs`` + the missing-node retry: an element's epochs (and the
underlying chain down to the root device) are injected into the graph on demand.

These tests deliberately drive the REAL ``epochnodes()`` /
``underlyingepochnodes()`` / merge / equivalence-edge / retry code through real
``ndi_element`` objects with real ``underlying_epochs`` populated by
``buildepochtable`` — not flat pre-built graph nodes — because a flat fake would
bypass exactly the machinery under test.
"""

from __future__ import annotations

import numpy as np

from ndi.element import ndi_element
from ndi.epoch.epochset import ndi_epoch_epochset
from ndi.time.clocktype import ndi_time_clocktype as CT
from ndi.time.syncgraph import (
    ndi_time_epochnode,
    ndi_time_graphinfo,
    ndi_time_syncgraph,
)
from ndi.time.timereference import ndi_time_timereference


class _FakeSession:
    def id(self):
        return "sess1"


class _Device(ndi_epoch_epochset):
    """A minimal but real root epoch set standing in for a DAQ system.

    It owns one epoch with the given clocks/windows. Being a sync-graph root,
    ``underlyingepochnodes`` stops here, so it is the leaf the element resolves
    down to.
    """

    subject_id = ""

    def __init__(self, name="dev1", clocks=None, t0_t1=None, session_id="sess1"):
        super().__init__()
        self._name = name
        self._clocks = clocks or [CT.DEV_LOCAL_TIME]
        self._t0_t1 = t0_t1 or [(0.0, 10.0)]
        self._session_id = session_id
        self.session = _FakeSession()

    def id(self):
        return "id_" + self._name

    def buildepochtable(self):
        return [
            {
                "epoch_number": 1,
                "epoch_id": "ep1",
                "epoch_session_id": self._session_id,
                "epochprobemap": [],
                "epoch_clock": list(self._clocks),
                "t0_t1": list(self._t0_t1),
                "underlying_epochs": {},
            }
        ]

    def epochsetname(self):
        return self._name

    def issyncgraphroot(self):
        return True


def _element_on(device, name="e1", reference=1):
    """A real ndi_element that takes its epochs directly from *device*."""
    return ndi_element(
        session=_FakeSession(),
        name=name,
        reference=reference,
        type="n",
        underlying_element=device,
        direct=True,
    )


class TestUnderlyingEpochNodes:
    def test_chain_returns_element_then_device(self):
        device = _Device()
        elem = _element_on(device)
        nodes = elem.epochnodes()
        assert len(nodes) == 1
        unodes, cost, mapping = elem.underlyingepochnodes(nodes[0])
        # element node + the device leaf it resolves down to
        assert len(unodes) == 2
        assert unodes[0]["objectname"] == "element: e1 | 1"
        assert unodes[1]["objectname"] == "dev1"
        # connected both ways at cost 1
        assert cost[0, 1] == 1 and cost[1, 0] == 1
        assert mapping[0][1] is not None and mapping[1][0] is not None


class TestRecursiveChain:
    def test_three_level_element_element_device(self):
        """element -> (non-root) element -> root device exercises the recursive
        sub-graph merge in underlyingepochnodes (epochset.m:469-499)."""
        device = _Device()
        mid = _element_on(device, name="mid")
        top = _element_on(mid, name="top")

        nodes = top.epochnodes()
        assert len(nodes) == 1
        unodes, cost, mapping = top.underlyingepochnodes(nodes[0])
        names = [u["objectname"] for u in unodes]
        assert names[0] == "element: top | 1"
        assert "element: mid | 1" in names
        assert "dev1" in names
        assert len(unodes) == 3
        # there is a finite-cost path top -> mid -> device
        mid_i = names.index("element: mid | 1")
        dev_i = names.index("dev1")
        assert np.isfinite(cost[0, mid_i])
        assert np.isfinite(cost[mid_i, dev_i])

    def test_three_level_time_convert_resolves(self):
        device = _Device()
        mid = _element_on(device, name="mid")
        top = _element_on(mid, name="top")
        sg = ndi_time_syncgraph(session=None)
        tin = ndi_time_timereference(top, CT.DEV_LOCAL_TIME, "ep1", 0)
        t, ref, msg = sg.time_convert(tin, 5.0, device, CT.DEV_LOCAL_TIME)
        assert msg == ""
        assert t == 5.0


class TestLazyInjection:
    def test_time_convert_element_to_device_resolves(self):
        """Source epoch is an element node absent from the graph: it must be
        injected and a path to the underlying device found."""
        device = _Device()
        elem = _element_on(device)
        sg = ndi_time_syncgraph(session=None)
        tin = ndi_time_timereference(elem, CT.DEV_LOCAL_TIME, "ep1", 0)
        t, ref, msg = sg.time_convert(tin, 5.0, device, CT.DEV_LOCAL_TIME)
        assert msg == ""
        assert t == 5.0
        assert ref.clocktype == CT.DEV_LOCAL_TIME
        assert ref.epoch == "ep1"

    def test_underlying_device_node_is_reused_not_duplicated(self):
        """Injecting the element must reuse a device node already in the graph
        rather than create a disconnected duplicate (mergegraph semantics)."""
        device = _Device()
        elem = _element_on(device)
        sg = ndi_time_syncgraph(session=None)
        ginfo = ndi_time_graphinfo()

        # Seed the graph with the device's own node first.
        sg._add_underlying_epochs(device, ginfo)
        n_after_device = len(ginfo.nodes)
        assert n_after_device == 1  # just the device epoch node

        # Poison the device's existing self-edge with a sentinel so we can prove
        # the overlay does NOT clobber pre-existing edges (mergegraph keeps the
        # upper-left block) when the element's device leaf is merged onto it.
        ginfo.G[0, 0] = 999.0

        # Now inject the element: only the element node should be added; the
        # device leaf must match (reuse) the existing device node.
        sg._add_underlying_epochs(elem, ginfo)
        assert len(ginfo.nodes) == n_after_device + 1
        objnames = [n.objectname for n in ginfo.nodes]
        assert "dev1" in objnames and "element: e1 | 1" in objnames

        # The reused device node must actually be connected to the element node
        # (a disconnected duplicate would still pass the name/count checks).
        di = objnames.index("dev1")
        ei = objnames.index("element: e1 | 1")
        assert np.isfinite(ginfo.G[ei, di]) and np.isfinite(ginfo.G[di, ei])
        # ...and the pre-existing device self-edge was preserved, not overwritten.
        assert ginfo.G[di, di] == 999.0

    def test_time_convert_device_to_element_resolves(self):
        """referent_out (the element) is absent from the graph: it must be
        injected via the destination-retry path (MATLAB syncgraph.m:751-762)."""
        device = _Device()
        elem = _element_on(device)
        sg = ndi_time_syncgraph(session=None)
        tin = ndi_time_timereference(device, CT.DEV_LOCAL_TIME, "ep1", 0)
        t, ref, msg = sg.time_convert(tin, 5.0, elem, CT.DEV_LOCAL_TIME)
        assert msg == ""
        assert t == 5.0
        assert ref.epoch == "ep1"

    def test_missing_referent_is_graceful(self):
        """A bare referent with no epochnodes() must be a no-op, not a crash."""

        class _Bare:
            def epochsetname(self):
                return "bare"

        sg = ndi_time_syncgraph(session=None)
        ginfo = ndi_time_graphinfo()
        out = sg._add_underlying_epochs(_Bare(), ginfo)
        assert out.nodes == []


class TestUtcCompanion:
    """The UTC->dev_local companion node (epochset.m:411-425) is the only
    non-identity affine math in the port; pin its offsets directly."""

    def test_companion_node_and_offsets(self):
        device = _Device(clocks=[CT.UTC], t0_t1=[(1000.0, 1010.0)])
        node = device.epochnodes()[0]
        assert node["epoch_clock"] == CT.UTC
        unodes, cost, mapping = device.underlyingepochnodes(node)
        assert len(unodes) == 2
        assert unodes[1]["epoch_clock"] == CT.DEV_LOCAL_TIME
        # companion window is the epoch duration starting at 0
        assert unodes[1]["t0_t1"] == (0.0, 10.0)
        assert cost[0, 1] == 1 and cost[1, 0] == 1
        # utc->local subtracts t0; local->utc adds it back
        assert mapping[0][1].map(1000.0) == 0.0
        assert mapping[1][0].map(0.0) == 1000.0


class TestNonIdentityComposition:
    """Guards mapping COMPOSITION (not just path existence). All-identity
    fixtures would let a transposed/dropped mapping pass silently, so these use
    a real affine offset that must survive the chain."""

    def test_recursion_block_carries_companion_offsets(self):
        """A UTC epoch at each level forces the recursive sub-graph merge
        (epochset.m:489-496) to carry non-identity mappings; a transpose or sign
        error in that block would corrupt them."""
        device = _Device(clocks=[CT.UTC], t0_t1=[(1000.0, 1010.0)])
        mid = _element_on(device, name="mid")
        top = _element_on(mid, name="top")
        unodes, cost, mapping = top.underlyingepochnodes(top.epochnodes()[0])

        def find(objectname, clock):
            for i, u in enumerate(unodes):
                if u["objectname"] == objectname and u["epoch_clock"] == clock:
                    return i
            raise AssertionError(f"missing {objectname}/{clock}")

        mid_utc = find("element: mid | 1", CT.UTC)
        mid_local = find("element: mid | 1", CT.DEV_LOCAL_TIME)
        # mid's companion offsets must be intact after block-merge into top
        assert mapping[mid_utc][mid_local].map(1000.0) == 0.0
        assert mapping[mid_local][mid_utc].map(0.0) == 1000.0

    def test_time_convert_applies_offset_end_to_end(self):
        """top UTC 1005 -> mid dev_local must be 5 (1005 - t0=1000). A broken
        composition would return a different number, not just fail to find a path."""
        device = _Device(clocks=[CT.UTC], t0_t1=[(1000.0, 1010.0)])
        mid = _element_on(device, name="mid")
        top = _element_on(mid, name="top")
        sg = ndi_time_syncgraph(session=None)
        tin = ndi_time_timereference(top, CT.UTC, "ep1", 0)
        t, ref, msg = sg.time_convert(tin, 1005.0, mid, CT.DEV_LOCAL_TIME)
        assert msg == ""
        assert t == 5.0
        assert ref.clocktype == CT.DEV_LOCAL_TIME


class TestEpochNodesFanout:
    def test_one_node_per_clock(self):
        """epochnodes() emits one node per (epoch, clock) with the correctly
        paired t0_t1 window (epochset.m:359-368)."""
        device = _Device(
            clocks=[CT.DEV_LOCAL_TIME, CT.EXP_GLOBAL_TIME],
            t0_t1=[(0.0, 10.0), (1000.0, 1010.0)],
        )
        nodes = device.epochnodes()
        assert len(nodes) == 2
        by_clock = {n["epoch_clock"]: n["t0_t1"] for n in nodes}
        assert by_clock[CT.DEV_LOCAL_TIME] == (0.0, 10.0)
        assert by_clock[CT.EXP_GLOBAL_TIME] == (1000.0, 1010.0)


class TestEquivalenceEdges:
    def test_global_clocks_get_cost77(self):
        """Two nodes sharing exp_global_time on different objects gain a
        fallback identity edge so global clocks stay mutually reachable."""
        sg = ndi_time_syncgraph(session=None)

        def node(name):
            return ndi_time_epochnode(
                epoch_id="e",
                epoch_session_id="s",
                epochprobemap=None,
                epoch_clock=CT.EXP_GLOBAL_TIME,
                t0_t1=(0.0, 1.0),
                objectname=name,
            )

        ginfo = ndi_time_graphinfo(nodes=[node("a"), node("b")])
        ginfo.G = np.full((2, 2), np.inf)
        ginfo.mapping = [[None, None], [None, None]]
        sg._add_equivalence_edges(ginfo)
        assert ginfo.G[0, 1] == 77 and ginfo.G[1, 0] == 77
        assert ginfo.mapping[0][1] is not None

    def test_does_not_clobber_cheaper_edge(self):
        sg = ndi_time_syncgraph(session=None)

        def node(name):
            return ndi_time_epochnode(
                epoch_id="e",
                epoch_session_id="s",
                epochprobemap=None,
                epoch_clock=CT.UTC,
                t0_t1=(0.0, 1.0),
                objectname=name,
            )

        ginfo = ndi_time_graphinfo(nodes=[node("a"), node("b")])
        ginfo.G = np.array([[np.inf, 1.0], [1.0, np.inf]])
        ginfo.mapping = [[None, "keep"], ["keep", None]]
        sg._add_equivalence_edges(ginfo)
        # existing cost-1 edge preserved, not overwritten with 77
        assert ginfo.G[0, 1] == 1 and ginfo.mapping[0][1] == "keep"


class TestC5Branch3DestTimeFilter:
    def test_destination_filtered_by_time_window(self):
        """When both clocks are global, only the dest epoch whose t0_t1 window
        contains the absolute time is a candidate (syncgraph.m:744-746)."""
        sg = ndi_time_syncgraph(session=None)

        class _Ref:
            def epochsetname(self):
                return "R"

        def node(epoch_id, t0, t1):
            return ndi_time_epochnode(
                epoch_id=epoch_id,
                epoch_session_id="s",
                epochprobemap=None,
                epoch_clock=CT.EXP_GLOBAL_TIME,
                t0_t1=(t0, t1),
                objectname="R",
            )

        nodes = [node("e1", 0.0, 10.0), node("e2", 100.0, 110.0)]
        # No time filter -> both candidates
        assert sg._find_destination_nodes(nodes, _Ref(), CT.EXP_GLOBAL_TIME, None) == [0, 1]
        # time 105 falls only in e2's window
        assert sg._find_destination_nodes(nodes, _Ref(), CT.EXP_GLOBAL_TIME, 105.0) == [1]
        # time 5 falls only in e1's window
        assert sg._find_destination_nodes(nodes, _Ref(), CT.EXP_GLOBAL_TIME, 5.0) == [0]
