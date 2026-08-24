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

FIXTURE CONTAINMENT — read before editing the fixtures
------------------------------------------------------
Constructing an ``ndi_dataset`` **writes to the directory it is pointed at**.
It always rewrites ``<path>/.ndi/reference.txt`` and
``<path>/.ndi/unique_reference.txt``, and when the database still carries
legacy ``dataset_session_info`` documents, ``build_session_info()`` calls
``ndi_dataset.repairDatasetSessionInfo()``, which performs a ``database_add``
of the replacement ``session_in_a_dataset`` documents followed by a
``database_rm`` of the legacy document — an add *and a delete* against the
live on-disk SQLite, during construction.

The shared corpus under ``DABROWSKA_PATH`` is therefore **never opened in
place**. ``dabrowska_corpus`` copies the whole corpus directory into a pytest
tmp dir once per module, and ``dabrowska_dataset`` opens only that private
copy. ``TestFixtureContainment`` is the regression gate for this: it checks the
opened path, and it snapshots the shared corpus immediately either side of the
``ndi_dataset(...)`` call so any write that construction performs is caught and
correctly attributed. Other processes open this corpus too, so do not widen
that window to the whole module — their writes would be reported as ours.

CORPUS INTEGRITY PREFLIGHT / RESTORE PATH
-----------------------------------------
The local corpus is already damaged: exactly one ``session`` document was
deleted from it at some point by an in-place open (SQLite AUTOINCREMENT shows
14646 ``doc_idx`` values allocated but only 14645 rows, with ``doc_idx = 2``
missing, and its ``doc_data`` rows cleanly removed — a ``database_rm``, not
corruption). Every other document class still matches ``EXPECTED_TYPE_COUNTS``
to the unit.

``EXPECTED_TOTAL_DOCUMENTS`` (14646) and ``EXPECTED_TYPE_COUNTS["session"]``
(3) are the **correct** values for the intended corpus and have been unchanged
since they were captured. **Do not lower them** — that would pin the damage
and permanently retire the coverage. Instead, ``_corpus_integrity()`` runs a
read-only SQLite preflight at import time and the three count-dependent tests
skip with a loud reason naming the restore path.

To restore: re-fetch NDI Cloud dataset ``67f723d574f5f79c6062389d`` into the
tutorials cache that ``DABROWSKA_PATH`` points at. The three tests then become
real assertions again with no code change.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import warnings
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Dataset paths — skip entire file if not downloaded locally
# ---------------------------------------------------------------------------

DABROWSKA_PATH = Path(os.path.expanduser("~/Documents/ndi-projects/datasets/dabrowska"))

#: NDI Cloud dataset to re-fetch from when the local corpus fails the preflight.
DABROWSKA_CLOUD_DATASET_ID = "67f723d574f5f79c6062389d"

#: Location of the DID SQLite database inside a corpus directory.
CORPUS_DB_RELPATH = Path(".ndi") / "did-sqlite.sqlite"

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

#: Total document count of the intended corpus. NOT a floor to be lowered —
#: see the "CORPUS INTEGRITY PREFLIGHT" section of the module docstring.
EXPECTED_TOTAL_DOCUMENTS = 14646


# ---------------------------------------------------------------------------
# Corpus integrity preflight (read-only SQLite — never opens ndi_dataset)
# ---------------------------------------------------------------------------


def _restore_message(detail: str) -> str:
    """Build the loud skip reason that names the restore path."""
    real = os.path.realpath(DABROWSKA_PATH) if DABROWSKA_PATH.exists() else "<missing>"
    return (
        "DABROWSKA CORPUS IS DAMAGED OR INCOMPLETE — THIS IS A FIXTURE "
        f"PROBLEM, NOT A CODE FAILURE. {detail}. "
        f"Corpus: {DABROWSKA_PATH} (resolves to {real}). "
        "RESTORE IT by re-fetching NDI Cloud dataset "
        f"{DABROWSKA_CLOUD_DATASET_ID} into that cache directory, then re-run; "
        "these tests become real assertions again with no code change. "
        "DO NOT lower EXPECTED_TOTAL_DOCUMENTS or EXPECTED_TYPE_COUNTS to go "
        "green — those values are correct for the intended corpus and pinning "
        "the damaged counts would freeze the defect."
    )


