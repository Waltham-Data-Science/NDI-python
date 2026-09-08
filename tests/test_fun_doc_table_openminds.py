"""``ndi.fun.doc_table.openminds`` against ``+ndi/+fun/+docTable/openminds.m``.

WHAT WAS WRONG, in four ways at once.

``type`` is an openMINDS TYPE, matched against
``document_properties.openminds.openminds_type`` as
``https://openminds.om-i.org/types/<type>``. The port ran ``isa(type)`` --
an isa query for a document class literally named e.g. ``"Strain"`` -- so it
selected the wrong documents, usually none.

It then read the row from ``props[type]`` rather than
``props["openminds"]["fields"]``, so every row came back holding nothing but
an ``id`` column, where MATLAB builds ``<type>Name`` and ``<type>Ontology``.

``depends_on``, ``depends_on_docs`` and ``allOpenMindsDocs`` were accepted
as parameters and never read, so MATLAB's optimised path -- filter the
pre-fetched documents by type and then by dependency -- did not exist.

And the third output took the FIRST entry of ``depends_on`` rather than the
one ``depends_on`` names, so it returned another document's id whenever a
document had more than one dependency.

NOT PORTED, AND RECORDED RATHER THAN INVENTED: MATLAB additionally walks
each openMINDS field that holds NDI document references, resolves those
documents, and adds a ``<FieldName>Name`` / ``<FieldName>Ontology`` column
pair for each. That expansion is what fills in a Strain's species and
background strains. It needs real linked documents to get right and is
noted on the bridge entry instead.
"""

from __future__ import annotations

from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from ndi.fun.doc_table import OPENMINDS_TYPE_URL_PREFIX, openminds  # noqa: E402


class FakeDoc:
    def __init__(self, props: dict[str, Any]):
        self.document_properties = props


class FakeSession:
    def __init__(self, docs: list[FakeDoc]):
        self.docs = docs

    def database_search(self, query: Any) -> list[FakeDoc]:
        return self.docs


def om_doc(doc_id: str, om_type: str, name: str, ontology: str, subject: str) -> FakeDoc:
    return FakeDoc(
        {
            "base": {"id": doc_id},
            "openminds": {
                "openminds_type": f"{OPENMINDS_TYPE_URL_PREFIX}{om_type}",
                "fields": {"name": name, "preferredOntologyIdentifier": ontology},
            },
            # Two dependencies, the wanted one second on purpose.
            "depends_on": [
                {"name": "other_id", "value": "not-the-one"},
                {"name": "subject_id", "value": subject},
            ],
        }
    )


DOCS = [
    om_doc("om1", "Strain", "N2", "RRID:WB-STRAIN:N2", "s1"),
    om_doc("om2", "Species", "Caenorhabditis elegans", "NCBITaxon:6239", "s1"),
]


class TestSelectionByOpenmindsType:
    def test_documents_are_selected_by_their_openminds_type(self):
        table, doc_ids, _ = openminds(FakeSession(DOCS), "Strain")
        assert doc_ids == ["om1"]
        assert len(table) == 1

    def test_a_different_type_selects_the_other_document(self):
        _, doc_ids, _ = openminds(FakeSession(DOCS), "Species")
        assert doc_ids == ["om2"]

    def test_an_absent_type_gives_an_empty_result(self):
        table, doc_ids, dep_ids = openminds(FakeSession(DOCS), "Nope")
        assert table.empty and doc_ids == [] and dep_ids == []

    def test_error_if_empty_is_honoured(self):
        """MATLAB: error('No documents of type "%s" were found.', type)."""
        with pytest.raises(ValueError, match='No documents of type "Nope"'):
            openminds(FakeSession(DOCS), "Nope", errorIfEmpty=True)


class TestTheColumns:
    def test_the_table_carries_matlabs_two_columns(self):
        """MATLAB: openMINDsRow.([type,'Name']) and ([type,'Ontology'])."""
        table, _, _ = openminds(FakeSession(DOCS), "Strain")
        assert list(table.columns) == ["StrainName", "StrainOntology"]

    def test_the_values_come_from_the_openminds_fields(self):
        table, _, _ = openminds(FakeSession(DOCS), "Strain")
        assert table.iloc[0]["StrainName"] == "N2"
        assert table.iloc[0]["StrainOntology"] == "RRID:WB-STRAIN:N2"

    def test_the_ontology_column_finds_any_ontology_named_field(self):
        """MATLAB picks the field whose name contains 'ontology', ignoring
        case, rather than a fixed key."""
        doc = FakeDoc(
            {
                "base": {"id": "x"},
                "openminds": {
                    "openminds_type": f"{OPENMINDS_TYPE_URL_PREFIX}Strain",
                    "fields": {"name": "n", "ontologyIdentifier": "ONT:1"},
                },
                "depends_on": [],
            }
        )
        table, _, _ = openminds(FakeSession([doc]), "Strain")
        assert table.iloc[0]["StrainOntology"] == "ONT:1"


class TestTheDependencyOutput:
    def test_it_returns_the_named_dependency_not_the_first(self):
        """The regression: with two dependencies it returned the first."""
        _, _, dep_ids = openminds(FakeSession(DOCS), "Strain", depends_on="subject_id")
        assert dep_ids == ["s1"]

    def test_it_is_empty_when_no_dependency_is_named(self):
        _, _, dep_ids = openminds(FakeSession(DOCS), "Strain")
        assert dep_ids == [""]

    def test_a_list_of_one_is_accepted(self):
        _, _, dep_ids = openminds(FakeSession(DOCS), "Strain", depends_on=["subject_id"])
        assert dep_ids == ["s1"]

    def test_more_than_one_dependency_name_is_refused(self):
        """MATLAB: error('depends_on must be a single string.')."""
        with pytest.raises(ValueError, match="must be a single string"):
            openminds(FakeSession(DOCS), "Strain", depends_on=["a", "b"])


class TestThePrefetchedPath:
    """MATLAB's optimised branch: filter the pre-fetched lists, no new query."""

    def test_it_filters_by_type_and_by_dependency(self):
        subjects = [FakeDoc({"base": {"id": "s1"}})]
        # The session would return nothing; everything comes from the lists.
        table, doc_ids, dep_ids = openminds(
            FakeSession([]),
            "Strain",
            depends_on="subject_id",
            depends_on_docs=subjects,
            allOpenMindsDocs=DOCS,
        )
        assert doc_ids == ["om1"]
        assert dep_ids == ["s1"]
        assert table.iloc[0]["StrainName"] == "N2"

    def test_a_document_depending_on_something_else_is_excluded(self):
        others = [FakeDoc({"base": {"id": "different"}})]
        table, doc_ids, _ = openminds(
            FakeSession([]),
            "Strain",
            depends_on="subject_id",
            depends_on_docs=others,
            allOpenMindsDocs=DOCS,
        )
        assert doc_ids == []
        assert table.empty
