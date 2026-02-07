# MATLAB-to-Python Test Mapping

This document maps every MATLAB unittest file from `ndi.unittest.*` to its Python
equivalent in `tests/matlab_tests/`. Use this for troubleshooting discrepancies
between the MATLAB and Python implementations.

## Overview

| Metric | Count |
|--------|-------|
| MATLAB test files (source) | 87 |
| Python test files (ported) | 17 |
| Python test classes | ~50 |
| Python test methods | ~405 |
| Intentionally skipped | ~5 (GUI, MATLAB-specific fixtures) |

The 87 MATLAB files consolidate into 17 Python files because related MATLAB test
classes (e.g., all 7 `+dataset/*.m` files) are grouped into a single Python module
(e.g., `test_dataset.py`).

---

## Batch 1: Dataset Tests

**Python file:** `tests/matlab_tests/test_dataset.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+dataset/testDatasetConstructor.m` | `TestDatasetConstructor` | `test_constructor_with_reference`, `test_constructor_path_only`, `test_two_datasets_have_different_ids` |
| `+dataset/buildDataset.m` | *(shared fixture in conftest.py)* | `build_dataset` fixture |
| `+dataset/testDatasetBuild.m` | `TestDatasetBuild` | `test_setup` — verifies Dataset+Session created with 5 demoNDI docs |
| `+dataset/testSessionList.m` | `TestSessionList` | `test_session_list_outputs` — verifies refs, IDs, session docs |
| `+dataset/testDeleteIngestedSession.m` | `TestDeleteIngestedSession` | `test_delete_success`, `test_delete_not_confirmed`, `test_delete_linked_session_error`, `test_delete_nonexistent_session` |
| `+dataset/testUnlinkSession.m` | `TestUnlinkSession` | `test_unlink_linked_session`, `test_unlink_with_remove_documents`, `test_unlink_ingested_session`, `test_unlink_nonexistent_session` |
| `+dataset/OldDatasetTest.m` | `TestOldDataset` | `test_open_existing_dataset` — backward compatibility |

---

## Batch 2: Session Tests

**Python file:** `tests/matlab_tests/test_session.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+session/buildSession.m` | *(shared fixture in conftest.py)* | `build_session` fixture |
| `+session/buildSessionNDRAxon.m` | *(not ported — NDR-specific)* | — |
| `+session/buildSessionNDRIntan.m` | *(not ported — NDR-specific)* | — |
| `+session/TestDeleteSession.m` | `TestDeleteSession` | `test_delete_no_confirm`, `test_delete_confirm`, `test_delete_preserves_data_files` |
| `+session/testIsIngestedInDataset.m` | `TestIsIngestedInDataset` | `test_standalone_session_not_in_dataset`, `test_ingested_session_in_dataset`, `test_linked_session_in_dataset` |
| *(new)* | `TestSessionBasics` | `test_session_creation`, `test_session_has_ndi_directory`, `test_session_reopens_with_same_id`, `test_session_requires_existing_directory`, `test_newdocument`, `test_creator_args` |

---

## Batch 3: Database Tests

**Python file:** `tests/matlab_tests/test_database.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+database/TestNDIDocument.m` | `TestNDIDocument` | `test_document_creation_and_io` — full create-add-search-read-binary workflow |
| `+database/TestNDIDocumentFields.m` | `TestNDIDocumentFields` | `test_field_discovery` — document field discovery from JSON schemas |
| `+database/TestNDIDocumentJSON.m` | `TestNDIDocumentJSON` | `test_single_json_definition` — parametrized over all JSON schema files |
| `+database/TestNDIDocumentPersistence.m` | `TestNDIDocumentPersistence` | `test_document_round_trip`, `test_multiple_document_types_persist` |
| `+database/TestNDIDocumentDiscovery.m` | `TestNDIDocumentDiscovery` | `test_document_discovery`, `test_schema_count` |
| `+database/TestDocComparison.m` | `TestDocComparison` | `test_construction`, `test_add_comparison_parameter`, `test_compare_documents`, `test_compare_mismatched_names` |

---

## Batch 4: Core Tests (Root-level)