def _corpus_integrity(corpus_path: Path) -> tuple[bool, str]:
    """Check corpus document/session counts straight from SQLite, read-only.

    Deliberately bypasses ``ndi_dataset`` — constructing one would write to the
    corpus, which is the very thing this module exists to avoid.

    Returns:
        ``(intact, reason)``. *reason* is empty when *intact* is True.
    """
    db_path = corpus_path / CORPUS_DB_RELPATH
    if not db_path.exists():
        return False, _restore_message(f"no DID SQLite database at {db_path}")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - depends on local disk state
        return False, _restore_message(f"cannot open {db_path} read-only: {exc}")

    try:
        total_docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        row = conn.execute(
            "SELECT field_idx FROM fields WHERE field_name = 'meta.class'"
        ).fetchone()
        if row is None:
            return False, _restore_message("'meta.class' is missing from the fields table")
        n_sessions = conn.execute(
            "SELECT COUNT(*) FROM doc_data WHERE field_idx = ? AND value = 'session'",
            (row[0],),
        ).fetchone()[0]
    except sqlite3.Error as exc:  # pragma: no cover - depends on local disk state
        return False, _restore_message(f"integrity query failed: {exc}")
    finally:
        conn.close()

    problems = []
    if total_docs < EXPECTED_TOTAL_DOCUMENTS:
        problems.append(
            f"corpus holds {total_docs} documents, expected >= {EXPECTED_TOTAL_DOCUMENTS} "
            f"({EXPECTED_TOTAL_DOCUMENTS - total_docs} missing)"
        )
    expected_sessions = EXPECTED_TYPE_COUNTS["session"]
    if n_sessions < expected_sessions:
        problems.append(
            f"corpus holds {n_sessions} 'session' documents, expected >= {expected_sessions}"
        )
    if problems:
        return False, _restore_message("; ".join(problems))
    return True, ""


if DABROWSKA_PATH.exists():
    CORPUS_INTACT, CORPUS_PROBLEM = _corpus_integrity(DABROWSKA_PATH)
    if not CORPUS_INTACT:
        warnings.warn(CORPUS_PROBLEM, stacklevel=1)
else:
    CORPUS_INTACT, CORPUS_PROBLEM = False, "Dabrowska dataset not downloaded locally"

#: Applied to the tests whose expectations depend on a complete corpus. They
#: are real assertions on an intact corpus and loud skips on a damaged one.
requires_intact_corpus = pytest.mark.skipif(not CORPUS_INTACT, reason=CORPUS_PROBLEM)


# ---------------------------------------------------------------------------
# Shared-corpus mutation canary
# ---------------------------------------------------------------------------


def _snapshot_tree(root: Path) -> dict[str, tuple[int, int]]:
    """Map every regular file under *root* to ``(size, mtime_ns)``.

    Symlinks are followed so the snapshot covers the real cache directory that
    ``DABROWSKA_PATH/.ndi`` points at.
    """
    snapshot: dict[str, tuple[int, int]] = {}
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=True):
        for name in filenames:
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


#: Entries under the shared corpus whose ``(size, mtime_ns)`` changed while
#: ``dabrowska_dataset`` was constructing its ndi_dataset. Populated by that
#: fixture; asserted empty by ``TestFixtureContainment``.
#:
#: The window is deliberately just the construction call rather than the whole
#: module. Other processes open this same corpus (the tutorials/verification
#: harnesses, and sibling test runs), so a module-wide window reports their
#: writes as ours — observed happening during development.
SHARED_CORPUS_WRITES: list[str] = []


# ---------------------------------------------------------------------------
# Module-scoped fixtures — corpus copied once, then loaded once for all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dabrowska_corpus(tmp_path_factory):
    """Private, writable copy of the shared Dabrowska corpus.

    Opening an ``ndi_dataset`` mutates the directory it is given (see the
    module docstring), so tests get their own copy and the shared corpus is
    only ever read. ~102 MB, copied once per module.
    """
    destination = tmp_path_factory.mktemp("dabrowska_corpus") / "dabrowska"
    shutil.copytree(
        DABROWSKA_PATH,
        destination,
        symlinks=False,
        ignore_dangling_symlinks=True,
    )
    yield destination
    shutil.rmtree(destination.parent, ignore_errors=True)


@pytest.fixture(scope="module")
def dabrowska_dataset(dabrowska_corpus):
    """Load the Dabrowska dataset from the private copy — never the shared corpus.

    Brackets the construction call with a snapshot of the shared corpus so
    ``TestFixtureContainment`` can prove this open wrote nothing to it.
    """
    import ndi.dataset

    before = _snapshot_tree(DABROWSKA_PATH)
    dataset = ndi.dataset.ndi_dataset(dabrowska_corpus)
    after = _snapshot_tree(DABROWSKA_PATH)

    SHARED_CORPUS_WRITES[:] = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    return dataset


