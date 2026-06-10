"""PR11 part 2: markgarbage valid_interval array/struct storage + identifyvalidintervals.

markvalidinterval now serializes each timeref into a reconstructable struct and
savevalidinterval stores the ndi_common schema's array-of-structs (MATLAB
markgarbage.m: load existing array -> dedup -> append -> clear -> store array).
identifyvalidintervals projects each stored region into a query timeref via the
session syncgraph and unions the results (mirrors vlt.math.interval_add).

markgarbage no longer depends on vlt, so this suite needs no vlt.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from ndi.app.markgarbage import ndi_app_markgarbage


class _FakeSession:
    """Minimal session: records add/remove, returns all stored docs on search."""

    def __init__(self):
        self.added = []
        self.removed = []
        self._docs = []

    def id(self):
        return "sess-1"

    def database_add(self, doc):
        self.added.append(doc)
        self._docs.append(doc)

    def database_remove(self, doc):
        self.removed.append(doc)
        if doc in self._docs:
            self._docs.remove(doc)

    def database_search(self, q):
        return list(self._docs)


# --------------------------------------------------------------------------
# _timeref_to_struct
# --------------------------------------------------------------------------


def test_timeref_to_struct_dict_passthrough():
    d = {
        "referent_epochsetname": "p",
        "referent_classname": "ndi_probe_timeseries",
        "clocktypestring": "dev_local_time",
        "epoch": "e1",
        "time": 0,
    }
    assert ndi_app_markgarbage._timeref_to_struct(d) == d


def test_timeref_to_struct_string_is_nonreconstructable():
    s = ndi_app_markgarbage._timeref_to_struct("opaque-tag")
    assert s["referent_epochsetname"] == "opaque-tag"
    # empty referent_classname/clocktypestring => identifyvalidintervals treats
    # it as non-projectable
    assert s["referent_classname"] == ""
    assert s["clocktypestring"] == ""


# --------------------------------------------------------------------------
# _interval_add (inline port of vlt.math.interval_add's union semantics)
# --------------------------------------------------------------------------


def test_interval_add_disjoint_keeps_both_sorted():
    out = ndi_app_markgarbage._interval_add(np.empty((0, 2)), [0.0, 1.0])
    out = ndi_app_markgarbage._interval_add(out, [2.0, 3.0])
    np.testing.assert_array_equal(out, [[0.0, 1.0], [2.0, 3.0]])


def test_interval_add_overlap_merges():
    out = ndi_app_markgarbage._interval_add(np.array([[0.0, 2.0]]), [1.0, 3.0])
    np.testing.assert_array_equal(out, [[0.0, 3.0]])


def test_interval_add_out_of_order_sorts():
    out = ndi_app_markgarbage._interval_add(np.array([[5.0, 6.0]]), [0.0, 1.0])
    np.testing.assert_array_equal(out, [[0.0, 1.0], [5.0, 6.0]])


# --------------------------------------------------------------------------
# savevalidinterval — array model (accumulate + dedup), MATLAB markgarbage.m
# --------------------------------------------------------------------------


def test_savevalidinterval_accumulates_array():
    sess = _FakeSession()
    app = ndi_app_markgarbage(sess)
    probe = SimpleNamespace(id="p1")
    app.markvalidinterval(probe, 0.0, "tagA", 1.0, "tagA")
    app.markvalidinterval(probe, 2.0, "tagB", 3.0, "tagB")
    vi = sess.added[-1].document_properties["valid_interval"]
    assert len(vi) == 2
    assert vi[0]["t0"] == 0.0
    assert vi[1]["t0"] == 2.0
    # the prior single-interval doc was cleared before the 2-interval doc landed
    assert len(sess.removed) == 1


def test_savevalidinterval_skips_exact_duplicate():
    sess = _FakeSession()
    app = ndi_app_markgarbage(sess)
    probe = SimpleNamespace(id="p1")
    app.markvalidinterval(probe, 0.0, "tagA", 1.0, "tagA")
    n_added = len(sess.added)
    # an identical entry returns True but does NOT add a new document
    assert app.markvalidinterval(probe, 0.0, "tagA", 1.0, "tagA") is True
    assert len(sess.added) == n_added


# --------------------------------------------------------------------------
# identifyvalidintervals
# --------------------------------------------------------------------------


def test_identifyvalidintervals_empty_returns_baseline():
    sess = _FakeSession()
    app = ndi_app_markgarbage(sess)
    timeref = SimpleNamespace(referent=SimpleNamespace(), clocktype=SimpleNamespace(), epoch="e1")
    assert app.identifyvalidintervals(SimpleNamespace(id="p1"), timeref, 0.0, 10.0) == [(0.0, 10.0)]


def test_identifyvalidintervals_nonreconstructable_returns_baseline():
    # string-tag timerefs cannot be projected -> no restriction -> whole baseline
    sess = _FakeSession()
    app = ndi_app_markgarbage(sess)
    probe = SimpleNamespace(id="p1")
    app.markvalidinterval(probe, 2.0, "stringtag", 5.0, "stringtag")
    timeref = SimpleNamespace(referent=SimpleNamespace(), clocktype=SimpleNamespace(), epoch="e1")
    assert app.identifyvalidintervals(probe, timeref, 0.0, 10.0) == [(0.0, 10.0)]


def test_identifyvalidintervals_projects_and_carves(monkeypatch):
    # a reconstructable region that projects (identity) into the query epoch is
    # carved out as the valid interval
    sess = _FakeSession()
    sess.syncgraph = SimpleNamespace(
        time_convert=lambda tr, t, ref, clk: (t, SimpleNamespace(epoch="e1"), "")
    )
    app = ndi_app_markgarbage(sess)
    probe = SimpleNamespace(id="p1")

    from ndi.document import ndi_document

    iv = {
        "timeref_structt0": {"referent_classname": "X", "clocktypestring": "dev_local_time"},
        "t0": 2.0,
        "timeref_structt1": {"referent_classname": "X", "clocktypestring": "dev_local_time"},
        "t1": 5.0,
    }
    doc = ndi_document("apps/markgarbage/valid_interval", valid_interval=[iv])
    sess._docs.append(doc)
    # avoid the from_struct/findexpobj round-trip: a reconstructable struct
    # yields a stand-in timeref object
    monkeypatch.setattr(
        app,
        "_struct_to_timeref",
        lambda s: SimpleNamespace() if s.get("referent_classname") else None,
    )

    timeref = SimpleNamespace(referent=SimpleNamespace(), clocktype=SimpleNamespace(), epoch="e1")
    assert app.identifyvalidintervals(probe, timeref, 0.0, 10.0) == [(2.0, 5.0)]


def test_identifyvalidintervals_wrong_epoch_returns_baseline(monkeypatch):
    # the region projects, but into a DIFFERENT epoch than the query -> baseline
    sess = _FakeSession()
    sess.syncgraph = SimpleNamespace(
        time_convert=lambda tr, t, ref, clk: (t, SimpleNamespace(epoch="other"), "")
    )
    app = ndi_app_markgarbage(sess)
    probe = SimpleNamespace(id="p1")

    from ndi.document import ndi_document

    iv = {
        "timeref_structt0": {"referent_classname": "X", "clocktypestring": "dev_local_time"},
        "t0": 2.0,
        "timeref_structt1": {"referent_classname": "X", "clocktypestring": "dev_local_time"},
        "t1": 5.0,
    }
    sess._docs.append(ndi_document("apps/markgarbage/valid_interval", valid_interval=[iv]))
    monkeypatch.setattr(app, "_struct_to_timeref", lambda s: SimpleNamespace())

    timeref = SimpleNamespace(referent=SimpleNamespace(), clocktype=SimpleNamespace(), epoch="e1")
    assert app.identifyvalidintervals(probe, timeref, 0.0, 10.0) == [(0.0, 10.0)]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
