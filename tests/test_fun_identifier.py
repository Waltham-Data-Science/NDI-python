"""Tests for ndi.fun.identifier.

Python only; MATLAB has one spelling, ``obj.id()``. On this side a session's
``id`` is a method while a document's, an element's and a probe's are
properties inherited from ``ndi.ido``, so a ported call site that writes
``probe.id()`` raises ``TypeError`` against a real probe -- and passes every
test whose double defines ``id`` as a method. That is the failure this
function exists to remove, so the regression at the bottom checks a real
document and a property-style probe, not another method-style double.
"""

from __future__ import annotations

from ndi.document import ndi_document
from ndi.fun import identifier


class MethodStyle:
    """A session: ``id`` is a method."""

    def id(self):
        return "session-id"


class PropertyStyle:
    """A probe, element or document: ``id`` is a property."""

    @property
    def id(self):
        return "probe-id"


def test_a_method_id_is_called():
    assert identifier(MethodStyle()) == "session-id"


def test_a_property_id_is_read():
    assert identifier(PropertyStyle()) == "probe-id"


def test_a_plain_attribute_is_read():
    class Attribute:
        id = "plain-id"

    assert identifier(Attribute()) == "plain-id"


def test_an_object_with_no_id_gives_none():
    """None, not "": a caller building a query wants to notice."""
    assert identifier(object()) is None


def test_a_real_document_answers():
    doc = ndi_document("base")
    assert identifier(doc) == doc.id
    assert isinstance(identifier(doc), str)


def test_geometry_lookup_works_against_a_property_style_probe():
    """The regression. ndi.fun.probe.geometry.get called probe.id(), which
    raises against every real probe; the tests it shipped with all used
    doubles whose id was a method, so nothing caught it."""
    import numpy as np

    from ndi.fun.probe.geometry import get

    class RealisticProbe:
        @property
        def id(self):
            return "probe1"

        def elementstring(self):
            return "ctx | 1"

        def epochtable(self):
            return [{"epoch_id": "e1", "t0_t1": [[0.0, 1.0]]}], "hash"

        def readtimeseries(
            self, timeref_or_epoch=None, t0=0.0, t1=0.0, timeref=None
        ):  # noqa: ARG002
            return np.zeros((1, 2)), np.zeros(1), None

    asked = []

    class Session:
        def database_search(self, query):
            asked.append(query.search_structure)
            return []

    result = get(Session(), RealisticProbe())

    assert result.found is False
    assert asked[0][1]["param2"] == "probe1"
