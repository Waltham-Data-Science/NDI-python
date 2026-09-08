"""ndi.fun.doc / .epoch / .probe against MATLAB.

Three of these wrote or read a field that does not exist:

* ``probeLocations4probes`` wrote ``probe_location.ontology``; the schema
  declares ``ontology_name``.
* ``epochid2element`` read ``element.epoch_table``, which appears in no
  document schema and which nothing writes, and filtered on
  ``document_class.class_list``, which element documents do not have.
* ``makeSpeciesStrainSex`` used a failed ontology lookup's INPUT as the
  resolved identifier, and dropped a strain's identifier entirely.
"""

from __future__ import annotations

import warnings
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest

from ndi.fun.doc import BIOLOGICAL_SEX_TERMS, makeSpeciesStrainSex, probeLocations4probes
from ndi.fun.epoch import epochid2element


class term(NamedTuple):
    """Stands in for ndi.ontology.OntologyResult.

    It has to be BOTH unpackable and attribute-accessible: makeSpeciesStrainSex
    does ``ont_id, name, *_ = lookup(...)`` while probeLocations4probes reads
    ``.id`` and ``.prefix``.
    """

    id: str
    name: str
    prefix: str


def probe(identifier="probe_1"):
    p = MagicMock()
    p.id = identifier
    p.probestring.return_value = f"probe|{identifier}"
    return p


@pytest.fixture
def session():
    s = MagicMock()
    s.id.return_value = "sess_1"
    return s


class TestProbeLocationsFieldName:
    """The schema declares probe_location.ontology_name."""

    def test_the_schema_field_is_written(self, session, monkeypatch):
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: term("0000411", "V1", "UBERON"))
        docs = probeLocations4probes(session, [probe()], ["UBERON:0000411"], doAdd=False)
        assert docs[0].document_properties["probe_location"] == {
            "ontology_name": "UBERON:0000411",
            "name": "V1",
        }

    def test_the_old_field_is_gone(self, session, monkeypatch):
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: term("0000411", "V1", "UBERON"))
        docs = probeLocations4probes(session, [probe()], ["UBERON:0000411"], doAdd=False)
        assert "ontology" not in docs[0].document_properties["probe_location"]

    def test_an_id_that_already_carries_its_prefix_is_not_doubled(self, session, monkeypatch):
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: term("UBERON:0000411", "V1", "UBERON"))
        docs = probeLocations4probes(session, [probe()], ["UBERON:0000411"], doAdd=False)
        assert docs[0].document_properties["probe_location"]["ontology_name"] == "UBERON:0000411"

    def test_the_probe_dependency_is_set(self, session, monkeypatch):
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: term("0000411", "V1", "UBERON"))
        docs = probeLocations4probes(session, [probe("p9")], ["UBERON:0000411"], doAdd=False)
        deps = {d["name"]: d["value"] for d in docs[0].document_properties["depends_on"]}
        assert deps["probe_id"] == "p9"


class TestProbeLocationsCounting:
    def test_mismatched_lengths_raise(self, session):
        # zip() silently truncated to the shorter list.
        with pytest.raises(ValueError, match="must match"):
            probeLocations4probes(session, [probe(), probe("p2")], ["UBERON:1"], doAdd=False)

    def test_a_failed_lookup_warns_and_skips_that_probe(self, session, monkeypatch):
        def boom(s):
            raise RuntimeError("no such term")

        monkeypatch.setattr("ndi.ontology.lookup", boom)
        with pytest.warns(UserWarning, match="Skipping probe"):
            docs = probeLocations4probes(session, [probe()], ["NOPE:1"], doAdd=False)
        assert docs == []

    def test_the_documents_are_added_in_one_call(self, session, monkeypatch):
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: term("1", "V1", "UBERON"))
        docs = probeLocations4probes(
            session, [probe("a"), probe("b")], ["UBERON:1", "UBERON:2"], doAdd=True
        )
        session.database_add.assert_called_once_with(docs)

    def test_a_failing_add_reaches_the_caller(self, session, monkeypatch):
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: term("1", "V1", "UBERON"))
        session.database_add.side_effect = RuntimeError("database is read-only")
        with pytest.raises(RuntimeError, match="read-only"):
            probeLocations4probes(session, [probe()], ["UBERON:1"])