@pytest.fixture(scope="module")
def subject_table(dabrowska_dataset):
    """Build subject summary table."""
    from ndi.fun.doc_table import subject as subject_summary

    return subject_summary(dabrowska_dataset)


@pytest.fixture(scope="module")
def probe_summary(dabrowska_dataset):
    """Build probe summary table."""
    from ndi.fun.doc_table import probe as probe_table

    return probe_table(dabrowska_dataset)


@pytest.fixture(scope="module")
def epoch_summary(dabrowska_dataset):
    """Build epoch summary table."""
    from ndi.fun.doc_table import epoch as epoch_table

    return epoch_table(dabrowska_dataset)


@pytest.fixture(scope="module")
def epm_table(dabrowska_dataset):
    """Query and convert EPM OTR docs to table."""
    from ndi.fun.doc_table import ontologyTableRowDoc2Table
    from ndi.query import ndi_query

    query = ndi_query("ontologyTableRow.variableNames").contains("ElevatedPlusMaze")
    docs = dabrowska_dataset.database_search(query)
    tables, *_ = ontologyTableRowDoc2Table(docs)
    return tables[0]


@pytest.fixture(scope="module")
def fps_table(dabrowska_dataset):
    """Query and convert FPS OTR docs to table."""
    from ndi.fun.doc_table import ontologyTableRowDoc2Table
    from ndi.query import ndi_query

    query = ndi_query("ontologyTableRow.variableNames").contains("Fear_potentiatedStartle")
    docs = dabrowska_dataset.database_search(query)
    tables, *_ = ontologyTableRowDoc2Table(docs)
    return tables[0]


# ===========================================================================
# Class 0: TestFixtureContainment
# ===========================================================================


class TestFixtureContainment:
    """Guard the shared corpus against in-place opens.

    ``ndi_dataset`` construction writes to the directory it opens, and under
    ``repairDatasetSessionInfo`` it also deletes documents from the live
    database. One such delete already cost this corpus a ``session`` document.
    These two tests fail the moment a fixture points ``ndi_dataset`` at
    ``DABROWSKA_PATH`` again.
    """

    def test_dataset_opens_a_private_copy(self, dabrowska_corpus, dabrowska_dataset):
        """The opened dataset is the tmp-dir copy, not the shared corpus."""
        shared = Path(os.path.realpath(DABROWSKA_PATH))
        opened = Path(os.path.realpath(dabrowska_dataset.getpath()))

        assert opened != shared, f"dataset was opened in place at the shared corpus {shared}"
        assert shared not in opened.parents, f"{opened} lives inside the shared corpus {shared}"
        assert opened == Path(os.path.realpath(dabrowska_corpus))

    def test_shared_corpus_is_not_mutated(self, dabrowska_dataset):
        """Constructing the dataset wrote nothing under the shared corpus.

        ``dabrowska_dataset`` brackets its ``ndi_dataset(...)`` call with a
        snapshot of the shared corpus; requesting the fixture here guarantees
        that has already happened.
        """
        assert not SHARED_CORPUS_WRITES, (
            "Constructing the ndi_dataset wrote to the SHARED Dabrowska corpus — "
            "a fixture is opening it in place again instead of the tmp-dir copy. "
            f"Entries changed under {DABROWSKA_PATH}: {SHARED_CORPUS_WRITES}"
        )


# ===========================================================================
# Class 1: TestDatasetLoading
# ===========================================================================


