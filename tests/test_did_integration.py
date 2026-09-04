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
    # Its blank decimation vectors are [], which reads as 0x0 against a
    # schema shape of [1 NaN] -- the same thing epochclocktimes below is
    # listed for, and pyraview inherits epochclocktimes. Copied byte for byte
    # from NDI-matlab, so it is recorded rather than edited: a definition that
    # differed between the ports would be worse than one that fails its own
    # schema in both.
    "data/pyraview": "DID:Database:ValidationFieldMatrix",
    "demoNDI": "DID:Database:ValidationFieldInteger",
    "epochclocktimes": "DID:Database:ValidationFieldMatrix",
    "mock/demoNDIMock": "DID:Database:ValidationFieldInteger",
    "session_in_a_dataset": "DID:Database:ValidationFieldDouble",
}

#: The same, for definitions ndi_install.py copies in from NDIcalc-vis-matlab.
#: Kept separate because they are absent on a bare checkout, so their existence
#: is not asserted -- only their behaviour when they are installed. Both were
#: named by NDI-matlab's own sweep (854a658) before this repo could see them.
KNOWN_UNVALIDATABLE_FROM_DEPENDENCIES = {
    # Inherits ngrid, which its schema omits.
    "neuro/hartley_reverse_correlation": "DID:Database:ValidationSuperClasses",
    "neuro/reverse_correlation": "DID:Database:ValidationFieldInteger",
}

#: Files that are not valid JSON and cannot be fixed from this repository.
#: stimloopsplitter_calc_schema.json is missing the opening quote of a value
#: (line 5), so stimloopsplitter_calc ships with no loadable schema in either
#: language. Broken at NDIcalc-vis-matlab's only tag (v0.9.0) *and* at its
#: default-branch head, so no pin bump fixes it -- it needs a one-character
#: change upstream. Quarantined, not suppressed: the test below fails if the
#: file ever parses, so the entry cannot rot.
KNOWN_BAD_UPSTREAM_JSON = {
    "schema_documents/calc/stimloopsplitter_calc_schema.json",
}

#: A blank template legitimately leaves required dependencies empty -- the
#: document that fills them in is the one that gets stored -- so these two
#: identifiers say nothing about the definition's structure.
_BLANK_TEMPLATE_IDENTIFIERS = frozenset(
    {"DID:Database:ValidationDependEmpty", "DID:Database:ValidationDependency"}
)


def _loads_as_matlab_reads(text):
    """``json.loads`` as MATLAB reads it: bare ``Inf`` / ``-Inf`` allowed.

    MATLAB's ``jsondecode`` accepts those tokens and definition files use them
    (``"parameters": [-Inf,Inf,0]`` for a double with no bounds). DID does the
    widening in ``did.validate.loads_matlab_json`` (VH-Lab/DID-python#40); this
    calls it so the gate measures the files by the same rule the reader uses.
    """
    from did.validate import loads_matlab_json

    return loads_matlab_json(text)


def _bundled_document_types():
    root = Path(str(ndi_common_PathConstants.DOCUMENT_PATH))
    for path in sorted(root.rglob("*.json")):
        try:
            raw = _loads_as_matlab_reads(path.read_text())
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
        """Every bundled file parses the way the languages actually read it.

        Not ``json.loads``: MATLAB's ``jsondecode`` accepts the bare tokens
        ``Inf``, ``-Inf`` and ``NaN``, and definition files written against it
        use them -- ``simple_calc_schema.json`` and
        ``valid_interval_schema.json`` declare ``"parameters": [-Inf,Inf,0]``
        for a double with no bounds. Those files are correct; NDI-matlab's own
        suite validates a simple_calc document against one of them. It was
        Python's stricter parser that had to catch up, which it now does in
        ``did.validate.loads_matlab_json``.

        Files the dependency trees supply are scanned too, so this only checks
        what is actually installed -- a machine where ``ndi_install.py`` has not
        run sees a smaller bundle than CI does.
        """
        root = Path(str(ndi_common_PathConstants.COMMON_FOLDER))
        unparseable = []
        still_bad = set()
        for path in sorted(root.rglob("*.json")):
            relative = str(path.relative_to(root))
            try:
                _loads_as_matlab_reads(path.read_text())
            except ValueError as exc:
                if relative in KNOWN_BAD_UPSTREAM_JSON:
                    still_bad.add(relative)
                    continue
                unparseable.append(f"{relative}: {exc}")
            else:
                if relative in KNOWN_BAD_UPSTREAM_JSON:
                    raise AssertionError(
                        f"{relative} parses now -- delete it from "
                        "KNOWN_BAD_UPSTREAM_JSON in this file."
                    )
        assert not unparseable, "unparseable JSON in ndi_common:\n" + "\n".join(unparseable)

    def test_definitions_validate_or_are_listed(self):
        newly_broken = {}
        newly_fixed = []
        for doc_type, _path in _bundled_document_types():
            identifier = _structural_failure(doc_type)
            expected = KNOWN_UNVALIDATABLE_DEFINITIONS.get(
                doc_type
            ) or KNOWN_UNVALIDATABLE_FROM_DEPENDENCIES.get(doc_type)
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
            "these definitions now validate -- delete them from the "
            "KNOWN_UNVALIDATABLE_* list in this file:\n"
            + "\n".join(f"  {t}" for t in sorted(newly_fixed))
        )

    def test_listed_entries_still_exist(self):
        """A renamed or deleted definition must not linger in the list.

        Only NDI's own tree is checked. The dependency-supplied list is not:
        those files are absent until ``ndi_install.py`` copies them in, and a
        bare checkout must not fail for that.
        """
        present = {t for t, _ in _bundled_document_types()}
        stale = sorted(set(KNOWN_UNVALIDATABLE_DEFINITIONS) - present)
        assert not stale, (
            "KNOWN_UNVALIDATABLE_DEFINITIONS names definitions that no longer "
            "exist: " + ", ".join(stale)
        )


