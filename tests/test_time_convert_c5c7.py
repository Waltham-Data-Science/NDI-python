"""
Tests for syncgraph time_convert branches (audit C5) and rule-daqsystem
threading (audit C7).

time_convert had zero coverage before; these pin the same-referent shortcut,
the empty-epoch global resolution, the cross-clock rescale, and the equal-cost
tie-break, plus that _apply_rules_to_edge now passes the daqsystem to rules.
"""

from __future__ import annotations

import numpy as np

from ndi.time.clocktype import ndi_time_clocktype as CT
from ndi.time.syncgraph import ndi_time_syncgraph
from ndi.time.timereference import ndi_time_timereference


class _FakeSession:
    def id(self):
        return "sess1"


class _FakeRef:
    """A minimal epochset referent with one epoch and two clocks."""

    def __init__(self, name="probeA"):
        self._n = name
        self.session = _FakeSession()

    def id(self):
        return "id_" + self._n

    def epochsetname(self):
        return self._n

    def epochtable(self):
        return (
            [
                {
                    "epoch_id": "ep1",
                    "epoch_clock": [CT.DEV_LOCAL_TIME, CT.EXP_GLOBAL_TIME],
                    "t0_t1": [(0.0, 10.0), (100.0, 110.0)],
                }
            ],
            "hash",
        )


class TestSameReferent:
    def test_same_clock_passthrough(self):
        sg = ndi_time_syncgraph(session=None)
        r = _FakeRef()
        tin = ndi_time_timereference(r, CT.DEV_LOCAL_TIME, "ep1", 0)
        t, ref, msg = sg.time_convert(tin, 5.0, r, CT.DEV_LOCAL_TIME)
        assert msg == ""
        assert t == 5.0

    def test_cross_clock_rescale(self):
        """dev_local 5 in window [0,10] maps to exp_global 105 in [100,110]."""
        sg = ndi_time_syncgraph(session=None)
        r = _FakeRef()
        tin = ndi_time_timereference(r, CT.DEV_LOCAL_TIME, "ep1", 0)
        t, ref, msg = sg.time_convert(tin, 5.0, r, CT.EXP_GLOBAL_TIME)
        assert msg == ""
        assert abs(t - 105.0) < 1e-9
        assert ref.clocktype == CT.EXP_GLOBAL_TIME

    def test_cross_clock_endpoints(self):
        sg = ndi_time_syncgraph(session=None)
        r = _FakeRef()
        tin = ndi_time_timereference(r, CT.DEV_LOCAL_TIME, "ep1", 0)
        assert abs(sg.time_convert(tin, 0.0, r, CT.EXP_GLOBAL_TIME)[0] - 100.0) < 1e-9
        assert abs(sg.time_convert(tin, 10.0, r, CT.EXP_GLOBAL_TIME)[0] - 110.0) < 1e-9


class TestEmptyEpochResolution:
    def test_resolves_global_epoch(self):
        sg = ndi_time_syncgraph(session=None)
        r = _FakeRef()
        tin = ndi_time_timereference(r, CT.EXP_GLOBAL_TIME, None, 0)
        t, ref, msg = sg.time_convert(tin, 105.0, r, CT.EXP_GLOBAL_TIME)
        assert msg == ""
        assert ref.epoch == "ep1"
        assert t == 105.0

    def test_out_of_range_errors(self):
        sg = ndi_time_syncgraph(session=None)
        r = _FakeRef()
        tin = ndi_time_timereference(r, CT.EXP_GLOBAL_TIME, None, 0)
        t, ref, msg = sg.time_convert(tin, 999.0, r, CT.EXP_GLOBAL_TIME)
        assert t is None
        assert "parent epoch" in msg


class TestRuleDaqsystemThreading:
    def test_apply_rules_passes_daqsystem(self):
        """C7: _apply_rules_to_edge must forward the daqsystem to rule.apply."""
        from ndi.time.syncgraph import ndi_time_epochnode

        captured = {}

        class _SpyRule:
            id = "spy"

            def apply(self, a, b, daqsystem=None):
                captured["daqsystem"] = daqsystem
                return None, None

        sg = ndi_time_syncgraph(session=None)
        sg._rules = [_SpyRule()]
        node = ndi_time_epochnode(
            epoch_id="e",
            epoch_session_id="s",
            epochprobemap=None,
            epoch_clock=CT.DEV_LOCAL_TIME,
            t0_t1=(0.0, 1.0),
            objectname="x",
        )
        from ndi.time.syncgraph import ndi_time_graphinfo

        ginfo = ndi_time_graphinfo(nodes=[node, node])
        ginfo.G = np.full((2, 2), np.inf)
        ginfo.mapping = [[None, None], [None, None]]
        ginfo.syncrule_G = np.zeros((2, 2), dtype=int)

        sentinel = object()
        sg._apply_rules_to_edge(ginfo, 0, 1, sentinel)
        assert captured["daqsystem"] is sentinel
