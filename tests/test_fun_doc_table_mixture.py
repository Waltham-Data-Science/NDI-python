"""Mixture tables: the char-array codec, and the two tables built from it.

Covers issue #138 -- ``ndi.database.fun.readtablechar`` / ``writetablechar``,
which had no Python implementation at all, and the two ``ndi.fun.doc_table``
functions that could not produce their mixture columns without them.

The interesting case throughout is a mixture of SEVERAL compounds, because
that is what ``mixtureStr2mixtureTable`` actually builds ('saline,3*TTX' is
two rows) and what a single-row test would never distinguish from taking
``[0]`` and stopping.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from ndi.database_fun import readtablechar, writetablechar  # noqa: E402
from ndi.fun.doc_table import epoch, treatment  # noqa: E402

# The shape marderbath.m stores: writetablechar(mixTable) with no options,
# so comma-delimited with a variable-name header.
SALINE_TTX = (
    "ontologyName,name,value,ontologyUnit,unitName\n"
    "CHEBI:26710,saline,2,OM:MolarVolumeUnit,Molar\n"
    "CHEBI:9506,TTX,0.0001,OM:MolarVolumeUnit,Molar\n"
)
PICROTOXIN = (
    "ontologyName,name,value,ontologyUnit,unitName\n"
    "CHEBI:8106,picrotoxin,0.05,OM:MolarVolumeUnit,Molar\n"
)


class TestTheCharArrayCodec:
    def test_matlabs_own_round_trip_example(self):
        """readtablechar(writetablechar(t)) == t, to MATLAB's tolerance.

        This is the example in both .m docstrings, which assert numeric
        equality within 1e-15 rather than text identity -- the text differs
        because a float is not written back the way it was typed.
        """
        import numpy as np

        rng = np.random.default_rng(0)
        original = pd.DataFrame(rng.random((10, 3)), columns=["a", "b", "c"])

        text = writetablechar(original, "Delimiter", "\t")
        restored = readtablechar(text, ".txt", "Delimiter", "\t")

        assert (abs(original.to_numpy() - restored.to_numpy()) < 1e-15).all()

    def test_the_stored_mixture_parses_into_its_compounds(self):
        table = readtablechar(SALINE_TTX, ".txt", "Delimiter", ",")
        assert table["name"].tolist() == ["saline", "TTX"]
        assert table["ontologyName"].tolist() == ["CHEBI:26710", "CHEBI:9506"]
        assert table["value"].tolist() == [2.0, 0.0001]

    def test_options_may_be_matlab_pairs_or_python_keywords(self):
        """A ported call site can read like its MATLAB twin, or not."""
        as_pairs = readtablechar(SALINE_TTX, ".txt", "Delimiter", ",")
        as_kwargs = readtablechar(SALINE_TTX, ".txt", Delimiter=",")
        assert as_pairs.equals(as_kwargs)

    def test_the_extension_may_carry_its_dot_or_not(self):
        """MATLAB prepends the dot if it is missing; so does this."""
        assert readtablechar(SALINE_TTX, "txt", Delimiter=",").equals(
            readtablechar(SALINE_TTX, ".txt", Delimiter=",")
        )

    def test_readvariablenames_false_keeps_the_first_line_as_data(self):
        text = "saline,2\nTTX,0.0001\n"
        table = readtablechar(text, ".txt", "Delimiter", ",", "ReadVariableNames", False)
        assert len(table) == 2

    def test_an_option_with_no_counterpart_is_refused_not_ignored(self):
        """Silently dropping Delimiter would return one column of joined text
        that still looks like a table -- the failure this port exists to end."""
        with pytest.raises(ValueError, match="no pandas counterpart"):
            readtablechar(SALINE_TTX, ".txt", "TreatAsMissing", "NA")

    def test_odd_numbered_options_are_refused(self):
        with pytest.raises(ValueError, match="pairs"):
            readtablechar(SALINE_TTX, ".txt", "Delimiter")

    def test_writetablechar_defaults_are_what_marderbath_stores(self):
        """marderbath.m calls writetablechar(mixTable) with NO options, so the
        defaults are the format of every stored mixture table."""
        table = readtablechar(SALINE_TTX, ".txt", Delimiter=",")
        text = writetablechar(table)
        assert text.startswith("ontologyName,name,value,ontologyUnit,unitName\n")
        assert readtablechar(text, ".txt", Delimiter=",")["name"].tolist() == ["saline", "TTX"]


# ---------------------------------------------------------------------------
# A session that actually evaluates the query it is handed.
# ---------------------------------------------------------------------------


class FakeDoc:
    def __init__(self, classname: str, props: dict):
        self._classname = classname
        self.document_properties = props

    def doc_isa(self, name: str) -> bool:
        return name == self._classname


def _isa_names(structure: dict) -> set[str]:
    """Every class named by an isa clause in a search structure."""
    if "search" in structure:
        names: set[str] = set()
        for sub in structure["search"]:
            names |= _isa_names(sub)
        return names
    if structure.get("operation") == "isa":
        return {structure.get("param1", "")}
    return set()


class FakeSession:
    """Returns only the documents the query actually asks for.

    A fake that returned everything would let ``treatment`` pass its mixture
    assertions even if it never learned to query treatment_drug -- which is
    precisely the defect under test.
    """

    def __init__(self, docs: list[FakeDoc]):
        self._docs = docs

    def database_search(self, query):
        wanted = _isa_names(query.to_searchstructure())
        if not wanted:
            return []
        return [d for d in self._docs if any(d.doc_isa(w) for w in wanted)]


def _bath(epochid: str, mixture: str, location_name: str = "bath") -> FakeDoc:
    return FakeDoc(
        "stimulus_bath",
        {
            "base": {"id": f"sb-{epochid}-{location_name}"},
            "epochid": {"epochid": epochid},
            "stimulus_bath": {
                "location": {"ontologyNode": "UBERON:0000000", "name": location_name},
                "mixture_table": mixture,
            },
        },
    )


def _drug_doc(mixture: str, doc_id: str = "d1") -> FakeDoc:
    return FakeDoc(
        "treatment_drug",
        {
            "base": {"id": doc_id},
            "depends_on": [{"name": "subject_id", "value": "subj-1"}],
            "treatment_drug": {
                "location_name": "bath",
                "location_ontologyName": "UBERON:0000000",
                "mixture_table": mixture,
                "administration_onset_time": "2024-01-01T00:00:00",
                "administration_duration": 30,
            },
        },
    )


def _element(name: str = "probe1", ref: int = 1, etype: str = "n-trode") -> FakeDoc:
    return FakeDoc(
        "element",
        {
            "base": {"id": "elem-1"},
            "element": {"name": name, "reference": ref, "type": etype},
            "depends_on": [{"name": "subject_id", "value": "subj-1"}],
        },
    )


def _epochfiles(
    epochid: str, name: str = "probe1", ref: int = 1, etype: str = "n-trode"
) -> FakeDoc:
    epm = f"name\treference\ttype\n{name}\t{ref}\t{etype}\n"
    return FakeDoc(
        "epochfiles_ingested",
        {
            "base": {"id": f"efi-{epochid}"},
            "epochfiles_ingested": {"epoch_id": epochid, "epochprobemap": epm},
        },
    )


class TestTreatmentGrowsTheColumnsMatlabAlwaysWrote:
    def test_the_three_derived_columns_exist(self):
        """treatment.m:111-114 writes MixtureName, Quantity and Ontology from
        the parsed table. Python produced none of them."""
        session = FakeSession([_drug_doc(SALINE_TTX)])
        table, _, _ = treatment(session)

        assert table["DrugTreatmentMixtureName"].iloc[0] == "saline,TTX"
        assert table["DrugTreatmentMixtureOntology"].iloc[0] == "CHEBI:26710,CHEBI:9506"

    def test_the_quantity_uses_matlabs_g_format_and_one_unit(self):
        """compose("%g %s", value, unitName{1}) -- %g, and the FIRST unit for
        every compound, not one unit per row."""
        session = FakeSession([_drug_doc(SALINE_TTX)])
        table, _, _ = treatment(session)
        assert table["DrugTreatmentMixtureQuantity"].iloc[0] == "2 Molar,0.0001 Molar"

    def test_a_treatment_drug_document_is_queried_at_all(self):
        """The old query asked only for "treatment"; treatment_drug is a
        sibling class, so no drug document was ever returned."""
        session = FakeSession([_drug_doc(SALINE_TTX)])
        table, doc_ids, dep_ids = treatment(session)
        assert doc_ids == ["d1"]
        assert dep_ids == ["subj-1"]

    def test_hide_drops_the_raw_table_and_keeps_the_expansion(self):
        """hideMixtureTable governs the RAW column only. Dropping every column
        matching "Mixture" threw away the expansion with it."""
        session = FakeSession([_drug_doc(SALINE_TTX)])

        hidden, _, _ = treatment(session, hideMixtureTable=True)
        assert "DrugTreatmentMixtureTable" not in hidden.columns
        assert "DrugTreatmentMixtureName" in hidden.columns

        # strtrim'd, as MATLAB strtrims every char field (treatment.m:93-95),
        # so the stored text loses the trailing newline writetable put there.
        shown, _, _ = treatment(session, hideMixtureTable=False)
        assert shown["DrugTreatmentMixtureTable"].iloc[0] == SALINE_TTX.strip()

    def test_the_location_fields_are_renamed_as_matlab_renames_them(self):
        session = FakeSession([_drug_doc(SALINE_TTX)])
        table, _, _ = treatment(session)
        assert table["DrugTreatmentLocationName"].iloc[0] == "bath"
        assert table["DrugTreatmentOnsetTime"].iloc[0] == "2024-01-01T00:00:00"

    def test_an_unreadable_mixture_costs_the_expansion_not_the_row(self):
        session = FakeSession([_drug_doc("this is not a table")])
        table, _, _ = treatment(session)
        assert len(table) == 1
        assert table["DrugTreatmentLocationName"].iloc[0] == "bath"


class TestEpochNamesTheCompoundNotTheBathLocation:
    """THE REGRESSION, through the real function rather than its helper.

    ``MixtureName`` held ``stimulus_bath.location.name`` -- the place the bath
    was applied -- so the column named a location while claiming to name a
    compound, and looked entirely plausible doing it.
    """

    def _session(self, *baths: FakeDoc) -> FakeSession:
        return FakeSession([_element(), _epochfiles("e1"), *baths])

    def test_the_column_holds_the_compound_not_the_location(self):
        table = epoch(self._session(_bath("e1", SALINE_TTX, location_name="left bath")))
        row = table.iloc[0]
        assert row["MixtureName"] == "saline,TTX"
        assert row["MixtureOntology"] == "CHEBI:26710,CHEBI:9506"
        # the location is what used to be here
        assert "left bath" not in row["MixtureName"]

    def test_every_bath_in_the_epoch_contributes(self):
        """MATLAB vstacks all of them; taking sbs[0] dropped the second drug
        of a two-bath epoch."""
        table = epoch(
            self._session(
                _bath("e1", SALINE_TTX, location_name="left"),
                _bath("e1", PICROTOXIN, location_name="right"),
            )
        )
        assert table.iloc[0]["MixtureName"] == "saline,TTX,picrotoxin"

    def test_an_epoch_with_no_bath_names_no_compound(self):
        table = epoch(self._session())
        assert table.iloc[0]["MixtureName"] == ""
        assert table.iloc[0]["MixtureOntology"] == ""


class TestTheMixtureHelper:
    def test_repeats_collapse_in_first_seen_order(self):
        """unique(mixtures,'stable')."""
        from ndi.fun.doc_table import _mixture_columns

        names, _ = _mixture_columns([SALINE_TTX, SALINE_TTX, PICROTOXIN])
        assert names == "saline,TTX,picrotoxin"

    def test_no_bath_names_no_compound(self):
        from ndi.fun.doc_table import _mixture_columns

        assert _mixture_columns([]) == ("", "")
        assert _mixture_columns([""]) == ("", "")

    def test_an_unreadable_mixture_is_skipped_not_raised(self):
        from ndi.fun.doc_table import _mixture_columns

        names, _ = _mixture_columns(["not a table at all", PICROTOXIN])
        assert names == "picrotoxin"
