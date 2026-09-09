"""An extract must be storable somewhere else, series and all.

MATLAB counterpart: ``+ndi/+database/+fun/extract_docs_files.m``

``extract_doc_files`` exists for ``ndi.dataset.copySessionToDataset``: it
copies the documents AND their files so the copy can be added to a different
database. That contract has three parts, and the Python version had none of
them.

Files go to ``target_path/<uid>`` under the uid the source database knows
them by, and each returned document's file_info is rebuilt to name its copy
-- otherwise the extract is a pile of bytes with nothing pointing at it.

A series' MEMBERS are copied, not just its manifest. ``current_file_list``
names the manifest only, deliberately, so that a 28,000-member series does
not materialise 28,000 names; the members are walked from the series record
and fetched by their ``NAME_<i>`` names, which resolve through the manifest.

And each member is recorded UNDER ITS ORIGINAL UID. Ingestion writes a
member to ``FileDir/<uid>`` from that record, and the copied manifest names
its members by uid, so a fresh uid would leave the copy's manifest pointing
at nothing -- and DID refuses a document declaring present members with no
ingest_locations at all (DID-matlab#185).

``TestTheExtractIsStorableElsewhere`` is the contract itself: the extract is
added to a second session and its members are read back there.
"""

from __future__ import annotations

import uuid

import pytest
from did.file import write_series_manifest

from ndi.database_fun import extract_doc_files
from ndi.document import ndi_document
from ndi.session.dir import ndi_session_dir

SLOT = "filename1.ext"
MANIFEST_BYTES_MARKER = 4
MEMBER_ONE = b"the first member's bytes"
MEMBER_THREE = b"the third member's bytes"
PLAIN_BYTES = b"an ordinary file"


@pytest.fixture
def tag():
    """A fresh uid prefix per test.

    DID's file cache is machine-global and keyed by uid, not scoped to
    tmp_path, so constant uids leak between runs and between tests.
    """
    return uuid.uuid4().hex[:8]


def member_uid(tag, n):
    return f"MEMBER{tag}{n:019d}"


