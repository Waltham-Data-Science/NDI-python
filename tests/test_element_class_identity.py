"""``element.ndi_element_class`` must name the class that wrote the document.

Issue #133. ``ndi_neuron`` and ``ndi_element_timeseries`` inherited
``ndi_element_class()`` from :class:`~ndi.element.ndi_element`, so both wrote
``"ndi.element"``, and neither name was in :mod:`ndi.class_registry`. That
loses data in both directions, and neither direction said anything:

* Python writes a neuron, anything reads it: the document says plain element,
  so it comes back a plain element -- no ``readtimeseries``, no error.
* MATLAB writes a neuron (MATLAB stores ``class(obj)``, so ``"ndi.neuron"``),
  Python reads it: the registry lookup returns ``None``,
  ``_document_to_object`` raises, and ``getelements`` swallowed the exception
  and returned the session's neurons as an empty list.

The round trips below go through a real ``ndi_session_dir`` and a real
database rather than asserting on ``ndi_element_class()`` alone: the string
being right matters only because the document written from it reconstructs as
the right class, and only a real write/read shows that.
"""

from __future__ import annotations

import logging

import pytest

from ndi.class_registry import get_class
from ndi.element import ndi_element
from ndi.element.ensemble import ndi_element_ensemble
from ndi.element_timeseries import ndi_element_timeseries
from ndi.neuron import ndi_neuron
from ndi.probe.timeseries import ndi_probe_timeseries
from ndi.session import ndi_session_dir
from ndi.subject import ndi_subject

#: Every class whose instances are stored as an ``element`` document, with the
#: MATLAB ``class(obj)`` string each one must record. The MATLAB name is the
#: contract: ``+ndi/element.m:546`` writes ``class(ndi_element_obj)``.
ELEMENT_CLASSES = [
    (ndi_element, "ndi.element"),
    (ndi_element_timeseries, "ndi.element.timeseries"),
    (ndi_neuron, "ndi.neuron"),
    (ndi_element_ensemble, "ndi.element.ensemble"),
    (ndi_probe_timeseries, "ndi.probe.timeseries"),
]


@pytest.fixture
def session(tmp_path):
    """A real session directory with a subject to hang elements off."""
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    s = ndi_session_dir("element_class_test", str(d))

    subject_doc = ndi_subject("mouse23@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(s.id())
    s.database_add(subject_doc)
    s.subject_id = subject_doc.id
    return s


# ----------------------------------------------------------------------
# the names themselves
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("cls", "expected"), ELEMENT_CLASSES, ids=lambda v: getattr(v, "__name__", v)
)
def test_ndi_element_class_matches_matlab(cls, expected):
    """Each class reports the name MATLAB's ``class(obj)`` would give it."""
    assert cls().ndi_element_class() == expected


@pytest.mark.parametrize(
    ("cls", "expected"), ELEMENT_CLASSES, ids=lambda v: getattr(v, "__name__", v)
)
def test_every_element_class_is_registered(cls, expected):
    """A name no registry entry resolves cannot be reconstructed at all."""
    assert get_class(expected) is cls


def test_subclasses_do_not_share_a_name():
    """Two element classes reporting one name would make the registry lossy."""
    names = [name for _, name in ELEMENT_CLASSES]
    assert len(names) == len(set(names))


# ----------------------------------------------------------------------
# direction 1: Python writes, Python reads
# ----------------------------------------------------------------------
def test_python_written_neuron_round_trips_as_a_neuron(session):
    """The defect that lost data: a written neuron came back a plain element."""
    neuron = ndi_neuron(session=session, name="neuron1", reference=1, subject_id=session.subject_id)
    doc = neuron.newdocument()
    assert doc.document_properties["element"]["ndi_element_class"] == "ndi.neuron"
    session.database_add(doc)

    elements = session.getelements()
    assert len(elements) == 1
    loaded = elements[0]
    assert type(loaded) is ndi_neuron
    assert loaded.id == neuron.id
    assert loaded.name == "neuron1"
    assert hasattr(loaded, "readtimeseries")


def test_python_written_timeseries_round_trips_as_a_timeseries(session):
    """Same defect, same fix, for the intermediate class."""
    elem = ndi_element_timeseries(
        session=session,
        name="ts1",
        reference=1,
        type="spikes",
        subject_id=session.subject_id,
    )
    doc = elem.newdocument()
    assert doc.document_properties["element"]["ndi_element_class"] == "ndi.element.timeseries"
    session.database_add(doc)

    loaded = session.getelements()[0]
    assert type(loaded) is ndi_element_timeseries
    assert loaded.id == elem.id


def test_a_plain_element_is_still_a_plain_element(session):
    """The overrides must not promote an element that really is one."""
    elem = ndi_element(
        session=session,
        name="elec1",
        reference=1,
        type="n-trode",
        subject_id=session.subject_id,
    )
    session.database_add(elem.newdocument())

    loaded = session.getelements()[0]
    assert type(loaded) is ndi_element


