"""NDI-python against the DID-python it actually installs.

DID-python grew a real document-vs-schema validator in August 2026
(``did.validate``), and ``did.database.add_docs`` runs it by default.  Nothing
in NDI-python asked for that; it arrived with the pinned dependency.  Two
consequences are pinned here:

* NDI's ``$NDI...PATH`` placeholders have to be registered with DID or *every*
  document add fails.  MATLAB has always registered them
  (``ndi.common.PathConstants.updateDIDConstants``); Python did not.
* Documents NDI itself creates now have to satisfy their own schemas.  The
  bundled definitions that do not are listed, with reasons, rather than
  discovered one at a time by whoever next adds one.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from ndi import ndi_ido, ndi_query
from ndi.common import (
    _DID_PLACEHOLDERS,
    ndi_common_PathConstants,
    updateDIDConstants,
)
from ndi.document import ndi_document

# ---------------------------------------------------------------------------
# $PATH placeholder registration
# ---------------------------------------------------------------------------


class TestDIDPathConstants:
    """ndi.common registers NDI's placeholders with did.common.PathConstants."""

    def test_all_placeholders_registered_on_import(self):
        from did.common import PathConstants

        for key in _DID_PLACEHOLDERS:
            assert key in PathConstants.DEFINITIONS, f"{key} not registered with DID"

    def test_placeholders_resolve_to_real_directories(self):
        from did.common import PathConstants

        for key in _DID_PLACEHOLDERS:
            target = Path(str(PathConstants.DEFINITIONS[key]))
            assert target.is_dir(), f"{key} -> {target} is not a directory"

    def test_document_and_schema_placeholders_point_where_ndi_keeps_them(self):
        from did.common import PathConstants

        definitions = PathConstants.DEFINITIONS
        assert Path(definitions["$NDIDOCUMENTPATH"]) == Path(
            str(ndi_common_PathConstants.DOCUMENT_PATH)
        )
        assert Path(definitions["$NDISCHEMAPATH"]) == Path(
            str(ndi_common_PathConstants.SCHEMA_PATH)
        )

    def test_calc_placeholders_share_the_main_tree(self):
        """ndi_install.py merges dependency ndi_common trees into NDI's own.

        MATLAB keeps calculator toolboxes separate and registers a list of
        directories; Python has one tree, so the calc placeholders resolve to
        the same two directories.  Pinned so the divergence is deliberate.
        """
        from did.common import PathConstants

        definitions = PathConstants.DEFINITIONS
        assert definitions["$NDICALCDOCUMENTPATH"] == definitions["$NDIDOCUMENTPATH"]
        assert definitions["$NDICALCSCHEMAPATH"] == definitions["$NDISCHEMAPATH"]

    def test_registration_does_not_clobber_an_existing_entry(self):
        """MATLAB only fills in keys that are absent; so does this."""
        from did.common import PathConstants

        definitions = PathConstants.DEFINITIONS
        original = definitions["$NDIDOCUMENTPATH"]
        definitions["$NDIDOCUMENTPATH"] = "/somewhere/an/embedder/chose"
        try:
            updateDIDConstants()
            assert definitions["$NDIDOCUMENTPATH"] == "/somewhere/an/embedder/chose"
            updateDIDConstants(force=True)
            assert definitions["$NDIDOCUMENTPATH"] == original
        finally:
            definitions["$NDIDOCUMENTPATH"] = original

    def test_did_resolves_an_ndi_schema_through_the_placeholder(self):
        """The failure this all exists to prevent, at its source."""
        from did.validate import get_document_schema

        schema = get_document_schema("$NDISCHEMAPATH/session.json")
        assert schema["classname"] == "session"


# ---------------------------------------------------------------------------
# Documents NDI creates survive the round trip
# ---------------------------------------------------------------------------


