"""Tests for ndi.element.timeseries.addMultiple — batched element creation (MATLAB cbbb099b).

addMultiple builds N elements (default ndi.neuron), their per-epoch
``epoch_binary_data.vhsb`` data, and caller-supplied extra documents in memory,
then commits them in batched ``database_add`` calls. These tests exercise the
real path against a real session: document/dependency structure, the
``build_objects`` toggle, extra documents, chunking, and a full VHSB
write→readtimeseries round-trip (which depends on PR4's VHSB writer present on
this branch).
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.element import ndi_element
from ndi.element_timeseries import ndi_element_timeseries
from ndi.neuron import ndi_neuron
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir
from ndi.time.clocktype import ndi_time_clocktype as CT


@pytest.fixture
def session(tmp_path):
    p = tmp_path / "sess"
    p.mkdir()
    return ndi_session_dir("T", p)


@pytest.fixture
def underlying(session):
    """A real probe-like underlying element registered in the session."""
    u = ndi_element(
        session=session,
        name="probe1",
        reference=1,
        type="probe",
        direct=False,
        subject_id="subj1",
    )
    session.database_add(u.newdocument())
    return u


def _spec(name, reference, t0=0.0, t1=10.0, tp=None, dp=None):
    tp = np.array([1.0, 2.0, 3.0]) if tp is None else tp
    dp = np.array([10.0, 20.0, 30.0]) if dp is None else dp
    return {
        "name": name,
        "reference": reference,
        "type": "spikes",
        "epochs": [
            {
                "epoch_id": "ep1",
                "epoch_clock": CT.DEV_LOCAL_TIME,
                "t0_t1": [t0, t1],
                "timepoints": tp,
                "datapoints": dp,
            }
        ],
    }


class TestAddMultiple:
    def test_creates_neuron_objects(self, session, underlying):
        specs = [_spec("n1", 1), _spec("n2", 2), _spec("n3", 3)]
        neurons = ndi_element_timeseries.addMultiple(session, underlying, specs)
        assert neurons is not None
        assert len(neurons) == 3
        assert all(isinstance(x, ndi_neuron) for x in neurons)
        assert [x.name for x in neurons] == ["n1", "n2", "n3"]

    def test_element_documents_registered(self, session, underlying):
        ndi_element_timeseries.addMultiple(session, underlying, [_spec("n1", 1), _spec("n2", 2)])
        docs = session.database_search(ndi_query("").isa("element"))
        elem_docs = [
            d
            for d in docs
            if d.document_properties.get("element", {}).get("ndi_element_class") == "ndi.neuron"
        ]
        assert len(elem_docs) == 2

    def test_epoch_documents_depend_on_elements(self, session, underlying):
        neurons = ndi_element_timeseries.addMultiple(session, underlying, [_spec("n1", 1)])
        nid = neurons[0].id
        epoch_docs = session.database_search(
            ndi_query("").isa("element_epoch") & ndi_query("").depends_on("element_id", nid)
        )
        assert len(epoch_docs) == 1

    def test_round_trip_readtimeseries(self, session, underlying):
        """Spike times written by addMultiple must read back via the VHSB path."""
        tp = np.array([0.5, 1.5, 2.5, 3.5])
        dp = np.array([1.0, 1.0, 1.0, 1.0])
        neurons = ndi_element_timeseries.addMultiple(
            session, underlying, [_spec("n1", 1, tp=tp, dp=dp)]
        )
        data, times, ref = neurons[0].readtimeseries("ep1")
        assert np.allclose(times, tp)
        assert np.allclose(data.reshape(-1), dp)
        assert ref is not None and ref.epoch == "ep1"

    def test_build_objects_false_returns_none_but_creates_docs(self, session, underlying):
        out = ndi_element_timeseries.addMultiple(
            session, underlying, [_spec("n1", 1), _spec("n2", 2)], build_objects=False
        )
        assert out is None
        docs = session.database_search(ndi_query("").isa("element"))
        neuron_docs = [
            d
            for d in docs
            if d.document_properties.get("element", {}).get("ndi_element_class") == "ndi.neuron"
        ]
        assert len(neuron_docs) == 2

    def test_extra_documents_committed_with_element_dependency(self, session, underlying):
        from ndi.document import ndi_document

        extra = ndi_document("element_epoch")  # any base document will do as a stand-in
        spec = _spec("n1", 1)
        spec["extra_documents"] = [extra]
        neurons = ndi_element_timeseries.addMultiple(session, underlying, [spec])
        nid = neurons[0].id
        assert extra.dependency_value("element_id") == nid
        # committed to the database
        found = session.database_search(ndi_query("base.id") == extra.id)
        assert len(found) == 1

    def test_empty_specs(self, session, underlying):
        assert ndi_element_timeseries.addMultiple(session, underlying, []) == []
        assert (
            ndi_element_timeseries.addMultiple(session, underlying, [], build_objects=False) is None
        )

    def test_chunking_creates_all(self, session, underlying):
        specs = [_spec(f"n{i}", i) for i in range(5)]
        neurons = ndi_element_timeseries.addMultiple(
            session, underlying, specs, chunksize=2, build_objects=False
        )
        assert neurons is None
        docs = session.database_search(ndi_query("").isa("element"))
        neuron_docs = [
            d
            for d in docs
            if d.document_properties.get("element", {}).get("ndi_element_class") == "ndi.neuron"
        ]
        assert len(neuron_docs) == 5