**Python file:** `tests/matlab_tests/test_core.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `CacheTest.m` | `TestCache` | `test_cache_creation`, `test_add_and_lookup`, `test_remove`, `test_clear`, `test_fifo_replacement`, `test_lifo_replacement`, `test_error_replacement` |
| `QueryTest.m` | `TestQuery` | `test_all_query`, `test_none_query`, `test_exact_string_query`, `test_isa_query`, `test_and_query`, `test_or_query`, `test_query_integration` |
| `DocumentWriteTest.m` | `TestDocumentWrite` | `test_write_json`, `test_write_preserves_id` |
| `NDIFileNavigatorTest.m` | `TestFileNavigator` | `test_navigator_creation`, `test_navigator_no_epochs_in_empty_dir`, `test_navigator_finds_epochs` |

---

## Batch 5: Cloud API Tests

**Python file:** `tests/matlab_tests/test_cloud_api.py`

All cloud tests are **dual-mode**: mocked by default, live when `NDI_CLOUD_USERNAME`/`NDI_CLOUD_PASSWORD` env vars are set.

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+cloud/AuthTest.m` | `TestAuth` | `test_login_mocked`, `test_logout_mocked`, `test_login_live`, `test_logout_live` |
| `+cloud/DatasetsTest.m` | `TestDatasets` | `test_create_dataset_mocked`, `test_list_datasets_mocked`, `test_update_dataset_mocked`, `test_delete_dataset_mocked`, `test_dataset_lifecycle_live` |
| `+cloud/DocumentsTest.m` | `TestDocuments` | `test_add_document_mocked`, `test_get_document_mocked`, `test_update_document_mocked`, `test_delete_document_mocked`, `test_document_lifecycle_live` |
| `+cloud/FilesTest.m` | `TestFiles` | `test_get_upload_url_mocked`, `test_list_files_mocked`, `test_single_file_upload_download_live` |
| `+cloud/UserTest.m` | `TestUser` | `test_get_current_user_mocked`, `test_get_current_user_live` |
| `+cloud/DuplicatesTest.m` | *(covered in TestDocuments)* | `test_bulk_delete_mocked` |
| `+cloud/TestPublishWithDocsAndFiles.m` | *(covered in TestDatasets)* | `test_dataset_lifecycle_live` |
| `+cloud/FilesDifficult.m` | *(covered in TestFiles)* | — |
| `+cloud/InvalidDatasetTest.m` | `TestInvalidDataset` | `test_get_nonexistent_dataset_mocked`, `test_get_nonexistent_dataset_live` |
| `+cloud/testNdiQuery.m` | `TestNdiQuery` | `test_list_documents_mocked`, `test_get_document_by_id_mocked`, `test_ndi_query_mocked` |
| `+cloud/APIMessage.m` | *(helper, not ported)* | — |

---

## Batch 6: Cloud Sync Tests

**Python file:** `tests/matlab_tests/test_cloud_sync.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+cloud/+sync/BaseSyncTest.m` | *(base fixture logic in test setup)* | — |
| `+cloud/+sync/UploadNewTest.m` | `TestUploadNew` | `test_upload_new_mocked`, `test_upload_new_live` |
| `+cloud/+sync/DownloadNewTest.m` | `TestDownloadNew` | `test_download_new_mocked` |
| `+cloud/+sync/MirrorFromRemoteTest.m` | `TestMirrorFromRemote` | `test_mirror_from_remote_structure` |
| `+cloud/+sync/MirrorToRemoteTest.m` | `TestMirrorToRemote` | `test_mirror_to_remote_structure` |
| `+cloud/+sync/TwoWaySyncTest.m` | `TestTwoWaySync` | `test_two_way_sync_structure` |
| `+cloud/+sync/DatasetSessionIdFromDocsTest.m` | `TestDatasetSessionIdFromDocs` | `test_session_id_extraction` |
| `+cloud/+sync/ValidateTest.m` | `TestSyncValidate` | `test_validate_dataset_structure`, `test_validate_empty_dataset` |
| `+cloud/+sync/datasetDemo.m` | *(helper, not ported)* | — |
| `+cloud/+sync/emptyDataset.m` | *(helper, not ported)* | — |

---

## Batch 7: Cloud Compute Tests

**Python file:** `tests/matlab_tests/test_cloud_compute.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+cloud/+compute/ComputeTest.m` | `TestCompute` | `test_start_session_mocked`, `test_get_session_status_mocked`, `test_list_sessions_mocked`, `test_hello_world_flow_live` |
| `+cloud/+compute/ZombieTest.m` | `TestZombie` | `test_zombie_flow_mocked`, `test_zombie_flow_live` |