def _session(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return ndi_session_dir(name, d)


def _doc_with_a_plain_file(tmp_path, session):
    source = tmp_path / "plain.bin"
    source.write_bytes(PLAIN_BYTES)
    props = ndi_document("demoNDI").document_properties
    props["base"]["session_id"] = session.id()
    props["demoNDI"]["value"] = 1
    doc = ndi_document(props).add_file(SLOT, str(source))
    session.database_add(doc)
    return doc


def _doc_with_a_sparse_series(tmp_path, session, tag):
    """A document whose series has members at slots 1 and 3 of 3.

    The gap at slot 2 is the case the whole mechanism exists for: a member
    with nothing to store is not written.
    """
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    write_series_manifest(
        str(source / "manifest.bin"), [member_uid(tag, 1), "", member_uid(tag, 3)]
    )
    (source / "m1").write_bytes(MEMBER_ONE)
    (source / "m3").write_bytes(MEMBER_THREE)

    props = ndi_document("demoNDI").document_properties
    props["base"]["session_id"] = session.id()
    props["demoNDI"]["value"] = 1
    props["files"]["file_series"] = [SLOT]
    doc = ndi_document(props).add_file(SLOT, str(source / "manifest.bin"))
    doc.document_properties["files"]["series_info"] = [
        {
            "name": SLOT,
            "count": 3,
            "n_present": 2,
            "source_root": "",
            "ingest_locations": [
                {
                    "index": index,
                    "uid": member_uid(tag, index),
                    "location": str(source / path),
                    "location_type": "file",
                    "ingest": 1,
                    "delete_original": 0,
                    "parameters": "",
                }
                for index, path in ((1, "m1"), (3, "m3"))
            ],
        }
    ]
    session.database_add(doc)
    return doc


def _extracted(docs, doc):
    return next(d for d in docs if d.id == doc.id)


def _ingest_locations(doc):
    return doc.document_properties["files"]["series_info"][0].get("ingest_locations", [])


class TestOrdinaryFiles:
    def test_a_file_is_copied_under_its_uid(self, tmp_path):
        session = _session(tmp_path, "src_session")
        doc = _doc_with_a_plain_file(tmp_path, session)
        out = tmp_path / "out"

        docs, path = extract_doc_files(session, str(out))

        assert str(out) == path
        copies = [p for p in out.iterdir() if p.is_file()]
        assert len(copies) == 1
        assert copies[0].read_bytes() == PLAIN_BYTES

        locations = _extracted(docs, doc).document_properties["files"]["file_info"][0]["locations"]
        assert len(locations) == 1, "the extract also names the source database's path"
        assert locations[0]["location"] == str(copies[0])

    def test_the_file_list_is_read_before_file_info_is_cleared(self, tmp_path):
        """Clearing first leaves nothing to copy, silently.

        current_file_list reads file_info, so rebuilding file_info before
        reading it produces an extract of no files at all and a document
        claiming it has none -- which looks exactly like a document that
        never had any.
        """
        session = _session(tmp_path, "src_session")
        _doc_with_a_plain_file(tmp_path, session)
        out = tmp_path / "out"

        extract_doc_files(session, str(out))

        assert [p for p in out.iterdir() if p.is_file()], "nothing was copied"

    def test_a_document_with_no_files_is_left_alone(self, tmp_path):
        session = _session(tmp_path, "src_session")
        props = ndi_document("demoNDI").document_properties
        props["base"]["session_id"] = session.id()
        props["demoNDI"]["value"] = 1
        session.database_add(ndi_document(props))
        out = tmp_path / "out"

        docs, _ = extract_doc_files(session, str(out))

        assert docs
        assert not [p for p in out.iterdir() if p.is_file()]

    def test_a_temp_directory_is_made_when_none_is_given(self, tmp_path):
        import os
        import shutil

        session = _session(tmp_path, "src_session")
        _doc_with_a_plain_file(tmp_path, session)

        _docs, path = extract_doc_files(session)
        try:
            assert os.path.isdir(path)
            assert [p for p in os.scandir(path) if p.is_file()]
        finally:
            shutil.rmtree(path, ignore_errors=True)


class TestSeriesMembers:
    def test_the_members_are_copied_not_just_the_manifest(self, tmp_path, tag):
        session = _session(tmp_path, "src_session")
        _doc_with_a_sparse_series(tmp_path, session, tag)
        out = tmp_path / "out"

        extract_doc_files(session, str(out))

        names = {p.name for p in out.iterdir() if p.is_file()}
        assert member_uid(tag, 1) in names, "the series' members were not copied"
        assert member_uid(tag, 3) in names
        assert (out / member_uid(tag, 1)).read_bytes() == MEMBER_ONE
        assert (out / member_uid(tag, 3)).read_bytes() == MEMBER_THREE
        assert len(names) == 3, "the manifest itself must be copied too"

    def test_each_member_keeps_its_original_uid(self, tmp_path, tag):
        """A fresh uid would leave the copied manifest pointing at nothing.

        The manifest names its members by uid, and ingestion writes each to
        FileDir/<uid> from this record, so the two have to agree.
        """
        session = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, session, tag)
        out = tmp_path / "out"

        docs, _ = extract_doc_files(session, str(out))

        entries = _ingest_locations(_extracted(docs, doc))
        assert [e["uid"] for e in entries] == [member_uid(tag, 1), member_uid(tag, 3)]

    def test_a_sparse_series_keeps_its_slot_numbers(self, tmp_path, tag):
        """The gap at slot 2 must not renumber slot 3 to 2."""
        session = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, session, tag)
        out = tmp_path / "out"

        docs, _ = extract_doc_files(session, str(out))

        assert [e["index"] for e in _ingest_locations(_extracted(docs, doc))] == [1, 3]

    def test_the_members_are_recorded_for_ingestion_into_the_target(self, tmp_path, tag):
        """ingest=1, delete_original=0: the copies are the caller's, and the
        target database takes its own copy of them."""
        session = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, session, tag)
        out = tmp_path / "out"

        docs, _ = extract_doc_files(session, str(out))

        for entry in _ingest_locations(_extracted(docs, doc)):
            assert entry["ingest"] == 1
            assert entry["delete_original"] == 0
            assert entry["location_type"] == "file"
            assert entry["location"] == str(out / entry["uid"])

    def test_the_series_record_still_describes_the_series(self, tmp_path, tag):
        """count, n_present and source_root describe the SERIES, not where
        its bytes are, so they travel with the copied manifest. Dropping
        them would leave series_count contradicting the manifest beside it."""
        session = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, session, tag)
        out = tmp_path / "out"

        docs, _ = extract_doc_files(session, str(out))

        record = _extracted(docs, doc).document_properties["files"]["series_info"][0]
        assert record["name"] == SLOT
        assert record["count"] == 3
        assert record["n_present"] == 2


class TestTheExtractIsStorableElsewhere:
    """The contract the function exists for."""

    def test_a_copied_series_can_be_added_to_another_session(self, tmp_path, tag):
        source = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, source, tag)
        out = tmp_path / "out"
        docs, _ = extract_doc_files(source, str(out))

        target = _session(tmp_path, "target_session")
        extracted = _extracted(docs, doc)
        extracted.document_properties["base"]["session_id"] = target.id()

        target.database_add(extracted)  # DID's guard must not fire

    def test_the_members_read_back_in_the_target(self, tmp_path, tag):
        """End to end. Fails if the members were not copied, if their uids
        were not preserved, or if ingest_locations was never recorded."""
        source = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, source, tag)
        out = tmp_path / "out"
        docs, _ = extract_doc_files(source, str(out))

        target = _session(tmp_path, "target_session")
        extracted = _extracted(docs, doc)
        extracted.document_properties["base"]["session_id"] = target.id()
        target.database_add(extracted)

        assert target.database_openbinarydoc(extracted, f"{SLOT}_1").read() == MEMBER_ONE
        assert target.database_openbinarydoc(extracted, f"{SLOT}_3").read() == MEMBER_THREE

    def test_the_absent_slot_is_still_absent_in_the_target(self, tmp_path, tag):
        source = _session(tmp_path, "src_session")
        doc = _doc_with_a_sparse_series(tmp_path, source, tag)
        out = tmp_path / "out"
        docs, _ = extract_doc_files(source, str(out))

        target = _session(tmp_path, "target_session")
        extracted = _extracted(docs, doc)
        extracted.document_properties["base"]["session_id"] = target.id()
        target.database_add(extracted)

        exists, _path = target.database_existbinarydoc(extracted, f"{SLOT}_2")
        assert not exists
