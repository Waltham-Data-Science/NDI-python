# Porting Log — 2026-08 catch-up

What this file is: the human-readable record of which NDI-matlab source files were
**examined against NDI-python** during the 2026-08 catch-up program, what happened to
each, and what the `matlab_last_sync_hash` in every `ndi_matlab_python_bridge.yaml`
now means.

## What `matlab_last_sync_hash` records

Per `PYTHON_PORTING_GUIDE.md` §3, the field holds the **short git hash of the last
NDI-matlab commit that touched that specific `.m` file**, obtained with:

```
git -C <NDI-matlab> log -1 --format=%h origin/main -- <path-to-file>
```

Three things it is **not**, all of which were found in the tree before this sweep and
all of which silently break upstream-change detection:

| Wrong value | What goes wrong |
|---|---|
| A **blob** hash (`git rev-parse origin/main:<file>`) | Never equals a commit hash, so every check reports drift forever. Found in `ndi_matlab_python_bridge_database.yaml` (`ad81fd7a`) — outside the 37 contracts, left alone, flagged below. |
| The **branch head** (`origin/main`) | Stops matching the moment any unrelated commit lands. Found on 4 entries in `src/ndi/common/`. |
| An **NDI-python** commit hash | Resolves to nothing in the MATLAB repo. Nearly happened for `vhtaste_bpod.json`, whose note cites the NDI-python commit `725a3b4`. |

**The hash records that the file was EXAMINED, not that it was fully ported.** That
distinction is the whole point: bumping the hash is what makes the *next* upstream
change visible, and the `decision_log` is what stops the bump from reading as a
completed sync. Every deferred entry below therefore carries the wording
`examined 2026-08 at <hash>; deferred: <reason>`.

## Reference points

| Item | Value |
|---|---|
| NDI-matlab `origin/main` | `7509dc96cac34bce25bd00f91417b48838962155` (2026-08-22) |
| NDI-matlab working tree | on `exp/backend-hardening-2026-07` — **not** main; all reads via `git show origin/main:` |
| Contracts in scope | the 37 files named exactly `ndi_matlab_python_bridge.yaml` |
| Examined set | every MATLAB file surfaced by `verify/matlab_drift.md` (M1–M5, S1–S10, blocked, category table) and by the wave build reports |

---

## Summary table

Disposition legend: **PORTED** = code landed this program · **DEFERRED** = examined,
deliberately not ported · **NEW** = entry created by this sweep.

### Ported this program

| MATLAB file | Contract | Old hash | New hash | Item |
|---|---|---|---|---|
| `+ndi/+session/dir.m` | `session/` | `b640e6ff` | `26d0638bf` | M1 marker + S9 SQLite close |
| `+ndi/+dataset/dir.m` | `dataset/` | `7512bcb0` | `26d0638bf` | M1 marker + S9 SQLite close |
| `+ndi/dataset.m` | `dataset/` | `f485088` | `41ef50f54` | M3 `isInCloud` |
| `+ndi/element.m` | `element/` | `c0de73f0` | `1b99d29a0` | M2 doc-guard |
| `+ndi/+fun/+file/pathSafeName.m` | `fun/` | *(none)* | `1b99d29a0` | M2 |
| `+ndi/+fun/+file/elementDirectoryName.m` | `fun/` | *(none)* | `1b99d29a0` | M2 |
| `+ndi/+fun/+file/elementDirectory.m` | `fun/` | *(none)* | `1b99d29a0` | M2 |
| `+ndi/+setup/lab.m` | root *(dup)* | `2566fe4d` | `68431eb38` | M4 — reconciled |
| `+ndi/+setup/rayolab.m` | root *(dup)* | `2566fe4d` | `ffe310085` | M4 — reconciled |
| `+ndi/+fun/+probe/+import/+kilosort/session.m` | `…/kilosort/` | `0a14cf2dc` | `1b99d29a0` | M2 call site |
| `+ndi/+fun/+probe/+import/+kilosort/probe.m` | `…/kilosort/` | `cbbb099bb` | `1b99d29a0` | M2 call site |
| `+ndi/+fun/+probe/+import/+kilosort/getInfo.m` | `…/kilosort/` | `0c1ae7454` | `1b99d29a0` | M2 call site |

Already correct before this sweep, left alone: `+ndi/+cloud/+api/+users/me.m`
(`f2b91923`, S2), `+ndi/+daq/+metadatareader/RayoLabStims.m` (`a05a0a80`, S1), the
three `+ndi/+fun/+stimulus/*` functions (S3), both `+ndi/+setup/+sync/*.m`
(`881919d39`, M4) and `+ndi/+setup/{lab,rayolab}.m` in the canonical `setup/`
contract.