---

## Batch 8: DAQ Reader Tests

**Python file:** `tests/matlab_tests/test_daq.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+daq/+reader/mfdaqIntanTest.m` | `TestIntanReader` | `test_intan_reader_instantiation`, `test_intan_reader_channel_types`, `test_intan_reader_mocked_getchannels`, `test_intan_reader_live` |
| `+daq/+reader/mfdaqNDRAxonTest.m` | *(covered in TestEpochSampleTimeConversion)* | — |
| `+daq/+reader/mfdaqNDRIntanTest.m` | *(covered in TestEpochSampleTimeConversion)* | — |
| *(new — expanded)* | `TestEpochSampleTimeConversion` | `test_epochsamples2times_basic`, `test_roundtrip_samples_times`, etc. |
| *(new — expanded)* | `TestChannelUtils` | `test_channel_name_parse_ai`, `test_channel_name_parse_amp`, etc. |
| *(new — expanded)* | `TestChannelTypeStandardization` | `test_standardize_ai`, `test_channel_type_from_abbreviation`, etc. |
| *(new — expanded)* | `TestMFDAQReaderBase` | `test_underlying_datatype_analog`, `test_epochclock_returns_dev_local_time`, etc. |

---

## Batch 9: Fun Utilities Tests

**Python file:** `tests/matlab_tests/test_fun.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+fun/+doc/TestAllTypes.m` | `TestAllTypes` | `test_all_types_returns_nonempty_list`, `test_all_types_contains_known_types`, `test_all_types_sorted` |
| `+fun/+doc/TestFindFuid.m` | `TestFindFuid` | `test_find_known_fuid`, `test_find_fuid_not_found`, `test_find_fuid_in_populated_session` |
| `+fun/+doc/testDiff.m` | `TestDocDiff` | `test_identical_docs`, `test_property_mismatch`, `test_ignore_fields`, `test_dependencies_order_independence` |
| `+fun/+session/diffTest.m` | `TestSessionDiff` | `test_identical_sessions`, `test_docs_only_in_s1`, `test_mismatched_docs` |
| `+fun/+dataset/diffTest.m` | `TestDatasetDiff` | `test_identical_datasets`, `test_docs_only_in_dataset1`, `test_mismatched_datasets` |
| `+fun/+table/TestVStack.m` | `TestVStack` | `test_basic_stacking`, `test_no_common_columns`, `test_vstack_preserves_dtypes` |

---

## Batch 10: Probe Tests

**Python file:** `tests/matlab_tests/test_probe.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+probe/ProbeMapTest.m` | `TestProbeMap` | `test_init_probe_type_map`, `test_map_contains_expected_types`, `test_map_ntrode_class` |
| `+probe/ProbeTest.m` | `TestProbe` | `test_probe_instantiation`, `test_probe_with_session`, `test_probe_issyncgraphroot`, `test_probe_epochsetname` |

---

## Batch 11: Ingestion Tests

**Python file:** `tests/matlab_tests/test_ingestion.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+ingestion/ingestionIntan.m` | `TestIngestionPlan` | `test_ingest_plan_with_files`, `test_expell_plan_identifies_ingested_files` |
| `+ingestion/ingestionAxonNDR.m` | `TestIngestionExecution` | `test_ingest_copies_files`, `test_ingest_deletes_originals`, `test_expell_deletes_files` |
| `+ingestion/ingestionIntanNDR.m` | `TestIngestionFullPipeline` | `test_plan_and_execute`, `test_plan_execute_with_delete`, `test_expell_pipeline` |

---

## Batch 12: Calculator Tests

**Python file:** `tests/matlab_tests/test_calculator.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+calc/+example/testSimple.m` | `TestSimpleCalc` | `test_simple_calc_instantiation`, `test_simple_calc_doc_types`, `test_simple_calc_calculate`, `test_simple_calc_repr` |
| `+calc/+stimulus/testCalcTuningCurve.m` | `TestTuningCurveCalc` | `test_tuning_curve_instantiation`, `test_tuning_curve_doc_types`, `test_tuning_curve_calculate`, `test_tuning_curve_generate_mock_docs` |

---

## Batch 13: App Tests