# ---------------------------------------------------------------------------
# Upstream tripwire
# ---------------------------------------------------------------------------


def test_removing_a_file_bearing_document(tmp_path):
    """A document with a binary attached can be removed again.

    DID's sqlitedb grew a ``files`` table with
    ``FOREIGN KEY(doc_idx) REFERENCES docs(doc_idx)`` while ``_do_remove_doc``
    still deleted only ``doc_data`` and ``docs``, so every document carrying a
    file was un-removable (``sqlite3.IntegrityError``).  Fixed upstream in
    VH-Lab/DID-python#39; kept here as the NDI-side regression, since
    ``session.database_rm`` is where it surfaced.
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

    assert session.database_search(ndi_query("base.id") == doc.id) == []


# ---------------------------------------------------------------------------
# Documents that refer to one another have to be offered together
# ---------------------------------------------------------------------------


class TestBatchAdd:
    """A set of documents is added in one call, as MATLAB does.

    ``did.database.validate_docs`` checks each dependency against "the superset
    of document ids already in the database and those in this batch, so a batch
    may depend on itself".  Adding one document at a time shrinks that batch to
    one, so anything referring to a document later in the list is judged to have
    a dangling dependency and is rejected.

    MATLAB hands the whole set over at once -- ``ndi.dataset.dir(reference,
    path_name, docs)`` -> ``add_docs(docs)`` -- so this never arose there.
    """

    def _subject_and_element(self):
        """An element and the subject it requires. ``subject_id`` is declared
        ``mustbenotempty``, so its value really is checked against the batch."""
        subject = ndi_document("subject", **{"base.name": "s"})
        element = ndi_document(
            "element",
            **{"base.name": "e", "element.type": "probe", "element.reference": 1},
        )
        element = element.set_dependency_value("subject_id", subject.id)
        return subject, element

    def test_dependent_document_first_is_rejected_one_at_a_time(self, tmp_path):
        """The failure this exists to prevent, at its source."""
        from did.validate import ValidationError

        from ndi.database import ndi_database

        db = ndi_database(tmp_path)
        _subject, element = self._subject_and_element()
        with pytest.raises(ValidationError):
            db.add(element)

    def test_the_same_pair_added_as_one_batch_is_accepted(self, tmp_path):
        from ndi.database import ndi_database

        db = ndi_database(tmp_path)
        subject, element = self._subject_and_element()

        # Dependent document first: order within the batch must not matter.
        db.add_many([element, subject])

        assert db.numdocs() == 2
        assert db.read(element.id) is not None
        assert db.read(subject.id) is not None

    def test_a_dataset_built_from_such_documents_keeps_them_all(self, tmp_path):
        """The path downloadDataset takes: ndi_dataset_dir(..., documents=...)."""
        from ndi.dataset import ndi_dataset_dir

        subject, element = self._subject_and_element()
        target = tmp_path / "ds"
        target.mkdir()
        dataset = ndi_dataset_dir("", target, documents=[element, subject])

        assert dataset.add_doc_failures == [], dataset.add_doc_failures
        stored = set(
            dataset._session._database._driver._db.get_doc_ids(
                dataset._session._database._driver._branch_id
            )
        )
        assert {element.id, subject.id} <= stored
