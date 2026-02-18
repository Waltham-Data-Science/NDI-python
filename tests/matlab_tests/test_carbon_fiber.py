"""
Tests for NDI-python against the Carbon fiber microelectrode dataset.

Dataset: 743 JSON documents + 66 element_epoch binary files (9.7 GB)
Source: NDI Cloud dataset 668b0539f13096e04f1feccd

This is an extracellular electrophysiology dataset with:
  - Carbon fiber microelectrode recordings (n-trode)
  - Spike-sorted neurons (jrclust)
  - Visual stimulus responses (orientation, spatial/temporal frequency)
  - Tuning curve computations

Binary files are NOT downloaded — documents carry presigned S3 URLs
in file_info and the data is fetched on demand when readtimeseries()
is called.  All tests here operate on the document metadata only.

Mirrors MATLAB analysis workflow:
  1. Load dataset
  2. Inspect sessions and elements
  3. Query neurons and waveforms
  4. Examine stimulus response scalars
  5. Verify tuning curves (orientation, spatial freq, temporal freq)
  6. Check cross-document referential integrity
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Dataset paths — skip entire file if not downloaded locally
# ---------------------------------------------------------------------------

CARBON_FIBER_DOCS = Path(
    os.path.expanduser("~/Documents/ndi-projects/datasets/carbon-fiber/documents")
)

pytestmark = pytest.mark.skipif(
    not CARBON_FIBER_DOCS.exists(),
    reason="Carbon fiber dataset not downloaded locally",
)

# Expected document type counts
EXPECTED_TYPE_COUNTS = {
    "stimulus_response_scalar_parameters_basic": 138,
    "stimulus_response_scalar": 138,
    "tuningcurve_calc": 126,
    "temporal_frequency_tuning_calc": 58,
    "openminds": 57,
    "element_epoch": 46,
    "oridirtuning_calc": 34,
    "spatial_frequency_tuning_calc": 34,
    "element": 20,
    "neuron_extracellular": 17,
    "openminds_stimulus": 10,
    "syncrule_mapping": 10,
    "epochfiles_ingested": 10,
    "daqreader_mfdaq_epochdata_ingested": 10,
    "stimulus_presentation": 5,
    "control_stimulus_ids": 5,
    "daqmetadatareader_epochdata_ingested": 5,
    "filenavigator": 3,
    "daqreader": 3,
    "daqsystem": 3,
    "session": 2,
    "syncrule": 2,
    "jrclust_clusters": 2,
    "daqmetadatareader": 1,
    "syncgraph": 1,
    "subject": 1,
    "dataset_session_info": 1,
    "metadata_editor": 1,
}

TOTAL_JSON_DOCS = 743


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def carbon_fiber_dataset(tmp_path_factory):
    """Load 743 JSON docs into a Dataset object (once per session)."""
    from ndi.cloud.orchestration import load_dataset_from_json_dir

    target = tmp_path_factory.mktemp("carbon_fiber_ds")
    dataset = load_dataset_from_json_dir(
        CARBON_FIBER_DOCS,
        target_folder=target,
        verbose=True,
    )
    return dataset


@pytest.fixture(scope="session")
def all_docs_raw():
    """Load all raw JSON dicts (no Dataset overhead)."""
    docs = []
    for f in sorted(CARBON_FIBER_DOCS.glob("*.json")):
        with open(f) as fh:
            docs.append(json.load(fh))
    return docs


# ===========================================================================
# Class 1: TestDatasetLoading
# ===========================================================================


class TestDatasetLoading:
    """Validate the bulk load of 743 documents."""

    def test_load_document_count(self, carbon_fiber_dataset):
        """At least 743 documents load (Dataset init adds 1 session doc)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("base"))
        assert len(docs) >= TOTAL_JSON_DOCS, f"Expected >= {TOTAL_JSON_DOCS}, got {len(docs)}"

    def test_document_type_counts(self, carbon_fiber_dataset):
        """All 27 document types have expected counts."""
        from ndi.fun.doc import get_doc_types

        doc_types, doc_counts = get_doc_types(carbon_fiber_dataset)
        actual = dict(zip(doc_types, doc_counts))
        for dtype, expected in EXPECTED_TYPE_COUNTS.items():
            actual_count = actual.get(dtype, 0)
            if dtype == "session":
                # Dataset init may add 1 extra session doc
                assert (
                    actual_count >= expected
                ), f"{dtype}: expected >= {expected}, got {actual_count}"
            else:
                assert actual_count == expected, f"{dtype}: expected {expected}, got {actual_count}"

    def test_get_doc_types(self, carbon_fiber_dataset):
        """get_doc_types returns sorted types and matching counts."""
        from ndi.fun.doc import get_doc_types

        doc_types, doc_counts = get_doc_types(carbon_fiber_dataset)
        assert doc_types == sorted(doc_types)
        # 27 from JSON + session doc auto-created by Dataset init = 28
        assert len(doc_types) >= 27
        assert sum(doc_counts) >= TOTAL_JSON_DOCS

    def test_all_documents_have_base_id(self, all_docs_raw):
        """Every document has a base.id field."""
        missing = [
            doc.get("document_class", {}).get("class_name", "?")
            for doc in all_docs_raw
            if not doc.get("base", {}).get("id")
        ]
        assert len(missing) == 0, f"{len(missing)} documents missing base.id: {missing[:5]}"