**Python file:** `tests/matlab_tests/test_app.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+app/TestMarkGarbage.m` | `TestMarkGarbageInstantiation` | `test_create_without_session`, `test_create_with_session`, `test_inherits_from_app` |
| `+app/TestMarkGarbage.m` | `TestMarkGarbageMocked` | `test_markvalidinterval_calls_database_add`, `test_markvalidinterval_creates_correct_document`, `test_clearvalidinterval_removes_docs`, `test_mark_then_load_workflow`, `test_multiple_intervals_workflow` |

---

## Batch 14: Element Tests

**Python file:** `tests/matlab_tests/test_element.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+element/OneEpochTest.m` | `TestOneEpoch` | `test_oneepoch_creates_element`, `test_oneepoch_preserves_type`, `test_oneepoch_empty_epochs_raises` |
| *(expanded)* | `TestElementInstantiation` | `test_create_element_no_session`, `test_element_type_attribute`, `test_element_inherits_ido` |
| *(expanded)* | `TestElementEpochTable` | `test_epochtable_no_session`, `test_elementstring`, `test_epochsetname` |
| *(expanded)* | `TestMissingEpochs` | `test_no_missing_epochs`, `test_missing_epochs_detected` |
| *(expanded)* | `TestSpikesForProbe` | `test_creates_spike_element`, `test_invalid_epoch_raises` |
| *(expanded)* | `TestDownsampleTimeseries` | `test_downsample_basic`, `test_downsample_multichannel` |

---

## Batch 15: Ontology Tests

**Python file:** `tests/matlab_tests/test_ontology.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+ontology/TestOntologyLookup.m` | `TestOntologyResult` | `test_result_creation`, `test_result_bool_empty`, `test_result_to_dict` |
| `+ontology/TestOntologyLookup.m` | `TestOntologyLookupMocked` | `test_lookup_returns_ontology_result`, `test_lookup_no_colon_returns_empty`, `test_clear_cache_function` |
| `+ontology/TestOntologyLookup.m` | `TestOntologyLookupLive` | `test_lookup_ncbi_taxonomy`, `test_lookup_cell_ontology` (requires network) |

---

## Batch 16: Validator Tests

**Python file:** `tests/matlab_tests/test_validators.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+validators/mustBeIDTest.m` | `TestIDValidation` | `test_valid_id_format`, `test_ido_generates_valid_ids`, `test_ido_is_valid_accepts_ndi_format`, `test_ido_is_valid_rejects_invalid` |
| `+validators/TestMustBeCellArrayOfClass.m` | `TestDocumentValidation` | `test_document_type_validation`, `test_session_id_validation` |
| `+validators/mustBeEpochInputTest.m` | *(covered in TestDocumentValidation)* | `test_document_properties_structure` |
| `+validators/mustBeTextLikeTest.m` | *(MATLAB-specific, not ported)* | — |
| `+validators/mustBeNumericClassTest.m` | *(MATLAB-specific, not ported)* | — |
| `+validators/mustHaveRequiredColumnsTest.m` | *(MATLAB-specific, not ported)* | — |
| `+validators/mustMatchRegexTest.m` | *(MATLAB-specific, not ported)* | — |
| `+validators/mustBeCellArrayOfNdiSessionsTest.m` | *(MATLAB-specific, not ported)* | — |
| `+validators/mustBeCellArrayOfNonEmptyCharacterArraysTest.m` | *(MATLAB-specific, not ported)* | — |
| `+validators/test_mustBeClassnameOfType.m` | *(MATLAB-specific, not ported)* | — |

---

## Batch 17: Utility Tests

**Python file:** `tests/matlab_tests/test_utils.py`

| MATLAB File | Python Class | Key Tests |
|------------|-------------|-----------|
| `+util/TestRehydrateJSONNanNull.m` | *(covered in TestTimestamp)* | — |
| `+util/TestUnwrapTableCellContent.m` | *(covered in TestNameUtils)* | — |
| `+util/getHexDiffFromFileObjTest.m` | *(not ported — hex diff is MATLAB-specific)* | — |
| `+util/hexDiffBytesTest.m` | *(not ported — hex diff is MATLAB-specific)* | — |
| `+util/testHexDiff.m` | *(not ported — hex diff is MATLAB-specific)* | — |
| `+util/testHexDump.m` | *(not ported — hex diff is MATLAB-specific)* | — |
| `+util/test_datestamp2datetime.m` | `TestTimestamp` | `test_timestamp_format`, `test_timestamp_starts_with_year` |
| *(expanded)* | `TestChannelNameUtils` | `test_analog_in`, `test_amp_channel`, `test_no_digits_raises` |
| *(expanded)* | `TestNameUtils` | `test_name2variable_simple`, `test_name2variable_with_special_chars` |
| *(expanded)* | `TestPseudoRandomInt` | `test_pseudorandomint_is_positive`, `test_pseudorandomint_uniqueness` |
| *(expanded)* | `TestAllTypes` | `test_all_types_returns_list`, `test_all_types_contains_base` |

