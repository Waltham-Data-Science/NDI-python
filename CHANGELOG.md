# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- **A double-click installer for end users** in `install/`: `Install NDI.command`
  (macOS), `Install NDI.cmd` (Windows), and the scripts behind them,
  `install-ndi.sh` (Linux and macOS) and `install-ndi.ps1` (Windows), which
  NDI-matlab also runs. A pinned uv (0.11.32) installs Python 3.12 and
  `ndi[gui,napari,pyraview]` as a uv tool, entirely under `~/.ndi/bin`,
  `~/.ndi/python` and `~/.ndi/venvs`, with no git, compiler or admin rights;
  `--uninstall` removes exactly those and the PATH lines. The
  `.github/workflows/installer.yml` workflow runs the real installer, with git
  hidden, on Linux x86_64/aarch64, Windows, macOS arm64, macOS Intel and
  x86_64-under-Rosetta.

- **Binary files upload in zip batches** (mirroring NDI-matlab#1033).
  `uploadFilesForDatasetDocuments` now honours `file_upload_strategy`:
  `'batch'` (the default, as in MATLAB) packs a document set's files into
  zips of at most `file_batch_size_limit` bytes and sends each through the
  bulk endpoint; `'serial'` keeps the old one-request-per-file path. Until now
  the strategy was read by nothing and every file went up singly.
  `ndi.cloud.upload.zipForUpload` is now a port of MATLAB's (it used to zip
  document JSON and had no caller); it reports the documents whose batch did
  not arrive, including a batch whose server-side extraction did not
  complete, so sync keeps them out of the index. `SyncOptions` gains
  `file_batch_size_limit`, and `uploadDataset` gains `file_upload_strategy`
  and `file_batch_size_limit`. Tests: `tests/test_cloud_upload_file_batches.py`.

