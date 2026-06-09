# NDI Ecosystem — Full Parity Analysis & Audit

**Date:** 2026-06-09
**Scope:** NDI-matlab ↔ NDI-python parity (guided by the 37 `ndi_matlab_python_bridge.yaml` contracts), plus full code-quality / security / performance-cost audits of both repos and their dependency ecosystem.

## Baselines analyzed (all verified at latest upstream HEAD on 2026-06-09)

| Repo | HEAD | Date |
|---|---|---|
| NDI-matlab (Source of Truth) | `2d76370` | 2026-06-09 |
| NDI-python (this repo) | `9c64acb` (= origin/main) | 2026-05-12 |
| DID-matlab / DID-python | `03b0f7f` / `1b1491f` | 2026-03-31 / 2026-04-12 |
| NDR-matlab / NDR-python | `4e15508` / `896ed63` | 2026-05-10 / 2026-04-13 |
| vhlab-toolbox-matlab / -python | `0bccce1` / `b073185` | 2026-06-03 / 2026-03-16 |
| NDI-compress-matlabp / -python | `84c4bdd` / `0c05d9d` | 2026-03-03 / 2026-02-05 |
| ndi-ontology-matlab | `dbb6396` | 2026-04-28 |
| vhlab-thirdparty-matlab, vhlab_vhtools | 2022 vintage (frozen upstream) | — |
| **ndi-cloud-node** | `fcce1ab` (audited in a separate session) | 2026-06-03 |

**Method.** Nine parallel deep-analysis passes: one architecture mapping of NDI-matlab + dependencies; five namespace-scoped parity analyses verifying every bridge entry against the *actual code on both sides* and using NDI-matlab's full git history to detect post-sync drift; three audits (NDI-python with linters/tests executed; NDI-matlab static; dependency ecosystem). Lint state at baseline: `black --check` and `ruff check` both pass; test suite (excluding symmetry/cloud-live) **1,568 passed, 2 failed (live-network ontology lookups), 212 skipped**.

---

## 1. Executive summary

The port is structurally faithful — naming, package layout, document model, query layer, DAQ wrappers, and the cloud API surface are largely at parity, and the bridge-file system mostly works. But the audit found **four zones where the Python port is functionally wrong or unsafe rather than merely incomplete**, several **cross-language interop breaks** (files written by one language unreadable by the other), one **repo-wide string corruption**, and systemic **supply-chain unpinning** on both sides.

