# MATLAB to Python Mapping

Complete reference mapping every MATLAB NDI function/class to its Python equivalent.

**MATLAB source**: [VH-Lab/NDI-matlab](https://github.com/VH-Lab/NDI-matlab)
**Python port**: [Waltham-Data-Science/NDI-python](https://github.com/Waltham-Data-Science/NDI-python)

---

## Core

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.document` | `ndi.Document` | `ndi.document` |
| `ndi.query` | `ndi.Query` | `ndi.query` |
| `ndi.ido` | `ndi.Ido` | `ndi.ido` |
| `ndi.database` | `ndi.Database` | `ndi.database` |
| `ndi.version` | `ndi.version()` | `ndi.__init__` |
| `ndi.validate` | `ndi.validate` | `ndi.validate` |
| `ndi.documentservice` | `ndi.DocumentService` | `ndi.documentservice` |

## Time Synchronization

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.time.clocktype` | `ndi.time.ClockType` | `ndi.time.clocktype` |
| `ndi.time.timemapping` | `ndi.time.TimeMapping` | `ndi.time.timemapping` |
| `ndi.time.timereference` | `ndi.time.TimeReference` | `ndi.time.timereference` |
| `ndi.time.syncgraph` | `ndi.time.SyncGraph` | `ndi.time.syncgraph` |
| `ndi.time.syncrule` | `ndi.time.SyncRule` | `ndi.time.syncrule` |
| `ndi.time.syncrule_filematch` | `ndi.time.syncrule.FileMatchRule` | `ndi.time.syncrule.filematch` |

## DAQ (Data Acquisition)

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.daq.system` | `ndi.daq.DAQSystem` | `ndi.daq.system` |
| `ndi.daq.system.mfdaq` | `ndi.daq.MFDAQSystem` | `ndi.daq.system_mfdaq` |
| `ndi.daq.daqsystemstring` | `ndi.daq.DAQSystemString` | `ndi.daq.daqsystemstring` |
| `ndi.daq.reader` | `ndi.daq.DAQReader` | `ndi.daq.reader` |
| `ndi.daq.reader.mfdaq` | `ndi.daq.MFDAQReader` | `ndi.daq.reader.mfdaq` |
| `ndi.daq.reader.mfdaq.intan` | `ndi.daq.reader.mfdaq.IntanReader` | `ndi.daq.reader.mfdaq.intan` |
| `ndi.daq.reader.mfdaq.blackrock` | `ndi.daq.reader.mfdaq.BlackrockReader` | `ndi.daq.reader.mfdaq.blackrock` |
| `ndi.daq.reader.mfdaq.cedspike2` | `ndi.daq.reader.mfdaq.CEDSpike2Reader` | `ndi.daq.reader.mfdaq.cedspike2` |
| `ndi.daq.reader.mfdaq.spikegadgets` | `ndi.daq.reader.mfdaq.SpikeGadgetsReader` | `ndi.daq.reader.mfdaq.spikegadgets` |
| `ndi.daq.metadatareader.NewStimStims` | `ndi.daq.metadatareader.NewStimStimsReader` | `ndi.daq.metadatareader.newstim_stims` |
| `ndi.daq.metadatareader.NielsenLabStims` | `ndi.daq.metadatareader.NielsenLabStimsReader` | `ndi.daq.metadatareader.nielsenlab_stims` |

## Epoch, Element, Probe

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.epoch.epochprobemap_daqsystem` | `ndi.epoch.EpochProbeMapDAQSystem` | `ndi.epoch.epochprobemap_daqsystem` |
| `ndi.element` | `ndi.Element` | `ndi.element` |
| `ndi.probe` | `ndi.Probe` | `ndi.probe` |
| `ndi.probe.timeseries` | `ndi.probe.ProbeTimeseries` | `ndi.probe.timeseries` |
| `ndi.probe.timeseries.mfdaq` | `ndi.probe.ProbeTimeseriesMFDAQ` | `ndi.probe.timeseries_mfdaq` |
| `ndi.probe.timeseries.stimulator` | `ndi.probe.ProbeTimeseriesStimulator` | `ndi.probe.timeseries_stimulator` |
| `ndi.probe.fun.initProbeTypeMap` | `ndi.probe.initProbeTypeMap()` | `ndi.probe` |
| `ndi.probe.fun.getProbeTypeMap` | `ndi.probe.getProbeTypeMap()` | `ndi.probe` |

## Session & Dataset

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.session` | `ndi.Session` | `ndi.session` |
| `ndi.session.dir` | `ndi.DirSession` | `ndi.session.dir` |
| `ndi.session.sessiontable` | `ndi.session.SessionTable` | `ndi.session.sessiontable` |
| MockSession (conceptual) | `ndi.session.MockSession` | `ndi.session.mock` |
| `ndi.dataset` | `ndi.Dataset` | `ndi.dataset` (`.cloud_client` property for on-demand file fetching) |
| `ndi.subject` | `ndi.Subject` | `ndi.subject` |
| `ndi.neuron` | `ndi.Neuron` | `ndi.neuron` |
| `ndi.element_timeseries` | `ndi.ElementTimeseries` | `ndi.element_timeseries` |

## File Navigation

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.file.navigator` | `ndi.file.FileNavigator` | `ndi.file.navigator` |
| `ndi.file.navigator_epochdir` | `ndi.file.navigator.EpochDirNavigator` | `ndi.file.navigator.epochdir` |
| `ndi.file.type.mfdaq_epoch_channel` | `ndi.file.type.MFDAQEpochChannel` | `ndi.file.type.mfdaq_epoch_channel` |
| `ndi.file.pfilemirror` | `ndi.file.PFileMirror` | `ndi.file.pfilemirror` |

## App Framework

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.app` | `ndi.App` | `ndi.app` |
| `ndi.app.appdoc` | `ndi.app.AppDoc` | `ndi.app.appdoc` |
| `ndi.app.markgarbage` | `ndi.app.MarkGarbage` | `ndi.app.markgarbage` |
| `ndi.app.spikeextractor` | `ndi.app.SpikeExtractor` | `ndi.app.spikeextractor` |
| `ndi.app.spikesorter` | `ndi.app.SpikeSorter` | `ndi.app.spikesorter` |
| `ndi.app.oridirtuning` | `ndi.app.OriDirTuning` | `ndi.app.oridirtuning` |
| `ndi.app.stimulus.decoder` | `ndi.app.stimulus.StimulusDecoder` | `ndi.app.stimulus.decoder` |
| `ndi.app.stimulus.tuning_response` | `ndi.app.stimulus.TuningResponse` | `ndi.app.stimulus.tuning_response` |

## Calculator Framework

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.calculator` | `ndi.Calculator` | `ndi.calculator` |
| `ndi.calc.example.simple` | `ndi.calc.example.SimpleCalc` | `ndi.calc.example.simple` |
| `ndi.calc.stimulus.tuningcurve` | `ndi.calc.stimulus.TuningCurveCalc` | `ndi.calc.stimulus.tuningcurve` |
| `ndi.calc.tuning_fit` | `ndi.calc.TuningFit` | `ndi.calc.tuning_fit` |

## Database Functions (`ndi.database.fun.*`)

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.database.fun.findallantecedents` | `ndi.database_fun.find_all_antecedents()` | `ndi.database_fun` |
| `ndi.database.fun.findalldependencies` | `ndi.database_fun.find_all_dependencies()` | `ndi.database_fun` |
| `ndi.database.fun.docs_from_ids` | `ndi.database_fun.docs_from_ids()` | `ndi.database_fun` |
| `ndi.database.fun.docs2graph` | `ndi.database_fun.docs_to_graph()` | `ndi.database_fun` |
| `ndi.database.fun.find_ingested_docs` | `ndi.database_fun.find_ingested_docs()` | `ndi.database_fun` |
| `ndi.database.fun.finddocs_elementEpochType` | `ndi.database_fun.find_docs_element_epoch_type()` | `ndi.database_fun` |
| `ndi.database.fun.ndi_document2ndi_object` | `ndi.database_fun.ndi_document_to_object()` | `ndi.database_fun` |
| `ndi.database.fun.copy_session_to_dataset` | `ndi.database_fun.copy_session_to_dataset()` | `ndi.database_fun` |
| `ndi.database.fun.finddocs_missing_dependencies` | `ndi.database_fun.find_docs_missing_dependencies()` | `ndi.database_fun` |
| `ndi.database.fun.write_presentation_time_structure` | `ndi.database_fun.write_presentation_time_structure()` | `ndi.database_fun` |
| `ndi.database.fun.read_presentation_time_structure` | `ndi.database_fun.read_presentation_time_structure()` | `ndi.database_fun` |
| `ndi.database.fun.database2json` | `ndi.database_fun.database_to_json()` | `ndi.database_fun` |
| `ndi.database.fun.copydocfile2temp` | `ndi.database_fun.copy_doc_file_to_temp()` | `ndi.database_fun` |
| `ndi.database.fun.extract_doc_files` | `ndi.database_fun.extract_docs_files()` | `ndi.database_fun` |

## Database Ingestion

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.database.implementations.fun.ingest_plan` | `ndi.database_ingestion.ingest_plan()` | `ndi.database_ingestion` |
| `ndi.database.implementations.fun.ingest` | `ndi.database_ingestion.ingest()` | `ndi.database_ingestion` |
| `ndi.database.implementations.fun.expell_plan` | `ndi.database_ingestion.expell_plan()` | `ndi.database_ingestion` |
| `ndi.database.implementations.fun.expell` | `ndi.database_ingestion.expell()` | `ndi.database_ingestion` |

## Document Comparison

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.database.doctools.docComparison` | `ndi.doc_comparison.DocComparison` | `ndi.doc_comparison` |

## Utility Functions (`ndi.fun.*`)

### Doc Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.doc.allTypes` | `ndi.fun.doc.allTypes()` | `ndi.fun.doc` |
| `ndi.fun.doc.getDocTypes` | `ndi.fun.doc.getDocTypes()` | `ndi.fun.doc` |
| `ndi.fun.doc.findFuid` | `ndi.fun.doc.findFuid()` | `ndi.fun.doc` |
| `ndi.fun.doc.subject.makeSpeciesStrainSex` | `ndi.fun.doc.makeSpeciesStrainSex()` | `ndi.fun.doc` |
| `ndi.fun.doc.probe.probeLocations4probes` | `ndi.fun.doc.probeLocations4probes()` | `ndi.fun.doc` |
| `ndi.fun.doc.diff` | `ndi.fun.doc.diff()` | `ndi.fun.doc` |
| `ndi.fun.doc.ontologyTableRowVars` | `ndi.fun.doc.ontologyTableRowVars()` | `ndi.fun.doc` |

### DocTable Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.docTable.docCellArray2Table` | `ndi.fun.doc_table.docCellArray2Table()` | `ndi.fun.doc_table` |
| `ndi.fun.doc.ontologyTableRowDoc2Table` | `ndi.fun.doc_table.ontologyTableRowDoc2Table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.element` | `ndi.fun.doc_table.element()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.subject` | `ndi.fun.doc_table.subject()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.probe` | `ndi.fun.doc_table.probe()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.epoch` | `ndi.fun.doc_table.epoch()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.openminds` | `ndi.fun.doc_table.openminds()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.treatment` | `ndi.fun.doc_table.treatment()` | `ndi.fun.doc_table` |

### Epoch Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.epoch.epochid2element` | `ndi.fun.epoch.epochid2element()` | `ndi.fun.epoch` |
| `ndi.fun.epoch.filename2epochid` | `ndi.fun.epoch.filename2epochid()` | `ndi.fun.epoch` |
| `ndi.fun.doc.t0_t1cell2array` | `ndi.fun.epoch.t0_t1cell2array()` | `ndi.fun.epoch` |

### File Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.file.MD5` | `ndi.fun.file.MD5()` | `ndi.fun.file` |
| `ndi.fun.file.dateCreated` | `ndi.fun.file.dateCreated()` | `ndi.fun.file` |
| `ndi.fun.file.dateUpdated` | `ndi.fun.file.dateUpdated()` | `ndi.fun.file` |

### Data Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.data.readngrid` | `ndi.fun.data.readngrid()` | `ndi.fun.data` |
| `ndi.fun.data.writengrid` | `ndi.fun.data.writengrid()` | `ndi.fun.data` |
| `ndi.fun.data.mat2ngrid` | `ndi.fun.data.mat2ngrid()` | `ndi.fun.data` |
| — | `ndi.fun.data.evaluate_fitcurve()` | `ndi.fun.data` |
| `ndi.fun.data.readImageStack` | `ndi.fun.data.readImageStack()` | `ndi.fun.data` |

### Stimulus Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.stimulus.tuning_curve_to_response_type` | `ndi.fun.stimulus.tuning_curve_to_response_type()` | `ndi.fun.stimulus` |
| `ndi.fun.stimulus.f0_f1_responses` | `ndi.fun.stimulus.f0_f1_responses()` | `ndi.fun.stimulus` |
| `ndi.fun.stimulus.findMixtureName` | `ndi.fun.stimulus.findMixtureName()` | `ndi.fun.stimulus` |
| `ndi.fun.stimulustemporalfrequency` | `ndi.fun.stimulus.stimulustemporalfrequency()` | `ndi.fun.stimulus` |
| `ndi.fun.calc.stimulus_tuningcurve_log` | `ndi.fun.stimulus.stimulus_tuningcurve_log()` | `ndi.fun.stimulus` |

### Table Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.table.identifyMatchingRows` | `ndi.fun.table.identifyMatchingRows()` | `ndi.fun.table` |
| `ndi.fun.table.identifyValidRows` | `ndi.fun.table.identifyValidRows()` | `ndi.fun.table` |
| `ndi.fun.table.join` | `ndi.fun.table.join()` | `ndi.fun.table` |
| `ndi.fun.table.moveColumnsLeft` | `ndi.fun.table.moveColumnsLeft()` | `ndi.fun.table` |
| `ndi.fun.table.vstack` | `ndi.fun.table.vstack()` | `ndi.fun.table` |

### Probe Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.probe.export_binary` | `ndi.fun.probe.export_binary()` | `ndi.fun.probe.export_binary` |
| `ndi.fun.probe.export_all_binary` | `ndi.fun.probe.export_all_binary()` | `ndi.fun.probe.export_binary` |
| `ndi.fun.probe.location` | `ndi.fun.probe.location()` | `ndi.fun.probe.location` |

### Plot Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.plot.bar3` | `ndi.fun.plot.bar3()` | `ndi.fun.plot` |
| `ndi.fun.plot.multichan` | `ndi.fun.plot.multichan()` | `ndi.fun.plot` |
| `ndi.fun.plot.stimulusTimeseries` | `ndi.fun.plot.stimulusTimeseries()` | `ndi.fun.plot` |

### General Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.channelname2prefixnumber` | `ndi.fun.channelname2prefixnumber()` | `ndi.fun.utils` |
| `ndi.fun.name2variableName` | `ndi.fun.name2variableName()` | `ndi.fun.utils` / `ndi.fun.name_utils` |
| `ndi.fun.pseudorandomint` | `ndi.fun.pseudorandomint()` | `ndi.fun.utils` |
| `ndi.fun.timestamp` | `ndi.fun.timestamp()` | `ndi.fun.utils` |

### Session & Dataset Diff

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.session.diff` | `ndi.fun.session.diff()` | `ndi.fun.session` |
| `ndi.fun.dataset.diff` | `ndi.fun.dataset.diff()` | `ndi.fun.dataset` |

## Cloud API

> For a detailed analysis of structural differences between the MATLAB and Python
> cloud modules (including why `+implementation/` was eliminated, where auth
> functions live, etc.), see [REPO_AUDIT.md](REPO_AUDIT.md).

### Authentication

Auth functions are re-exported from `ndi.cloud.__init__` so `from ndi.cloud import login` works.

| MATLAB | Python | Notes |
|--------|--------|-------|
| `ndi.cloud.authenticate` | `ndi.cloud.authenticate()` | |
| `ndi.cloud.api.auth.login` | `ndi.cloud.login()` | Also at `ndi.cloud.auth.login()` |
| `ndi.cloud.api.auth.logout` | `ndi.cloud.logout()` | Also at `ndi.cloud.auth.logout()` |
| `ndi.cloud.api.auth.changePassword` | `ndi.cloud.changePassword()` | |
| `ndi.cloud.api.auth.resetPassword` | `ndi.cloud.resetPassword()` | |
| `ndi.cloud.api.auth.verifyUser` | `ndi.cloud.verifyUser()` | |
| `ndi.cloud.api.auth.resendConfirmation` | `ndi.cloud.resendConfirmation()` | |
| `ndi.cloud.uilogin` | — | GUI-only, no Python equivalent |

### Client & Config

| MATLAB | Python | Notes |
|--------|--------|-------|
| `ndi.cloud.api.url()` | `ndi.cloud.CloudClient` | HTTP client wrapping `requests.Session` |
| `ndi.cloud.api.call` (abstract classdef) | `ndi.cloud.CloudClient._request()` | See [REPO_AUDIT.md](REPO_AUDIT.md) §1 |
| `ndi.cloud.api.implementation.*` | — | Eliminated; `CloudClient` replaces all 60 impl classes |
| Cloud config constants | `ndi.cloud.CloudConfig` | Dataclass with `from_env()` classmethod |
| Cloud error IDs | `ndi.cloud.exceptions.*` | `CloudError`, `CloudAPIError`, `CloudAuthError`, `CloudNotFoundError`, `CloudSyncError`, `CloudUploadError` |

### Datasets API (`ndi.cloud.api.datasets`)

| MATLAB | Python | Notes |
|--------|--------|-------|
| `getDataset` | `getDataset(dataset_id)` | |
| `createDataset` | `createDataset(org_id, name, ...)` | |
| `updateDataset` | `updateDataset(dataset_id, **fields)` | |
| `deleteDataset` | `deleteDataset(dataset_id, when='7d')` | `when` param for soft-delete |
| `listDatasets` | `listDatasets(org_id, ...)` | |
| — | `listAllDatasets(org_id)` | Auto-paginator (Python-only) |
| `getPublished` | `getPublished(...)` | |
| `getUnpublished` | `getUnpublished(...)` | |
| `publishDataset` | `publishDataset(dataset_id)` | |
| `unpublishDataset` | `unpublishDataset(dataset_id)` | |
| `submitDataset` | `submitDataset(dataset_id)` | |
| `createDatasetBranch` | `createDatasetBranch(dataset_id)` | |
| `getBranches` | `getBranches(dataset_id)` | |
| `undeleteDataset` | `undeleteDataset(dataset_id)` | |
| `listDeletedDatasets` | `listDeletedDatasets(...)` | |

### Documents API (`ndi.cloud.api.documents`)

| MATLAB | Python | Notes |
|--------|--------|-------|
| `getDocument` | `getDocument(dataset_id, doc_id)` | |
| `addDocument` | `addDocument(dataset_id, doc_json)` | |
| `addDocumentAsFile` | `addDocumentAsFile(dataset_id, path)` | |
| `updateDocument` | `updateDocument(dataset_id, doc_id, doc_json)` | |
| `deleteDocument` | `deleteDocument(dataset_id, doc_id, when='7d')` | `when` param for soft-delete |
| `listDatasetDocuments` | `listDatasetDocuments(dataset_id, ...)` | |
| `listDatasetDocumentsAll` | `listDatasetDocumentsAll(dataset_id, ...)` | |
| `countDocuments` / `documentCount` | `countDocuments(dataset_id)` | Single function with fallback |
| `getBulkUploadURL` | `getBulkUploadURL(dataset_id)` | |
| `getBulkDownloadURL` | `getBulkDownloadURL(dataset_id, ...)` | |
| `bulkDeleteDocuments` | `bulkDeleteDocuments(dataset_id, doc_ids, when='7d')` | `when` param for soft-delete |
| `ndiquery` | `ndiquery(scope, search_structure, ...)` | |
| `ndiqueryAll` | `ndiqueryAll(scope, search_structure, ...)` | |
| — | `bulkUpload(dataset_id, zip_path)` | Python-only |
| `listDeletedDocuments` | `listDeletedDocuments(dataset_id, ...)` | |

### Files API (`ndi.cloud.api.files`)

| MATLAB | Python | Notes |
|--------|--------|-------|
| `getFile` | `getFile(url, target_path, ...)` | |
| `getFileUploadURL` | `getFileUploadURL(org_id, dataset_id, uid)` | |
| `getFileCollectionUploadURL` | `getFileCollectionUploadURL(...)` | |
| `getFileDetails` | `getFileDetails(dataset_id, uid)` | Used by `fetch_cloud_file` for on-demand download |
| `listFiles` | `listFiles(dataset_id)` | |
| `putFiles` | `putFiles(url, file_path, ...)` | |
| — | `putFileBytes(url, data, ...)` | Python-only (raw bytes) |
| — | `getBulkUploadURL(org_id, dataset_id)` | Python-only |

### Users API (`ndi.cloud.api.users`)

| MATLAB | Python | Notes |
|--------|--------|-------|
| `createUser` | `createUser(email, name, password)` | |
| `GetUser` | `GetUser(user_id)` | |
| `me` | `me()` | |

### Compute API (`ndi.cloud.api.compute`)

| MATLAB | Python | Notes |
|--------|--------|-------|
| `startSession` | `startSession(pipeline_id, ...)` | |
| `getSessionStatus` | `getSessionStatus(session_id)` | |
| `triggerStage` | `triggerStage(session_id, stage_id)` | |
| `finalizeSession` | `finalizeSession(session_id)` | |
| `abortSession` | `abortSession(session_id)` | |
| `listSessions` | `listSessions()` | |

### Top-Level Convenience Functions

These match MATLAB's `ndi.cloud.*` functions and are importable directly from `ndi.cloud`:

```python
from ndi.cloud import downloadDataset, uploadDataset, syncDataset, uploadSingleFile
```

| MATLAB | Python | Notes |
|--------|--------|-------|
| `ndi.cloud.downloadDataset` | `ndi.cloud.downloadDataset(...)` | Also at `ndi.cloud.orchestration.downloadDataset()` |
| `ndi.cloud.uploadDataset` | `ndi.cloud.uploadDataset(...)` | Also at `ndi.cloud.orchestration.uploadDataset()` |
| `ndi.cloud.syncDataset` | `ndi.cloud.syncDataset(...)` | Also at `ndi.cloud.orchestration.syncDataset()` |
| `ndi.cloud.uploadSingleFile` | `ndi.cloud.uploadSingleFile(...)` | Also at `ndi.cloud.upload.uploadSingleFile()` |
| `ndi.cloud.upload.newDataset` | `ndi.cloud.orchestration.newDataset(...)` | |
| `ndi.cloud.upload.scanForUpload` | `ndi.cloud.orchestration.scanForUpload(...)` | |
| *(customFileHandler in didsqlite.m)* | `ndi.cloud.fetch_cloud_file(ndic_uri, path, ...)` | On-demand binary file download via `ndic://` protocol |

### Download

| MATLAB | Python | Notes |
|--------|--------|-------|
| `ndi.cloud.download.dataset` | `download.downloadFullDataset(...)` | |
| `ndi.cloud.download.downloadDatasetFiles` | `download.downloadDatasetFiles(...)` | |
| `ndi.cloud.download.downloadDocumentCollection` | `download.downloadDocumentCollection(...)` | |
| `ndi.cloud.download.jsons2documents` | `download.jsons2documents(doc_jsons)` | |
| `ndi.cloud.download.datasetDocuments` | — | Handled inside orchestration |
| `ndi.cloud.download.internal.*` | — | Folded into main functions |
| `+sync/+internal/updateFileInfoForRemoteFiles` | `filehandler.rewrite_file_info_for_cloud()` | Rewrites file_info to `ndic://` URIs |
| `+download/+internal/setFileInfo` | `filehandler.rewrite_file_info_for_cloud()` | Same function handles both modes |

### Upload

| MATLAB | Python | Notes |
|--------|--------|-------|
| `ndi.cloud.upload.uploadDocumentCollection` | `upload.uploadDocumentCollection(...)` | |
| `ndi.cloud.upload.zipForUpload` | `upload.zipForUpload(docs, ...)` | |
| `ndi.cloud.upload.uploadFilesForDatasetDocuments` | `upload.uploadFilesForDatasetDocuments(...)` | |
| `ndi.cloud.upload.uploadToNDICloud` | — | Subsumed by `uploadDataset()` |
| `ndi.cloud.upload.internal.*` | — | Promoted or folded inline |

### Sync

| MATLAB | Python | Notes |
|--------|--------|-------|
| `SyncOptions` classdef | `ndi.cloud.sync.SyncOptions` | Dataclass |
| `SyncMode` enum | `ndi.cloud.sync.SyncMode` | Python Enum |
| `downloadNew` | `ndi.cloud.sync.downloadNew(...)` | |
| `uploadNew` | `ndi.cloud.sync.uploadNew(...)` | |
| `mirrorFromRemote` | `ndi.cloud.sync.mirrorFromRemote(...)` | |
| `mirrorToRemote` | `ndi.cloud.sync.mirrorToRemote(...)` | |
| `twoWaySync` | `ndi.cloud.sync.twoWaySync(...)` | |
| `validate` | `ndi.cloud.sync.validate(...)` | |
| — | `ndi.cloud.sync.sync(..., mode)` | Dispatch by SyncMode (Python-only) |
| `+sync/+internal/Constants` | — | Inlined |
| `+sync/+internal/index.*` (5 funcs) | `ndi.cloud.sync.SyncIndex` | Collapsed into dataclass |

### Internal Helpers

| MATLAB | Python | Notes |
|--------|--------|-------|
| `+internal/listRemoteDocumentIds` | `internal.listRemoteDocumentIds()` | |
| `+internal/getCloudDatasetIdForLocalDataset` | `internal.getCloudDatasetIdForLocalDataset()` | |
| `+internal/createRemoteDatasetDoc` | `internal.createRemoteDatasetDoc()` | |
| `+internal/decodeJwt` | `auth.decodeJwt()` | Moved to auth |
| `+internal/getActiveToken` | `auth.getActiveToken()` | Moved to auth |
| `+internal/getTokenExpiration` | `auth.getTokenExpiration()` | Moved to auth |
| `+internal/getWeboptionsWithAuthHeader` | — | Replaced by `CloudClient` |
| `+internal/getUploadedDocumentIds` | — | Via `listRemoteDocumentIds()` |
| `+internal/getUploadedFileIds` | — | Via `listFiles()` |
| `+internal/dropDuplicateDocsFromJsonDecode` | — | Not needed (Python JSON is exact) |
| `+internal/duplicateDocuments` | `internal.duplicateDocuments()` | |
| `+sync/+internal/listLocalDocuments` | `internal.listLocalDocuments()` | |
| `+sync/+internal/getFileUidsFromDocuments` | `internal.getFileUidsFromDocuments()` | |
| `+sync/+internal/filesNotYetUploaded` | `internal.filesNotYetUploaded()` | |
| `+sync/+internal/datasetSessionIdFromDocs` | `internal.datasetSessionIdFromDocs()` | |
| `+sync/+internal/deleteLocalDocuments` | `sync.operations._delete_local_docs()` | Private |
| `+sync/+internal/deleteRemoteDocuments` | Inline in `mirrorToRemote()` | |
| `+sync/+internal/downloadNdiDocuments` | `sync.operations._download_docs_by_ids()` | Private |
| `+sync/+internal/uploadFilesForDatasetDocuments` | `upload.uploadFilesForDatasetDocuments()` | |
| *(ndic:// URI parsing in didsqlite.m)* | `filehandler.parse_ndic_uri()` | `ndic://dataset_id/file_uid` → tuple |

### Admin (DOI & Crossref)

| MATLAB | Python | Notes |
|--------|--------|-------|
| `ndi.cloud.admin.createNewDOI` | `admin.doi.createNewDOI()` | |
| `ndi.cloud.admin.registerDatasetDOI` | `admin.doi.registerDatasetDOI()` | |
| `ndi.cloud.admin.checkSubmission` | `admin.doi.checkSubmission()` | |
| `+crossref/Constants` | `admin.crossref.CrossrefConstants` | Frozen dataclass |
| `+crossref/createDoiBatchSubmission` | `admin.crossref.createDoiBatchSubmission()` | |
| `+crossref/convertCloudDatasetToCrossrefDataset` | `admin.crossref.convertCloudDatasetToCrossrefDataset()` | |
| `+crossref/createDatabaseMetadata` | — | Inline in `createDoiBatchSubmission()` |
| `+crossref/createDoiBatchHeadElement` | — | Inline in `createDoiBatchSubmission()` |
| `+crossref/+conversion/convertContributors` | `admin.crossref.convertContributors()` | |
| `+crossref/+conversion/convertDatasetDate` | `admin.crossref.convertDatasetDate()` | |
| `+crossref/+conversion/convertFunding` | `admin.crossref.convertFunding()` | |
| `+crossref/+conversion/convertLicense` | `admin.crossref.convertLicense()` | |
| `+crossref/+conversion/convertRelatedPublications` | `admin.crossref.convertRelatedPublications()` | |

### Cloud: Not Ported

| MATLAB | Reason |
|--------|--------|
| `ndi.cloud.uilogin` | MATLAB GUI |
| `ndi.cloud.ui.dialog.selectCloudDataset` | MATLAB GUI dialog |
| `ndi.cloud.utility.createCloudMetadataStruct` | MATLAB struct validator; `CloudConfig` replaces |
| `ndi.cloud.utility.mustBeValidMetadata` | MATLAB struct validator; type hints replace |

## Ontology

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.ontology` | `ndi.ontology.OntologyProvider` | `ndi.ontology` |
| `ndi.ontology.lookup` | `ndi.ontology.lookup()` | `ndi.ontology` |

## OpenMINDS Integration

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.database.fun.openMINDSobj2struct` | `ndi.openminds_convert.openminds_obj_to_dict()` | `ndi.openminds_convert` |
| `ndi.database.fun.openMINDSobj2ndi_document` | `ndi.openminds_convert.openminds_obj_to_ndi_document()` | `ndi.openminds_convert` |
| `ndi.util.openminds.find_instance_name` | `ndi.openminds_convert.find_controlled_instance()` | `ndi.openminds_convert` |
| `ndi.util.openminds.find_techniques_names` | `ndi.openminds_convert.find_technique_names()` | `ndi.openminds_convert` |

## Mock / Testing

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.mock.fun.subject_stimulator_neuron` | `ndi.mock.subject_stimulator_neuron()` | `ndi.mock` |
| `ndi.mock.fun.stimulus_presentation` | `ndi.mock.stimulus_presentation()` | `ndi.mock` |
| `ndi.mock.fun.clear` | `ndi.mock.clear_mock()` | `ndi.mock` |
| `ndi.mock.ctest` | `ndi.mock.CalculatorTest` | `ndi.mock` |

## Not Ported (MATLAB-Specific)

The following MATLAB components were intentionally not ported (GUI, MATLAB-specific tooling, one-time scripts):

| MATLAB | Reason |
|--------|--------|
| `ndi.gui.*` (10+ files) | MATLAB GUI infrastructure |
| `ndi.database.fun.databasehierarchyinit` | MATLAB `eval()` for dynamic class creation |
| `ndi.fun.projectvardef` | MATLAB cell array helper |
| `metadata_ds_core/*` | MATLAB metadata editor GUI |
| `createNIFbrainareas.m` | One-time data preparation script |
| `readGenBankNames.m` / `readGenBankNodes.m` | Batch taxonomy scripts |
| `createGenBankControlledVocabulary.m` | Batch vocabulary builder |
| `find_calc_directories.m` | MATLAB path/toolbox discovery |
| `ndi.fun.assertAddonOnPath` | MATLAB addon/path checker |
| `ndi.fun.check_Matlab_toolboxes` | MATLAB toolbox checker |
| `ndi.fun.console` / `debuglog` / `errlog` / `syslog` | MATLAB console/logging |
| `ndi.fun.convertoldnsd2ndi` | Legacy NSD→NDI migration |
| `ndi.fun.run_Linux_checks` | MATLAB Linux environment checks |
| `ndi.fun.plot_extracellular_spikeshapes` | MATLAB GUI plotting |
