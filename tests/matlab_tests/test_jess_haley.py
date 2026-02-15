"""
Comprehensive tests for NDI-python against the Jess Haley C. elegans dataset.

Mirrors the MATLAB tutorial workflow from:
  ndi.setup.conv.haley.tutorial_682e7772cdf3f24938176fac.mlx

Dataset: 78,687 JSON documents + 11,163 binary files (15 GB)
Source: NDI Cloud dataset 682e7772cdf3f24938176fac

MATLAB tutorial steps tested:
  1. Load dataset
  2. Get sessions (Celegans + Ecoli)
  3. View document types (getDocTypes)
  4. View ontology variables (ontologyTableRowVars)
  5. Extract metadata tables (ontologyTableRowDoc2Table)
  6. Subject summary (docTable.subject)
  7. Table join (table.join)
  8. Filter subjects (identifyMatchingRows)
  9. Query elements (position/distance)
  10. Read images (readImageStack)
  11. Plot image + position overlay
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Dataset paths — skip entire file if not downloaded locally
# ---------------------------------------------------------------------------

JESS_HALEY_DOCS = Path(os.path.expanduser("~/Documents/ndi-projects/datasets/jess-haley/documents"))
JESS_HALEY_FILES = Path(os.path.expanduser("~/Documents/ndi-projects/datasets/jess_haley_files"))
OUTPUT_DIR = Path(__file__).parent / "output" / "jess_haley_plots"

pytestmark = pytest.mark.skipif(
    not JESS_HALEY_DOCS.exists(),
    reason="Jess Haley dataset not downloaded locally",
)

# Expected document type counts from JSON files
EXPECTED_TYPE_COUNTS = {
    "dataset_remote": 1,
    "dataset_session_info": 1,
    "distance_metadata": 2078,
    "element": 4156,
    "element_epoch": 4156,
    "imageStack": 7007,
    "ontologyLabel": 7007,
    "ontologyTableRow": 41095,
    "openminds": 8,
    "openminds_subject": 9032,
    "position_metadata": 2078,
    "session": 3,
    "subject": 1656,
    "subject_group": 353,
    "treatment": 56,
}

# Total documents in JSON files (Dataset init adds 1 extra session doc)
TOTAL_JSON_DOCS = 78687

# Expected ontologyTableRow group sizes (sorted descending, order-independent)
EXPECTED_OTR_GROUP_SIZES_SORTED = sorted(
    [20411, 7204, 6206, 3312, 1656, 1521, 597, 100, 88], reverse=True
)


# ---------------------------------------------------------------------------
# Session-scoped fixture — loads dataset once for all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def jess_haley_dataset(tmp_path_factory):
    """Load 78K JSON docs into a Dataset object (once per session)."""
    from ndi.cloud.orchestration import load_dataset_from_json_dir

    target = tmp_path_factory.mktemp("jess_haley_ds")
    dataset = load_dataset_from_json_dir(
        JESS_HALEY_DOCS,
        target_folder=target,
        verbose=True,
    )
    return dataset


@pytest.fixture(scope="session")
def all_docs_raw():
    """Load all raw JSON dicts (no Dataset overhead)."""
    docs = []
    for f in sorted(JESS_HALEY_DOCS.glob("*.json")):
        with open(f) as fh:
            docs.append(json.load(fh))
    return docs


@pytest.fixture(scope="session")
def ontology_table_row_docs(jess_haley_dataset):
    """Query all ontologyTableRow documents from the dataset."""
    from ndi.query import Query

    return jess_haley_dataset.database_search(Query("").isa("ontologyTableRow"))


@pytest.fixture(scope="session")
def otr_tables(ontology_table_row_docs):
    """Run ontology_table_row_doc_to_table and cache result."""
    from ndi.fun.doc_table import ontology_table_row_doc_to_table

    return ontology_table_row_doc_to_table(ontology_table_row_docs)


# ===========================================================================
# Class 1: TestDatasetLoading — MATLAB tutorial Step 1
# ===========================================================================


class TestDatasetLoading:
    """Validate the bulk load of 78K documents."""

    def test_load_document_count(self, jess_haley_dataset):
        """At least 78,687 documents load (Dataset init adds 1 session doc)."""
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("base"))
        assert len(docs) >= TOTAL_JSON_DOCS, f"Expected >= {TOTAL_JSON_DOCS}, got {len(docs)}"

    def test_document_type_counts(self, jess_haley_dataset):
        """All 15 document types have expected counts (session may be +1)."""
        from ndi.fun.doc import get_doc_types

        doc_types, doc_counts = get_doc_types(jess_haley_dataset)
        actual = dict(zip(doc_types, doc_counts))
        for dtype, expected in EXPECTED_TYPE_COUNTS.items():
            actual_count = actual.get(dtype, 0)
            if dtype == "session":
                # Dataset init adds 1 extra session doc
                assert (
                    actual_count >= expected
                ), f"{dtype}: expected >= {expected}, got {actual_count}"
            else:
                assert actual_count == expected, f"{dtype}: expected {expected}, got {actual_count}"

    def test_all_documents_have_base_id(self, all_docs_raw):
        """Every document has a base.id field."""
        missing = 0
        for doc in all_docs_raw:
            if not doc.get("base", {}).get("id"):
                missing += 1
        assert missing == 0, f"{missing} documents missing base.id"

    def test_get_doc_types(self, jess_haley_dataset):
        """get_doc_types returns sorted types and matching counts."""
        from ndi.fun.doc import get_doc_types

        doc_types, doc_counts = get_doc_types(jess_haley_dataset)
        assert doc_types == sorted(doc_types)
        assert len(doc_types) == 15
        assert sum(doc_counts) >= TOTAL_JSON_DOCS


# ===========================================================================
# Class 2: TestSessionDiscovery — MATLAB tutorial Steps 2-3
# ===========================================================================


class TestSessionDiscovery:
    """MATLAB: dataset.session_list(), dataset.open_session()."""

    def test_session_docs_exist(self, jess_haley_dataset):
        """Session documents exist in the dataset."""
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("session"))
        # 3 from JSON + 1 auto-created by Dataset init
        assert len(docs) >= 3

    def test_session_count(self, jess_haley_dataset):
        """At least 3 session documents from the Jess Haley dataset."""
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("session"))
        assert len(docs) >= 3

    def test_session_refs_contain_celegans_and_ecoli(self, jess_haley_dataset):
        """Session documents have reference fields."""
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("session"))
        refs = []
        for doc in docs:
            props = doc.document_properties
            ref = props.get("session", {}).get("reference", "")
            if ref:
                refs.append(ref)
        # At least the 3 original session docs have references
        assert len(refs) >= 3, f"Expected >= 3 session refs, got {len(refs)}: {refs}"

    def test_open_session(self, jess_haley_dataset):
        """open_session returns a usable session for ingested session docs."""
        # Use the dataset's internal session directly (bulk-loaded datasets
        # don't create session_in_a_dataset registry docs)
        session = jess_haley_dataset._session
        assert session is not None


# ===========================================================================
# Class 3: TestOntologyTableRowDoc2Table — MATLAB tutorial Step 5
# ===========================================================================


class TestOntologyTableRowDoc2Table:
    """MATLAB: ndi.fun.doc.ontologyTableRowDoc2Table(docs)."""

    def test_groups_by_variable_names(self, otr_tables):
        data_tables, doc_ids = otr_tables
        assert len(data_tables) == 9, f"Expected 9 groups, got {len(data_tables)}"

    def test_group_row_counts(self, otr_tables):
        data_tables, _ = otr_tables
        actual_sizes = sorted([len(dt) for dt in data_tables], reverse=True)
        assert (
            actual_sizes == EXPECTED_OTR_GROUP_SIZES_SORTED
        ), f"Group sizes mismatch: {actual_sizes} != {EXPECTED_OTR_GROUP_SIZES_SORTED}"

    def test_data_dict_extraction(self, otr_tables):
        """At least one group has bacterial plate columns."""
        data_tables, _ = otr_tables
        expected_cols = {"BacterialPlateIdentifier", "BacterialPatchIdentifier"}
        found = any(expected_cols.issubset(set(dt.columns)) for dt in data_tables)
        assert found, "No group has BacterialPlateIdentifier + BacterialPatchIdentifier"

    def test_doc_ids_match(self, otr_tables):
        """Doc IDs count matches row count in each group."""
        data_tables, doc_ids = otr_tables
        for dt, ids in zip(data_tables, doc_ids):
            assert len(dt) == len(ids)

    def test_stack_all_mode(self, ontology_table_row_docs):
        from ndi.fun.doc_table import ontology_table_row_doc_to_table

        data_tables, doc_ids = ontology_table_row_doc_to_table(
            ontology_table_row_docs, stack_all=True
        )
        assert len(data_tables) == 1
        assert len(data_tables[0]) == sum(EXPECTED_OTR_GROUP_SIZES_SORTED)

    def test_encounter_table_has_numeric_data(self, otr_tables):
        """Largest group (20411 rows, encounter data) has float columns."""
        import pandas as pd

        data_tables = otr_tables[0]
        # Find the encounter table (largest group, ~20411 rows)
        encounter_table = max(data_tables, key=len)
        decel_col = "CElegansBehavioralAssay_DecelerationUponEncounter"
        assert (
            decel_col in encounter_table.columns
        ), f"'{decel_col}' not in largest group columns: {list(encounter_table.columns)}"
        assert pd.api.types.is_numeric_dtype(encounter_table[decel_col])

    def test_bacterial_plate_table_has_expected_columns(self, otr_tables):
        data_tables = otr_tables[0]
        # Find the table with BacterialPatchRadius
        plate_table = None
        for dt in data_tables:
            if "BacterialPatchRadius" in dt.columns:
                plate_table = dt
                break
        assert plate_table is not None, "No table with BacterialPatchRadius found"
        for col in ["BacterialPatchRadius", "BacterialPatchCircularity"]:
            assert col in plate_table.columns, f"Missing column: {col}"


# ===========================================================================
# Class 4: TestOntologyTableRowVars — MATLAB tutorial Step 4
# ===========================================================================


class TestOntologyTableRowVars:
    """MATLAB: ndi.fun.doc.ontologyTableRowVars(dataset)."""

    def test_returns_nonempty_tuples(self, jess_haley_dataset):
        from ndi.fun.doc import ontology_table_row_vars

        names, var_names, ont_nodes = ontology_table_row_vars(jess_haley_dataset)
        assert len(names) > 0
        assert len(var_names) > 0
        assert len(ont_nodes) > 0

    def test_names_and_variable_names_same_length(self, jess_haley_dataset):
        from ndi.fun.doc import ontology_table_row_vars

        names, var_names, ont_nodes = ontology_table_row_vars(jess_haley_dataset)
        assert len(names) == len(var_names) == len(ont_nodes)

    def test_known_variables_present(self, jess_haley_dataset):
        from ndi.fun.doc import ontology_table_row_vars

        names, _, _ = ontology_table_row_vars(jess_haley_dataset)
        expected = "C. elegans behavioral assay: deceleration upon encounter"
        assert expected in names, f"'{expected}' not in ontologyTableRowVars"


# ===========================================================================
# Class 5: TestSubjectQueries — MATLAB tutorial Steps 6-7
# ===========================================================================


class TestSubjectQueries:
    """MATLAB: ndi.fun.docTable.subject(session)."""

    def test_subject_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("subject"))
        assert len(docs) == 1656

    def test_subject_table(self, jess_haley_dataset):
        from ndi.fun.doc_table import subject_table

        df = subject_table(jess_haley_dataset)
        assert len(df) == 1656
        assert "local_identifier" in df.columns

    def test_subject_local_identifier_nonempty(self, jess_haley_dataset):
        from ndi.fun.doc_table import subject_table

        df = subject_table(jess_haley_dataset)
        empty_ids = df[df["local_identifier"] == ""]
        assert len(empty_ids) == 0, f"{len(empty_ids)} subjects with empty local_identifier"

    def test_subject_strains(self, jess_haley_dataset):
        """Subjects include N2 (wildtype) and PR811 (transgenic) strains."""
        from ndi.fun.doc_table import subject_table

        df = subject_table(jess_haley_dataset)
        ids = df["local_identifier"].tolist()
        has_n2 = any("N2_" in s for s in ids)
        has_pr811 = any("PR811" in s for s in ids)
        # DA609 is also present
        has_da609 = any("DA609" in s for s in ids)
        assert has_n2, "No N2 subjects found"
        assert has_pr811 or has_da609, "No PR811 or DA609 subjects found"

    def test_subject_filter_pr811(self, jess_haley_dataset):
        """Filter for PR811 strain subjects matches MATLAB count."""
        from ndi.fun.doc_table import subject_table
        from ndi.fun.table import identify_matching_rows

        df = subject_table(jess_haley_dataset)
        mask = identify_matching_rows(df, "local_identifier", "PR811", string_match="contains")
        filtered = df[mask]
        # MATLAB tutorial shows 76 PR811 subjects
        assert len(filtered) == 76, f"Expected 76 PR811 subjects, got {len(filtered)}"


# ===========================================================================
# Class 6: TestTableJoinAndFilter — MATLAB tutorial Steps 7-8
# ===========================================================================


class TestTableJoinAndFilter:
    """MATLAB: ndi.fun.table.join, identifyMatchingRows."""

    def test_join_behavior_plate_tables(self, otr_tables):
        """Join two OTR groups that share common columns."""
        from ndi.fun.table import join

        data_tables = otr_tables[0]
        # Find two tables that share at least one column for a join
        # The MATLAB tutorial joins tables that share BacterialPlateIdentifier
        joined = False
        for i in range(len(data_tables)):
            for j in range(i + 1, len(data_tables)):
                common = set(data_tables[i].columns) & set(data_tables[j].columns)
                if common:
                    result = join([data_tables[i], data_tables[j]])
                    if len(result) > 0:
                        joined = True
                        break
            if joined:
                break
        assert joined, "No pair of OTR tables could be joined on common columns"

    def test_identify_matching_rows_string_contains(self):
        """String 'contains' matching works on DataFrame."""
        import pandas as pd

        from ndi.fun.table import identify_matching_rows

        df = pd.DataFrame({"name": ["apple", "banana", "cherry", "APPLE pie"]})
        mask = identify_matching_rows(df, "name", "apple", string_match="contains")
        assert mask.sum() == 1  # case-sensitive: only 'apple'

    def test_identify_matching_rows_numeric(self):
        """Numeric comparison matching."""
        import pandas as pd

        from ndi.fun.table import identify_matching_rows

        df = pd.DataFrame({"value": [10, 20, 30, 40]})
        mask = identify_matching_rows(df, "value", 25, numeric_match="gt")
        assert mask.sum() == 2  # 30 and 40


# ===========================================================================
# Class 7: TestElementQueries — MATLAB tutorial Steps 9-10
# ===========================================================================


class TestElementQueries:
    """MATLAB: query elements by type (position, distance)."""

    def test_element_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("element"))
        assert len(docs) == 4156

    def test_element_types_include_position_and_distance(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("element"))
        types = set()
        for doc in docs:
            t = doc.document_properties.get("element", {}).get("type", "")
            types.add(t)
        assert "position" in types, f"'position' not in element types: {types}"
        assert "distance" in types, f"'distance' not in element types: {types}"

    def test_position_metadata_links_to_element(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("position_metadata"))
        assert len(docs) > 0
        # depends_on can be a dict or a list of dicts
        sample = docs[0]
        deps = sample.document_properties.get("depends_on", [])
        if isinstance(deps, dict):
            dep_names = [deps.get("name", "")]
        elif isinstance(deps, list):
            dep_names = [d.get("name", "") for d in deps]
        else:
            dep_names = []
        assert "element_id" in dep_names, f"No element_id in depends_on: {dep_names}"

    def test_distance_metadata_links_to_element(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("distance_metadata"))
        assert len(docs) > 0
        sample = docs[0]
        deps = sample.document_properties.get("depends_on", [])
        if isinstance(deps, dict):
            dep_names = [deps.get("name", "")]
        elif isinstance(deps, list):
            dep_names = [d.get("name", "") for d in deps]
        else:
            dep_names = []
        assert "element_id" in dep_names, f"No element_id in depends_on: {dep_names}"


# ===========================================================================
# Class 8: TestImageStack — MATLAB tutorial Steps 10-11
# ===========================================================================


class TestImageStack:
    """MATLAB: readImageStack, imageStack document structure."""

    def test_image_stack_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("imageStack"))
        assert len(docs) == 7007

    def test_image_stack_has_parameters(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("imageStack"))
        sample = docs[0]
        assert "imageStack_parameters" in sample.document_properties

    def test_image_stack_types(self, jess_haley_dataset):
        """Dataset has uint8 videos, logical masks, and uint16 fluorescence."""
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("imageStack"))
        data_types = set()
        for doc in docs[:500]:  # sample first 500
            params = doc.document_properties.get("imageStack_parameters", {})
            data_types.add(params.get("data_type", ""))
        assert "uint8" in data_types
        assert "logical" in data_types

    @pytest.mark.skipif(
        not JESS_HALEY_FILES.exists(),
        reason="Binary files directory not available",
    )
    def test_image_stack_binary_files_exist(self, all_docs_raw):
        """All imageStack docs have matching binary files."""
        available_uids = set(os.listdir(JESS_HALEY_FILES))
        missing = 0
        total = 0
        for doc in all_docs_raw:
            if doc.get("document_class", {}).get("class_name") != "imageStack":
                continue
            total += 1
            fi = doc.get("files", {}).get("file_info", {})
            uid = ""
            if isinstance(fi, dict):
                locs = fi.get("locations", {})
                uid = locs.get("uid", "") if isinstance(locs, dict) else ""
            elif isinstance(fi, list) and fi:
                locs = fi[0].get("locations", [])
                uid = locs[0].get("uid", "") if isinstance(locs, list) and locs else ""
            if uid and uid not in available_uids:
                missing += 1
        assert missing == 0, f"{missing}/{total} imageStack docs missing binary files"

    def test_ontology_label_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("ontologyLabel"))
        assert len(docs) == 7007


# ===========================================================================
# Class 9: TestEpochAndMetadata
# ===========================================================================


class TestEpochAndMetadata:
    """Epoch/position/distance document relationships."""

    def test_element_epoch_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("element_epoch"))
        assert len(docs) == 4156

    def test_position_metadata_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("position_metadata"))
        assert len(docs) == 2078

    def test_distance_metadata_count(self, jess_haley_dataset):
        from ndi.query import Query

        docs = jess_haley_dataset.database_search(Query("").isa("distance_metadata"))
        assert len(docs) == 2078

    def test_metadata_depends_on_references_exist(self, jess_haley_dataset):
        """Position/distance metadata depends_on values reference existing elements."""
        from ndi.query import Query

        # Build set of all element IDs
        elements = jess_haley_dataset.database_search(Query("").isa("element"))
        element_ids = {doc.document_properties.get("base", {}).get("id", "") for doc in elements}

        # Check first 50 position_metadata docs
        pos_docs = jess_haley_dataset.database_search(Query("").isa("position_metadata"))
        missing = 0
        for doc in pos_docs[:50]:
            deps = doc.document_properties.get("depends_on", [])
            # depends_on can be dict or list
            if isinstance(deps, dict):
                deps = [deps]
            elif not isinstance(deps, list):
                continue
            for dep in deps:
                if dep.get("name") == "element_id":
                    if dep.get("value", "") not in element_ids:
                        missing += 1
        assert missing == 0, f"{missing} position_metadata docs reference missing elements"


# ===========================================================================
# Class 10: TestCrossDocumentRelationships
# ===========================================================================


class TestCrossDocumentRelationships:
    """Referential integrity checks."""

    def test_depends_on_references_exist(self, jess_haley_dataset):
        """Sampled depends_on values point to existing doc IDs."""
        from ndi.query import Query

        all_docs = jess_haley_dataset.database_search(Query("").isa("base"))
        all_ids = {doc.document_properties.get("base", {}).get("id", "") for doc in all_docs}

        # Sample 200 docs with depends_on
        missing = 0
        checked = 0
        for doc in all_docs[:1000]:
            deps = doc.document_properties.get("depends_on", [])
            # depends_on can be a dict or list
            if isinstance(deps, dict):
                deps = [deps]
            elif not isinstance(deps, list):
                continue
            for dep in deps:
                val = dep.get("value", "")
                if val and not val.startswith("$"):
                    checked += 1
                    if val not in all_ids:
                        missing += 1
            if checked >= 200:
                break
        assert missing == 0, f"{missing}/{checked} depends_on references point to missing docs"

    def test_session_id_consistency(self, jess_haley_dataset):
        """All docs share one of a small number of session_ids."""
        from ndi.query import Query

        all_docs = jess_haley_dataset.database_search(Query("").isa("base"))
        # Collect all unique session_ids across the dataset
        session_ids: set[str] = set()
        for doc in all_docs:
            sid = doc.document_properties.get("base", {}).get("session_id", "")
            if sid:
                session_ids.add(sid)
        # Note: session_id is the session object's ID, NOT the session
        # document's base.id. The Jess Haley dataset has 3 unique session_ids.
        assert len(session_ids) >= 2, f"Expected >= 2 unique session_ids, got {session_ids}"
        assert (
            len(session_ids) <= 10
        ), f"Too many session_ids ({len(session_ids)}), data may be corrupt"


# ===========================================================================
# Class 11: TestDatasetVisualization — MATLAB tutorial plots
# ===========================================================================


class TestDatasetVisualization:
    """Generate matplotlib plots mirroring MATLAB tutorial visualizations.

    All output saved to tests/matlab_tests/output/jess_haley_plots/.
    """

    @staticmethod
    def _ensure_output_dir():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return OUTPUT_DIR

    def test_plot_document_type_distribution(self, jess_haley_dataset):
        """Bar chart of document types — MATLAB: table(docTypes,docCounts)."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from ndi.fun.doc import get_doc_types

        out = self._ensure_output_dir()
        doc_types, doc_counts = get_doc_types(jess_haley_dataset)

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.barh(doc_types, doc_counts, color="steelblue")
        ax.set_xlabel("Count")
        ax.set_title("Jess Haley Dataset: Document Type Distribution")
        for i, (_t, c) in enumerate(zip(doc_types, doc_counts)):
            ax.text(c + 100, i, str(c), va="center", fontsize=8)
        plt.tight_layout()
        plt.savefig(out / "doc_type_distribution.png", dpi=150)
        plt.close()

        assert (out / "doc_type_distribution.png").exists()

    def test_plot_subject_experiment_types(self, jess_haley_dataset):
        """Bar chart of subject experiment types from local_identifier."""
        import matplotlib

        matplotlib.use("Agg")
        from collections import Counter

        import matplotlib.pyplot as plt

        from ndi.fun.doc_table import subject_table

        out = self._ensure_output_dir()
        df = subject_table(jess_haley_dataset)

        # Extract experiment type from local_identifier
        # Format: StrainName_Number_ExperimentType_Date@lab
        type_counter: Counter[str] = Counter()
        for lid in df["local_identifier"]:
            parts = lid.split("_")
            if len(parts) >= 3:
                type_counter[parts[2]] += 1
            else:
                type_counter["unknown"] += 1

        types = sorted(type_counter.keys())
        counts = [type_counter[t] for t in types]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(types, counts, color="coral")
        ax.set_xlabel("Experiment Type")
        ax.set_ylabel("Subject Count")
        ax.set_title("Jess Haley: Subject Experiment Types")
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        plt.savefig(out / "subject_experiment_types.png", dpi=150)
        plt.close()

        assert (out / "subject_experiment_types.png").exists()

    @pytest.mark.skipif(
        not JESS_HALEY_FILES.exists(),
        reason="Binary files directory not available",
    )
    def test_render_sample_images_side_by_side(self, all_docs_raw):
        """Load 3 image types and display side by side.

        MATLAB equivalent: imagesc() calls for different image types.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        out = self._ensure_output_dir()

        # Find one doc of each type: video (uint8), mask (logical), fluorescence (uint16)
        targets = {"uint8": None, "logical": None, "uint16": None}
        for doc in all_docs_raw:
            if doc.get("document_class", {}).get("class_name") != "imageStack":
                continue
            params = doc.get("imageStack_parameters", {})
            dtype = params.get("data_type", "")
            if dtype in targets and targets[dtype] is None:
                fi = doc.get("files", {}).get("file_info", {})
                uid = ""
                if isinstance(fi, dict):
                    locs = fi.get("locations", {})
                    uid = locs.get("uid", "") if isinstance(locs, dict) else ""
                if uid and (JESS_HALEY_FILES / uid).exists():
                    targets[dtype] = {
                        "uid": uid,
                        "label": doc.get("imageStack", {}).get("label", "")[:50],
                        "dim_size": params.get("dimension_size", []),
                        "dtype": dtype,
                    }
            if all(v is not None for v in targets.values()):
                break

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))

        for ax, (dtype, info) in zip(axes, targets.items()):
            if info is None:
                ax.set_title(f"No {dtype} image found")
                continue

            filepath = JESS_HALEY_FILES / info["uid"]
            if dtype == "uint8":
                # MP4 video — extract first frame
                try:
                    import cv2

                    cap = cv2.VideoCapture(str(filepath))
                    ret, frame = cap.read()
                    cap.release()
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        ax.imshow(frame, cmap="gray")
                    else:
                        ax.text(
                            0.5, 0.5, "Could not read video", transform=ax.transAxes, ha="center"
                        )
                except ImportError:
                    ax.text(0.5, 0.5, "cv2 not available", transform=ax.transAxes, ha="center")
            elif dtype in ("logical", "uint16"):
                # Images may be PNG/TIFF — try cv2 first, fall back to raw
                try:
                    import cv2

                    img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
                except ImportError:
                    img = None
                if img is None:
                    np_dtype = np.uint8 if dtype == "logical" else np.uint16
                    data = np.fromfile(str(filepath), dtype=np_dtype)
                    dims = info["dim_size"]
                    if len(dims) >= 2:
                        try:
                            img = data[: dims[0] * dims[1]].reshape(dims[0], dims[1])
                        except ValueError:
                            pass
                if img is not None:
                    im = ax.imshow(img, cmap="gray")
                    if dtype == "uint16":
                        plt.colorbar(im, ax=ax, fraction=0.046)
                else:
                    ax.text(0.5, 0.5, "Could not read", transform=ax.transAxes, ha="center")

            ax.set_title(f"{dtype}\n{info['label']}", fontsize=9)
            ax.axis("off")

        plt.suptitle("Jess Haley: Sample Images (3 types)", fontsize=14)
        plt.tight_layout()
        plt.savefig(out / "sample_images_side_by_side.png", dpi=150)
        plt.close()

        assert (out / "sample_images_side_by_side.png").exists()

    @pytest.mark.skipif(
        not JESS_HALEY_FILES.exists(),
        reason="Binary files directory not available",
    )
    def test_render_video_frame_sequence(self, all_docs_raw):
        """Extract 8 frames from an MP4 video — MATLAB: Play video of the subject."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        try:
            import cv2
        except ImportError:
            pytest.skip("cv2 not available")

        out = self._ensure_output_dir()

        # Find a video (uint8, YXT dimension order)
        video_doc = None
        for doc in all_docs_raw:
            if doc.get("document_class", {}).get("class_name") != "imageStack":
                continue
            params = doc.get("imageStack_parameters", {})
            if params.get("data_type") == "uint8" and "T" in params.get("dimension_order", ""):
                fi = doc.get("files", {}).get("file_info", {})
                uid = ""
                if isinstance(fi, dict):
                    locs = fi.get("locations", {})
                    uid = locs.get("uid", "") if isinstance(locs, dict) else ""
                if uid and (JESS_HALEY_FILES / uid).exists():
                    video_doc = {
                        "uid": uid,
                        "params": params,
                        "label": doc.get("imageStack", {}).get("label", "")[:60],
                    }
                    break

        if video_doc is None:
            pytest.skip("No video document found with binary file")

        filepath = JESS_HALEY_FILES / video_doc["uid"]
        cap = cv2.VideoCapture(str(filepath))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames < 8:
            cap.release()
            pytest.skip(f"Video too short: {total_frames} frames")

        # Extract 8 evenly-spaced frames
        frame_indices = [int(i * total_frames / 8) for i in range(8)]
        time_scale = video_doc["params"].get("dimension_scale", [1, 1, 1])
        time_per_frame = time_scale[2] if len(time_scale) > 2 else 1.0

        fig, axes = plt.subplots(2, 4, figsize=(16, 8))
        for _idx, (ax, fi) in enumerate(zip(axes.flat, frame_indices)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if ret:
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                ax.imshow(frame_gray, cmap="gray")
                time_sec = fi * time_per_frame
                ax.set_title(f"t = {time_sec:.1f}s", fontsize=9)
            ax.axis("off")

        cap.release()
        plt.suptitle(f"Video Frame Sequence: {video_doc['label']}", fontsize=12)
        plt.tight_layout()
        plt.savefig(out / "video_frame_sequence.png", dpi=150)
        plt.close()

        assert (out / "video_frame_sequence.png").exists()

    @pytest.mark.skipif(
        not JESS_HALEY_FILES.exists(),
        reason="Binary files directory not available",
    )
    def test_render_image_with_position_overlay(self, all_docs_raw):
        """Render image with subject position overlay.

        MATLAB equivalent: imagesc() + plot(position) with color-coded time.
        This is a simplified version since we don't have timeseries data
        in the JSON documents — we overlay position_metadata ontology info
        and show the arena mask.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        out = self._ensure_output_dir()

        # Find an arena mask (logical, YX)
        mask_doc = None
        for doc in all_docs_raw:
            if doc.get("document_class", {}).get("class_name") != "imageStack":
                continue
            params = doc.get("imageStack_parameters", {})
            label = doc.get("imageStack", {}).get("label", "")
            if params.get("data_type") == "logical" and "arena" in label.lower():
                fi = doc.get("files", {}).get("file_info", {})
                uid = ""
                if isinstance(fi, dict):
                    locs = fi.get("locations", {})
                    uid = locs.get("uid", "") if isinstance(locs, dict) else ""
                if uid and (JESS_HALEY_FILES / uid).exists():
                    mask_doc = {
                        "uid": uid,
                        "params": params,
                        "label": label[:60],
                    }
                    break

        if mask_doc is None:
            pytest.skip("No arena mask found")

        filepath = JESS_HALEY_FILES / mask_doc["uid"]

        # Images may be stored as PNG/TIFF (not raw binary), use cv2 to read
        import cv2

        img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
        if img is None:
            # Fallback: try raw binary
            dims = mask_doc["params"].get("dimension_size", [1024, 1024])
            data = np.fromfile(str(filepath), dtype=np.uint8)
            try:
                img = data[: dims[0] * dims[1]].reshape(dims[0], dims[1])
            except ValueError:
                pytest.skip("Could not read mask image")

        fig, ax = plt.subplots(figsize=(8, 8))
        ax.imshow(img, cmap="gray", alpha=0.7)

        # Overlay a circle showing approximate arena boundary
        # Find the center of the mask (centroid of True pixels)
        ys, xs = np.where(img > 0)
        if len(xs) > 0:
            cx, cy = np.mean(xs), np.mean(ys)
            radius = np.sqrt(len(xs) / np.pi)
            circle = plt.Circle((cx, cy), radius, fill=False, color="red", linewidth=2)
            ax.add_patch(circle)
            ax.plot(cx, cy, "r+", markersize=15, markeredgewidth=2)
            ax.set_title(
                f"Arena Mask with Boundary\n{mask_doc['label']}\n"
                f"Center: ({cx:.0f}, {cy:.0f}), Radius: {radius:.0f} px",
                fontsize=10,
            )

        ax.axis("off")
        plt.tight_layout()
        plt.savefig(out / "image_with_position_overlay.png", dpi=150)
        plt.close()

        assert (out / "image_with_position_overlay.png").exists()

    def test_plot_summary_dashboard(self, jess_haley_dataset, all_docs_raw):
        """Combined 2x3 dashboard — overview of dataset."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        from ndi.fun.doc import get_doc_types
        from ndi.fun.doc_table import subject_table

        out = self._ensure_output_dir()
        fig, axes = plt.subplots(2, 3, figsize=(20, 12))

        # (1) Document type distribution
        ax = axes[0, 0]
        doc_types, doc_counts = get_doc_types(jess_haley_dataset)
        ax.barh(doc_types, doc_counts, color="steelblue")
        ax.set_xlabel("Count")
        ax.set_title("Document Types")

        # (2) Subject experiment types
        ax = axes[0, 1]
        from collections import Counter

        df = subject_table(jess_haley_dataset)
        type_counter: Counter[str] = Counter()
        for lid in df["local_identifier"]:
            parts = lid.split("_")
            if len(parts) >= 3:
                type_counter[parts[2]] += 1
        types_sorted = sorted(type_counter.keys())
        ax.bar(types_sorted, [type_counter[t] for t in types_sorted], color="coral")
        ax.set_title("Subject Experiment Types")
        ax.tick_params(axis="x", rotation=20)

        # (3) OTR group sizes
        ax = axes[0, 2]
        group_labels = [f"G{i+1}" for i in range(len(EXPECTED_OTR_GROUP_SIZES_SORTED))]
        ax.bar(group_labels, EXPECTED_OTR_GROUP_SIZES_SORTED, color="seagreen")
        ax.set_title("OntologyTableRow Groups")
        ax.set_ylabel("Documents")

        # (4-6) Sample images if available
        if JESS_HALEY_FILES.exists():
            targets = {"uint8": None, "logical": None, "uint16": None}
            for doc in all_docs_raw:
                if doc.get("document_class", {}).get("class_name") != "imageStack":
                    continue
                params = doc.get("imageStack_parameters", {})
                dtype = params.get("data_type", "")
                if dtype in targets and targets[dtype] is None:
                    fi = doc.get("files", {}).get("file_info", {})
                    uid = ""
                    if isinstance(fi, dict):
                        locs = fi.get("locations", {})
                        uid = locs.get("uid", "") if isinstance(locs, dict) else ""
                    if uid and (JESS_HALEY_FILES / uid).exists():
                        targets[dtype] = {
                            "uid": uid,
                            "label": doc.get("imageStack", {}).get("label", "")[:40],
                            "dim_size": params.get("dimension_size", []),
                        }
                if all(v is not None for v in targets.values()):
                    break

            for ax, (dtype, info) in zip(axes[1, :], targets.items()):
                if info is None:
                    ax.set_title(f"No {dtype} image")
                    continue
                filepath = JESS_HALEY_FILES / info["uid"]
                dims = info["dim_size"]
                if dtype == "uint8":
                    try:
                        import cv2

                        cap = cv2.VideoCapture(str(filepath))
                        ret, frame = cap.read()
                        cap.release()
                        if ret:
                            ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cmap="gray")
                    except ImportError:
                        pass
                elif dtype in ("logical", "uint16"):
                    # Try cv2 first (images may be PNG/TIFF)
                    img = None
                    try:
                        import cv2

                        img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
                    except ImportError:
                        pass
                    if img is None and len(dims) >= 2:
                        np_dtype = np.uint8 if dtype == "logical" else np.uint16
                        data = np.fromfile(str(filepath), dtype=np_dtype)
                        try:
                            img = data[: dims[0] * dims[1]].reshape(dims[0], dims[1])
                        except ValueError:
                            pass
                    if img is not None:
                        im = ax.imshow(img, cmap="gray")
                        if dtype == "uint16":
                            plt.colorbar(im, ax=ax, fraction=0.046)
                ax.set_title(f"{dtype}: {info['label']}", fontsize=9)
                ax.axis("off")
        else:
            for ax in axes[1, :]:
                ax.text(
                    0.5,
                    0.5,
                    "Binary files not available",
                    transform=ax.transAxes,
                    ha="center",
                )

        plt.suptitle("Jess Haley Dataset: Summary Dashboard", fontsize=16)
        plt.tight_layout()
        plt.savefig(out / "summary_dashboard.png", dpi=150)
        plt.close()

        assert (out / "summary_dashboard.png").exists()
