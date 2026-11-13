"""Schema validation can be skipped on add; building a dataset from documents skips it.

Mirrors NDI-matlab#1240: ``ndi.database/add`` takes a ``'Validate'`` name/value
pair (default 1) that is passed to ``did.database/add_docs``, and
``ndi.dataset.dir(reference, path_name, docs)`` -- the path ``downloadDataset``
takes -- adds the documents with ``'Validate', false``. Those documents were
validated when they were first added; validating them again is slow for large
datasets and unnecessary.
"""

from unittest.mock import patch

import pytest

from ndi.document import ndi_document


def _subject_and_element():
    """An element and the subject it requires. Added alone, the element fails
    validation (dangling ``subject_id`` dependency), which makes the check
    observable."""
    subject = ndi_document("subject", **{"base.name": "s"})
    element = ndi_document(
        "element",
        **{"base.name": "e", "element.type": "probe", "element.reference": 1},
    )
    element = element.set_dependency_value("subject_id", subject.id)
    return subject, element


class TestValidateOption:
    def test_add_validates_by_default(self, tmp_path):
        from did.validate import ValidationError

        from ndi.database import ndi_database

        db = ndi_database(tmp_path)
        _subject, element = _subject_and_element()
        with pytest.raises(ValidationError):
            db.add(element)

    def test_add_with_validate_false_skips_validation(self, tmp_path):
        from ndi.database import ndi_database

        db = ndi_database(tmp_path)
        _subject, element = _subject_and_element()
        db.add(element, validate=False)
        assert db.read(element.id) is not None

    @pytest.mark.parametrize("validate", [True, False])
    def test_add_many_passes_validate_to_did(self, tmp_path, validate):
        from ndi.database import ndi_database

        db = ndi_database(tmp_path)
        subject, element = _subject_and_element()
        with patch.object(db._driver._db, "add_docs") as mock_add:
            db.add_many([element, subject], validate=validate)
        assert mock_add.call_args.kwargs.get("validate") is validate

    def test_add_many_validates_by_default(self, tmp_path):
        from ndi.database import ndi_database

        db = ndi_database(tmp_path)
        subject, element = _subject_and_element()
        with patch.object(db._driver._db, "add_docs") as mock_add:
            db.add_many([element, subject])
        assert mock_add.call_args.kwargs.get("validate") is True


class TestDatasetFromDocumentsSkipsValidation:
    def test_dataset_build_does_not_validate_documents(self, tmp_path):
        """The path downloadDataset takes: ndi_dataset_dir(..., documents=...)."""
        from did.database import Database

        from ndi.dataset import ndi_dataset_dir

        subject, element = _subject_and_element()
        target = tmp_path / "ds"
        target.mkdir()

        offered = {subject.id, element.id}
        validated_ids = set()
        original = Database.validate_docs

        def spy(self, document_objs, *args, **kwargs):
            for d in document_objs if isinstance(document_objs, list) else [document_objs]:
                props = getattr(d, "document_properties", d)
                validated_ids.add(props.get("base", {}).get("id", ""))
            return original(self, document_objs, *args, **kwargs)

        with patch.object(Database, "validate_docs", spy):
            dataset = ndi_dataset_dir("", target, documents=[element, subject])

        assert dataset.add_doc_failures == [], dataset.add_doc_failures
        assert not (validated_ids & offered), "downloaded documents were re-validated"
        stored = set(
            dataset._session._database._driver._db.get_doc_ids(
                dataset._session._database._driver._branch_id
            )
        )
        assert offered <= stored
