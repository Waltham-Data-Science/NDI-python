"""The downloaded-document-set report.

Exists because three readings of one CI failure each produced a different and
wrong story: that the cloud dataset was incomplete, that the download dropped
documents, and a completeness check that compared cloud ObjectIds against NDI
base.ids and declared every document missing. None of them was measurable from
what the pipeline printed.

The report answers the one question those readings kept guessing at -- is the
set internally complete? -- from the JSON alone, with no database and no add.
"""

from __future__ import annotations

from ndi.cloud.diagnostics import document_set_report


def _doc(doc_id, class_name, deps=None):
    out = {"base": {"id": doc_id}, "document_class": {"class_name": class_name}}
    if deps is not None:
        out["depends_on"] = deps
    return out


class TestComplete:
    def test_a_closed_set_says_so(self):
        docs = [
            _doc("a", "subject"),
            _doc("b", "element", [{"name": "subject_id", "value": "a"}]),
        ]
        report = document_set_report(docs)
        assert "every dependency resolves within the set." in report
        assert "pointing outside the set: 0" in report

    def test_counts_documents_and_classes(self):
        docs = [_doc("a", "subject"), _doc("b", "element"), _doc("c", "element")]
        report = document_set_report(docs)
        assert "documents:            3" in report
        assert "distinct base.id:     3" in report
        assert "2  element" in report


class TestDangling:
    def test_names_the_absent_target_and_who_refers_to_it(self):
        docs = [
            _doc("b", "element", [{"name": "subject_id", "value": "missing-1"}]),
            _doc("c", "element", [{"name": "subject_id", "value": "missing-1"}]),
        ]
        report = document_set_report(docs)
        assert "pointing outside the set: 2" in report
        assert "distinct absent targets:  1" in report
        assert "2  element.subject_id" in report
        assert "missing-1  <- element.subject_id" in report

    def test_a_bare_dict_depends_on_is_read(self):
        """MATLAB's jsonencode unwraps a one-element cell array."""
        docs = [_doc("b", "element", {"name": "subject_id", "value": "missing-1"})]
        report = document_set_report(docs)
        assert "pointing outside the set: 1" in report

    def test_empty_dependency_values_are_not_edges(self):
        """A blank slot is not a reference to anything."""
        docs = [_doc("b", "element", [{"name": "subject_id", "value": ""}])]
        report = document_set_report(docs)
        assert "dependency edges:     0" in report
        assert "every dependency resolves within the set." in report

    def test_resolution_is_case_insensitive(self):
        docs = [
            _doc("AAA", "subject"),
            _doc("b", "element", [{"name": "subject_id", "value": "aaa"}]),
        ]
        assert "every dependency resolves within the set." in document_set_report(docs)


class TestMalformed:
    def test_documents_without_an_id_are_counted_separately(self):
        docs = [_doc("a", "subject"), {"document_class": {"class_name": "orphan"}}]
        report = document_set_report(docs)
        assert "WITHOUT a base.id:    1" in report

    def test_duplicate_ids_are_reported(self):
        docs = [_doc("a", "subject"), _doc("a", "subject")]
        report = document_set_report(docs)
        assert "duplicate base.id:    1" in report

    def test_an_empty_set_does_not_raise(self):
        report = document_set_report([])
        assert "documents:            0" in report

    def test_junk_entries_do_not_raise(self):
        report = document_set_report([None, "nonsense", 42, _doc("a", "subject")])
        assert "documents:            4" in report
