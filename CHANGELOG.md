# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- **`mean+F1` stimulus responses** (`ndi.app.stimulus.tuning_response`, MATLAB
  VH-Lab/NDI-matlab#1209). Whenever the mean and F1 are both computed,
  `compute_stimulus_response_scalar` also writes a `stimulus_response_scalar`
  document with `response_type` `'mean+F1'`. Each trial is
  `mean_i * exp(1j*theta) + F1_i`, theta being the phase of the
  vector-averaged F1 for that stimulus, so the tuning curve value is
  `mean(F0) + abs(mean(F1))` with F1 still averaged with its phase. Stimuli
  without a fundamental frequency get the mean. It shares the F1 parameter
  document. `ndi.fun.stimulus.f0_f1_responses` accepts a `mean+F1` curve.

- **Stream files to an NDI Cloud session** (`ndi.cloud.session_writer.SessionWriter`,
  MATLAB `ndi.cloud.upload.SessionWriter`). To the lightsheet builders it looks
  like a session. Chunks are sent in the background as they are made,
  CRC-32-signed, `Cloud.Upload.Parallel_Uploads` at a time (on a thread pool
  where MATLAB uses a background curl). Each batch is checked with the cloud a
  batch later, late-recorded files are rechecked, failed sends are resent at
  once, and a resumed build adopts what the cloud has.
  `ndi.cloud.signed_upload_urls.signedUploadURLs` gets a batch's upload URLs
  concurrently. The preferences `Cloud.Upload.Parallel_Uploads` and
  `Cloud.Upload.Send_Batches_As_Zip` are shared with NDI-matlab.