---

## Not Ported (Intentionally Skipped)

| MATLAB File | Reason |
|------------|--------|
| `+gui/+component/TestProgressBarWindow.m` | GUI test — no Python equivalent |
| `+setup/+NDIMaker/SimpleTestCreator.m` | MATLAB test helper, not a test |
| `+setup/+NDIMaker/testSubjectMaker.m` | MATLAB-specific fixture |
| `+fixtures/CreateWhiteMatter*.m` (3 files) | Test fixtures used by MATLAB tests |
| `+cloud/APIMessage.m` | MATLAB helper class, not a test |
| `+cloud/+sync/datasetDemo.m` | MATLAB helper |
| `+cloud/+sync/emptyDataset.m` | MATLAB helper |
| `+session/buildSessionNDRAxon.m` | NDR-specific fixture (no NDR in Python) |
| `+session/buildSessionNDRIntan.m` | NDR-specific fixture (no NDR in Python) |
| `+validators/mustBeTextLikeTest.m` | MATLAB type system test |
| `+validators/mustBeNumericClassTest.m` | MATLAB type system test |
| `+validators/mustHaveRequiredColumnsTest.m` | MATLAB table-specific test |
| `+validators/mustMatchRegexTest.m` | MATLAB regex validation test |
| `+validators/mustBeCellArrayOf*.m` (2 files) | MATLAB cell array tests |
| `+validators/test_mustBeClassnameOfType.m` | MATLAB class hierarchy test |
| `+util/getHexDiffFromFileObjTest.m` | MATLAB hex utility |
| `+util/hexDiffBytesTest.m` | MATLAB hex utility |
| `+util/testHexDiff.m` | MATLAB hex utility |
| `+util/testHexDump.m` | MATLAB hex utility |

---

## Production Bugs Found During Porting

The MATLAB test porting process uncovered **16 production bugs** in Document schema
paths. These were all caused by `Document('type_name')` not finding the schema file
because it doesn't search subdirectories — the full path from `database_documents/`
must be specified. **All 16 bugs have been fixed** in the same commit that added these tests.

| File | Bug | Fix |
|------|-----|-----|
| `src/ndi/daq/system.py` | `Document('daqsystem')` | `Document('daq/daqsystem')` |
| `src/ndi/daq/reader_base.py` | `Document('daqreader')` | `Document('daq/daqreader')` |
| `src/ndi/daq/reader_base.py` | `Document('daqreader_epochdata_ingested')` | `Document('ingestion/daqreader_epochdata_ingested')` |
| `src/ndi/daq/reader/spikeinterface_adapter.py` | `Document('daqreader')` | `Document('daq/daqreader')` |
| `src/ndi/daq/metadatareader/__init__.py` | `Document('daqmetadatareader')` | `Document('daq/daqmetadatareader')` |
| `src/ndi/daq/metadatareader/__init__.py` | `Document('daqmetadatareader_epochdata_ingested')` | `Document('ingestion/daqmetadatareader_epochdata_ingested')` |
| `src/ndi/file/navigator/__init__.py` | `Document('filenavigator')` | `Document('daq/filenavigator')` |
| `src/ndi/file/navigator/__init__.py` | `Document('epochfiles_ingested')` | `Document('ingestion/epochfiles_ingested')` |
| `src/ndi/time/syncgraph.py` | `Document('syncgraph')` | `Document('daq/syncgraph')` |
| `src/ndi/time/syncrule_base.py` | `Document('syncrule')` | `Document('daq/syncrule')` |
| `src/ndi/probe/__init__.py` | `Document('probe')` | `Document('element')` (no probe.json exists) |
| `src/ndi/app/markgarbage.py` | `Document('apps/valid_interval')` | `Document('apps/markgarbage/valid_interval')` |
| `src/ndi/openminds_convert.py` | `Document('openminds')` | `Document('metadata/openminds')` |
| `src/ndi/openminds_convert.py` | `Document('openminds_subject')` | `Document('metadata/openminds_subject')` |
| `src/ndi/openminds_convert.py` | `Document('openminds_element')` | `Document('metadata/openminds_element')` |
| `src/ndi/openminds_convert.py` | `Document('openminds_stimulus')` | `Document('metadata/openminds_stimulus')` |