- **`ndi.cloud.api.admin`: organization and user administration** (mirroring
  NDI-matlab#1031). Wraps the NDI Cloud `/admin` endpoints:
  `listOrganizations`, `getOrganization`, `createOrganization`,
  `updateOrganization`, `addOrganizationMember`, `removeOrganizationMember`,
  `listUsers` and `getUser`, plus `findUserByEmail` (exact, case-insensitive
  match over the server's substring search), `addOrganizationMemberByEmail`,
  `removeOrganizationMemberByEmail` and `getUserOrganizations`. All require
  an administrator account (others raise `CloudAuthError`), except
  `getUserOrganizations()` with no user, which lists your own organizations.
  `CloudClient` gains `patch()`. Tests: `tests/test_cloud_api_admin.py`
  (offline) and `tests/test_cloud_admin_live.py`, which skips the admin tests
  for a non-admin account and the membership-changing tests outside dev.

- **Pyraview from pre-built wheels, never from source.** New `pyraview`
  extra (`pyraview==0.4.2`). Pyraview is not on PyPI, so the wheels on its
  GitHub release are named in a committed flat index,
  `install/pyraview-wheels.html` (each link with its `#sha256`; the sdist left
  out), with the same hashes in `install/pyraview-constraints.txt` for uv.
  `tools/make_pyraview_index.py` regenerates both from a release tag.
  `ndi_install.py` no longer clones Pyraview and compiles its C++; it installs
  the wheel with `--only-binary pyraview`. CI installs it without git, CMake
  or a compiler on Linux x86_64/aarch64, Windows, macOS arm64, macOS Intel and
  x86_64-under-Rosetta.

- **File CRC-32 checksums for NDI Cloud** (ndi-cloud-node#162, mirroring
  NDI-matlab#1025), so an importer can resume an interrupted upload by
  re-uploading only the files whose cloud copy does not match.
  `ndi.fun.file.crc32(path)` gives a file's CRC-32 in the cloud's encoding
  (base64 of the 4-byte big-endian value). `getFileUploadURL` and `putFiles`
  / `putFileBytes` take `checksum_crc32=`, so S3 rejects a corrupted upload
  and the cloud records the value; `ndi.cloud.upload.uploadSingleFile` sends
  it by default (`checksum=False` turns it off). New
  `ndi.cloud.api.files.lookupFiles(dataset_id, uids)` returns `uploaded`,
  `size` and `crc32` for given uids plus the `missing` ones, splitting lists
  over the server's 5000-uid limit. `getSignedURLSetAll` merges the pages'
  `fileInfo`. `listFiles` and `getFileDetails` already pass `crc32` through.

### Fixed

- **Saving preferences no longer drops NDI-matlab's own entries.**
  `~/.ndi/NDI_Preferences.json` is shared with NDI-matlab, and each side
  rewrote it with only the preferences it registers, so saving from Python
  reset MATLAB-only preferences (such as `Tools.FFmpegPath`) to their
  defaults, and vice versa. `ndi_preferences` now re-reads the file just
  before writing and keeps every key it does not register, unchanged.

- `uploadSingleFile(use_bulk_upload=True)` passed the whole
  `getFileCollectionUploadURL` result (a `{"url", "jobId"}` dict) to
  `putFiles` as the URL, so it could never succeed.

- **Bulk document downloads wait up to 60 s for each chunk** (mirroring
  NDI-matlab#1030). `downloadDocumentCollection` polls each chunk's
  presigned ZIP URL while the server builds the archive, and gave up after
  20 s; a chunk of 2000 large documents can take longer, which surfaced as a
  `TimeoutError` (in MATLAB, a 404 from curl) partway through downloading a
  dataset. The default `timeout` is now 60 s in both
  `downloadDocumentCollection` and `_download_chunk_zip`.

- **`ndi.probe.timeseries.readtimeseries()` names its first argument
  `timeref_or_epoch`, matching MATLAB and `ndi.element.timeseries`**
  (NDI-python#166). It was called `epoch`, so the two classes could not be
  used interchangeably by keyword: `readtimeseries(epoch=...)` bound on a
  probe and raised `TypeError` on an element. `ndi.fun.probe.export.binary`
  called it that way, which made exporting silently probe-only even though a
  non-direct `ndi.element.timeseries` with registered epochs is a reasonable
  thing to export. The four call sites in `ndi.fun.probe` now pass
  positionally, which works against both classes.

  The argument also now accepts an `ndi.time.timereference` in that position,
  as MATLAB's does; the extra `timeref=` keyword, which has no MATLAB
  counterpart, keeps working. **Callers passing `epoch=` by keyword must
  update** -- pass it positionally, or as `timeref_or_epoch=`.
  `readtimeseriesepoch()` still takes `epoch`, which is correct: it takes an
  epoch and nothing else.

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

- **`napariViewGEF` and `napariViewLightsheet` are safe to start from MATLAB
  by themselves.** They now go through `_ndi_launch`, a stdlib-only module
  beside the package: started with `NDI_FROM_MATLAB=1` (or with MATLAB's
  directories on the loader path), it drops `LD_LIBRARY_PATH`, `LD_PRELOAD`,
  `DYLD_*`, `PYTHONHOME` and `PYTHONPATH` and re-execs before `import ndi`
  loads numpy and friends (on Windows: cleans `PATH` in place). The shell
  wrappers `tools/napariViewGEF` and `scripts/napariViewLightsheet` that did
  this are removed, and the `GUI.GEFManager.ViewerLauncher` preference now
  defaults to `""`, meaning "find napariViewGEF automatically".

- **Cloud batch sizes come from preferences** (mirroring NDI-matlab#1033).
  `Cloud.Upload.Max_File_Batch_Size` now defaults to 250 MB (was 500 MB) and
  sets the zip batch size; `Cloud.Upload.Max_Document_Batch_Count` is the
  default for `uploadDocumentCollection(max_chunk=None)`; and
  `Cloud.Download.Max_Document_Batch_Count` (10000) is the default for
  `downloadDocumentCollection(chunk_size=None)`, which was 2000. All three
  were registered but nothing read them.

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