class TestValidatedAdd:
    """add_docs validates now; NDI's own documents must pass."""

    def test_session_document_can_be_added(self, tmp_path):
        from ndi.session.dir import ndi_session_dir

        session_dir = tmp_path / "session"
        session_dir.mkdir()
        session = ndi_session_dir("validated_add", session_dir)
        doc = session.newdocument("base")
        session.database_add(doc)
        assert session.database_search(ndi_query("base.id") == doc.id)

    def test_a_document_that_lies_about_its_class_is_rejected(self):
        """The gate is real: a document with no property_list_name fails."""
        import tempfile

        from did.document import Document
        from did.implementations.sqlitedb import SQLiteDB
        from did.validate import ValidationError

        with tempfile.TemporaryDirectory() as tmp:
            db = SQLiteDB(str(Path(tmp) / "did.sqlite"))
            db.add_branch("a", "")
            props = {
                "document_class": {"class_name": "base", "superclasses": []},
                "base": {
                    "id": ndi_ido().id,
                    "session_id": "",
                    "name": "n",
                    "datestamp": "2026-01-01T00:00:00.000Z",
                },
            }
            with pytest.raises(ValidationError):
                db.add_docs([Document(props)], "a")


# ---------------------------------------------------------------------------
# Which bundled definitions do not validate, and why
# ---------------------------------------------------------------------------

#: Document types whose *blank* form does not satisfy its own schema, mapped to
#: the DID error identifier each raises.  Every entry is a defect in the shared
#: ``ndi_common`` JSON -- NDI-matlab and NDI-python carry the same bytes -- not
#: something NDI-python introduced, and every one is reported upstream in
#: docs/developer_notes/DEPENDENCY_DRIFT_2026-08.md.  Two groups:
#:
#: * ``ValidationField*`` -- the blank template seeds a value its own schema
#:   rejects: ``""`` where a ``double`` is declared, ``[]`` where a matrix
#:   schema declares dimensions.  Same family as the open ``t0_t1``
#:   orientation question, and it needs one answer for the whole family:
#:   either the templates carry schema-valid defaults, or the schemas allow
#:   empty (a fourth ``parameters`` entry).
#: * ``PropertyFieldMissing`` -- the five vhlab_voltage2firingrate schemas are
#:   JSON-Schema draft-2019-09 documents, not DID schema documents.  They have
#:   never been ported to the DID schema format.
#:
#: A type that starts validating must be deleted from this list; the test says
#: so by name.  A type that stops validating fails the test.
KNOWN_UNVALIDATABLE_DEFINITIONS = {
    "apps/vhlab_voltage2firingrate/binnedspikeratevm": "DID:Database:PropertyFieldMissing",
    "apps/vhlab_voltage2firingrate/vmneuralresponseresiduals": "DID:Database:PropertyFieldMissing",
    "apps/vhlab_voltage2firingrate/vmspikefilteringparameters": "DID:Database:PropertyFieldMissing",
    "apps/vhlab_voltage2firingrate/vmspikefit": "DID:Database:PropertyFieldMissing",
    "apps/vhlab_voltage2firingrate/vmspikesummary": "DID:Database:PropertyFieldMissing",
    "data/binaryseries_parameters": "DID:Database:ValidationFieldInteger",
    "data/generic_file": "DID:Database:ValidationFieldDouble",
    "data/image": "DID:Database:ValidationFieldMatrix",
    "data/imageStack": "DID:Database:ValidationFieldMatrix",
    "data/imageStack_parameters": "DID:Database:ValidationFieldMatrix",
    "data/ngrid": "DID:Database:ValidationFieldInteger",
    "data/ontologyImage": "DID:Database:ValidationFieldInteger",
    "demoNDI": "DID:Database:ValidationFieldInteger",
    "epochclocktimes": "DID:Database:ValidationFieldMatrix",
    "mock/demoNDIMock": "DID:Database:ValidationFieldInteger",
    "session_in_a_dataset": "DID:Database:ValidationFieldDouble",
}

#: A blank template legitimately leaves required dependencies empty -- the
#: document that fills them in is the one that gets stored -- so these two
#: identifiers say nothing about the definition's structure.
_BLANK_TEMPLATE_IDENTIFIERS = frozenset(
    {"DID:Database:ValidationDependEmpty", "DID:Database:ValidationDependency"}
)


def _bundled_document_types():
    root = Path(str(ndi_common_PathConstants.DOCUMENT_PATH))
    for path in sorted(root.rglob("*.json")):
        try:
            raw = json.loads(path.read_text())
        except ValueError:
            continue
        document_class = raw.get("document_class")
        if not isinstance(document_class, dict) or not document_class.get("validation"):
            continue
        yield str(path.relative_to(root)).replace(".json", ""), path


