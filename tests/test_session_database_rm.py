"""``session.database_rm`` removes each id once, and can be made strict.

MATLAB counterpart: ``+ndi/session.m``, whose ``database_rm`` moved from
``vlt.data.assign(varargin{:})`` to a declared ``ErrIfNotFound`` argument
and, in the same change, started removing dependents and documents in one
de-duplicated pass::

    remove_list = cat(2, dependent_docs(:)', doc_list(:)');
    ... skip an id already in removed_ids ...

Both halves were broken on the Python side, and both were invisible:

* ``error_if_not_found`` was accepted and then never read, so a caller who
  asked to be told about a missing document was told nothing.
* dependents were removed inside the per-document loop, so a document
  reachable both directly and as another's dependency -- a daqsystem and
  its daqreader, say -- was deleted twice. That passed only because the
  second delete was silently ignored; the moment the strict flag worked,
  it would have reported a document missing that the same call had just
  removed.
"""

from __future__ import annotations

import pytest

from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir


@pytest.fixture
def session(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    return ndi_session_dir("rm_test", session_dir)


def _a_document(session):
    doc = session.newdocument("data/generic_file")
    doc.document_properties["generic_file"]["dateCreated"] = 0
    doc.document_properties["generic_file"]["dateUpdated"] = 0
    session.database_add(doc)
    return doc


class TestTheDefaultStaysForgiving:
    def test_removing_an_unknown_id_is_not_an_error(self, session):
        """The point of a removal is that the document ends up gone, so an
        id someone else already deleted counts as success."""
        session.database_rm("no-such-document-id")

    def test_removing_the_same_document_twice_is_not_an_error(self, session):
        doc = _a_document(session)
        session.database_rm(doc)
        session.database_rm(doc)
        assert session.database_search(ndi_query("base.id") == doc.id) == []


class TestTheStrictFlagIsActuallyRead:
    """It was a parameter the function never looked at.

    It governs the removal itself, not the lookup: an id STRING that names
    no document is dropped while the input is resolved, in Python and in
    MATLAB alike (``ndi.session.docinput2docs`` collects only what it
    found). What the flag catches is a document that was resolved and is
    gone by the time it is removed -- the case that made MATLAB's
    de-duplication necessary.
    """

    def test_an_unresolvable_id_string_is_still_dropped_quietly(self, session):
        session.database_rm("no-such-document-id", error_if_not_found=True)

    def test_a_document_already_gone_raises(self, session):
        doc = _a_document(session)
        session.database_rm(doc)
        with pytest.raises(KeyError):
            session.database_rm(doc, error_if_not_found=True)

    def test_a_present_document_still_removes_cleanly(self, session):
        doc = _a_document(session)
        session.database_rm(doc, error_if_not_found=True)
        assert session.database_search(ndi_query("base.id") == doc.id) == []


class TestOneIdIsRemovedOnlyOnce:
    def test_a_repeated_document_does_not_double_delete(self, session):
        """The same document twice in one call is one removal.

        Under the strict flag this is what distinguishes de-duplication from
        a swallowed error: without it, the second delete reports the
        document missing even though this very call removed it.
        """
        doc = _a_document(session)
        session.database_rm([doc, doc], error_if_not_found=True)
        assert session.database_search(ndi_query("base.id") == doc.id) == []

    def test_two_distinct_documents_both_go(self, session):
        first, second = _a_document(session), _a_document(session)
        session.database_rm([first, second], error_if_not_found=True)
        for doc in (first, second):
            assert session.database_search(ndi_query("base.id") == doc.id) == []
