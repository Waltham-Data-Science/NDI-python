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
| `ndi.probe.fun.initProbeTypeMap` | `ndi.probe.init_probe_type_map()` | `ndi.probe` |
| `ndi.probe.fun.getProbeTypeMap` | `ndi.probe.get_probe_type_map()` | `ndi.probe` |

## Session & Dataset

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.session` | `ndi.Session` | `ndi.session` |
| `ndi.session.dir` | `ndi.DirSession` | `ndi.session.dir` |
| `ndi.session.sessiontable` | `ndi.session.SessionTable` | `ndi.session.sessiontable` |
| MockSession (conceptual) | `ndi.session.MockSession` | `ndi.session.mock` |
| `ndi.dataset` | `ndi.Dataset` | `ndi.dataset` |
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
| `ndi.fun.doc.allTypes` | `ndi.fun.doc.all_types()` | `ndi.fun.doc` |
| `ndi.fun.doc.getDocTypes` | `ndi.fun.doc.get_doc_types()` | `ndi.fun.doc` |
| `ndi.fun.doc.findFuid` | `ndi.fun.doc.find_fuid()` | `ndi.fun.doc` |
| `ndi.fun.doc.subject.makeSpeciesStrainSex` | `ndi.fun.doc.make_species_strain_sex()` | `ndi.fun.doc` |
| `ndi.fun.doc.probe.probeLocations4probes` | `ndi.fun.doc.probe_locations_for_probes()` | `ndi.fun.doc` |
| `ndi.fun.doc.diff` | `ndi.fun.doc.doc_diff()` | `ndi.fun.doc` |
| `ndi.fun.doc.ontologyTableRowVars` | `ndi.fun.doc.ontology_table_row_vars()` | `ndi.fun.doc` |

### DocTable Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.docTable.docCellArray2Table` | `ndi.fun.doc_table.doc_cell_array_to_table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.element` | `ndi.fun.doc_table.element_table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.subject` | `ndi.fun.doc_table.subject_table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.probe` | `ndi.fun.doc_table.probe_table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.epoch` | `ndi.fun.doc_table.epoch_table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.openminds` | `ndi.fun.doc_table.openminds_table()` | `ndi.fun.doc_table` |
| `ndi.fun.docTable.treatment` | `ndi.fun.doc_table.treatment_table()` | `ndi.fun.doc_table` |

### Epoch Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.epoch.epochid2element` | `ndi.fun.epoch.epochid2element()` | `ndi.fun.epoch` |
| `ndi.fun.epoch.filename2epochid` | `ndi.fun.epoch.filename2epochid()` | `ndi.fun.epoch` |
| `ndi.fun.doc.t0_t1cell2array` | `ndi.fun.epoch.t0_t1_to_array()` | `ndi.fun.epoch` |

### File Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.file.MD5` | `ndi.fun.file.md5()` | `ndi.fun.file` |
| `ndi.fun.file.dateCreated` | `ndi.fun.file.date_created()` | `ndi.fun.file` |
| `ndi.fun.file.dateUpdated` | `ndi.fun.file.date_updated()` | `ndi.fun.file` |

### Data Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.data.readngrid` | `ndi.fun.data.read_ngrid()` | `ndi.fun.data` |
| `ndi.fun.data.writengrid` | `ndi.fun.data.write_ngrid()` | `ndi.fun.data` |
| `ndi.fun.data.mat2ngrid` | `ndi.fun.data.mat_to_ngrid()` | `ndi.fun.data` |
| `ndi.fun.data.evaluate_fitcurve` | `ndi.fun.data.evaluate_fitcurve()` | `ndi.fun.data` |
| `ndi.fun.data.readImageStack` | `ndi.fun.data.read_image_stack()` | `ndi.fun.data` |