class TestEpochId2Element:
    """MATLAB asks the ELEMENT for its epochtable()."""

    @staticmethod
    def _element(epoch_ids):
        element = MagicMock()
        element.epochtable.return_value = ([{"epoch_id": e} for e in epoch_ids], "")
        return element

    def test_it_reads_the_live_epoch_table(self, session):
        element = self._element(["t00001"])
        session.getelements.return_value = [element]
        assert epochid2element(session, ["t00001"]) == {"t00001": [element]}

    def test_element_epoch_table_is_not_a_real_field(self):
        # The old implementation read props['element']['epoch_table'].
        from ndi.document import ndi_document

        assert "epoch_table" not in ndi_document("element").document_properties["element"]

    def test_the_filters_are_passed_to_getelements(self, session):
        session.getelements.return_value = []
        with pytest.warns(UserWarning):
            epochid2element(session, ["e"], element_name="probe1", element_type="spikes")
        session.getelements.assert_called_once_with(
            **{"element.name": "probe1", "element.type": "spikes"}
        )

    def test_no_filters_means_no_arguments(self, session):
        session.getelements.return_value = []
        with pytest.warns(UserWarning):
            epochid2element(session, ["e"])
        session.getelements.assert_called_once_with()

    def test_a_missing_epoch_id_warns(self, session):
        session.getelements.return_value = []
        with pytest.warns(UserWarning, match="nowhere"):
            result = epochid2element(session, ["nowhere"])
        assert result["nowhere"] == []

    def test_an_element_whose_table_cannot_be_read_is_skipped(self, session):
        broken = MagicMock()
        broken.epochtable.side_effect = RuntimeError("no epoch files")
        good = self._element(["t1"])
        session.getelements.return_value = [broken, good]
        assert epochid2element(session, ["t1"]) == {"t1": [good]}

    def test_an_element_is_listed_once_per_epoch_id(self, session):
        element = self._element(["t1", "t1"])
        session.getelements.return_value = [element]
        assert epochid2element(session, ["t1"]) == {"t1": [element]}


class TestMakeSpeciesStrainSex:
    def test_the_four_matlab_terms_are_the_accepted_ones(self):
        assert set(BIOLOGICAL_SEX_TERMS) == {
            "male",
            "female",
            "hermaphrodite",
            "notDetectable",
        }

    def test_an_unknown_biological_sex_is_rejected(self, session):
        # MATLAB's mustBeMember rejects it; this made a document out of it.
        with pytest.raises(ValueError, match="BiologicalSex must be one of"):
            makeSpeciesStrainSex(session, "subj_1", BiologicalSex="unspecified")

    def test_notDetectable_is_accepted(self, session):
        pytest.importorskip("openminds")
        docs = makeSpeciesStrainSex(session, "subj_1", BiologicalSex="notDetectable")
        assert len(docs) == 1

    def test_a_failed_species_lookup_warns_but_keeps_the_name(self, session, monkeypatch):
        pytest.importorskip("openminds")

        def boom(s):
            raise RuntimeError("not in ontology")

        monkeypatch.setattr("ndi.ontology.lookup", boom)
        with pytest.warns(UserWarning, match="Could not look up ontology term for species"):
            docs = makeSpeciesStrainSex(session, "subj_1", Species="Mus musculus")
        assert len(docs) == 1
        fields = docs[0].document_properties["openminds"]["fields"]
        assert fields["name"] == "Mus musculus"
        # The identifier used to be filled in with the name itself.
        assert not fields.get("preferred_ontology_identifier")

    def test_a_strain_carries_its_ontology_identifier(self, session, monkeypatch):
        pytest.importorskip("openminds")
        terms = {
            "NCBITaxon:10090": term("NCBITaxon:10090", "Mus musculus", "NCBITaxon"),
            "RRID:IMSR_JAX:000664": term("RRID:IMSR_JAX:000664", "C57BL/6J", "RRID"),
        }
        monkeypatch.setattr("ndi.ontology.lookup", lambda s: terms[s])

        docs = makeSpeciesStrainSex(
            session,
            "subj_1",
            Species="NCBITaxon:10090",
            Strain="RRID:IMSR_JAX:000664",
        )
        strain = [
            d
            for d in docs
            if d.document_properties["openminds"]["fields"].get("name") == "C57BL/6J"
        ]
        assert len(strain) == 1
        fields = strain[0].document_properties["openminds"]["fields"]
        # MATLAB passes 'ontologyIdentifier', ID; this dropped it entirely.
        # (The Python openminds serialisation spells the field snake_case.)
        assert fields.get("ontology_identifiers") == ["RRID:IMSR_JAX:000664"]

    def test_a_strain_without_a_species_warns_and_makes_nothing(self, session):
        pytest.importorskip("openminds")
        with pytest.warns(UserWarning, match="without a valid Species"):
            docs = makeSpeciesStrainSex(session, "subj_1", Strain="RRID:1")
        assert docs == []

    def test_a_failing_add_reaches_the_caller(self, session, monkeypatch):
        pytest.importorskip("openminds")
        monkeypatch.setattr(
            "ndi.ontology.lookup", lambda s: term("NCBITaxon:10090", "Mus musculus", "NCBITaxon")
        )
        session.database_add.side_effect = RuntimeError("database is read-only")
        with pytest.raises(RuntimeError, match="read-only"):
            makeSpeciesStrainSex(session, "subj_1", Species="NCBITaxon:10090", AddToSession=True)

    def test_the_documents_are_added_in_one_call(self, session, monkeypatch):
        pytest.importorskip("openminds")
        monkeypatch.setattr(
            "ndi.ontology.lookup", lambda s: term("NCBITaxon:10090", "Mus musculus", "NCBITaxon")
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            docs = makeSpeciesStrainSex(
                session, "subj_1", Species="NCBITaxon:10090", AddToSession=True
            )
        session.database_add.assert_called_once_with(docs)