- **Build lightsheet pyramids in Python** (`ndi.fun.doc_lightsheet`, MATLAB
  `ndi.fun.doc.lightsheet`). `fromSPIM` builds from a SmartSPIM acquisition's
  `All_Channels` slices, `fromOMEZarr` from an OME-Zarr store, and both use
  `makePyramid`. They write the same `lightsheetZarrPyramid` /
  `lightsheetZarrLevel` documents and chunk bytes as NDI-matlab: `<u2` dtype,
  corner translations, C-order chunks with Blosc-Zstd. That covers
  levelSources, whole-row super-blocks, level 1 folded into level 0, twin
  levels, streaming to a cloud target and resume. Compression and slice
  reads run on thread pools (`numWorkers`, `readWorkers`). The helpers are
  ported too: `dtypeName`, `reduceBlocks`, `chooseTileShape`, `chooseLevel`,
  `levelTable`, `makeSourceFile`, `viewCommand`, `view` and `BuildProfile`
  (`profile.csv` with MATLAB's columns).

- **Keep the computer awake while a job runs** (`ndi.util.keep_awake.ndi_util_KeepAwake`,
  MATLAB `ndi.util.KeepAwake`). It uses caffeinate on macOS, systemd-inhibit on
  Linux and SetThreadExecutionState on Windows. A job holds it while it runs
  unless the preference `Jobs.KeepComputerAwake` is false. The navigator's NDI
  pane has MATLAB's coffee-cup button to keep the computer awake by hand, and the
  cup shows when something is holding it.

- **Jobs pane in the navigator** (`ndi.gui.nav.JobsPane`, MATLAB
  `ndi.gui.nav.jobsPane`): every job on this computer, with its state,
  percent done, time left and last update, and Pause / Resume / Restart /
  Remove. It opens itself when a job exists. A running job refreshes it and
  lets the window redraw at every heartbeat. Jobs MATLAB runs are listed and
  can be paused from here.

- **`ndi.job`: the job record shared with NDI-matlab** (mirroring
  VH-Lab/NDI-matlab#1178). `ndi_job_Job` reads and writes `job.json`
  (`ndi_common/job_schema/job.schema.json`) the way `ndi.job.Job` does, so
  `ndi_job_Job.list()` shows every job on this computer, including MATLAB's
  lightsheet uploads, with `effectiveState`, `percentText` and
  `remainingSeconds`, and `requestPause()` pauses one from Python. A job kind
  Python does not run (a kind only MATLAB defines) loads as
  `ndi_job_ForeignJob`: listed and pausable, never run. `lightsheetToCloud`
  (`ndi_job_LightsheetToCloud`) is ported: a SmartSPIM or OME-Zarr image built
  straight into a session of an NDI Cloud dataset through
  `ndi.cloud.session_writer.SessionWriter`, resumable from where it stopped,
  and started, paused or resumed from either language. Subclasses define
  `Kind` and `work()` and get run / pause / resume / restart / interrupted
  detection.

- **Choosing and moving the tools folder** (mirroring VH-Lab/NDI-matlab
  5f5960c3b). `ndi.update.toolsFolder()` says where `ndi_install.py` cloned the
  dependencies (read from the `ndi-deps.pth` it writes), and
  `ndi.update.moveToolsFolder(newFolder)` moves them: it copies and checks the
  copy, rewrites `ndi-deps.pth` (keeping a `.bak`), updates `sys.path` and
  deletes the old folder, changing nothing if a check or the copy fails. The
  preferences editor has a matching **Tools folder...** button.
  `ndi_install.py` with no `--tools-dir` now reuses the folder an earlier run
  used, and `ndi.update.check`/`install` follow it instead of assuming
  `~/.ndi/tools`.

- **`vhneuropixelsGLX_nidq` vhlab DAQ system** (mirroring VH-Lab/NDI-matlab#1127).
  Reads the SpikeGLX NI-DAQ stream (`*.nidq.bin` / `*.nidq.meta`) with the NDR
  `neuropixelsGLX` reader, so probes on NI-DAQ digital lines can be described
  in `epochprobemap.txt` -- e.g. an optogenetic fiber on XD4 as
  `vhneuropixelsGLX_nidq:dimp5` (SpikeGLX XDn is channel di(n+1)).
  `vhneuropixelsGLX` reads the IMEC `.ap.bin`, whose digital lines are the IMEC
  sync bits. A blank vhlab session now has ten DAQ systems.

- **Update button: a package table with tick boxes** (mirroring
  NDI-matlab 19b8ab573 and 749b1a266). The navigator's Update button now lists
  NDI-python and each dependency clone in `~/.ndi/tools` in
  `ndi.gui.nav.update_dialog`, with installed and latest commits, status, notes
  (what updating does to your changes, what blocks it) and a tick box each, and
  updates only the ticked packages. Behind it: `ndi.update.packageStatus`, a
  `Packages` option for `ndi.update.install` (update named packages only;
  changes elsewhere need no consent, and the clone need not be on main unless
  NDI-python is named), and `CurrentVersion`/`LatestVersion` on each dependency
  in `ndi.update.check`. Pulls now stash and restore your edits in every
  repository and merge local commits (`git pull --no-edit`) instead of refusing
  them. Bridge entries are added for `updateDialog`, `packageStatus`,
  `pullRepo` and `findCalculators` (MATLAB-only: NDI-python has no calculator
  clones), and the `ndi.fun.epoch` and `ndi.setup` entries are re-examined
  against NDI-matlab main.

- **Ingestion stores the data** (mirroring NDI-matlab's
  `ndi.daq.reader.mfdaq/ingest_epochfiles`, with VH-Lab/NDI-matlab#1089's
  within-epoch progress). Ingesting an epoch used to make its documents
  without any data, so an ingested epoch could not be read (`channel_list.bin
  not found`). `ndi_daq_reader_mfdaq.ingest_epochfiles` now writes the channel
  list and the epoch's data in compressed segments as MATLAB does -- analog
  data in the reader's underlying type (Intan: uint16, via the new
  `ndi_daq_reader_mfdaq_intan.underlying_datatype`), digital, time, and
  event/marker/text channels -- and metadata readers store their parameters
  (`data.bin`), which `readmetadata_ingested` now reads back. The channel list
  is written in MATLAB's `saveStructArray` format so NDI-matlab can read it.
  `ingest_epochfiles` takes a `ProgressFcn`, and `ingestEpochDocuments`
  reports fractional progress as segments are written, in worker processes
  too. The Intan reader now reads auxiliary inputs at their own sample rate
  and its digital channels as NDR numbers them (both as MATLAB), and no
  longer pads reads that run past the end of the file. Needs ndi-compress with
  Waltham-Data-Science/NDI-compress-python#4.

- **Parallel ingestion by segment, and an ingest comparison tool** (mirroring
  VH-Lab/NDI-matlab#1090 and #1091). `ingest_epochfiles` is split into
  `ingest_epochfiles_plan`, `ingest_segment` and the static
  `ingest_attach_segments`, and `ingestEpochDocuments` now hands single
  segments to the worker processes, so every worker stays busy even when one
  epoch is much longer than the others. The new `ndi.test.ingest.compare`
  and `mfdaq_compare` compare a raw session with an ingested copy of it --
  every epoch, channel list, sample and event -- and return a report of
  every check, with no stopping or prompting on a mismatch.

- **Ingestion progress bars and parallel per-epoch work** (mirroring
  VH-Lab/NDI-matlab#1079). `ndi_session.ingest()` now shows progress through
  `ndi_gui_component_ProgressBarWindow` -- one bar for the session and one per
  DAQ system -- on by default (`ShowProgress=False` turns it off;
  `ProgressBar=` / `ProgressBarTag=` reuse a window). The per-epoch reader and
  metadata-reader work moves to the new `ndi.daq.fun.ingestEpochDocuments`,
  which runs it on spawned worker processes when NDI's parallel preferences
  allow; database writes stay serial and in epoch order. To support this:
  `ProgressBarWindow` gains MATLAB's silent (headless) mode -- `Silent`,
  `isHeadless`, `silentModeDefault`, `resolveSilentMode` -- so a run with no
  display or no PySide6 keeps the bookkeeping and builds no window instead of
  Qt aborting the process, and `addBar` gains MATLAB's per-bar `Timeout`; and
  the `Parallel.OpenPoolIfNone`, `Parallel.UseDefaultNumberOfWorkers` and
  `Parallel.NumberOfWorkers` preferences are registered (shared with
  NDI-matlab) and read by the new `ndi.fun.parallelWorkers`. Python has no
  pool that outlives a call, so with the default `OpenPoolIfNone=false`
  ingestion is serial.

- **Navigator: DAQ system browser, cloud dataset id, Assign to workspace,
  and faster DAQ system loading** (mirroring VH-Lab/NDI-matlab#1058).
  "Session > DAQ Systems..." opens the new `ndi.gui.nav.DaqSystemBrowser`, a
  read-only list of a session's DAQ systems with, for the selected one, its
  reader, file navigator and file patterns, epoch probe map class and
  patterns, metadata readers, and -- on "Load epochs" -- an epoch's actual
  files, the pattern each matches and which is the epoch probe map. "Check
  Cloud status" now opens `ndi.gui.nav.CloudStatusDialog`, which shows the
  NDI Cloud dataset id with a Copy button (disabled when the dataset is not
  in the cloud). Dataset and session nodes gain "Assign to workspace...",
  which binds the object to a variable in `__main__` and relabels the tree in
  place. `session.daqsystem_load(name='(.*)')` (and any match-everything
  name) no longer sends a regexp to the database -- on a ~100,000-document
  database that halved the load time -- via the new
  `ndi_session.isMatchAllRegexp`; probe epoch tables, `getprobes` and the sync
  graph, which all load DAQ systems that way, benefit too.

- **Bulk document upload, and waiting for it to be ingested** (mirroring
  VH-Lab/NDI-matlab#1047). `ndi.cloud.upload.uploadDocumentCollection` now
  uploads documents in bulk, as NDI-matlab does: each chunk
  (`Cloud.Upload.Max_Document_Batch_Count`) is one zipped JSON array
  (new `zip_documents_for_upload`) PUT to `getBulkUploadURL`, instead of one
  `addDocument` request per document, which for a dataset of 100,000
  documents took hours. `NDI_CLOUD_UPLOAD_NO_ZIP=true` keeps the
  one-at-a-time path. A bulk upload returns before the server has ingested
  the zip and has no job to wait on, so afterwards it waits, with the new
  `ndi.cloud.api.documents.waitForDocumentCount`, for the dataset to list the
  uploaded documents (`wait_for_ingestion`, `ingestion_timeout`, default
  300 s; a timeout is a warning, and the result is in `report["ingestion"]`).
  `upload_type` now says `'batch'` or `'serial'` truthfully.

- **Checking for, and installing, a newer NDI-python** (mirroring
  VH-Lab/NDI-matlab#1038). New `ndi.update`: `check()` compares this copy with
  the latest commit on main -- a git clone through `git fetch` (plus the
  `~/.ndi/tools` clones `ndi_install.py` makes, and the user's own changed
  files, new files and local commits), an installer install through the commit
  in `~/.ndi/install.json` -- and `install()` updates it: `git pull --ff-only`
  then `ndi_install.py --update`, or the NDI installer again. It refuses a
  clone not on main, and lists the user's own changes and asks (default No)
  before touching them. `ndi update` / `ndi update --check [--json]` on the
  command line, an **Update** button in the navigator's NDI pane, and a quiet
  once-a-day check when the navigator opens (`Update.CheckOnStartup`,
  `Update.CheckIntervalDays`, shared with NDI-matlab; `Update.Python.LastCheckTime`).
  The installers now install the exact commit main is at and record it, with
  the install time, in `~/.ndi/install.json` (removed by `--uninstall`), which
  NDI-matlab's `ndi.update.checkPython` reads too. `ndi.version()` reports that
  commit for an installer install.

- **Users in several NDI Cloud organizations** (mirroring VH-Lab/NDI-matlab#1037).
  Login no longer keeps only the first organization: it caches the user's
  whole list -- id, name and upload permission -- as JSON in
  `NDI_CLOUD_ORGANIZATIONS`, and `logout` clears it. New
  `ndi.cloud.internal.getOrganizations`, `setOrganizations`,
  `normalizeOrganizations`, `chooseOrganization` and `userIsAdmin`, and
  `ndi.cloud.ui.dialog.organizationLabels` / `selectOrganization`.
  `chooseOrganization` uses a named organization, else the only one that
  qualifies, else asks (on a terminal, or through a supplied chooser), else
  raises `CloudOrganizationError` listing the organizations by name and id.
  `createDataset` and `uploadDataset` take `organization_name` /
  `organization_id`; `listDatasets()` with no organization lists every
  organization's datasets, tagged with `organizationId` and
  `organizationName`. File uploads now go to the organization that owns the
  dataset rather than the login's first organization.

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

- **Recomputing stimulus responses replaced nothing** when the prestimulus
  parameters were empty (the default): the parameter document lookup never
  matched, so each run added new responses beside the old ones. Empty
  parameters are now matched as empty, and the delete-before-recompute is
  scoped by `response_type` (VH-Lab/NDI-matlab#1209).

- **Uploads wait for NDI Cloud to record them** (mirroring VH-Lab/NDI-matlab#1027).
  `ndi.cloud.api.files.waitForFileUpload` polls until uploaded files are
  recorded. `uploadSingleFile` waits through it by default
  (`wait_for_upload`). The serial upload path waits once for all its files and
  counts any that are never recorded as failed, so their documents are not
  marked synced. A PUT returning 200 only means S3 has the bytes.

- **Lightsheet viewer: pyramids drawn half a voxel short.** A lightsheet
  pyramid records where voxel 0's corner sits (now written down in
  `lightsheetZarrLevel.md`, mirroring NDI-matlab 1b7876574); napari places
  pixel centres, so `ndi.pyramid.multiscale.worldTransform` now adds half a
  voxel along z, y and x.

- **`waitForAllBulkUploads` no longer sits out its deadline on abandoned
  uploads** (mirroring VH-Lab/NDI-matlab#1189; server side
  Waltham-Data-Science/ndi-cloud-node#172). The server creates a `queued`
  bulk-upload job as soon as an upload URL is requested, and an upload that
  failed or was interrupted left that job `queued` forever, so every sync on a
  real dataset waited the full deadline at its bulk-upload boundary. New
  `stale_after` (default 3600 s): `queued` jobs created longer ago are ignored
  and returned in `staleJobs`; `extracting` jobs are always waited for.
  `require_all_complete` now counts only failures from the last `stale_after`
  seconds instead of the listing's 24 h history. `listActiveBulkUploads` takes
  an optional `since` (sent with each poll; older servers ignore it).

- **Bulk document download of large datasets no longer fails with HTTP 500**
  (mirroring NDI-matlab). `Cloud.Download.Max_Document_Batch_Count` defaulted
  to 10000, but the server sends a chunk's ids in one SNS message (256 KiB cap,
  about 9,700 ids), so the first chunk of any dataset over that size failed.
  The default is now 2000, and `downloadDocumentCollection` reduces any chunk
  size above the server's limit of 5000 ids (`MAX_BULK_DOWNLOAD_IDS`) to that
  limit, so a value saved in preferences earlier no longer breaks downloads.

- **Digital-edge events were one sample early.** `ndi_daq_reader_mfdaq`'s
  `dep`, `den`, `dimp` and `dimn` events (the non-ingested read) timed each
  "on" edge at the last sample before the transition; MATLAB, the "off" edges
  and the ingested read all use the first sample after it. A line going high
  at 1.000 s at 1 kHz gave 0.999 s. They now agree.

- **Reading samples through a DAQ system: raw and ingested epochs now agree.**
  `ndi_daq_system_mfdaq.readchannels_epochsamples` takes 0-based samples, as
  `epochtimes2samples` and `epochsamples2times` do, but passed them unchanged
  to a raw reader, whose samples are 1-based. A raw epoch therefore read one
  sample later than the same epoch ingested, and a probe's raw data
  (`ndi_probe_timeseries_mfdaq.readtimeseriesepoch`) were one sample off from
  the times returned with them. The system now converts for the raw reader.

- **`session.daqsystem_add` raised AttributeError for every DAQ system**: it
  called `dev.setsession`, but `ndi_daq_system`'s method is `set_session`.

- **Deleting a document left its dependents behind with current DID-python.**
  `session.database_rm`'s cascade asked for `depends_on("", id)`, relying on
  an empty name meaning "any"; DID's SQL `depends_on` search (DID-python#101)
  treats only `'*'` as any, so nothing was found and, e.g., deleting neurons
  in the spike sorter importer left them in the database. It now asks for
  `'*'`, as MATLAB's `findalldependencies` does.

- **Lightsheet viewer: slow tiles from the local cache.** Each pyramid level was
  built as one dask graph layer per chunk (`from_delayed` + `da.block`), and
  dask walks every layer each time napari computes a slice, so the cost grew
  with the size of the level rather than the view: 16 cached chunks took ~1.4 s
  to show on a 16k-chunk level and ~26 s on a 131k-chunk one, against ~15 ms to
  read the files. This is the "Loading view 50/112" with nothing in flight.
  A level is now a single `map_blocks` layer: the same view takes ~20 ms at
  any level size, and building the level at open time is ~20x faster.
  The viewer also now prints one `[lightsheet] tiles:` line per burst of reads
  showing where tile time goes (path lookup, queue wait, disk read, decode,
  and the burst's wall-clock span); `NDI_LIGHTSHEET_TIMING=0` turns it off.
  The gene-expression pyramid viewer built its levels the same way and gets
  the same fix.
  Downloaded tiles also took about a minute each to be stored in DID's file
  cache: with dozens of download threads finishing together, each scanned the
  cache's index row by row and waited on its lock a second at a time. The
  viewer now checks the disk instead of the index and lets one thread at a
  time add to the cache; the debug fetch line reports the add as
  `cache add Xs`. The underlying cache fixes are VH-Lab/DID-python#89 and
  VH-Lab/DID-matlab#221.

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

- **No single NDI Cloud organization any more** (VH-Lab/NDI-matlab#1037).
  `CloudConfig.org_id` and `NDI_CLOUD_ORGANIZATION_ID` are gone, and
  `ndi.cloud.auth.getActiveToken` returns the token only. The second output of
  `ndi.cloud.auth.authenticate` is deprecated: it is the user's only
  organization, or `""` when there are several. Code that read
  `client.config.org_id` should call `ndi.cloud.internal.chooseOrganization`.

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
