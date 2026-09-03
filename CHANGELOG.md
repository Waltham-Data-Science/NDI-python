# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed

- **`ndi_install.py` no longer times out installing on a slow network**
  (NDI-python#165). The editable install was capped at 120 seconds while
  taking about 80 on a healthy machine, and `pip install -e .` resolves six
  git-URL dependencies from `pyproject.toml`, so a slow clone crossed the line
  and failed the install outright. In CI that meant random red test jobs that
  had never run a test.

  Network-bound steps -- the clone, the pull, and both pip installs -- now
  share a `NETWORK_TIMEOUT` of 600 seconds; purely local git commands share a
  `LOCAL_TIMEOUT` of 30. Naming them is the point: it makes "does this talk to
  the network?" a question the next author answers rather than skips, and a
  test enforces that every installer subprocess uses one of the two or is a
  literal listed with a reason.

### Changed

- **`ndi.element.epochtable()` now returns registered epochs alphabetized by
  `epoch_id`** (NDI-python#162). They previously came back in the database's
  natural row order, which was stable for a given database but was neither
  insertion order nor anything a caller could predict. Sorting matches
  MATLAB, whose `ndi.element/buildepochtable` already orders them through
  `intersect`. The order is plain codepoint order on the raw id, so
  `epoch_10` precedes `epoch_2` — the ids are not zero-padded.

  **This changes the epoch order an existing database reports.** Two
  consequences worth knowing:

  - `ndi.fun.probe.export.binary` concatenates a probe's epochs in
    `epochtable()` order, and `ndi.fun.probe.import_.kilosort` maps spike
    sample indices back through it. A binary exported BEFORE this change does
    not necessarily match one imported after — re-export before importing a
    sort made against an older binary.
  - `epoch_number` is assigned from the sorted position, so an epoch's number
    can differ from what an older run reported. Code pairing epochs by number
    rather than by `epoch_id` should be checked.

  Epochs of a *direct* element are unaffected: they are the underlying
  element's, paired by position, and are deliberately left in that order.

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
- **CI/CD**: GitHub Actions workflow for Python 3.10-3.12 with lint (black + ruff) and test matrix
- **Code quality**: black formatting + ruff linting enforced in CI
- **1,704 tests** across 50 test files

### Notes

- Ported from [VH-Lab/NDI-matlab](https://github.com/VH-Lab/NDI-matlab)
- 117 production Python files, ~26,000 lines of code
- Requires [DID-python](https://github.com/VH-Lab/DID-python) and [vhlab-toolbox-python](https://github.com/VH-Lab/vhlab-toolbox-python)