def _structural_failure(doc_type):
    """Validate a blank document of ``doc_type``; return an error id or None."""
    from did.validate import ValidationError, get_document_schema, validate_doc_vs_schema

    doc = ndi_document(doc_type)
    props = doc.document_properties
    doc_id = props["base"]["id"]
    session_id = ndi_ido().id
    props["base"]["session_id"] = session_id
    try:
        schema = get_document_schema(props["document_class"]["validation"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            validate_doc_vs_schema(props, schema, [doc_id.lower(), session_id.lower()])
    except ValidationError as exc:
        if exc.identifier in _BLANK_TEMPLATE_IDENTIFIERS:
            return None
        return exc.identifier
    return None


class TestBundledDefinitions:
    """Every bundled definition parses, resolves, and validates -- or is listed."""

    def test_every_bundled_json_parses(self):
        root = Path(str(ndi_common_PathConstants.COMMON_FOLDER))
        unparseable = []
        for path in sorted(root.rglob("*.json")):
            try:
                json.loads(path.read_text())
            except ValueError as exc:
                unparseable.append(f"{path.relative_to(root)}: {exc}")
        assert not unparseable, "unparseable JSON in ndi_common:\n" + "\n".join(unparseable)

    def test_definitions_validate_or_are_listed(self):
        newly_broken = {}
        newly_fixed = []
        for doc_type, _path in _bundled_document_types():
            identifier = _structural_failure(doc_type)
            expected = KNOWN_UNVALIDATABLE_DEFINITIONS.get(doc_type)
            if identifier and not expected:
                newly_broken[doc_type] = identifier
            elif identifier and expected and identifier != expected:
                newly_broken[doc_type] = f"{identifier} (listed as {expected})"
            elif expected and not identifier:
                newly_fixed.append(doc_type)

        assert not newly_broken, (
            "document definitions that no longer validate against their own "
            "schemas:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(newly_broken.items()))
        )
        assert not newly_fixed, (
            "these definitions now validate -- delete them from "
            "KNOWN_UNVALIDATABLE_DEFINITIONS in this file:\n"
            + "\n".join(f"  {t}" for t in sorted(newly_fixed))
        )

    def test_listed_entries_still_exist(self):
        """A renamed or deleted definition must not linger in the list."""
        present = {t for t, _ in _bundled_document_types()}
        stale = sorted(set(KNOWN_UNVALIDATABLE_DEFINITIONS) - present)
        assert not stale, (
            "KNOWN_UNVALIDATABLE_DEFINITIONS names definitions that no longer "
            "exist: " + ", ".join(stale)
        )


# ---------------------------------------------------------------------------
# Upstream tripwire
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Upstream DID-python bug: sqlitedb gained a 'files' table with "
        "FOREIGN KEY(doc_idx) REFERENCES docs(doc_idx) (commit 9997412), but "
        "_do_remove_doc still deletes only doc_data and docs, so removing any "
        "document that carries a file raises sqlite3.IntegrityError. Reported "
        "upstream; when DID fixes it this test passes and the marker goes."
    ),
)
def test_removing_a_file_bearing_document(tmp_path):
    """NDI cannot delete a document with a binary file attached.

    This is not an NDI defect and there is no NDI-side fix -- the missing
    DELETE is inside DID's own SQLite driver.  Held as a strict xfail so the
    day DID repairs it, CI says so instead of staying quietly red.
    """
    from ndi.session.dir import ndi_session_dir

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    session = ndi_session_dir("file_bearing", session_dir)

    payload = tmp_path / "generic_file.ext"
    payload.write_bytes(b"payload")

    doc = session.newdocument("data/generic_file")
    doc.document_properties["generic_file"]["dateCreated"] = 0
    doc.document_properties["generic_file"]["dateUpdated"] = 0
    doc.document_properties["files"] = {
        "file_list": ["generic_file.ext"],
        "file_info": [
            {
                "name": "generic_file.ext",
                "locations": [
                    {
                        "uid": ndi_ido().id,
                        "location": str(payload),
                        "location_type": "file",
                        "ingest": 0,
                        "delete_original": 0,
                    }
                ],
            }
        ],
    }
    session.database_add(doc)
    session.database_rm(doc)