### Additional Bug: `markgarbage.py` getattr vs dict.get

`document_properties` returns a dict, but `getattr(dict, 'field')` always returns
`None` silently. Fixed to use `dict.get('field')`.

### `make_species_strain_sex` Rewrite

`src/ndi/fun/doc.py:make_species_strain_sex` was completely rewritten to use the
official `openminds` Python library (v0.4.0) instead of non-existent
`Document('openminds_species')` schemas. The function now:
1. Creates real openMINDS objects (`Species`, `Strain`, `BiologicalSex`)
2. Converts them via `openminds_obj_to_ndi_document()` — matching the MATLAB flow

---

## Cloud Orchestration Tests (`tests/test_cloud_gaps_extra.py`)

Five cloud orchestration functions previously had zero or mock-only coverage. These
are now tested with mocked API calls in `tests/test_cloud_gaps_extra.py` (19 tests).
These tests also uncovered and fixed **4 additional production bugs**:

| File | Bug | Fix |
|------|-----|-----|
| `cloud/upload.py` | `get_collection_upload_url` (wrong name) | `get_file_collection_upload_url` |
| `cloud/upload.py` | `get_upload_url(client, dataset_id, file_uid)` missing org_id | `get_upload_url(client, client.config.org_id, dataset_id, file_uid)` |
| `cloud/internal.py` | `doc.set_value(...)` (doesn't exist) | `doc._set_nested_property(...)` |
| `cloud/internal.py` | `remote.get('cloud_dataset_id')` (wrong field) | `remote.get('dataset_id')` (matches schema) |

**True end-to-end verification still requires live cloud credentials** — the mocked
tests validate the wiring and argument passing but not the actual API responses.

---

## Live Cloud Tests Not Yet Verified

The cloud tests use two skip markers with increasing privilege levels:

| Marker | Condition | Tests |
|--------|-----------|-------|
| `@requires_cloud` | `NDI_CLOUD_USERNAME` env var is set | Login/logout, list datasets, get user, get published/unpublished, get branches, invalid dataset, sync upload |
| `@requires_upload` | `requires_cloud` + account has `canUploadDataset=true` | Dataset lifecycle (create/update/delete), document lifecycle (add/get/update/delete), file upload/download, bulk operations, compute hello-world |

**None of the `_live` tests have been run against the real NDI cloud API yet.** They
are all currently skipped in CI because no credentials are configured. The mocked
versions pass and mirror the MATLAB test logic, but the live versions need to be
validated with real credentials and an account that has upload permissions.

To run them:

```bash
# Read-only cloud tests (list, get, auth)
NDI_CLOUD_USERNAME=user NDI_CLOUD_PASSWORD=pass \
  pytest tests/matlab_tests/test_cloud_api.py -v -k "live"

# Full cloud tests including dataset/document creation (needs canUploadDataset=true)
NDI_CLOUD_USERNAME=user NDI_CLOUD_PASSWORD=pass \
  pytest tests/matlab_tests/test_cloud_api.py tests/matlab_tests/test_cloud_sync.py \
         tests/matlab_tests/test_cloud_compute.py -v -k "live"
```

---

## Running the Tests

```bash
cd /path/to/NDI-python
source venv/bin/activate

# Run ONLY the MATLAB-ported tests
pytest tests/matlab_tests/ -v --tb=short

# Run ALL tests (existing + MATLAB ports)
pytest tests/ -v --tb=short

# Run cloud tests with real credentials
NDI_CLOUD_USERNAME=xxx NDI_CLOUD_PASSWORD=yyy pytest tests/matlab_tests/ -v -m cloud_live

# Run a specific batch
pytest tests/matlab_tests/test_dataset.py -v
pytest tests/matlab_tests/test_cloud_api.py -v
```