**Do-not-use until fixed (NDI-python):**
1. `ndi.cloud.sync.operations` — stub uploads, index-only view of local state, and `twoWaySync` **propagates deletions** (MATLAB's is strictly additive). A remote deletion can silently delete local data. (§3.1)
2. Binary-file upload — `uploadFilesForDatasetDocuments` reads file UIDs from fields real documents don't have, so `uploadDataset(sync_files=True)` uploads **zero** binaries without error; `uploadSingleFile`'s bulk branch and `uploadToNDICloud` are broken outright. (§3.1)
3. `ndi.time.syncgraph.time_convert` — missing the empty-epoch global resolution, same-referent rescale, destination time filtering, underlying-epoch injection, and never passes the DAQ system to trigger-based syncrules — element/probe time conversion cannot work. (§3.2)
4. `element_timeseries.readtimeseries` — bypasses the syncgraph entirely and persists data in a headerless format with the wrong filename (loses the time axis; incompatible with MATLAB's `epoch_binary_data.vhsb`). (§3.2)

**Cross-language interop breaks:** sync-index JSON keys (snake_case vs camelCase — same file, two dialects), `epochprobemap_daqsystem` serialize/decode (header-row mismatch), element binary format, DID `isa` query semantics, DID sqlite `timestamp` meaning, NDR format-alias registries, ontology prefix registries.

**Repo-wide defect (NDI-python):** a past bad find/replace injected the token `ndi_gui_` into prose, URLs, and identifiers across ~38 source files + docs + AGENTS.md (e.g. `version()` returns `https://github.com/Waltham-ndi_gui_Data-Science/NDI-python`; `ontology/providers.py:511` fetches a 404 URL; `gui/data.py` defines class `ndi_gui_Data` where MATLAB has `ndi.gui.Data`).

**Both repos:** unpinned moving-target dependencies (`@main` git deps in pyproject; ref-less git URLs in MATLAB requirements.txt) mean the cross-language symmetry tests compare two moving targets; CI actions pinned to mutable tags; secrets stored with weak obfuscation, no file-permission hardening, and exported into process env vars; document-definition JSON re-read from disk on every document construction in both languages.

Counts: **~240 items verified OK** across the five parity scopes; **8 Critical**, **~30 High**, **~40 Medium**, **~45 Low** findings consolidated below (duplicates across passes merged).

---

## 2. System understanding (grounding)

NDI is a session-centric, document-oriented framework: `ndi.session[.dir]` owns a DID-backed document database (`.ndi/did-sqlite.sqlite` + `files/`), DAQ systems (`ndi.daq.system` = file navigator + NDR-backed reader + metadata readers), epochs discovered from raw files and mapped to probes/elements via `epochprobemap`, a time system (`clocktype`/`syncrule`/`syncgraph`) that computes time conversion paths across clocks, apps/calculators that persist results as documents, and a cloud layer syncing datasets to the ndi-cloud-node REST API (`api.ndi-cloud.com/v1`). Both languages build documents from the JSON definitions in `ndi_common/database_documents` + `schema_documents` — those trees are part of the contract.

Dependency bindings: `ndi.query`/`ndi.document`/database wrap DID (~150–200 call sites in MATLAB); DAQ readers wrap NDR; `vlt.*` is pervasive utility glue in MATLAB (~420 uses) while NDI-python imports only two `vlt` functions (`loadStructArray`, `vhsb_read`) — both solid. Ontology lookup logic lives in ndi-ontology-matlab (19 ontology classes) on the MATLAB side and is embedded in `src/ndi/ontology` on the Python side.

**Where MATLAB moved recently (483 commits in 3 months)** — and therefore where the port is most behind: the Kilosort import pipeline (`ndi.fun.probe.import.kilosort.*`, `extracellularInfo`, `spikeSorterImporter` GUI — entirely unported), cloud sync hardening (504 handling, sync-index guards, listFiles stabilization — unported), and batch element creation (`addMultiple` — unported).

---

## 3. NDI-python — required changes

### 3.1 Critical — cloud sync & upload (unsafe / non-functional)

| # | Finding | Where | Fix |
|---|---|---|---|
| C1 | `sync/operations.py` reads "local state" from the sync index instead of the dataset (new local docs invisible); uploads stub bodies `{"ndiId": id}` instead of documents; `twoWaySync` propagates deletions while MATLAB `twoWaySync.m` is strictly additive — combined with the index-only view, a remote deletion deletes local data | `cloud/sync/operations.py:149-153,169,202,254,272,331,398,461-477` | Rebuild the five sync ops on dataset enumeration (`internal.listLocalDocuments`) + real uploads (`upload.uploadDocumentCollection`); remove deletion propagation from `twoWaySync` (or gate behind an explicit opt-in recorded in the bridge decision_log) |
| C2 | Sync-index file format incompatible with MATLAB: Python writes `local_doc_ids_last_sync`/`remote_doc_ids_last_sync`/`last_sync_timestamp`; MATLAB writes `localDocumentIdsLastSync`/`remoteDocumentIdsLastSync`/`lastSyncTimestamp` to the *same* `.ndi/sync/index.json`. Alternating clients see an empty index → full re-transfer; under mirror modes, mass deletion | `cloud/sync/index.py:50-57` vs MATLAB `createSyncIndexStruct.m:33-41` | Read both key dialects, write MATLAB's camelCase |
| C3 | Binary upload non-functional: `uploadFilesForDatasetDocuments`/`scanForUpload` look at top-level `file_uid`/`file_path`, but documents keep binaries under `files.file_info[].locations[].uid` — zero files uploaded, no error. `uploadSingleFile` bulk branch passes the `{url,jobId}` dict into `putFiles(url=...)` (always fails pydantic); `uploadToNDICloud` mis-unpacks `zipForUpload`'s `(Path, list)` return | `cloud/upload.py:152-165,204-209,289-303,354` | Build the manifest via `internal.getFileUidsFromDocuments`; fix the call signatures; rewrite `uploadToNDICloud` on `uploadDocumentCollection` |
| C4 | Sync downloads write raw JSON into `.ndi/documents/` instead of `database_add` — downloaded docs invisible to `database_search`; `deleteLocalDocuments` deletes that JSON cache, not database docs | `cloud/sync/operations.py:34-48` | Reuse `orchestration._sync_download_new`'s database path |

### 3.2 Critical — time system & timeseries (scientifically load-bearing)

| # | Finding | Where | Fix |
|---|---|---|---|
| C5 | `syncgraph.time_convert` missing: empty-epoch global resolution (scan epochtable for the epoch whose `t0_t1` contains `time+t_in`; MATLAB `syncgraph.m:653-675`); same-referent shortcut with cross-clock rescale (`:677-700`); destination time-window filtering (`:744-746`); equal-cost tie-breaking (`:772-789`) | `time/syncgraph.py:394-540` | Port the four branches |
| C6 | `addunderlyingepochs` never ported: graph contains DAQ nodes only; element/probe epochs are never injected (plus the cost-77 utc/exp_global equivalence edges), so time conversion for elements/probes can't resolve | `time/syncgraph.py:232-355` vs `syncgraph.m:461-550` | Implement `_add_underlying_epochs` + missing-node retry in `time_convert` |
| C7 | `_apply_rules_to_edge` calls `rule.apply(a, b)` without the DAQ system — trigger-based rules early-return `(None, None)`, so `commonTriggersOverlappingEpochs`/`randomPulses` can never produce an edge; ingested `syncrule_mapping` docs never consulted | `time/syncgraph.py:357-376` vs `syncgraph.m:427-429` | Thread the daqsystem through; add the ingested-rule lookup |
| C8 | `element_timeseries.readtimeseries` ignores the syncgraph (no `time_convert` in/out, returns `timeref=None`); `_store_timeseries_data` writes only `datapoints.tobytes()` (no VHSB header, **drops the time axis**) to `timeseries.vhsb` while MATLAB uses `epoch_binary_data.vhsb` with real VHSB | `element_timeseries.py:47-93,147,227` vs `+element/timeseries.m:31-78,70,114-116` | Route through `time_convert` (after C5–C7); use `vlt.file.custom_file_formats` VHSB read/write; align the filename |

### 3.3 Critical — repo-wide correctness

| # | Finding | Where | Fix |
|---|---|---|---|
| C9 | `ndi_gui_` token corruption (bad find/replace): broken `version()` URL (`__init__.py:96`), broken **live** ontology fetch URL (`ontology/providers.py:511` → 404), `__author__ = "VH-ndi_gui_Lab"` (`__init__.py:80`), corrupted class `ndi_gui_Data` (`gui/data.py:23`; MATLAB source is `ndi.gui.Data`), corrupted clone URLs in `docs/index.md`/`getting-started.md`/`matlab-migration.md`, corrupted prose in `AGENTS.md` ("Neuroscience ndi_gui_Data Interface", "VH-ndi_gui_Lab"), `.cursorrules`, GUI bridge `matlab_path` fields pointing at phantom files, and string literals in `daq/metadatareader/nielsenlab_stims.py` + test fixtures | repo-wide (~38 .py files + docs) | One reviewed global cleanup distinguishing the spurious token from legitimately flattened GUI class names (`ndi_gui_component_*` pattern is intentional); fix `version()` URL and ontology URL first |
| C10 | `epochprobemap_daqsystem` serialize/decode: MATLAB writes header row + data rows (and array support); Python emits/expects a single header-less line — MATLAB-written files crash Python decode (`int('reference')`), Python-written strings parse as empty in MATLAB. The navigator's own `_load_epochprobemap_file` does it correctly, so the class is also internally inconsistent | `epoch/epochprobemap_daqsystem.py:72-146` vs MATLAB `:136-210` | Emit header + arrays in `serialize`/`savetofile`; skip header in `decode`/`loadfromfile` |

### 3.4 High — parity gaps (behavioral)

1. **`document.dependency_value_n`** never falls back to the unnumbered dependency name (MATLAB `document.m:367-378`, incl. the 2026-03-25 empty-placeholder skip). `document.py:388-418`.
2. **`document.__add__`** silently de-duplicates file lists via `set()` (loses order, never raises); MATLAB errors on duplicate names. `document.py:612-614`.
3. **`ndi_common` definitions missing/divergent** (both languages build documents from these): missing `apps/kilosort/kilosort_clusters.json`, `data/filter.json`, `data/pyraview.json`, `treatment/treatment_transfer.json` + their 4 schemas; `data/ontologyTableRow.json` + schema dropped the `depends_on: [{name: document_id}]` block MATLAB added (5b5b56d5). Copy from MATLAB tree.
4. **`daq/system_mfdaq.py:312-346`** missing analog-event channel types (`aep/aen/aimp/aimn`) and `_t<threshold>` suffix stripping (MATLAB 2157c70f). The reader level already handles them; only the system-level statics are behind.
5. **`VHAudreyBPod`** Python is a raw-JSON passthrough; MATLAB's `readAudreyBPodJson` 7-stimulus transform (solenoid/tastant/duration/wash structure) never ported; also absent from bridge. `daq/metadatareader/vhaudreybpod_stims.py:84-104`.
6. **`epochset.matchedepochtable`** name collision: MATLAB = boolean hash check; Python = entry lookup with different args; bridge claims "Exact match". `epoch/epochset.py:238`. Also `epochgraph` returns node dicts vs MATLAB's `(cost, mapping)`.
7. **Sync algorithms substituted, not ported:** `commonTriggersOverlappingEpochs` hard-fails on unequal trigger counts (MATLAB falls back to `ndi.time.fun.syncTriggerTrains` — absent in Python); `random_pulses.py` uses cross-correlation instead of MATLAB's quantized interval-fingerprint algorithm — diverges on partial-overlap/drifting data.
8. **`probe/timeseries_stimulator.py`** stale: MATLAB `pairOnOff` rework (f1e2ff8c, issue #248: NaN-fill orphaned on/off events) unported — errors/mis-pairs on partial read windows.
9. **`session` API rename unported:** MATLAB `is_fully_ingested` → `isIngested` (3cde88c8) + new `dataset.isIngested`. Keep an alias for back-compat.
10. **`dataset.convertLinkedSessionToIngested`** in the bridge and in MATLAB but absent from Python (`dataset/_dataset.py`).
11. **`element.timeseries.addMultiple`** (MATLAB cbbb099b, batched neuron creation — the new recommended bulk path) unported.
12. **Kilosort import pipeline entirely unported:** `+fun/+probe/+import/+kilosort/*` (7 files), `extracellularInfo.m`, `plotProbeGeometry.m` — the most active recent MATLAB area. Port or record explicit bridge deferral.
13. **App compute methods are `NotImplementedError` stubs labeled "Exact match"** in the bridge: `spikeextractor.extract/filter/makefilterstruct`, `spikesorter.loadwaveforms/spike_sort/clusters2neurons`, `oridirtuning` (5 methods), `tuning_response` (5 methods), `markgarbage.identifyvalidintervals`. Either implement or mark `not_yet_implemented` in the bridge — the current labels are false.
14. **Ontology providers missing:** no `Uberon`, `NCIT`, `EDAM`, `IAO`, `SchemaOrg`, `STATO` providers although `ontology_list.json` registers some of their prefixes — `lookup("UBERON:heart")` (MATLAB's headline example) fails. UBERON/NCIT route cleanly through the existing `OLSProvider`. Also `ndi_common/ontology/ontology_list.json` (17 mappings) is out of sync with ndi-ontology-matlab's (22).
15. **Cloud API contract drift:** `ndiquery` scope `Literal` rejects MATLAB-accepted CSV dataset-ID scopes (88c0fb90) and scalar `searchstructure` isn't array-wrapped; `compute.abortSession` uses `POST /compute/{id}/abort` vs MATLAB `DELETE /compute/{id}`; `files.getBulkUploadURL` POSTs a path MATLAB GETs (and its bridge entry cites a nonexistent MATLAB file); `addDocumentAsFile` posts JSON where MATLAB sends multipart; `documents.bulkUpload` sends the ZIP *path string* as the body; pagination defaults diverge (1000 vs MATLAB 20/100) under "Exact match" labels.
16. **Cloud post-2026-05-10 MATLAB hardening unported:** `listFiles` stabilization/normalization (#807), `filesNotYetUploaded` re-queue on `uploaded==false`/missing (#805), `waitForAllBulkUploads` barrier before sync inventory (c425cd11), `formatApiError` (9a0465b3), `helloMatlab` entry point, `uploadDataset` `isIngested` precondition; `uploadDocumentCollection` is serial-only (MATLAB defaults to ZIP bulk — orders of magnitude fewer requests); `orchestration.syncDataset` mirror modes are no-op stubs and its upload phase ignores `sync_files`.
17. **`_retry_on_server_error` does not exist** despite REPO_AUDIT.md:474's claim — no 5xx retry anywhere. Implement a small 502/503/504 retry (idempotent verbs) in `client.py:_request`, or delete the claim. REPO_AUDIT.md also still documents the pre-camelCase API (`download_dataset` etc.) — mark it superseded.

### 3.5 High — security & packaging

1. **Secrets at rest:** `cloud/profile.py` writes `NDI_Cloud_Secrets.json`/`NDI_Cloud_Profiles.json` with no `chmod` (umask-default 0644) and derives the AES key deterministically from `sha256(hostname+user+"NDI Cloud")[:16]` — local-user decryptable. `os.chmod(0o600)` both files (+ `~/.ndi` 0700), prefer keyring, document the AES fallback as obfuscation. Plaintext `NDI_CLOUD_PASSWORD`/`NDI_CLOUD_TOKEN` are exported into `os.environ` (`auth.py:247-249`, `profile.py:461-463`) — inherited by all subprocesses (matches MATLAB; fix both, §4).
2. **`eval()` on document-derived strings:** `file/navigator/__init__.py:62,251` evals MATLAB-cell-array `fileparameters` from document properties — arbitrary code exec if a malicious document is loaded (documents can arrive via cloud download). Replace the fallback with `ast.literal_eval`. (`fun/data.py:203` is sandboxed — acceptable.)
3. **Unpinned supply chain:** four `@main` git deps (`pyproject.toml:38-41`), `ndi_install.py` clones at `main` with no checksums, CI curls a tarball from `refs/heads/main`. Pin SHAs/tags + lockfile (see §6.3).
4. **CI:** cloud credentials (`TEST_USER_2_*`) injected into per-PR `ci.yml` (any collaborator branch); move cloud-credential tests to the scheduled workflow or gate `if: github.event_name != 'pull_request'`. Pin third-party actions (`ehennestad/matbox-actions`, etc.) to SHAs. Add pip caching (every job reruns full `ndi_install.py`).
5. **Packaging:** sdist + MANIFEST.in + docs reference `MATLAB_MAPPING.md` which **does not exist**; license metadata incoherent (`CC-BY-NC-SA-4.0` text vs `License :: Other/Proprietary` classifier — also flag to maintainers that CC-BY-NC-SA is an awkward software license); 7.0 MB `pythonArtifacts.tar.gz` committed at root is referenced by **nothing** (CI regenerates artifacts) — `git rm`, gitignore `*.tar.gz`, attach to a release if needed.
6. **XML parsing:** stdlib `xml.etree.fromstring` on NCBI/Crossref network responses (`ontology/providers.py:299-343`, `cloud/admin/crossref.py:15`) — use `defusedxml`.
7. **Download path traversal:** `cloud/download.py:390-432` joins remote-document-derived filenames into `target/` unsanitized — `os.path.basename` + containment check.

### 3.6 Medium / Low

- **Perf:** cache `document.read_blank_definition` (re-reads + re-parses the JSON definition *and every superclass* from disk per document construction — `document.py:765,795`); batch/parallelize per-file `getFileDetails`+S3 GET fan-out in downloads; stream bulk-download ZIPs to temp file instead of `io.BytesIO(resp.content)`; route sync deletes/uploads through existing bulk endpoints.
- **Hard-fail principle:** 53 silent `try/except: pass` sites (e.g. `client.py:289`, `database_fun.py:73-79`) — at minimum `logger.debug` the exception; convert genuine errors to raises.
- **`@pydantic.validate_call` mandate is ignored across the core** (document/query/session/element/daq/syncgraph/navigator: 0 decorated methods) while the cloud layer complies — apply to core public surface or amend the guide.
- **Test ergonomics:** `tests/_matlab_license_guard.py:67` raises at *collection* when `NDI_CLOUD_TEST_USER_HAS_MATLAB_LICENSE` unset → bare `pytest tests/` (the AGENTS.md command) errors on every unconfigured machine. Convert to skip while keeping the destructive-path refusal. `@requires_network` ontology tests should skip (not fail) on empty remote results.
- **Auth:** `authenticate()` never consults `profile.py` (MATLAB has a vault tier); `isTokenExpired` lacks MATLAB's 60 s skew margin; login errors embed full server response bodies.
- **Docs:** PYTHON_PORTING_GUIDE.md §6 says Black line length 88; config and AGENTS.md say 100 — fix the guide. `version()` reports git-describe SHA inside checkouts vs `0.1.0` package version (intentional; document it).
- Small parity gaps: `probe.epochprobemapmatch` compares `type` case-sensitively (MATLAB lowercases); `timereference` struct key `session_id` vs MATLAB `session_ID`; missing minor ports `epochNodeName`, `temp_fid`/`temp_name`, `probestruct2probe`, `avi2mp4`, `prism2csv`, `parseText`, per-lab setup syncrule additions (generic `lab()` ports daq systems but drops e.g. vhlab's `filematch`/`filefind` rules); ndr.py wrapper lacks `newdocument` (reader string not persisted), calls `MightHaveTimeGaps` as attribute not method, lacks ingested gap overrides.

---

## 4. NDI-matlab — required changes

### Security
1. **[High] Install-time supply chain:** `ndi_install.m:69,74` + `ndi_setup.m:33` + `tools/+nditools/installMatBox.m` fetch manifests/code from mutable branch refs and execute immediately (`installMatBox('commit')`). Pin tags/SHAs; checksum before executing downloaded `.m`.
2. **[High] Java validator:** `pom.xml` depends on everit json-schema 1.12.1 (2020, via jitpack) with unpinned old jackson-databind transitives (CVE families incl. CVE-2022-42003/4) and a milestone JUnit; the committed 13 MB `ndi-validator-java.jar` is a non-reproducible `1.0-SNAPSHOT`. Upgrade/pin, drop jitpack, build the JAR in CI instead of committing it.
3. **[Medium] `eval()` of document/config-derived strings** (79 eval/feval sites; worst: `+app/+stimulus/tuning_response.m:195,296,426`, `calculator.m:250`, `findepochnode.m:40`) — documents can arrive from cloud downloads; replace with allow-listed `feval` + dynamic field access.
4. **[Medium] Shell interpolation into `system()`:** cloud `PutFiles.m:104-109`/`GetFile.m:68-71` interpolate URLs/paths into curl commands; `convertoldnsd2ndi.m:40-48` interpolates an **unquoted** path into `find -exec bash -c`. Prefer the existing `matlab.net.http` path; escape/validate otherwise.
5. **[Medium] JWT in env var (`setenv('NDI_CLOUD_TOKEN',…)`, `authenticate.m:159`) — inherited by every `system()` child (including the curl calls above); auth failures embed the full response body (`authenticate.m:163-168`). Keep token in-memory; trim error bodies. Mirror the §3.5(1) file-permission fixes for the MATLAB profile/secrets store (same weak AES scheme, documented in profile.m).**
6. **[High, functional bug] `+sync/+enum/SyncMode.m:38` calls `syncOptions.nvpairs()` but `SyncOptions` only defines `toCell()` — `ndi.cloud.syncDataset` should fail at dispatch for every mode. Fix to `toCell()` and add a regression test (also evidence the sync path lacks test coverage).**

### Quality / performance / hygiene
7. **[High] Memoize `document.readblankdefinition`** (`document.m:1016-1031`) — recursive per-construction disk reads, same hot-path issue as Python (§3.6).
8. **[Medium] CI:** SHA-pin actions (esp. personal `ehennestad/matbox-actions` used in secret-bearing workflows); pass `NDI_CLOUD_PASSWORD` via `env:` not command-string interpolation; remove the stale `add-cloud-api-testing` branch trigger in test-cloud-api.yml.
9. **[Medium] Repo bloat:** 45 MB sample tif, 29 MB uncompressed GenBank TSV committed **alongside its own .gz** (twice), 3×16 MB .rec, 13 MB JAR, duplicate .rhd examples → LFS/release assets; drop the uncompressed TSV.
10. **[Medium] God-files:** `mfdaq.m` (1180), `document.m`, `tuning_response.m`, `calculator.m`, `dataset.m`, `syncgraph.m`, `session.m` 950–1200 LOC; conv importers carry copy-pasted boilerplate — extract shared helpers opportunistically (don't big-bang refactor).
11. **[Low] Error identifiers:** ~477 bare `error('msg')` vs ~87 structured `ndi:...` — adopt `ndi:<area>:<reason>` convention going forward.
12. **[Low] Dead code:** `+setup/+daq/+system/deprecating/*` (uses eval), `+api/+auth/loginOriginal.m`/`logoutOriginal.m`, `+upload/for_deletion/*`; two parallel test trees (`src/.../+test` vs `tests/+unittest`); `requirements.txt` is a bespoke unpinned line format (see §6.3); preallocation in ~159 `(end+1)=` growth sites in hot loops; verify no orphaned callers from the `saveStructArray` add-then-revert churn (R2).
13. **[Backport from Python]** Python-only conveniences MATLAB lacks and the team already flagged: auto-paginators, soft-delete API wrappers, `put_file_bytes`; plus the `filehandler` `ndic://` fetch is callback-based in MATLAB but standalone in Python — fine, but document.

---

## 5. Bridge YAML contract — fixes (the contract itself has drifted)

1. **Hash discipline:** several `matlab_last_sync_hash` values are git **blob** hashes, not commit hashes (e.g. `_database_fun.yaml` `6db763c9`) — drift detection silently breaks. Standardize on short commit hashes. Entire bridges (fun, fun/probe, app, app/stimulus, calc/*, gui/*, ontology, file navigator entries) carry **no hashes at all** — add them.
2. **Phantom paths:** GUI bridges' `matlab_path`/`python_path` use flattened class names as filenames (`ndi_gui_Data.m` etc. — the §3.3 C9 corruption); epoch bridge lists `+ndi/+epoch/epoch.m` which never existed (Python-only class — set `matlab_path: null`); cloud bridge cites nonexistent `+api/+files/getBulkUploadURL.m`.
3. **False "Exact match" claims to correct:** app compute stubs (§3.4-13), `epochset.matchedepochtable`/`epochgraph`, `epochprobemap_daqsystem` serialize/decode, sync ops signatures (MATLAB takes `ndi.dataset`, returns `[success,errorMessage,report]`), `zipForUpload` conflation (MATLAB zips binaries; Python zips documents), pagination defaults, `sync.validate` content comparison.
4. **Missing entries to add** (port or explicit `not_applicable`): root — `cache`, `validate`, `subject`, `neuron`, `calculator`; database — `binarydoc`, `matfid`, `doc2ingesteddbfilename`, `list_binary_files`, `table2treatment`, `docComparison`↔`doc_comparison.py`; daq — `ndr.m` wrapper, `VHAudreyBPod`; epoch — `+epochset/param.m` fold-in, `epochNodeName`; time — `timeseries.m`, `+fun/{samples2times,times2samples,syncTriggerTrains,syncRandomTriggers}`; element — `timeseries.m` (incl. `addMultiple`); probe — `probestruct2probe`; fun — `parseText`, `+data/{avi2mp4,prism2csv}`, `+probe/{extracellularInfo,plotProbeGeometry,import.kilosort.*}`; gui — `preferencesEditor`, `profileEditor`, `spikeSorterImporter`; cloud — `formatApiError`, `helloMatlab`, `loginOriginal`/`logoutOriginal`, UI items; util — `readNPY`, `removehiddenfilegroups`; namespaces — add `+example`, `+test` to root `not_applicable`; python-only — `check.py`, `__main__.py`, `class_registry.py`.
5. **Ontology bridge rewrite:** it claims MATLAB has 3 ontologies and no `lookup()` — MATLAB (ndi-ontology-matlab) has 19 classes and a working dispatcher; the "Python-ahead" list is wrong on every item; `matlab_path` should point at the ndi-ontology-matlab repo.
6. **REPO_AUDIT.md:** predates the camelCase migration; documents dead identifiers and the nonexistent `_retry_on_server_error`. Mark superseded (or refresh).

---

## 6. Dependency repos — required changes

### 6.1 DID (the database layer both ecosystems stand on)
1. **[Critical] `isa` operator divergence:** MATLAB expands `isa` to OR(`document_class.superclasses[].definition` CONTAINS x, `document_class.definition` CONTAINS x); DID-python brute-force checks a different field (`class_name`, exact) and its SQL path matches `meta.class`/`meta.superclass` — fields that **never exist** in stored docs. Same query → different result sets per language. Port MATLAB's expansion into `Query._resolve_single` + fix SQL field names (`DID-python/src/did/datastructures.py:279-283`, `implementations/sqlitedb.py:460-465`).
2. **[Medium] `timestamp` column semantics:** MATLAB writes datenum days, Python Unix seconds, same NUMERIC column. Standardize (epoch seconds or ISO-8601 TEXT) with documented conversion.
3. **[Medium] SQL injection surface:** MATLAB concatenates IDs into SQL (`sqlitedb.m:156,…`); Python interpolates **query field names** unescaped (`sqlitedb.py:429-457`). Parameterize/validate (`^[A-Za-z0-9_.]+$`).
4. **[Low] Python omits MATLAB's three sqlite indexes** (`sqlitedb.m:956-958`) — add; document that `doc_data` is a search cache (authoritative content is `docs.json_code`; structural cross-readability is otherwise intact and symmetry-tested).

### 6.2 NDR / vlt / compress / ontology
5. **[High] Six NDR-python readers are stubs** raising `NotImplementedError` on read: `spikegadgets_rec`, `whitematter`, `bjg`, `tdt_sev`, `dabrowska`, and **`neo`** (the gateway to blackrock/plexon/etc.). Prioritize `neo` + `spikegadgets_rec`; make `known_readers` mark stubs so dispatch fails fast.
6. **[Medium] `ndr_reader_types.json` alias registries diverge** (`RHD`/`son`/`ced-smr`/`SpikeGadgets` resolve in MATLAB only; `intan_rhd`/`ced` in Python only). Single shared source + case-insensitive match. Same pattern for `ontology_list.json` (§3.4-14).
7. **[Medium] NDI-compress is unauditable on both sides** (P-code vs committed C binaries, built at different times — format drift can't be ruled out). Vendor the codec source or pin a versioned build + checksums; add a cross-language round-trip fixture test. Add `timeout=` to `compress.py:16` subprocess call.
8. **[Medium] Licensing:** DID-python, NDR-python, vhlab-toolbox-python, NDI-compress-python, ndi-ontology-matlab have **no LICENSE** — add (match their MATLAB counterparts' CC BY-NC-SA).
9. **[Low] vlt:** healthy — NDI-python imports only `loadStructArray` + `vhsb_read`, both implemented. vhlab-thirdparty-matlab/vhlab_vhtools are frozen-2022 but load-bearing (vendored SON32/NPMK binaries; installer `git pull master` over all sibling repos) — treat as frozen, checksum the vendored binaries, replace the pull-master installer with pinned checkouts.

### 6.3 Pinning strategy (one policy for both ecosystems)
Tag releases in lockstep across each MATLAB/Python pair at known-good symmetry points; pin **commit SHAs** in `pyproject.toml` and NDI-matlab `requirements.txt` (currently: four `@main` Python deps; ref-less git URLs in MATLAB); freeze the opaque deps (thirdparty, vhtools, mksqlite, compress binaries) at SHAs with a checksum manifest; run symmetry CI against the pinned SHAs and add a separate scheduled job that bumps to latest and *reports* drift. Today a green symmetry run proves nothing about any fixed release.

---

## 7. ndi-cloud-node (backend) — verified findings

**Source audit completed** in a separate session at HEAD `fcce1ab` (2026-06-03). Stack: Express 4 on Lambda via serverless-http, routes under `/v1`, Mongoose 7 → DocumentDB, Cognito auth, S3 + SNS/SQS async pipeline; API Lambda 30 s / API Gateway 29 s cap (the 504 source). The audit confirmed every client-inferred item below and surfaced higher-severity issues only the source revealed.

### 7.1 Security (source-verified)
1. **[Critical] Any authenticated user can modify any *published* dataset, incl. Mongo-operator injection.** `POST /datasets/:datasetId` is gated only by `userHasAccessToDataset` (visibility, not membership — published datasets are visible to everyone), then passes `req.body` straight to `findByIdAndUpdate`. The field stripper is a top-level deny-list that misses `organizationId`/`branchOf`/`writeLock`/`doi`… and is fully bypassed by an operator body like `{"$set":{"isPublished":false}}`. Any logged-in user can deface, re-own, or un-publish anyone's dataset. (`dataset.controller.ts:368-387`, `:830-843`). **Fix:** require org membership + explicit field allowlist + reject keys starting `$` or containing `.`.
2. **[High] Same visibility-as-write gap on `POST /datasets/:id/submit`** (`dataset.controller.ts:446`) and write-lock acquire — any authed user flips `isSubmitted` on any published dataset. **Fix:** membership check (build a shared `userCanWriteToDataset` middleware and apply to all mutating dataset/document routes).
3. **[High] `POST /compute/start` does not validate org membership** — `organizationId` is taken from the body with a live `// TODO: Validate…` (`compute.controller.ts:109`) and interpolated into a bucket name the API will create if absent → cross-tenant compute I/O. **Fix:** verify membership + ObjectId-validate before interpolation.
4. **[High] Vulnerable dep + no committed lockfile.** `npm audit` = 10 vulns (2 high): `js-cookie ≤3.0.5` via runtime `amazon-cognito-identity-js`. CI gates only `--audit-level=critical` and regenerates the lockfile each run (unreproducible). **Fix:** commit lockfile, bump cognito, gate at `high`.
5. **[Medium] Bookmark IDOR** (`GET /datasets/user/:userId/bookmarks` — any user reads any user's bookmarks), **PII logged** (`updateDataset` dumps full `req.user` incl. matlabLicense ciphertext to CloudWatch, `dataset.controller.ts:370`), **presigned URLs 7-day expiry & `:uid` unvalidated on the single-file path** (`%2F` in uid escapes the dataset key prefix — the bulk path regex-validates, the API path doesn't), **raw `error.message` returned** to clients, **open CORS + no auth rate-limiting**, **static IAM keys in Lambda env**, **403-instead-of-401**. (E5–E12.)
6. **[Info] Solid pieces to keep:** the ndiquery/search translators are properly hardened (field-name regex blocking `$`/dots, depth + regex-length caps, ReDoS heuristic); document reads are dataset-scoped and fail-closed; runner JWTs are KMS-signed ES256 with session-bound revocation; Stripe webhook verifies signatures; zip extraction is zip-slip-safe. The injection surface I worried about from the client side (searchstructure → DB query) is the *best*-defended part of the backend.

### 7.2 Async / 504 (source-verified)
7. **[High] `POST /datasets/:id/submit` 504s by construction** — handler ends `return res.status(204);` with no `.send()`, so the response never finishes; the gateway times out at 29 s *after* the `isSubmitted` write committed. Every submit looks like a 504 while succeeding. **One-line fix:** `res.status(204).send()`.
8. **[High] bulk-delete is a synchronous per-document 2-query loop, uncapped, non-transactional** (`document.controller.ts:296-320`) — a 30 s kill leaves a partial delete (the documented incident). A batched `updateMany` already exists unused (`document.repository.ts:485-490`). Retry-after-504 is safe (soft-delete is idempotent). **Fix:** validate + cap ids, single batched delete, return deleted ids; consider 202+job.
9. **[Confirmed] Publish/unpublish already fall back to 202+SQS** (over 50 / 500 files respectively — the asymmetric thresholds look unintentional), but with **no jobId** — clients poll `isPublishing/publishProgress`. **Bulk-document download has no job status by design** — the API returns a 7-day presigned GET for an object built later, so clients polling S3 until it stops 404-ing is the only mechanism. **Fix:** add a `BulkDownloadJob` status row mirroring the existing `BulkUploadJob`.
10. **[Confirmed] Gateway gzip** is `minimumCompressionSize: 1024` stack-wide (the MATLAB `Accept-Encoding: identity` workaround cause); the bulk-download ZIP is uploaded with no `ContentType` — set `application/zip`.

### 7.3 Data integrity (source-verified)
11. **[High] No unique index on `(dataset, ndiId)`** — the index is non-unique/sparse; create and bulk paths never check for an existing ndiId (which even defaults to `""`). Re-POST or retry-after-504 creates a duplicate row every time — this is the entire reason both clients ship dedup tooling. **Fix:** unique partial index after a dedup backfill, or upsert-by-ndiId.
12. **[High] File-record race confirmed, two windows.** Single-file path `$push`es `{uploaded:false}` with no `size` until the S3 trigger fires; **bulk path is worse** — Stage 1 registers `uploaded:true` + zip-header `size` *before* Stage 2 extracts the bytes, so `uploaded:true` does not mean downloadable and a URL minted in that window 404s. This is the direct cause of the clients' poll-until-stable logic (#805/#807). **Fix:** set `uploaded:true` only after bytes land; expose a stable paginated files endpoint.
13. **[Contract] Timestamp format is undecidable server-side** — document payload is `Mixed`, stored verbatim; the backend has no opinion, so MATLAB datenums and Python epoch-seconds coexist and silently break cross-client `lessthan/greaterthan` ndiquery. **The clients must converge on one format** (ties to DID §6.1-2); a backend normalizer is the alternative.

### 7.4 Contract ambiguities — resolved (updates client findings in §3.4-15)
- **Compute abort = `DELETE /compute/{sessionId}` only.** Python's `POST .../abort` **will 404** — confirmed must change (raises §3.4-15 abort item from drift to a hard bug). Swagger also wrongly advertises `/finalize`; the real route is `/advance`.
- **`/files/bulk` = GET** (Python's POST 404s); it already returns a pollable `jobId` neither client uses.
- **`searchstructure`** = single object *or* array, both accepted (a single dict gets wrapped) — so Python's scalar-dict passthrough actually works; **downgrade** that part of §3.4-15 to stylistic. But **`scope` accepts a CSV of 24-hex dataset IDs** in addition to the enum — Python's `Literal` genuinely loses that capability (keep).
- **Pagination** is inconsistent per endpoint with **no server-side max** on dataset/search/ndiquery (a client `pageSize=100000` is honored); `GET .../documents` is **unpaginated by default**. The **total field varies** (`totalNumber` dataset lists / `totalItems` search / `number_matches` ndiquery / none on `.../documents`). Clients must treat these per-endpoint; backend should standardize + cap.
- **`addDocumentAsFile`** = neither multipart nor strict JSON; the endpoint reads the raw body as **JSON5** (Content-Type ignored). Python's JSON body works; a true multipart envelope would 500. So §3.4-15's "send multipart" is wrong — **keep JSON, drop the multipart recommendation**.
- **`/datasets/search` and `/auth/password/confirm` both exist** — do not drop (confirm-password returns 200 even on failure; clients must read the body).

### 7.5 Performance (source-verified)
- **[High] Auth work is done ~twice per request** — `userHasAccessToDataset` re-parses/re-verifies the same JWT and a fresh `CognitoJwtVerifier` is built per call (defeats JWKS cache); controllers re-build user context. ~2 verifications + 2 user fetches + 2-3 org queries per request. **Fix:** hoist the verifier to module scope, reuse `request.user`, stash `userContext`.
- **[High] `GET .../documents` unpaginated by default** → full-collection scan + serialize inside 30 s. **[Medium]** N+1 S3 on download hydration (new `S3Client` per file, up to 3 HeadObjects each); `documentCount` recomputed via `countDocuments` after every create/delete (use `$inc`). Indexing is otherwise strong.

### 7.6 Top backend fixes (prioritized)
1. Lock down `POST /datasets/:id` (membership + allowlist + reject `$`/dotted) — **Critical**.
2. Shared `userCanWriteToDataset` on `/submit` + all mutating routes.
3. One-line `submitDataset` `res.status(204).send()` (kills a guaranteed-504 core flow).
4. Implement the compute org-membership TODO + ObjectId-validate.
5. Batch + cap (+ optional 202) bulk-delete.
6. Commit lockfile, bump cognito, raise CI audit gate.
7. Unique partial index on `(dataset, ndiId)` after dedup backfill.
8. Hoist Cognito verifier + collapse duplicate auth (biggest latency/cost win).
9. Default + max pagination on documents/search/ndiquery; standardize the total field.
10. Presigned-URL hygiene: validate `:uid`, cut expiry to ≤24 h, set ZIP ContentType, add `BulkDownloadJob` status.

> Two notes to propagate back to the clients: the bulk-file endpoint already returns a `jobId` neither client polls, and the timestamp split (item 13) is the clients' to resolve.

---

## 8. Prioritized roadmap (smallest correct fixes, no overengineering)

**P0 — stop the bleeding (days):**
`ndi_gui_` cleanup (C9) · sync-index camelCase compat (C2) · disable-or-fix `sync/operations.py` deletion path (C1) · binary-upload manifest fix (C3) · `SyncMode.nvpairs()` MATLAB bug (§4-6) · copy the 9 missing/divergent `ndi_common` JSONs (§3.4-3) · chmod 0600 secrets files both languages · **backend: lock down `POST /datasets/:id` published-dataset write (§7.1-1, Critical) + one-line `submit` 504 fix (§7.2-7) + Python `abortSession`→`DELETE` (§7.4, 404 today).**

**P1 — restore parity where science is wrong (1–2 weeks):**
syncgraph branches + underlying epochs + rule daqsystem (C5–C7) · `readtimeseries`/VHSB (C8) · `epochprobemap_daqsystem` format (C10) · DID `isa` (§6.1-1) · `dependency_value_n` · `system_mfdaq` analog-event types · stimulator `pairOnOff` · `syncTriggerTrains` + `randomPulses` algorithms · ontology providers (UBERON/NCIT + registry sync) · cloud contract drift items (§3.4-15/16) + 5xx retry.

**P2 — supply chain & contract hygiene (parallelizable):**
SHA-pin everything (§6.3) + CI action pinning + move cloud creds off PR CI (both repos) · Java validator rebuild (§4-2) · installer pinning (§4-1) · bridge YAML overhaul (§5) · remove dead tarball/`MATLAB_MAPPING.md` references/license classifier · `eval` hardening both languages · defusedxml · path-traversal sanitization.

**P3 — quality & performance:**
definition caching both languages · bulk upload/download batching · except-pass cleanup · validate_call policy decision · NDR stub readers (`neo` first) · MATLAB god-file decomposition + error identifiers + repo-bloat moves · port Kilosort pipeline + `addMultiple` (or record explicit deferral) · refresh/supersede REPO_AUDIT.md & fix porting-guide line-length.

---

## 9. Parity statistics by scope (verified items)

| Scope | OK | Drift/Mismatch | Stale (material) | Missing in Python | Missing in bridge | N/A (documented) |
|---|---|---|---|---|---|---|
| Root/database/util/common/validators/setup | ~52 | 4 | 1 | 9 | 12+ | ~24 |
| DAQ/file/epoch/mock | 24 | 3 | 1 | 3 | 4 | 5 |
| Time/element/probe/session/dataset/fun | ~78 | 4 | 3 | ~18 | ~20 | 1 |
| App/calc/ontology/GUI | ~26 | 6 | 3 | 9 | 6 | 2 |
| Cloud (incl. API contract) | 78 | 18 | 7 | 11 | 10 | 71 |

*(Counts deduplicate within scope, not across; detailed per-item tables live in the underlying analysis passes and the corrected bridge files are the durable home for this state.)*
