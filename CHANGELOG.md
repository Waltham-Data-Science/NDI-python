# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-02-07

### Added

- Initial Python port of NDI (Neuroscience Data Interface)
- **Core**: Document, Query, Ido, Database (SQLite backend via DID-python)
- **Time synchronization**: ClockType, TimeMapping, TimeReference, SyncGraph, SyncRule
- **DAQ system**: DAQSystem, MFDAQSystem, DAQReader with format readers (Intan, Blackrock, CED Spike2, SpikeGadgets)
- **Metadata readers**: NewStimStims, NielsenLabStims
- **Elements and Probes**: Element, Probe, ProbeTimeseries, ProbeTimeseriesMFDAQ, ProbeTimeseriesStimulator
- **Epochs**: Epoch, EpochSet, EpochProbeMap, EpochProbeMapDAQSystem
- **File navigation**: FileNavigator, EpochDirNavigator, PFileMirror
- **Sessions**: Session, DirSession, MockSession, SessionTable
- **Subject, Neuron, Dataset**: Full data model classes
- **App framework**: App, AppDoc, DocExistsAction, Calculator with run loop
- **Built-in apps**: MarkGarbage, SpikeExtractor, SpikeSorter, OriDirTuning, StimulusDecoder, TuningResponse
- **Calculators**: SimpleCalc, TuningCurveCalc, TuningFit (abstract)
- **Cloud API**: CloudClient, CloudConfig, JWT auth, REST endpoints (datasets, documents, files, users, compute)
- **Cloud sync**: SyncMode, SyncIndex, push/pull/validate operations
- **Cloud admin**: DOI generation, Crossref XML batch submission
- **Upload/Download**: Batch and single-file upload, dataset download orchestration
- **Ontology**: 13 providers (OLS, NCBITaxon, PubChem, RRID, UniProt, GO, ChEBI, MOD, PO, HSAPDV, CHEBI, STATO, PMID) with LRU cache
- **Validation**: JSON Schema validation with superclass chain walking
- **Database utilities**: Document graph traversal, antecedent/dependency search, session-to-dataset copy, ingestion/expulsion
- **Fun utilities**: Doc, epoch, file, data, stimulus, table, session, dataset utility functions
- **OpenMINDS integration**: Object-to-dict serialization, NDI document conversion, controlled term lookup
- **Mock utilities**: Subject/stimulator/neuron generators, CalculatorTest fixture
- **MATLAB mapping**: Comprehensive MATLAB-to-Python function reference (MATLAB_MAPPING.md)
- **CI/CD**: GitHub Actions workflow for Python 3.9-3.12
- **1,277 tests** across 30 test files

### Notes

- Ported from [VH-Lab/NDI-matlab](https://github.com/VH-Lab/NDI-matlab)
- 117 production Python files, 25,691 lines of code
- Requires [DID-python](https://github.com/VH-Lab/DID-python) and [vhlab-toolbox-python](https://github.com/VH-Lab/vhlab-toolbox-python)
