"""ndi.dataset.database_openbinarydoc dispatches to a member session.

Regression coverage for waltham-data-science/ndi-python#175. Before the
fix, dataset.database_openbinarydoc unconditionally delegated to the
dataset's internal session, which does not own binaries for documents
that live in a linked/ingested member session. Opening such a binary
raised FileNotFoundError even though the file was really there.

The MATLAB counterpart (+ndi/dataset.m:database_openbinarydoc) resolves
the doc's owning session and delegates there. These tests pin the same
behavior on the Python side, and confirm the internal-session path is
unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ndi.dataset import ndi_dataset_dir
from ndi.document import ndi_document
from ndi.session.dir import ndi_session_dir

FILE_SLOT = "filename1.ext"
PAYLOAD = b"hello cross-session world"


def _add_doc_with_file(session: ndi_session_dir, name: str) -> ndi_document:
    path = Path(session.path) / f"{name}.bin"
    path.write_bytes(PAYLOAD)
    doc = ndi_document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = name
    props["demoNDI"]["value"] = 1
    props["base"]["session_id"] = session.id()
    doc = ndi_document(props).add_file(FILE_SLOT, str(path))
    session.database_add(doc)
    return doc


@pytest.fixture
def dataset(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    return ndi_dataset_dir("myds", str(d))


@pytest.fixture
def member_session(tmp_path):
    d = tmp_path / "member"
    d.mkdir()
    return ndi_session_dir("member_ref", d)


def test_openbinarydoc_reaches_a_linked_session(dataset, member_session):
    # A doc that lives in a linked session, not the dataset's own.
    doc = _add_doc_with_file(member_session, "linked_doc")
    dataset.add_linked_session(member_session)

    # Before the fix this raised FileNotFoundError -- the dataset's
    # internal session's database doesn't know about the doc.
    handle = dataset.database_openbinarydoc(doc, FILE_SLOT)
    try:
        assert handle.read() == PAYLOAD
    finally:
        handle.close()


def test_openbinarydoc_reaches_a_linked_session_by_id(dataset, member_session):
    # Same as above, but the caller passes just the doc id -- Python has
    # to look it up in the linked session's database.
    doc = _add_doc_with_file(member_session, "linked_by_id")
    dataset.add_linked_session(member_session)

    handle = dataset.database_openbinarydoc(doc.id, FILE_SLOT)
    try:
        assert handle.read() == PAYLOAD
    finally:
        handle.close()


def test_existbinarydoc_reaches_a_linked_session(dataset, member_session):
    doc = _add_doc_with_file(member_session, "exists_check")
    dataset.add_linked_session(member_session)

    exists, path = dataset.database_existbinarydoc(doc, FILE_SLOT)
    assert exists
    assert path is not None


def test_openbinarydoc_still_works_for_internal_session_docs(dataset, tmp_path):
    # An internal-session doc: session_id is the dataset's own id.
    path = tmp_path / "internal.bin"
    path.write_bytes(PAYLOAD)
    doc = ndi_document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = "internal_doc"
    props["demoNDI"]["value"] = 1
    props["base"]["session_id"] = dataset.id()
    doc = ndi_document(props).add_file(FILE_SLOT, str(path))
    dataset.database_add(doc)

    handle = dataset.database_openbinarydoc(doc, FILE_SLOT)
    try:
        assert handle.read() == PAYLOAD
    finally:
        handle.close()