# ===========================================================================
# Class 2: TestSessionDiscovery
# ===========================================================================


class TestSessionDiscovery:
    """Inspect sessions and infrastructure documents."""

    def test_session_count(self, carbon_fiber_dataset):
        """At least 2 session documents (recording + publication)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("session"))
        assert len(docs) >= 2

    def test_session_references(self, carbon_fiber_dataset):
        """Session references include the recording date."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("session"))
        refs = [doc.document_properties.get("session", {}).get("reference", "") for doc in docs]
        assert "2019-11-19" in refs, f"Recording session not found in {refs}"

    def test_subject_exists(self, carbon_fiber_dataset):
        """Single subject document exists."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("subject"))
        assert len(docs) == 1

    def test_subject_local_identifier(self, carbon_fiber_dataset):
        """Subject has a local identifier from vhlab.org."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("subject"))
        lid = docs[0].document_properties.get("subject", {}).get("local_identifier", "")
        assert "vhlab.org" in lid, f"Expected vhlab.org in identifier, got '{lid}'"


# ===========================================================================
# Class 3: TestElements
# ===========================================================================


class TestElements:
    """Element document structure and types."""

    def test_element_count(self, carbon_fiber_dataset):
        """20 element documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("element"))
        assert len(docs) == 20

    def test_element_types(self, carbon_fiber_dataset):
        """Three element types: n-trode, spikes, stimulator."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("element"))
        types = {doc.document_properties.get("element", {}).get("type", "") for doc in docs}
        assert types == {"n-trode", "spikes", "stimulator"}

    def test_ntrode_elements(self, carbon_fiber_dataset):
        """2 n-trode (carbonfiber) elements."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("element"))
        ntrodes = [
            doc
            for doc in docs
            if doc.document_properties.get("element", {}).get("type") == "n-trode"
        ]
        assert len(ntrodes) == 2
        names = {doc.document_properties.get("element", {}).get("name", "") for doc in ntrodes}
        assert names == {"carbonfiber"}

    def test_spike_elements(self, carbon_fiber_dataset):
        """17 spike-sorted elements (one per neuron)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("element"))
        spikes = [
            doc
            for doc in docs
            if doc.document_properties.get("element", {}).get("type") == "spikes"
        ]
        assert len(spikes) == 17

    def test_stimulator_element(self, carbon_fiber_dataset):
        """1 visual stimulator element."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("element"))
        stims = [
            doc
            for doc in docs
            if doc.document_properties.get("element", {}).get("type") == "stimulator"
        ]
        assert len(stims) == 1
        assert stims[0].document_properties.get("element", {}).get("name") == "vhvis_spike2"

    def test_element_depends_on_subject(self, carbon_fiber_dataset):
        """All elements depend on the subject document."""
        from ndi.query import Query

        elements = carbon_fiber_dataset.database_search(Query("").isa("element"))
        subjects = carbon_fiber_dataset.database_search(Query("").isa("subject"))
        subject_id = subjects[0].document_properties.get("base", {}).get("id", "")

        for elem in elements:
            deps = elem.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            subject_deps = [d for d in deps if d.get("name") == "subject_id"]
            assert len(subject_deps) == 1, "Element missing subject_id dependency"
            assert subject_deps[0]["value"] == subject_id


# ===========================================================================
# Class 4: TestNeurons
# ===========================================================================


class TestNeurons:
    """Neuron extracellular document structure."""

    def test_neuron_count(self, carbon_fiber_dataset):
        """17 neuron_extracellular documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("neuron_extracellular"))
        assert len(docs) == 17

    def test_neuron_waveform_shape(self, carbon_fiber_dataset):
        """All neurons have 21 samples x 16 channels waveforms."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("neuron_extracellular"))
        for doc in docs:
            ne = doc.document_properties.get("neuron_extracellular", {})
            assert ne.get("number_of_samples_per_channel") == 21
            assert ne.get("number_of_channels") == 16

    def test_neuron_has_mean_waveform(self, carbon_fiber_dataset):
        """All neurons have non-empty mean waveform arrays."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("neuron_extracellular"))
        for doc in docs:
            ne = doc.document_properties.get("neuron_extracellular", {})
            waveform = ne.get("mean_waveform", [])
            assert len(waveform) > 0, "Neuron missing mean_waveform"

    def test_neuron_depends_on_element_and_clusters(self, carbon_fiber_dataset):
        """Every neuron depends on element_id and spike_clusters_id."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("neuron_extracellular"))
        for doc in docs:
            deps = doc.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            dep_names = {d.get("name", "") for d in deps}
            assert "element_id" in dep_names
            assert "spike_clusters_id" in dep_names

    def test_neuron_app_is_jrclust(self, carbon_fiber_dataset):
        """All neurons were sorted with JRCLUST."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("neuron_extracellular"))
        for doc in docs:
            app = doc.document_properties.get("app", {})
            assert app.get("name") == "JRCLUST"