### Examined and deferred

| MATLAB file | Contract | Old hash | New hash | Deferral reason |
|---|---|---|---|---|
| `+ndi/session.m` | `session/` | `a97ab7d0` | `3cde88c87` | Read while porting M1/S9; no item resolved to this file |
| `+ndi/+cloud/profile.m` | `cloud/` | `2566fe4d` | `c4562f578` | 3 in-window commits (+80/−14), none taken — **live interop divergence, see S3 below** |
| `+ndi/+daq/+reader/mfdaq.m` | `daq/` | `9e11fbb` | `866bee2bd` | Python has no ingest-write path to attach the fix to |
| `+ndi/+daq/+reader/+mfdaq/cedspike2.m` | `daq/reader/mfdaq/` | `fe64a9f5` | `ca2d556aa` | S4 blocked on NDR son64 **and** architecturally moot |
| `+ndi/+fun/+probe/plotProbeGeometry.m` | `fun/probe/` | `4f7c78c82` | `ac1b68d2f` | 4 new site-label options unported — **see S4 below** |
| `+ndi/+fun/+probe/+geometry/fromStruct.m` | `fun/probe/` | `bf85e24b7` | `f252f1eb9` | S5 geometry library sized L |
| `+ndi/+fun/+file/dateCreated.m` | `fun/` | *(none)* | `5e97cdeaf` | Parity holds; Linux `st_ctime` fallback divergence recorded |
| `+ndi/preferences.m` | root | `9061865d` | `9a9150e7c` | MATLAB-ONLY parallel-pool preference |

### Branch-head corrections (`src/ndi/common/`, vendored data)

| Entry | Old hash | New hash | Note |
|---|---|---|---|
| `probe_geometry_library` | `7509dc96c` | `1be6aac75` | branch head → per-directory commit |
| `empty_ontology_example_ids` | `7509dc96c` | `64aef69fe` | 5 files / 2 commits → added `matlab_last_sync_hash_by_file` |
| `database_document_markdown_companions` | `7509dc96c` | `79ab22f40` | 2 files / 2 commits → added `matlab_last_sync_hash_by_file` |
| `vhtaste_bpod_daq_system` | `7509dc96c` | `9f77f7919` | branch head → per-file commit |

### Entries created by this sweep (S7, `…/kilosort/`, `not_yet_ported`)

| MATLAB file | Hash | Status |
|---|---|---|
| `recalculatemeanwaveform.m` | `c5df2bf7e` | NEW — not ported (distinct from the ported `meanwaveform.m`) |
| `binaryinfo.m` | `c5df2bf7e` | NEW — not ported |
| `promptrawbinary.m` | `6e20c544d` | NEW — not ported; interactive prompt is the wrong Python surface |
| `readspikeglxmeta.m` | `6e20c544d` | NEW — not ported |

### Examined, deliberately given no entry

No contract entry was created for MATLAB-only or schema-coupled namespaces with no
Python surface: `+ndi/calculator.m`, `+ndi/+mock/*`, `+ndi/+calc/*` (Python's `mock`
layer is empty — blocked), `+ndi/+element/ensemble.m` and the four `image.m` files
(SCHEMA-COUPLED), `+ndi/+setup/+file/+navigator/*` and `VHAudreyBPod.m` (S8, no
Python package), `+ndi/+common/systemCurlEnvPrefix.m` and the `+files/{GetFile,
PutFiles}.m` pair (S10, MATLAB-runtime pathology only), `+ndi/+fun/parallelWorkers.m`
and `+ndi/+fun/clearAllCaches.m`, `+ndi/+setup/vhlab.m`.

---

## Coverage after the sweep

Across the 37 contracts: **0** branch-head hashes, **0** blob hashes, **0**
unresolvable hashes. 24 hashes corrected, 4 entries created.

**42 MATLAB files still carry a stale hash and were left untouched**, because they
were not examined by this program. That is deliberate — bumping them would claim an
examination that never happened. **37 of the 42 are in the `ndi.cloud` namespace**
(`cloud/`, `cloud/api/`, `cloud/sync/`), the rest are
`+ndi/+file/+navigator/rhd_series{,_epochdir}.m`, `+ndi/document.m`,
`+ndi/+time/clocktype.m` and `+ndi/+time/syncgraph.m`. **Eighteen of the 42** are
still pinned at `2566fe4d`, a **2026-05-10 merge commit** that is not a per-file hash
for any of them — it looks like a bulk stamp from an earlier sync. The cloud
namespace has the most contract entries, the most staleness, and received the least
examination in this program; it is the obvious next target.