### Stimulus Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.stimulus.tuning_curve_to_response_type` | `ndi.fun.stimulus.tuning_curve_to_response_type()` | `ndi.fun.stimulus` |
| `ndi.fun.stimulus.f0_f1_responses` | `ndi.fun.stimulus.f0_f1_responses()` | `ndi.fun.stimulus` |
| `ndi.fun.stimulus.findMixtureName` | `ndi.fun.stimulus.find_mixture_name()` | `ndi.fun.stimulus` |
| `ndi.fun.stimulustemporalfrequency` | `ndi.fun.stimulus.stimulus_temporal_frequency()` | `ndi.fun.stimulus` |
| `ndi.fun.calc.stimulus_tuningcurve_log` | `ndi.fun.stimulus.stimulus_tuningcurve_log()` | `ndi.fun.stimulus` |

### Table Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.table.identifyMatchingRows` | `ndi.fun.table.identify_matching_rows()` | `ndi.fun.table` |
| `ndi.fun.table.identifyValidRows` | `ndi.fun.table.identify_valid_rows()` | `ndi.fun.table` |
| `ndi.fun.table.join` | `ndi.fun.table.join_tables()` | `ndi.fun.table` |
| `ndi.fun.table.moveColumnsLeft` | `ndi.fun.table.move_columns_left()` | `ndi.fun.table` |
| `ndi.fun.table.vstack` | `ndi.fun.table.vstack()` | `ndi.fun.table` |

### General Utilities

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.channelname2prefixnumber` | `ndi.fun.utils.channel_name_to_prefix_number()` | `ndi.fun.utils` |
| `ndi.fun.name2variableName` | `ndi.fun.utils.name_to_variable_name()` | `ndi.fun.utils` |
| `ndi.fun.pseudorandomint` | `ndi.fun.utils.pseudorandom_int()` | `ndi.fun.utils` |
| `ndi.fun.timestamp` | `ndi.fun.utils.ndi_timestamp()` | `ndi.fun.utils` |

### Session & Dataset Diff

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.fun.session.diff` | `ndi.fun.session.session_diff()` | `ndi.fun.session` |
| `ndi.fun.dataset.diff` | `ndi.fun.dataset.dataset_diff()` | `ndi.fun.dataset` |

## Cloud API

### Authentication

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.cloud.api.auth.login` | `ndi.cloud.auth.login()` | `ndi.cloud.auth` |
| `ndi.cloud.api.auth.signup` | `ndi.cloud.auth.signup()` | `ndi.cloud.auth` |
| `ndi.cloud.api.auth.changePassword` | `ndi.cloud.auth.change_password()` | `ndi.cloud.auth` |
| `ndi.cloud.api.auth.resetPassword` | `ndi.cloud.auth.reset_password()` | `ndi.cloud.auth` |
| `ndi.cloud.api.auth.verifyUser` | `ndi.cloud.auth.verify_user()` | `ndi.cloud.auth` |
| `ndi.cloud.api.auth.resendConfirmation` | `ndi.cloud.auth.resend_confirmation()` | `ndi.cloud.auth` |

### Client & Config

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.cloud.api.url()` | `ndi.cloud.CloudClient` | `ndi.cloud.client` |
| Cloud config constants | `ndi.cloud.CloudConfig` | `ndi.cloud.config` |
| Cloud error IDs | `ndi.cloud.exceptions.*` | `ndi.cloud.exceptions` |

