"""
Regression tests for audit C8b: ndi.neuron must be constructable so that
sorted units round-trip through the database.

Before the fix, ndi_neuron inherited ndi_element_class() == "ndi.element" and
was absent from the class registry, so a neuron document written with
element.ndi_element_class == "ndi.neuron" could not be reconstructed;
getelements() swallowed the failure and silently returned zero neurons.
"""

from __future__ import annotations

import pytest

from ndi.element import ndi_element
from ndi.element_timeseries import ndi_element_timeseries
from ndi.neuron import ndi_neuron
from ndi.session.dir import ndi_session_dir


@pytest.fixture
def session(tmp_path):
    p = tmp_path / "session1"
    p.mkdir(parents=True, exist_ok=True)
    return ndi_session_dir("TestSession", p)


class TestElementClassStrings:
    def test_neuron_class_string(self):
        assert ndi_neuron().ndi_element_class() == "ndi.neuron"

    def test_element_timeseries_class_string(self):
        assert ndi_element_timeseries().ndi_element_class() == "ndi.element.timeseries"

    def test_plain_element_unchanged(self):
        assert ndi_element().ndi_element_class() == "ndi.element"


class TestRegistry:
    def test_registry_resolves_neuron(self):
        from ndi.class_registry import get_class

        assert get_class("ndi.neuron") is ndi_neuron

    def test_registry_resolves_element_timeseries(self):
        from ndi.class_registry import get_class

        assert get_class("ndi.element.timeseries") is ndi_element_timeseries


class TestNeuronRoundTrip:
    def test_neuron_survives_getelements(self, session):
        """A stored neuron must come back from getelements() as an ndi_neuron —
        before C8b this returned zero neurons."""
        n = ndi_neuron(session=session, name="unit1", reference=1)
        doc = n.newdocument()
        # The stored class label must be ndi.neuron, not ndi.element.
        assert doc.document_properties["element"]["ndi_element_class"] == "ndi.neuron"

        session.database_add(doc)

        elements = session.getelements()
        neurons = [e for e in elements if isinstance(e, ndi_neuron)]
        assert len(neurons) == 1
        assert neurons[0].ndi_element_class() == "ndi.neuron"

    def test_getelements_surfaces_unconstructable(self, session):
        """An element document whose class is not registered must make
        getelements raise, not silently drop the element (audit C8b)."""
        n = ndi_neuron(session=session, name="unit1", reference=1)
        doc = n.newdocument()
        # Corrupt the class label to an unregistered name.
        doc.document_properties["element"]["ndi_element_class"] = "ndi.does_not_exist"
        session.database_add(doc)

        with pytest.raises(Exception):
            session.getelements()
