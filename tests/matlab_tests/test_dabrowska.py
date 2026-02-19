"""
Tests for NDI-python against the Dabrowska electrophysiology dataset.

Mirrors the MATLAB tutorial workflow from:
  ndi.setup.conv.dabrowska.tutorial_67f723d574f5f79c6062389d.mlx

Dataset: 14,646 documents (SQLite), 215 subjects, 606 probes, ~4800 epochs
Source: NDI Cloud dataset 67f723d574f5f79c6062389d

Dabrowska dataset contains:
  - Whole-cell patch-clamp recordings (patch-Vm, patch-I)
  - Optogenetic stimulation protocols
  - Elevated Plus Maze (EPM) behavioral data (45 OTR docs)
  - Fear-Potentiated Startle (FPS) behavioral data (6160 OTR docs)
  - Species: Rattus norvegicus
  - Strains: CRF-Cre, OTR-IRES-Cre, AVP-Cre, SD wildtype

MATLAB tutorial steps tested:
  1. Load dataset + document types
  2. Subject summary (docTable.subject) — 215 subjects, dynamic treatments
  3. Filter subjects by strain (identifyMatchingRows)
  4. Probe summary (docTable.probe) — 606 probes, 9 columns
  5. Epoch summary (docTable.epoch) — ~4800 epochs, 8 columns
  6. Combined table + filtering
  7. Electrophysiology data exploration
  8. Elevated Plus Maze analysis
  9. Fear-Potentiated Startle analysis
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Dataset paths — skip entire file if not downloaded locally
# ---------------------------------------------------------------------------

DABROWSKA_PATH = Path(os.path.expanduser("~/Documents/ndi-projects/datasets/dabrowska"))

pytestmark = pytest.mark.skipif(
    not DABROWSKA_PATH.exists(),
    reason="Dabrowska dataset not downloaded locally",
)

# Expected document type counts (from Phase 1 exploration)
EXPECTED_TYPE_COUNTS = {
    "daqreader_mfdaq_epochdata_ingested": 1605,
    "element": 606,
    "epochfiles_ingested": 1604,
    "ontologyTableRow": 6205,
    "openminds_element": 404,
    "openminds_stimulus": 635,
    "openminds_subject": 1305,
    "probe_location": 404,
    "session": 3,
    "stimulus_bath": 1605,
    "subject": 215,
    "treatment": 49,
}


# ---------------------------------------------------------------------------
# Session-scoped fixtures — loaded once for all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def dabrowska_dataset():
    """Load the Dabrowska dataset from SQLite."""
    import ndi.dataset

    return ndi.dataset.Dataset(DABROWSKA_PATH)


@pytest.fixture(scope="session")
def subject_table(dabrowska_dataset):
    """Build subject summary table."""
    from ndi.fun.doc_table import subject_summary

    return subject_summary(dabrowska_dataset)


@pytest.fixture(scope="session")
def probe_summary(dabrowska_dataset):
    """Build probe summary table."""
    from ndi.fun.doc_table import probe_table

    return probe_table(dabrowska_dataset)


@pytest.fixture(scope="session")
def epoch_summary(dabrowska_dataset):
    """Build epoch summary table."""
    from ndi.fun.doc_table import epoch_table

    return epoch_table(dabrowska_dataset)


@pytest.fixture(scope="session")
def epm_table(dabrowska_dataset):
    """Query and convert EPM OTR docs to table."""
    from ndi.fun.doc_table import ontology_table_row_doc_to_table
    from ndi.query import Query

    query = Query("ontologyTableRow.variableNames").contains("ElevatedPlusMaze")
    docs = dabrowska_dataset.database_search(query)
    tables, _ = ontology_table_row_doc_to_table(docs)
    return tables[0]


@pytest.fixture(scope="session")
def fps_table(dabrowska_dataset):
    """Query and convert FPS OTR docs to table."""
    from ndi.fun.doc_table import ontology_table_row_doc_to_table
    from ndi.query import Query

    query = Query("ontologyTableRow.variableNames").contains("Fear_potentiatedStartle")
    docs = dabrowska_dataset.database_search(query)
    tables, _ = ontology_table_row_doc_to_table(docs)
    return tables[0]


# ===========================================================================
# Class 1: TestDatasetLoading
# ===========================================================================


class TestDatasetLoading:
    """Validate dataset loading and document type counts."""

    def test_dataset_loads(self, dabrowska_dataset):
        """Dataset object is created successfully."""
        assert dabrowska_dataset is not None

    def test_document_type_counts(self, dabrowska_dataset):
        """All 13+ document types have expected counts."""
        from ndi.fun.doc import get_doc_types

        doc_types, doc_counts = get_doc_types(dabrowska_dataset)
        actual = dict(zip(doc_types, doc_counts))
        for dtype, expected in EXPECTED_TYPE_COUNTS.items():
            actual_count = actual.get(dtype, 0)
            if dtype == "session":
                assert (
                    actual_count >= expected
                ), f"{dtype}: expected >= {expected}, got {actual_count}"
            else:
                assert actual_count == expected, f"{dtype}: expected {expected}, got {actual_count}"

    def test_total_document_count(self, dabrowska_dataset):
        """Total documents >= 14,646."""
        from ndi.query import Query

        docs = dabrowska_dataset.database_search(Query("").isa("base"))
        assert len(docs) >= 14646, f"Expected >= 14646, got {len(docs)}"

    def test_session_docs_exist(self, dabrowska_dataset):
        """At least 3 session documents exist."""
        from ndi.query import Query

        docs = dabrowska_dataset.database_search(Query("").isa("session"))
        assert len(docs) >= 3


# ===========================================================================
# Class 2: TestSubjectSummary
# ===========================================================================


class TestSubjectSummary:
    """Validate subject_summary() — MATLAB: ndi.fun.docTable.subject()."""

    def test_row_count(self, subject_table):
        """215 subjects in the dataset."""
        assert len(subject_table) == 215

    def test_required_columns_exist(self, subject_table):
        """Core metadata columns are present."""
        required = [
            "SubjectDocumentIdentifier",
            "SubjectLocalIdentifier",
            "SpeciesName",
            "StrainName",
        ]
        for col in required:
            assert col in subject_table.columns, f"Missing column: {col}"

    def test_dynamic_treatment_columns(self, subject_table):
        """Dynamic treatment columns from EMPTY ontology are generated."""
        treatment_cols = [
            c for c in subject_table.columns if "OptogeneticTetanusStimulationTargetLocation" in c
        ]
        assert len(treatment_cols) >= 1, (
            f"Expected OptogeneticTetanusStimulationTargetLocation columns, "
            f"found: {[c for c in subject_table.columns if 'treatment' in c.lower() or 'Optogenetic' in c]}"
        )

    def test_species_all_rattus(self, subject_table):
        """All subjects are Rattus norvegicus."""
        species = subject_table["SpeciesName"].unique()
        assert len(species) == 1
        assert "Rattus norvegicus" in species[0]

    def test_strain_distribution(self, subject_table):
        """Four expected strains present."""
        strains = subject_table["StrainName"].unique()
        expected_patterns = ["CRF-Cre", "OTR-IRES-Cre", "AVP-Cre"]
        for pattern in expected_patterns:
            found = any(pattern in str(s) for s in strains)
            assert found, f"Strain pattern '{pattern}' not found in {strains}"

    def test_filter_avp_cre(self, subject_table):
        """AVP-Cre strain filtering returns expected count."""
        from ndi.fun.table import identify_matching_rows

        row_ind = identify_matching_rows(
            subject_table, "StrainName", "AVP-Cre", string_match="contains"
        )
        filtered = subject_table[row_ind]
        assert len(filtered) == 49, f"Expected 49 AVP-Cre, got {len(filtered)}"

    def test_filter_otr_cre(self, subject_table):
        """OTR-IRES-Cre filtering works."""
        from ndi.fun.table import identify_matching_rows

        row_ind = identify_matching_rows(
            subject_table, "StrainName", "OTR-IRES-Cre", string_match="contains"
        )
        filtered = subject_table[row_ind]
        assert len(filtered) > 0, "No OTR-IRES-Cre subjects found"


# ===========================================================================
# Class 3: TestProbeSummary
# ===========================================================================


class TestProbeSummary:
    """Validate probe_table() — MATLAB: ndi.fun.docTable.probe()."""

    def test_row_count(self, probe_summary):
        """606 probes (202 each of 3 types)."""
        assert len(probe_summary) == 606

    def test_column_count(self, probe_summary):
        """9 columns including location and cell type."""
        assert len(probe_summary.columns) >= 9, (
            f"Expected >= 9 columns, got {len(probe_summary.columns)}: "
            f"{list(probe_summary.columns)}"
        )

    def test_probe_type_distribution(self, probe_summary):
        """Three probe types, 202 each."""
        type_counts = probe_summary["ProbeType"].value_counts()
        for ptype in ["patch-I", "patch-Vm", "stimulator"]:
            assert ptype in type_counts.index, f"Missing probe type: {ptype}"
            assert type_counts[ptype] == 202, f"{ptype}: expected 202, got {type_counts[ptype]}"

    def test_probe_location_columns(self, probe_summary):
        """ProbeLocationName and ProbeLocationOntology columns exist."""
        assert "ProbeLocationName" in probe_summary.columns
        assert "ProbeLocationOntology" in probe_summary.columns

    def test_cell_type_columns(self, probe_summary):
        """CellTypeName and CellTypeOntology columns exist."""
        assert "CellTypeName" in probe_summary.columns
        assert "CellTypeOntology" in probe_summary.columns

    def test_probes_have_location(self, probe_summary):
        """At least 404 probes have location data (patch-I and patch-Vm)."""
        has_location = probe_summary["ProbeLocationName"].notna() & (
            probe_summary["ProbeLocationName"] != ""
        )
        assert (
            has_location.sum() >= 400
        ), f"Expected >= 400 probes with location, got {has_location.sum()}"

    def test_subject_id_column(self, probe_summary):
        """SubjectDocumentIdentifier column links probes to subjects."""
        assert "SubjectDocumentIdentifier" in probe_summary.columns
        non_empty = probe_summary["SubjectDocumentIdentifier"].notna() & (
            probe_summary["SubjectDocumentIdentifier"] != ""
        )
        assert non_empty.sum() > 0


# ===========================================================================
# Class 4: TestEpochSummary
# ===========================================================================


class TestEpochSummary:
    """Validate epoch_table() — MATLAB: ndi.fun.docTable.epoch()."""

    def test_row_count(self, epoch_summary):
        """At least 4000 epoch rows."""
        assert len(epoch_summary) >= 4000, f"Expected >= 4000 epochs, got {len(epoch_summary)}"

    def test_column_count(self, epoch_summary):
        """At least 8 columns."""
        assert len(epoch_summary.columns) >= 8, (
            f"Expected >= 8 columns, got {len(epoch_summary.columns)}: "
            f"{list(epoch_summary.columns)}"
        )

    def test_epoch_number_column(self, epoch_summary):
        """EpochNumber column exists and has positive values."""
        assert "EpochNumber" in epoch_summary.columns
        assert epoch_summary["EpochNumber"].min() >= 1

    def test_epoch_doc_id_column(self, epoch_summary):
        """EpochDocumentIdentifier column exists."""
        assert "EpochDocumentIdentifier" in epoch_summary.columns

    def test_probe_doc_id_column(self, epoch_summary):
        """ProbeDocumentIdentifier column exists."""
        assert "ProbeDocumentIdentifier" in epoch_summary.columns

    def test_approach_column(self, epoch_summary):
        """ApproachName column exists and has values."""
        assert "ApproachName" in epoch_summary.columns
        non_empty = epoch_summary["ApproachName"].notna() & (epoch_summary["ApproachName"] != "")
        assert non_empty.sum() > 0

    def test_mixture_column(self, epoch_summary):
        """MixtureName column exists."""
        assert "MixtureName" in epoch_summary.columns

    def test_unique_probes(self, epoch_summary):
        """Multiple probes represented in epochs."""
        n_probes = epoch_summary["ProbeDocumentIdentifier"].nunique()
        assert n_probes >= 100, f"Expected >= 100 unique probes in epochs, got {n_probes}"


# ===========================================================================
# Class 5: TestCombinedTable
# ===========================================================================


class TestCombinedTable:
    """Validate table join and filtering operations."""

    def test_join_produces_rows(self, subject_table, probe_summary, epoch_summary):
        """Joining subject + probe + epoch produces a non-empty table."""
        from ndi.fun.table import join

        combined = join([subject_table, probe_summary, epoch_summary])
        assert len(combined) > 0

    def test_joined_columns(self, subject_table, probe_summary, epoch_summary):
        """Joined table has columns from all three source tables."""
        from ndi.fun.table import join

        combined = join([subject_table, probe_summary, epoch_summary])
        assert "SubjectLocalIdentifier" in combined.columns
        assert "ProbeType" in combined.columns
        assert "EpochNumber" in combined.columns

    def test_move_columns_left(self, subject_table, probe_summary, epoch_summary):
        """move_columns_left reorders columns correctly."""
        from ndi.fun.table import join, move_columns_left

        combined = join([subject_table, probe_summary, epoch_summary])
        reordered = move_columns_left(combined, ["SubjectLocalIdentifier", "EpochNumber"])
        assert list(reordered.columns[:2]) == [
            "SubjectLocalIdentifier",
            "EpochNumber",
        ]

    def test_filter_by_approach(self, subject_table, probe_summary, epoch_summary):
        """Filter by ApproachName containing 'optogenetic' works."""
        from ndi.fun.table import identify_matching_rows, join

        combined = join([subject_table, probe_summary, epoch_summary])
        row_ind = identify_matching_rows(
            combined, "ApproachName", "optogenetic", string_match="contains"
        )
        opto = combined[row_ind]
        assert len(opto) > 0, "No optogenetic approach epochs found"


# ===========================================================================
# Class 6: TestEPMAnalysis
# ===========================================================================


class TestEPMAnalysis:
    """Validate Elevated Plus Maze OTR data analysis."""

    def test_epm_doc_count(self, dabrowska_dataset):
        """45 EPM OTR documents."""
        from ndi.query import Query

        query = Query("ontologyTableRow.variableNames").contains("ElevatedPlusMaze")
        docs = dabrowska_dataset.database_search(query)
        assert len(docs) == 45

    def test_epm_table_shape(self, epm_table):
        """EPM table has 45 rows and 51 columns."""
        assert epm_table.shape == (45, 51), f"Expected (45, 51), got {epm_table.shape}"

    def test_epm_treatment_values(self, epm_table):
        """Treatment column has CNO and Saline values."""
        col = "Treatment_CNOOrSalineAdministration"
        assert col in epm_table.columns
        values = set(epm_table[col].unique())
        assert "CNO" in values
        assert "Saline" in values

    def test_epm_data_exclusion_flag(self, epm_table):
        """DataExclusionFlag column exists with boolean values."""
        assert "DataExclusionFlag" in epm_table.columns
        # Some should be True (excluded), most False
        assert epm_table["DataExclusionFlag"].any()  # at least 1 excluded
        assert not epm_table["DataExclusionFlag"].all()  # not all excluded

    def test_epm_subject_identifier(self, epm_table):
        """SubjectLocalIdentifier column exists."""
        assert "SubjectLocalIdentifier" in epm_table.columns
        assert epm_table["SubjectLocalIdentifier"].nunique() == 45

    def test_epm_open_arm_columns(self, epm_table):
        """Key EPM behavioral columns exist."""
        expected = [
            "ElevatedPlusMaze_OpenArmTotalEntries",
            "ElevatedPlusMaze_OpenArmTotalTime",
            "ElevatedPlusMaze_ClosedArmTotalEntries",
            "ElevatedPlusMaze_TestDuration",
        ]
        for col in expected:
            assert col in epm_table.columns, f"Missing EPM column: {col}"


# ===========================================================================
# Class 7: TestFPSAnalysis
# ===========================================================================


class TestFPSAnalysis:
    """Validate Fear-Potentiated Startle OTR data analysis."""

    def test_fps_doc_count(self, dabrowska_dataset):
        """6160 FPS OTR documents."""
        from ndi.query import Query

        query = Query("ontologyTableRow.variableNames").contains("Fear_potentiatedStartle")
        docs = dabrowska_dataset.database_search(query)
        assert len(docs) == 6160

    def test_fps_table_shape(self, fps_table):
        """FPS table has 6160 rows and 13 columns."""
        assert fps_table.shape == (6160, 13), f"Expected (6160, 13), got {fps_table.shape}"

    def test_fps_trial_types(self, fps_table):
        """Four trial types present."""
        col = "Fear_potentiatedStartle_TrialTypeIdentifier"
        trial_types = set(fps_table[col].unique())
        expected = {
            "Startle 95 dB Trial",
            "FPS (N) Testing Trial",
            "FPS (L+N) Testing Trial",
            "FPS Training Trial",
        }
        assert expected == trial_types, f"Trial types: {trial_types}"

    def test_fps_experimental_phases(self, fps_table):
        """Multiple experimental phases present including Cue tests."""
        col = "Fear_potentiatedStartle_ExperimentalPhaseOrTestName"
        phases = fps_table[col].unique()
        cue_tests = [p for p in phases if "Cue test" in str(p)]
        assert len(cue_tests) >= 3, f"Expected >= 3 Cue test phases, got {cue_tests}"

    def test_fps_startle_amplitude_numeric(self, fps_table):
        """AcousticStartleResponse_MaximumAmplitude is numeric."""
        import pandas as pd

        col = "AcousticStartleResponse_MaximumAmplitude"
        assert col in fps_table.columns
        numeric_col = pd.to_numeric(fps_table[col], errors="coerce")
        assert numeric_col.notna().sum() > 6000

    def test_fps_groupby_aggregation(self, fps_table):
        """Groupby aggregation for mean startle amplitude works."""
        import pandas as pd

        phase_col = "Fear_potentiatedStartle_ExperimentalPhaseOrTestName"
        subject_col = "SubjectLocalIdentifier"
        trial_col = "Fear_potentiatedStartle_TrialTypeIdentifier"
        amp_col = "AcousticStartleResponse_MaximumAmplitude"

        fps_table[amp_col] = pd.to_numeric(fps_table[amp_col], errors="coerce")
        grouped = fps_table.groupby([phase_col, subject_col, trial_col], as_index=False)[
            amp_col
        ].mean()

        assert len(grouped) > 0
        assert grouped[amp_col].notna().all()

    def test_fps_fear_percentage_calculation(self, fps_table):
        """Cued and non-cued fear % calculation produces valid results."""
        import pandas as pd

        phase_col = "Fear_potentiatedStartle_ExperimentalPhaseOrTestName"
        subject_col = "SubjectLocalIdentifier"
        trial_col = "Fear_potentiatedStartle_TrialTypeIdentifier"
        amp_col = "AcousticStartleResponse_MaximumAmplitude"
        mean_col = f"mean_{amp_col}"

        fps_copy = fps_table.copy()
        fps_copy[amp_col] = pd.to_numeric(fps_copy[amp_col], errors="coerce")

        grouped = fps_copy.groupby([phase_col, subject_col, trial_col], as_index=False)[
            amp_col
        ].mean()
        grouped = grouped.rename(columns={amp_col: mean_col})

        join_keys = [phase_col, subject_col]

        light_noise = grouped[grouped[trial_col] == "FPS (L+N) Testing Trial"][
            [phase_col, subject_col, mean_col]
        ].rename(columns={mean_col: "LN"})
        noise_only = grouped[grouped[trial_col] == "FPS (N) Testing Trial"][
            [phase_col, subject_col, mean_col]
        ].rename(columns={mean_col: "N"})
        startle = grouped[grouped[trial_col] == "Startle 95 dB Trial"][
            [phase_col, subject_col, mean_col]
        ].rename(columns={mean_col: "S"})

        cue = light_noise.merge(noise_only, on=join_keys, how="inner")
        cue = cue.merge(startle, on=join_keys, how="inner")

        cue["cuedFear"] = 100 * (cue["LN"] - cue["N"]) / cue["N"]
        cue["nonCuedFear"] = 100 * (cue["N"] - cue["S"]) / cue["S"]

        assert len(cue) > 0
        assert cue["cuedFear"].notna().sum() > 0
        assert cue["nonCuedFear"].notna().sum() > 0


# ===========================================================================
# Class 8: TestOntologyIntegration
# ===========================================================================


class TestOntologyIntegration:
    """Validate EMPTY ontology integration for the Dabrowska dataset."""

    def test_ontology_table_row_vars(self, dabrowska_dataset):
        """ontology_table_row_vars returns names, short names, nodes."""
        from ndi.fun.doc import ontology_table_row_vars

        names, short_names, nodes = ontology_table_row_vars(dabrowska_dataset)
        assert len(names) > 0
        assert len(names) == len(short_names) == len(nodes)

    def test_empty_ontology_lookup(self):
        """EMPTY ontology provider resolves treatment term."""
        from ndi.ontology import lookup as ontology_lookup

        result = ontology_lookup("EMPTY:0000074")
        assert result is not None
        assert result.name is not None
        assert len(result.name) > 0

    def test_name_to_variable_name(self):
        """name_to_variable_name produces correct PascalCase output."""
        from ndi.fun.name_utils import name_to_variable_name

        assert (
            name_to_variable_name("treatment: food restriction onset time")
            == "Treatment_FoodRestrictionOnsetTime"
        )
        assert (
            name_to_variable_name("elevated plus maze: test duration")
            == "ElevatedPlusMaze_TestDuration"
        )
        assert (
            name_to_variable_name("Optogenetic Tetanus Stimulation Target Location")
            == "OptogeneticTetanusStimulationTargetLocation"
        )

    def test_name_to_variable_name_edge_cases(self):
        """name_to_variable_name handles edge cases."""
        from ndi.fun.name_utils import name_to_variable_name

        assert name_to_variable_name("") == ""
        assert name_to_variable_name("   ") == ""
        assert name_to_variable_name("123abc") == "var_123abc"
        assert name_to_variable_name("simple") == "Simple"