# ===========================================================================
# Class 5: TestStimulusResponses
# ===========================================================================


class TestStimulusResponses:
    """Stimulus response scalar documents."""

    def test_stimulus_response_count(self, carbon_fiber_dataset):
        """138 stimulus_response_scalar documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("stimulus_response_scalar"))
        assert len(docs) == 138

    def test_response_types(self, carbon_fiber_dataset):
        """Three response types: mean, F1, F2 (46 each)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("stimulus_response_scalar"))
        type_counts: Counter[str] = Counter()
        for doc in docs:
            rt = doc.document_properties.get("stimulus_response_scalar", {}).get(
                "response_type", ""
            )
            type_counts[rt] += 1

        assert type_counts["mean"] == 46
        assert type_counts["F1"] == 46
        assert type_counts["F2"] == 46

    def test_stimulus_response_has_responses(self, carbon_fiber_dataset):
        """Each stimulus_response_scalar has stimid and response arrays."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("stimulus_response_scalar"))
        for doc in docs[:10]:  # sample first 10
            srs = doc.document_properties.get("stimulus_response_scalar", {})
            responses = srs.get("responses", {})
            assert "stimid" in responses, "Missing stimid in responses"
            assert len(responses["stimid"]) > 0

    def test_stimulus_response_depends_on_five_docs(self, carbon_fiber_dataset):
        """Each response depends on element, stimulator, control, presentation, and parameters."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("stimulus_response_scalar"))
        expected_deps = {
            "element_id",
            "stimulator_id",
            "stimulus_control_id",
            "stimulus_presentation_id",
            "stimulus_response_scalar_parameters_id",
        }
        for doc in docs[:10]:
            deps = doc.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            dep_names = {d.get("name", "") for d in deps}
            assert expected_deps.issubset(dep_names), f"Missing deps: {expected_deps - dep_names}"


# ===========================================================================
# Class 6: TestTuningCurves
# ===========================================================================