---

## Surprises

**S1 — `src/ndi/setup/` was already under contract, in the root file.** Both
`verify/matlab_drift.md` (SURPRISE 7) and the W3-A build report state that
`src/ndi/setup/` had no bridge contract and that the namespace was outside the
declared parity contract. It was not: `src/ndi/ndi_matlab_python_bridge.yaml` has
carried `setup.lab` and `setup.rayolab` entries all along. W3-A then created a
second contract at `src/ndi/setup/ndi_matlab_python_bridge.yaml` and bumped the
hashes only there, so `+ndi/+setup/lab.m` was described by two entries with two
different hashes (`2566fe4d` vs `68431eb38`) — an upstream-drift check answered
"stale" or "current" depending on which file it happened to read. Both entries are
now equal, the root entries carry a `canonical_contract:` pointer and a
duplicate-entry warning, and the `setup/` file remains canonical.

**S2 — a blob hash is already in the tree, just outside the 37.**
`src/ndi/ndi_matlab_python_bridge_database.yaml:20` records
`matlab_last_sync_hash: "ad81fd7a"`, which resolves to a **blob**, not a commit. The
three `ndi_matlab_python_bridge_database*.yaml` files are not named
`ndi_matlab_python_bridge.yaml` and so fall outside both the 37-contract scope and
the drift analysis; they were left untouched. W3-A's report warns that bumping by
blob hash would corrupt the contract — that has already happened once, in a file
nobody is auditing.

**S3 — MATLAB and Python now write cloud passwords to different stores.** Deferring
`+ndi/+cloud/profile.m` surfaced a live interop break that the drift analysis had
only as a one-line category-11 row. MATLAB `46672187a` switched the default secret
backend from vault to **AES file**, because MATLAB's `setSecret` is interactive and
cannot persist a password supplied in code; MATLAB's own docstring says the AES file
is deliberately readable "from other languages such as ndi-python on that same
host+user". Python's `_detect_backend` (`src/ndi/cloud/profile.py:192`) still prefers
the OS keyring whenever `keyring` imports. So on a normal machine the two languages
share `NDI_Cloud_Profiles.json` but write the password to two different places and
neither can read the other's. The bridge's own claim that "the on-disk JSON is
interchangeable" holds for metadata and **not** for secrets. Recorded, not fixed —
moving Python's secrets out of the OS keychain into a hostname-keyed file is a
security decision, not a port.

**S4 — `plotProbeGeometry` gained four arguments Python does not have, and one of
them defaults to on.** MATLAB `ac1b68d2f` added `show_labels` (**default true**),
`labels`, `label_font_size`, `label_color`, plus an `h.labels` output. The same
`probe_geometry` therefore renders differently in the two languages today: MATLAB
numbers every site, Python does not. It arrived inside a KIASORT/GUI commit, which is
why a drift table organised by subsystem classified it away from the `fun/probe`
surface it actually changes. Recorded on the entry so the hash bump cannot hide it.

**S5 — the withheld bumps were withheld for a good reason, and bumping them is still
correct.** W1-B, W1-E, W3-B and W3-D each explicitly declined to bump a hash on a
partial sync, reasoning that bumping "would claim a sync that did not happen". Under
the guide's §3 semantics that reasoning inverts: withholding the bump does not
record the partial sync, it just leaves the file looking un-examined, and the next
drift run re-reports work already done while the *genuinely* unported part stays
invisible either way. The fix is the bump **plus** explicit deferral wording, which
is what this sweep applied. Worth settling as a convention so the next wave does not
re-litigate it.

**S6 — `meanwaveform.m` and `recalculatemeanwaveform.m` are different files.** The
kilosort contract's `meanwaveform` entry is current at `4c84a1ac4` and maps to
`meanwaveform.py`, which averages templates already on disk. Drift item S7 is about
`recalculatemeanwaveform.m`, which re-reads the raw binary and has no Python
counterpart at all. Reading S7 as "the meanwaveform entry is stale" would have
produced a wrong bump on a correctly-synced entry; the four S7 files got their own
`not_yet_ported` entries instead.

**S7 — one decision_log had been made false by the port that followed it.** The
kilosort `session` entry still read "Spaces in the element string are replaced by
underscores, matching the export layout" — the pre-M2 behaviour that W1-C replaced
with `elementDirectory` resolution. Appending without reading would have left two
contradictory sentences in one contract; the entry now carries a dated `SUPERSEDES`
line. Append-only is right for history, but a superseded claim has to be marked as
such or the contract lies.