def test_mixed_elements_each_load_as_their_own_class(session):
    """All three kinds in one session, each reconstructed as what wrote it."""
    written = {
        "elec1": ndi_element(
            session=session,
            name="elec1",
            reference=1,
            type="n-trode",
            subject_id=session.subject_id,
        ),
        "ts1": ndi_element_timeseries(
            session=session,
            name="ts1",
            reference=1,
            type="spikes",
            subject_id=session.subject_id,
        ),
        "neuron1": ndi_neuron(
            session=session, name="neuron1", reference=1, subject_id=session.subject_id
        ),
    }
    for elem in written.values():
        session.database_add(elem.newdocument())

    loaded = {e.name: e for e in session.getelements()}
    assert set(loaded) == set(written)
    for name, elem in written.items():
        assert type(loaded[name]) is type(elem), name
        assert loaded[name].id == elem.id


def test_searchquery_finds_the_document_it_wrote(session):
    """``searchquery`` matches on the class name, so it moves with the fix."""
    neuron = ndi_neuron(session=session, name="neuron1", reference=1, subject_id=session.subject_id)
    session.database_add(neuron.newdocument())

    found = session.database_search(neuron.searchquery())
    assert [d.id for d in found] == [neuron.id]


# ----------------------------------------------------------------------
# direction 2: MATLAB writes, Python reads
# ----------------------------------------------------------------------
def _matlab_style_element_doc(session, ndi_element_class, name, type_):
    """An element document shaped the way MATLAB writes one.

    MATLAB's ``ndi.element/newdocument`` stores ``class(ndi_element_obj)``
    verbatim (``+ndi/element.m:546``), so this is the only field that differs
    from a Python-written document -- which is exactly why the mislabelling
    was invisible until something tried to reconstruct the object.
    """
    doc = session.newdocument(
        "element",
        **{
            "element.ndi_element_class": ndi_element_class,
            "element.name": name,
            "element.reference": 1,
            "element.type": type_,
            "element.direct": 1,
        },
    )
    doc.set_session_id(session.id())
    doc.set_dependency_value("subject_id", session.subject_id)
    return doc


def test_matlab_written_neuron_reaches_getelements(session):
    """THE POINT: ``getelements`` used to return [] for a MATLAB session."""
    doc = _matlab_style_element_doc(session, "ndi.neuron", "neuron1", "neuron")
    session.database_add(doc)

    elements = session.getelements()
    assert len(elements) == 1, "a MATLAB-written neuron was dropped from getelements"
    assert type(elements[0]) is ndi_neuron
    assert elements[0].id == doc.id


def test_matlab_written_timeseries_reaches_getelements(session):
    """The same for ``ndi.element.timeseries``."""
    doc = _matlab_style_element_doc(session, "ndi.element.timeseries", "ts1", "spikes")
    session.database_add(doc)

    elements = session.getelements()
    assert len(elements) == 1
    assert type(elements[0]) is ndi_element_timeseries


# ----------------------------------------------------------------------
# the swallow that hid all of it
# ----------------------------------------------------------------------
def test_an_unreconstructable_document_is_reported_not_swallowed(session, caplog):
    """``getelements`` may skip a document it cannot build, but must say so.

    A bare ``except Exception: pass`` is what let five files' worth of this
    bug run unnoticed. The contract stays "one bad document does not cost the
    caller the others"; what changes is that the drop is visible.
    """
    good = ndi_neuron(session=session, name="neuron1", reference=1, subject_id=session.subject_id)
    session.database_add(good.newdocument())
    bad = _matlab_style_element_doc(session, "ndi.no.such.class", "mystery", "neuron")
    session.database_add(bad)

    with caplog.at_level(logging.WARNING, logger="ndi.session.session_base"):
        elements = session.getelements()

    assert [e.id for e in elements] == [good.id], "the readable element must survive"
    assert bad.id in caplog.text
    assert "ndi.no.such.class" in caplog.text


def test_a_legacy_python_neuron_document_is_flagged(session, caplog):
    """A neuron written before the fix says ``ndi.element``; warn about it.

    The label is deliberately NOT rewritten from ``element.type``: MATLAB
    builds ``feval(stored class name)`` and nothing else, so inferring a class
    the document does not name would make the two languages disagree about
    what the same document is. The document still loads as a plain element --
    the user is simply told why it has no ``readtimeseries``.
    """
    doc = _matlab_style_element_doc(session, "ndi.element", "neuron1", "neuron")
    session.database_add(doc)

    with caplog.at_level(logging.WARNING, logger="ndi.session.session_base"):
        elements = session.getelements()

    assert len(elements) == 1
    assert type(elements[0]) is ndi_element
    assert doc.id in caplog.text
    assert "#133" in caplog.text


def test_a_current_element_document_is_not_flagged(session, caplog):
    """The legacy warning must not fire on documents written today."""
    for elem in (
        ndi_element(
            session=session,
            name="elec1",
            reference=1,
            type="n-trode",
            subject_id=session.subject_id,
        ),
        ndi_neuron(session=session, name="neuron1", reference=1, subject_id=session.subject_id),
    ):
        session.database_add(elem.newdocument())

    with caplog.at_level(logging.WARNING, logger="ndi.session.session_base"):
        assert len(session.getelements()) == 2

    assert caplog.text == ""