class TestTuningCurves:
    """Tuning curve computation documents."""

    def test_tuningcurve_count(self, carbon_fiber_dataset):
        """126 tuningcurve_calc documents total."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("tuningcurve_calc"))
        assert len(docs) == 126

    def test_tuningcurve_types(self, carbon_fiber_dataset):
        """Three tuning curve types: Orientation (34), Spatial (34), Temporal (58)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("tuningcurve_calc"))
        label_counts: Counter[str] = Counter()
        for doc in docs:
            tc = doc.document_properties.get("stimulus_tuningcurve", {})
            labels = tc.get("independent_variable_label", [])
            label_counts[tuple(labels)] += 1

        assert label_counts[("Orientation",)] == 34
        assert label_counts[("Spatial_Frequency",)] == 34
        assert label_counts[("Temporal_Frequency",)] == 58

    def test_orientation_tuning_has_12_directions(self, carbon_fiber_dataset):
        """Orientation tuning curves sample 12 directions (0-330 deg, 30 deg steps)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("tuningcurve_calc"))
        for doc in docs:
            tc = doc.document_properties.get("stimulus_tuningcurve", {})
            if tc.get("independent_variable_label") == ["Orientation"]:
                values = tc.get("independent_variable_value", [])
                assert values == list(range(0, 360, 30)), f"Expected 0-330 by 30, got {values}"
                assert len(tc.get("response_mean", [])) == 12
                assert len(tc.get("response_stddev", [])) == 12
                break

    def test_tuningcurve_has_control_response(self, carbon_fiber_dataset):
        """Tuning curves include control response mean."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("tuningcurve_calc"))
        for doc in docs[:10]:
            tc = doc.document_properties.get("stimulus_tuningcurve", {})
            assert "control_response_mean" in tc, "Missing control_response_mean"

    def test_oridirtuning_count(self, carbon_fiber_dataset):
        """34 orientation/direction tuning analysis documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("oridirtuning_calc"))
        assert len(docs) == 34

    def test_oridirtuning_has_compass_coordinates(self, carbon_fiber_dataset):
        """Ori/dir tuning uses compass coordinates."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("oridirtuning_calc"))
        for doc in docs:
            odt = doc.document_properties.get("orientation_direction_tuning", {})
            props = odt.get("properties", {})
            assert props.get("coordinates") == "compass"

    def test_spatial_frequency_tuning_count(self, carbon_fiber_dataset):
        """34 spatial frequency tuning documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("spatial_frequency_tuning_calc"))
        assert len(docs) == 34

    def test_temporal_frequency_tuning_count(self, carbon_fiber_dataset):
        """58 temporal frequency tuning documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("temporal_frequency_tuning_calc"))
        assert len(docs) == 58

    def test_temporal_frequency_has_5_frequencies(self, carbon_fiber_dataset):
        """Temporal frequency tuning samples 5 frequencies (1,2,4,8,16 Hz)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("temporal_frequency_tuning_calc"))
        for doc in docs[:5]:
            tft = doc.document_properties.get("temporal_frequency_tuning", {})
            tc = tft.get("tuning_curve", {})
            freqs = tc.get("temporal_frequency", [])
            assert freqs == [1, 2, 4, 8, 16], f"Expected [1,2,4,8,16], got {freqs}"


# ===========================================================================
# Class 7: TestEpochStructure
# ===========================================================================


class TestEpochStructure:
    """Epoch and DAQ infrastructure documents."""

    def test_element_epoch_count(self, carbon_fiber_dataset):
        """46 element_epoch documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("element_epoch"))
        assert len(docs) == 46

    def test_element_epoch_has_file_info(self, all_docs_raw):
        """element_epoch documents carry file_info with S3 URLs."""
        epoch_docs = [
            d
            for d in all_docs_raw
            if d.get("document_class", {}).get("class_name") == "element_epoch"
        ]
        with_files = 0
        for doc in epoch_docs:
            fi = doc.get("files", {}).get("file_info")
            if fi:
                with_files += 1
                # Verify URL structure
                if isinstance(fi, dict):
                    locs = fi.get("locations", {})
                    if isinstance(locs, dict):
                        assert locs.get("location_type") == "url"
                        assert "s3" in locs.get("location", "")

        # Not all element_epochs necessarily have files (some may be metadata-only)
        assert with_files > 0, "No element_epoch documents have file_info"

    def test_epochfiles_ingested_count(self, carbon_fiber_dataset):
        """10 epochfiles_ingested documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("epochfiles_ingested"))
        assert len(docs) == 10

    def test_stimulus_presentation_count(self, carbon_fiber_dataset):
        """5 stimulus_presentation documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("stimulus_presentation"))
        assert len(docs) == 5


# ===========================================================================
# Class 8: TestOpenMinds
# ===========================================================================