class TestDatasetLoading:
    """Validate dataset loading and document type counts."""

    def test_dataset_loads(self, dabrowska_dataset):
        """ndi_dataset object is created successfully."""
        assert dabrowska_dataset is not None

    @requires_intact_corpus
    def test_document_type_counts(self, dabrowska_dataset):
        """All 13+ document types have expected counts.

        Every type is checked and all mismatches are reported together — an
        early mismatch used to abort the loop and hide the types after it.
        """
        from ndi.fun.doc import getDocTypes

        doc_types, doc_counts = getDocTypes(dabrowska_dataset)
        actual = dict(zip(doc_types, doc_counts))

        mismatches: list[str] = []
        for dtype, expected in EXPECTED_TYPE_COUNTS.items():
            actual_count = actual.get(dtype, 0)
            if dtype == "session":
                if actual_count < expected:
                    mismatches.append(f"{dtype}: expected >= {expected}, got {actual_count}")
            elif actual_count != expected:
                mismatches.append(f"{dtype}: expected {expected}, got {actual_count}")

        assert not mismatches, "Document type count mismatches:\n  " + "\n  ".join(mismatches)

    @requires_intact_corpus
    def test_total_document_count(self, dabrowska_dataset):
        """Total documents >= 14,646."""
        from ndi.query import ndi_query

        docs = dabrowska_dataset.database_search(ndi_query("").isa("base"))
        assert (
            len(docs) >= EXPECTED_TOTAL_DOCUMENTS
        ), f"Expected >= {EXPECTED_TOTAL_DOCUMENTS}, got {len(docs)}"

    @requires_intact_corpus
    def test_session_docs_exist(self, dabrowska_dataset):
        """At least 3 session documents exist."""
        from ndi.query import ndi_query

        docs = dabrowska_dataset.database_search(ndi_query("").isa("session"))
        assert len(docs) >= EXPECTED_TYPE_COUNTS["session"]


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
        from ndi.fun.table import identifyMatchingRows

        row_ind = identifyMatchingRows(
            subject_table, "StrainName", "AVP-Cre", stringMatch="contains"
        )
        filtered = subject_table[row_ind]
        assert len(filtered) == 49, f"Expected 49 AVP-Cre, got {len(filtered)}"

    def test_filter_otr_cre(self, subject_table):
        """OTR-IRES-Cre filtering works."""
        from ndi.fun.table import identifyMatchingRows

        row_ind = identifyMatchingRows(
            subject_table, "StrainName", "OTR-IRES-Cre", stringMatch="contains"
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

    def test_moveColumnsLeft(self, subject_table, probe_summary, epoch_summary):
        """moveColumnsLeft reorders columns correctly."""
        from ndi.fun.table import join, moveColumnsLeft

        combined = join([subject_table, probe_summary, epoch_summary])
        reordered = moveColumnsLeft(combined, ["SubjectLocalIdentifier", "EpochNumber"])
        assert list(reordered.columns[:2]) == [
            "SubjectLocalIdentifier",
            "EpochNumber",
        ]

    def test_filter_by_approach(self, subject_table, probe_summary, epoch_summary):
        """Filter by ApproachName containing 'optogenetic' works."""
        from ndi.fun.table import identifyMatchingRows, join

        combined = join([subject_table, probe_summary, epoch_summary])
        row_ind = identifyMatchingRows(
            combined, "ApproachName", "optogenetic", stringMatch="contains"
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
        from ndi.query import ndi_query

        query = ndi_query("ontologyTableRow.variableNames").contains("ElevatedPlusMaze")
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
        from ndi.query import ndi_query

        query = ndi_query("ontologyTableRow.variableNames").contains("Fear_potentiatedStartle")
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

    def test_ontologyTableRowVars(self, dabrowska_dataset):
        """ontologyTableRowVars returns names, short names, nodes."""
        from ndi.fun.doc import ontologyTableRowVars

        names, short_names, nodes = ontologyTableRowVars(dabrowska_dataset)
        assert len(names) > 0
        assert len(names) == len(short_names) == len(nodes)

    def test_empty_ontology_lookup(self):
        """EMPTY ontology provider resolves treatment term."""
        from ndi.ontology import lookup as ontology_lookup

        result = ontology_lookup("EMPTY:0000074")
        assert result is not None
        assert result.name is not None
        assert len(result.name) > 0

    def test_name2variableName(self):
        """name2variableName produces correct PascalCase output."""
        from ndi.fun.name_utils import name2variableName

        assert (
            name2variableName("treatment: food restriction onset time")
            == "Treatment_FoodRestrictionOnsetTime"
        )
        assert (
            name2variableName("elevated plus maze: test duration")
            == "ElevatedPlusMaze_TestDuration"
        )
        assert (
            name2variableName("Optogenetic Tetanus Stimulation Target Location")
            == "OptogeneticTetanusStimulationTargetLocation"
        )

    def test_name2variableName_edge_cases(self):
        """name2variableName handles edge cases."""
        from ndi.fun.name_utils import name2variableName

        assert name2variableName("") == ""
        assert name2variableName("   ") == ""
        assert name2variableName("123abc") == "var_123abc"
        assert name2variableName("simple") == "Simple"