### API Endpoints

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.cloud.api.datasets.*` | `ndi.cloud.api.datasets.*` | `ndi.cloud.api.datasets` |
| `ndi.cloud.api.datasets.getUnpublished` | `ndi.cloud.api.datasets.get_unpublished()` | `ndi.cloud.api.datasets` |
| `ndi.cloud.api.documents.*` | `ndi.cloud.api.documents.*` | `ndi.cloud.api.documents` |
| `ndi.cloud.api.documents.ndiquery` | `ndi.cloud.api.documents.ndi_query()` | `ndi.cloud.api.documents` |
| `ndi.cloud.api.documents.ndiqueryAll` | `ndi.cloud.api.documents.ndi_query_all()` | `ndi.cloud.api.documents` |
| `ndi.cloud.api.documents.addDocumentAsFile` | `ndi.cloud.api.documents.add_document_as_file()` | `ndi.cloud.api.documents` |
| `ndi.cloud.api.files.*` | `ndi.cloud.api.files.*` | `ndi.cloud.api.files` |
| `ndi.cloud.api.files.getFile` | `ndi.cloud.api.files.get_file()` | `ndi.cloud.api.files` |
| `ndi.cloud.api.files.listFiles` | `ndi.cloud.api.files.list_files()` | `ndi.cloud.api.files` |
| `ndi.cloud.api.files.getFileDetails` | `ndi.cloud.api.files.get_file_details()` | `ndi.cloud.api.files` |
| `ndi.cloud.api.files.getFileCollectionUploadURL` | `ndi.cloud.api.files.get_collection_upload_url()` | `ndi.cloud.api.files` |
| `ndi.cloud.api.users.*` | `ndi.cloud.api.users.*` | `ndi.cloud.api.users` |

### Upload & Download

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.cloud.uploadSingleFile` | `ndi.cloud.upload.upload_single_file()` | `ndi.cloud.upload` |
| `ndi.cloud.downloadDataset` | `ndi.cloud.orchestration.download_dataset()` | `ndi.cloud.orchestration` |
| `ndi.cloud.uploadDataset` | `ndi.cloud.orchestration.upload_dataset()` | `ndi.cloud.orchestration` |
| `ndi.cloud.syncDataset` | `ndi.cloud.orchestration.sync_dataset()` | `ndi.cloud.orchestration` |
| `ndi.cloud.upload.newDataset` | `ndi.cloud.orchestration.create_new_dataset()` | `ndi.cloud.orchestration` |
| `ndi.cloud.upload.scanForUpload` | `ndi.cloud.orchestration.scan_for_upload()` | `ndi.cloud.orchestration` |

### Sync

| MATLAB | Python | Module |
|--------|--------|--------|
| Sync mode constants | `ndi.cloud.sync.SyncMode` | `ndi.cloud.sync.mode` |
| `ndi.cloud.sync.validate` | `ndi.cloud.sync.operations.validate_sync()` | `ndi.cloud.sync.operations` |
| `+sync/+internal/listLocalDocuments` | `ndi.cloud.internal.list_local_document_ids()` | `ndi.cloud.internal` |
| `+sync/+internal/getFileUidsFromDocuments` | `ndi.cloud.internal.get_file_uids_from_documents()` | `ndi.cloud.internal` |
| `+sync/+internal/filesNotYetUploaded` | `ndi.cloud.internal.files_not_yet_uploaded()` | `ndi.cloud.internal` |
| `+sync/+internal/datasetSessionIdFromDocs` | `ndi.cloud.internal.dataset_session_id_from_docs()` | `ndi.cloud.internal` |

### Admin (DOI & Crossref)

| MATLAB | Python | Module |
|--------|--------|--------|
| `ndi.cloud.admin.createNewDoi` | `ndi.cloud.admin.doi.create_new_doi()` | `ndi.cloud.admin.doi` |
| `+crossref/Constants` | `ndi.cloud.admin.crossref.CrossrefConstants` | `ndi.cloud.admin.crossref` |
| `+crossref/+conversion/convertContributors` | `ndi.cloud.admin.crossref.convert_contributors()` | `ndi.cloud.admin.crossref` |
| `+crossref/+conversion/convertDatasetDate` | `ndi.cloud.admin.crossref.convert_dataset_date()` | `ndi.cloud.admin.crossref` |
| `+crossref/+conversion/convertFunding` | `ndi.cloud.admin.crossref.convert_funding()` | `ndi.cloud.admin.crossref` |
| `+crossref/+conversion/convertLicense` | `ndi.cloud.admin.crossref.convert_license()` | `ndi.cloud.admin.crossref` |

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