class TestOpenMinds:
    """OpenMINDS metadata documents."""

    def test_openminds_count(self, carbon_fiber_dataset):
        """57 openminds + 10 openminds_stimulus = 67 total (isa matches subclasses)."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("openminds"))
        # isa("openminds") matches both openminds (57) and openminds_stimulus (10)
        assert len(docs) == 67

    def test_openminds_stimulus_count(self, carbon_fiber_dataset):
        """10 openminds_stimulus documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("openminds_stimulus"))
        assert len(docs) == 10


# ===========================================================================
# Class 9: TestCrossDocumentRelationships
# ===========================================================================


class TestCrossDocumentRelationships:
    """Referential integrity checks."""

    def test_depends_on_references_exist(self, carbon_fiber_dataset):
        """All depends_on values point to existing document IDs."""
        from ndi.query import Query

        all_docs = carbon_fiber_dataset.database_search(Query("").isa("base"))
        all_ids = {doc.document_properties.get("base", {}).get("id", "") for doc in all_docs}

        missing = 0
        checked = 0
        for doc in all_docs:
            deps = doc.document_properties.get("depends_on", [])
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

        assert checked > 0, "No depends_on references found"
        assert missing == 0, f"{missing}/{checked} depends_on references point to missing docs"

    def test_session_id_consistency(self, carbon_fiber_dataset):
        """All docs share one of 2 session_ids."""
        from ndi.query import Query

        all_docs = carbon_fiber_dataset.database_search(Query("").isa("base"))
        session_ids: set[str] = set()
        for doc in all_docs:
            sid = doc.document_properties.get("base", {}).get("session_id", "")
            if sid:
                session_ids.add(sid)
        # 2 original + 1 from Dataset init
        assert len(session_ids) >= 2, f"Expected >= 2 session_ids, got {session_ids}"
        assert len(session_ids) <= 5, f"Too many session_ids ({len(session_ids)})"

    def test_neuron_element_chain(self, carbon_fiber_dataset):
        """Each neuron -> element -> subject chain is valid."""
        from ndi.query import Query

        neurons = carbon_fiber_dataset.database_search(Query("").isa("neuron_extracellular"))
        elements = carbon_fiber_dataset.database_search(Query("").isa("element"))
        element_ids = {doc.document_properties.get("base", {}).get("id", "") for doc in elements}

        for neuron in neurons:
            deps = neuron.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            elem_dep = [d for d in deps if d.get("name") == "element_id"]
            assert len(elem_dep) == 1, "Neuron missing element_id dependency"
            assert elem_dep[0]["value"] in element_ids, "Neuron points to non-existent element"

    def test_tuningcurve_depends_on_stimulus_response(self, carbon_fiber_dataset):
        """Each tuning curve depends on a stimulus_response_scalar document."""
        from ndi.query import Query

        tcs = carbon_fiber_dataset.database_search(Query("").isa("tuningcurve_calc"))
        sr_docs = carbon_fiber_dataset.database_search(Query("").isa("stimulus_response_scalar"))
        sr_ids = {doc.document_properties.get("base", {}).get("id", "") for doc in sr_docs}

        for tc in tcs:
            deps = tc.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            sr_dep = [d for d in deps if d.get("name") == "stimulus_response_scalar_id"]
            assert len(sr_dep) == 1, "Tuning curve missing stimulus_response_scalar_id"
            assert sr_dep[0]["value"] in sr_ids, "Tuning curve points to non-existent SR doc"


# ===========================================================================
# Class 10: TestDAQInfrastructure
# ===========================================================================


class TestDAQInfrastructure:
    """DAQ system, reader, and navigator documents."""

    def test_daqsystem_count(self, carbon_fiber_dataset):
        """3 daqsystem documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("daqsystem"))
        assert len(docs) == 3

    def test_daqreader_count(self, carbon_fiber_dataset):
        """3 daqreader documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("daqreader"))
        assert len(docs) == 3

    def test_filenavigator_count(self, carbon_fiber_dataset):
        """3 filenavigator documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("filenavigator"))
        assert len(docs) == 3

    def test_syncgraph_exists(self, carbon_fiber_dataset):
        """Single syncgraph document."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("syncgraph"))
        assert len(docs) == 1

    def test_syncrule_count(self, carbon_fiber_dataset):
        """2 syncrule documents."""
        from ndi.query import Query

        docs = carbon_fiber_dataset.database_search(Query("").isa("syncrule"))
        assert len(docs) == 2
