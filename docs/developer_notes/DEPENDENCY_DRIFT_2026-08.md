# Dependency drift, August 2026 — what DID-python and NDR-python mean for NDI-python

Examined 2026-08-29 against:

| Repository | Tip examined | Previous state NDI-python was written against |
|---|---|---|
| `VH-Lab/DID-python` | `8a6cd22` (2026-08-29) | `361df8d` (2026-06-14) — 50 commits of drift |
| `VH-Lab/NDR-python` | `56d5535` (2026-08-28) | ~2026-06 — 26 commits of drift |
| `VH-Lab/NDI-matlab` | `e8d53ef` | — |
| `Waltham-Data-Science/NDI-python` | `ed78f8b` (`main`) | — |

`pyproject.toml` pins both dependencies at `@main`, so this drift reaches every
fresh install with no change in this repository. Everything below was measured
in a clean venv with the installed SHAs verified through `direct_url.json`, not
read off the source.

---

## 1. The break: DID-python now validates every document it stores

`did.database.add_docs` gained a `validate=True` default (`2e6e445`,
`feat(validate): port document-vs-schema validation from DID-matlab`). It runs
the new `did.validate`, a port of DID-matlab's `validate_docs` /
`validate_doc_vs_schema` / `validate_field_type_and_value` / `checkfiles`.

Before this change, storing a document checked nothing. Now every document is
resolved against its `document_class.validation` schema, and against each
superclass schema in turn, on the way into the database.

**Measured effect on `main` before any fix: 57 failed, 59 errors** across the
core suite. Every one of them reduced to a single cause:

```
did.validate.ValidationError: Validation file "$NDISCHEMAPATH/session.json" not found
```

### Root cause

DID resolves every `$…PATH/…` location through
`did.common.PathConstants.DEFINITIONS`. NDI-matlab has always registered its
four placeholders there — `ndi.common.PathConstants` does it from the
`mustUpdateDidGlobals` property validator and from the static
`updateDIDConstants`:

```matlab
'$NDISCHEMAPATH',       ndi.common.PathConstants.DocumentSchemaFolder
'$NDIDOCUMENTPATH',     ndi.common.PathConstants.DocumentFolder
'$NDICALCSCHEMAPATH',   ndi.common.PathConstants.CalcDocSchema
'$NDICALCDOCUMENTPATH', ndi.common.PathConstants.CalcDoc
```

**NDI-python never registered any of them.** It resolved `$NDIDOCUMENTPATH`
by literal string replacement at two call sites in `ndi/document.py`, which was
enough while nothing else needed to resolve a path — and silently insufficient
the moment DID had to.

### Fix

`ndi.common.updateDIDConstants()` ports `updateDIDConstants`, and `ndi.common`
calls it at import time (Python has no constant-property validators to hang it
on). Like MATLAB it fills in absent keys only, unless `force=True`; like MATLAB
it raises if `$NDIDOCUMENTPATH` cannot be resolved.

One deliberate divergence, recorded in the bridge YAML: MATLAB registers the
two `$NDICALC…PATH` keys as a *cell array* of calculator-toolbox directories
found by `ndi.fun.find_calc_directories`. Python has no separate calculator
packages — `ndi_install.py` copies each dependency's
`ndi_common/{database,schema}_documents` into NDI-python's own tree — so both
calc placeholders resolve to the same two directories as the non-calc ones. If
Python ever grows out-of-tree calculator packages, `_did_placeholder_values()`
is where the extra directories belong.

After this fix and the one in §4, the whole suite is green: **1576 passed,
216 skipped, 2 xfailed** (both the DID bug in §3). Excluded: four
`TestOntologyLookupLive` tests that need live NCBI/EBI lookups, and one
symmetry artifact test that downloads from the cloud — neither reachable from
this sandbox.

### `python -m ndi check` now covers it

The old check imported `did`, constructed an `ndi_document('base')`, and
stopped. Constructing a document exercises none of the schema resolution that
*storing* one does, so a completely unusable install reported 14/14. It now
also asserts the four placeholders are registered and resolve to real
directories, imports `ndr` and `ndicompress` (neither of which anything else in
the check touched), and round-trips a document through a throwaway session:
add, search, remove.

---

## 2. The other DID change that reaches us

`add_docs` also gained `OnDuplicate` (`'error'` by default, mirroring
DID-matlab's `mustBeMember`). NDI's `SQLiteDriver.add` and `bulk_add` do their
own duplicate checks against `get_doc_ids` before calling through, so behaviour
is unchanged — but `bulk_add`'s hand-rolled skip loop is now a candidate to
become `OnDuplicate='ignore'`, which would let DID do it in one statement
instead of one round-trip per document. Not changed here; noted.

Also newly available and not yet used by NDI-python:

* `SQLiteDB.open_doc(..., custom_file_handler=...)` and the new `files` table —
  DID's own seam for retrieving a document's files from a non-local location.
  NDI-python already does this outside DID, in `ndi.cloud.filehandler` /
  `session._try_cloud_fetch`. DID-python's `did_matlab_python_bridge` records
  how NDI-**matlab** supplies file retrieval to DID; aligning Python with that
  is its own task.
* `did.file.binaryTable` / `FileCache`, wired into `open_doc`.
* `did.document` ISO-8601 UTC datestamp — ported *from* NDI-python into DID
  (`875de5c`), so `ndi.common.timestamp` could now delegate rather than
  duplicate.

---

## 3. Upstream DID-python bug — removing a file-bearing document

`9997412` (`fix(sqlitedb): record file locations so MATLAB can find them`)
added a `files` table with `FOREIGN KEY(doc_idx) REFERENCES docs(doc_idx)`.
`_do_remove_doc` was not updated: it deletes from `branch_docs`, `doc_data` and
`docs`, but never from `files`.

Any document that carries a file therefore cannot be removed:

```
sqlite3.IntegrityError: FOREIGN KEY constraint failed
  did/implementations/sqlitedb.py:1134  DELETE FROM docs WHERE doc_idx = ?
```

Reproduced with DID alone, no NDI involved. In NDI-python it breaks
`session.database_rm` for any document with a binary attached
(`tests/matlab_tests/test_database.py::TestNDIDocument::test_document_creation_and_io`).

**There is no NDI-side fix** — the missing `DELETE` is inside DID's driver.
Fixed upstream in [VH-Lab/DID-python#39](https://github.com/VH-Lab/DID-python/pull/39),
which adds the missing statement and a rollback (the failure also left the
`branch_docs` delete sitting in an open transaction for the next commit on the
connection to pick up).

**The fix is independent of DID-matlab; nothing there needs to change.**
MATLAB's `do_remove_doc` deletes only the `branch_docs` row — the `docs` and
`doc_data` deletes sit in a commented-out block under `% TODO - remove all
document records if no branch references remain?`. Python implements that TODO,
so only Python ever deletes the row the foreign key points at, and only Python
can hit the constraint. The bridge recorded this pair as "Exact match", which
is why the asymmetry went unnoticed; #39 corrects it.

Held here as a **strict xfail** in two places — `tests/test_did_integration.py`
and `tests/matlab_tests/test_database.py` — so the day #39 lands CI says so by
name instead of staying quietly red.

---

## 4. A second NDI-python gap the validator exposed: unflattened superclasses

With the placeholders registered, ingestion still failed outright:

```
Dissimilar superclasses defined/found for daqreader_epochdata_ingested doc …
  ("base" <=> "base,epochid")
```

and four more document types disagreed with their own schemas the same way,
while `stimulus_response_scalar` was found carrying **one** dependency where
its schema declares five.

### Root cause

`did.document._merge_superclasses` — and MATLAB's `did.document` before it —
inherits **three** things from a superclass: its property groups, its
`depends_on` entries (unioned by name, subclass winning), and *its own
superclass list*, so a stored document carries the full transitive closure.
NDI-python's `ndi_document.read_blank_definition` merged only the first.

Documents built by NDI-python therefore carried just their direct superclasses
and just their own dependencies, while the schemas — written against MATLAB,
where DID flattens — declare the closure. Nothing compared the two until
`add_docs` began validating.

This is why `stimulus_response_scalar` documents were being written with 1 of 5
`depends_on` slots: not a schema-v2 question, an unflattened parent.

### Fix

`read_blank_definition` now unions the superclass list and the dependency list
as DID does, unique by definition string / by name, order preserved. That alone
resolved `oneepoch`, `mock/demoNDIMock`,
`ingestion/daqreader_mfdaq_epochdata_ingested` and
`stimulus/stimulus_response_scalar`, and un-broke ingestion
(`tests/symmetry/make_artifacts/session/test_ingestion_intan*.py`,
`test_ingestion_axon_ndr.py`).

> Note for whoever merges **#63**: that PR also edits `read_blank_definition`
> (adding the recursive bare-name lookup). The two changes are independent —
> one resolves *where* a definition lives, this one merges *what* it carries —
> but they touch the same function and will need a hand merge.

`ingestion/daqreader_epochdata_ingested_schema.json` was a genuine schema
defect and is fixed in NDI-matlab: its definition names `base` and `epochid`
directly, and its own child's schema already lists `epochid`, but its
`superclasses` said `["base"]`.

---

## 4a. Documents NDI still cannot store

Sixteen bundled document types remain invalid against their own schemas. These
are defects in the shared `ndi_common` JSON — NDI-matlab and NDI-python carry
the same bytes — listed by name in `KNOWN_UNVALIDATABLE_DEFINITIONS`
(`tests/test_did_integration.py`), which fails if a new one appears *and* if a
listed one starts working. Two groups:

| Group | Types | What is wrong |
|---|---|---|
| `ValidationField*` | `data/generic_file`, `data/ngrid`, `data/ontologyImage`, `data/image`, `data/imageStack`, `data/imageStack_parameters`, `data/binaryseries_parameters`, `epochclocktimes`, `demoNDI`, `mock/demoNDIMock`, `session_in_a_dataset` | The blank template seeds a value its own schema rejects — `""` where a `double` is declared, `[]` where a matrix schema declares dimensions. Same family as the open `t0_t1` orientation question; it wants one answer for the whole family (schema-valid defaults in the templates, or a fourth `parameters` entry allowing empty). |
| `PropertyFieldMissing` | the five `apps/vhlab_voltage2firingrate/*` | Their `_schema.json` files are JSON-Schema **draft-2019-09** documents, not DID schema documents. They were never ported to the DID schema format. |

None of these blocks a live NDI-python path today — the affected classes are
either unused (`demoNDI`, `mock`) or only ever read, never written
(`generic_file` in `ndi.cloud.download`). They will block whoever first writes
one.

### Shared `ndi_common` JSON repaired in this change

Fixed in **NDI-matlab first** (it leads) and mirrored here:

| File | Defect | Fix |
|---|---|---|
| `schema_documents/data/image_schema.json` | superclass named `imageStackParameters`; the definition's actual superclass is `imageStack_parameters` | renamed to match |
| `schema_documents/ingestion/daqreader_epochdata_ingested_schema.json` | `superclasses: ["base"]`, but the definition names `base` **and** `epochid`, and the child class's schema already lists `epochid` | added `"epochid"` |
| `database_documents/apps/calculators/simple_calc.json`, `apps/jrclust/jrclust_clusters.json`, and four `apps/vhlab_voltage2firingrate/*` | dependency default `"value": 0` — a number where every other definition uses `""`, which DID rejects as a non-character dependency value | `"value": ""` |

Python-side drift, re-synced from NDI-matlab:

| File | Defect |
|---|---|
| `schema_documents/data/image_schema.json` | NDI-python's copy carried a trailing comma in `depends_on`, making it unparseable. NDI-matlab's copy was already correct. |

`tests/test_did_integration.py::test_every_bundled_json_parses` now keeps the
whole `ndi_common` tree parseable.

---

## 4b. `[-Inf,Inf,0]` is not a defect — a correction

An earlier pass on this work read `"parameters": [-Inf,Inf,0]` in
`apps/calculations/simple_calc_schema.json`, `simple_calc_v2_schema.json` and
`apps/markgarbage/valid_interval_schema.json`, saw Python's `json` reject it,
and concluded the files were broken in both languages. **That was wrong**, and
the substitution it prompted (the largest finite double) has been reverted.

MATLAB's `jsondecode` accepts the bare tokens `Inf`, `-Inf` and `NaN`. Python's
`json` accepts `Infinity` / `-Infinity` / `NaN` but not `Inf`. Only Python was
failing.

The evidence, rather than an appeal to what `jsondecode` ought to do: NDI-matlab
PR #889 is the change that first made `testSimple` exercise the whole validation
path — `verifySelfTests` → `run()` → `database_add` → `did.database/validate_docs`
→ `get_document_schema` on the document's own `validation` pointer, which after
that PR is `simple_calc_v2_schema.json`, the file containing `[-Inf,Inf,0]`.
`testSimple` is collected by `TestSuite.fromFolder(tests, IncludingSubfolders=true)`
and is neither a cloud nor a `Graphical` test. `run-tests.yml` run 1313
(2026-08-26) is **green on a real MATLAB runner**, as is every run on `main`
since. A `jsondecode` that rejected `-Inf` would have failed it.

So the bound really is infinite and MATLAB really reads it. Rewriting the shared
JSON to a finite bound would have narrowed what those schemas mean in the
language that reads them correctly, to accommodate the parser in the language
that does not. The reader is what needed fixing:
[VH-Lab/DID-python#40](https://github.com/VH-Lab/DID-python/pull/40) widens bare
`Inf` to `Infinity` outside strings in DID's two definition-file loaders.

Until that pin lands, `apps/calculators/simple_calc` and
`apps/markgarbage/valid_interval` sit in `KNOWN_UNVALIDATABLE_DEFINITIONS` with
`ValidationFileBad` and a note to delete them when it does — they are the one
group in that list that clears without anyone touching a definition file. The
`test_every_bundled_json_parses` gate applies the same widening locally, so it
measures the files rather than the reader.

**General lesson for this kind of sweep:** "Python cannot parse it" is not the
same as "it is malformed". Where the two languages read the same bytes, check
what the language that owns the file actually does before calling the file
wrong — a green CI run on the path that reads it is the cheapest proof
available.

---

## 5. NDR-python: two deferrals in PR #61 are no longer blocked

Nothing in NDR broke NDI-python — the names `ndi.daq.reader.mfdaq.intan` and
`ndi.daq.reader.mfdaq.ndr` import from still exist and still behave the same.
What changed is that two items PR #61 deferred *as blocked* now have the
upstream support they were waiting on.

### `cedspike2` / son64 — unblocked

PR #61: *"Blocked on NDR (verified): NDR-python has zero son64/sonpipe support
and hard-rejects `.smrx`."* That is no longer true. `b058546` routes all CED
reads through the sonpipe CLI, and `ndr_reader_types.json` now advertises
`smrx`, `ced-smrx` and `son` on `ndr.reader.ced_smr`.

NDI-python's `cedspike2` still goes through the SpikeInterface adapter, which
has no CED branch and no `spikeinterface` installed, so both `.smr` and `.smrx`
silently return `[]`. The port is now the same shape as MATLAB's: route
`cedspike2` through NDR. Needs sonpipe present at runtime.

### `vhprairieview` — unblocked

The one symmetry failure PR #61 deliberately left red
(`daqSystemNames` 8 in Python vs 9 in MATLAB) is `vhprairieview`, which needed
`ndi.daq.reader.image.ndr` and `ndi.setup.file.navigator.vhPrairie2p`. NDR-python
now has the whole image/frame API (`numframes`, `framesize`, `frametimes`,
`framelayout`) plus `tiffstack`, `prairieview` and `vld` readers (`e792a13`).
The NDI side — an image DAQ reader and the PrairieView navigator — is still to
be written, but it is now a port rather than a blocked one.

### Behaviour changes to watch when those ports happen

* `de641c0` — round half **away from zero** at every time-to-sample conversion.
  NDI's epoch and sample arithmetic sits directly on top of this.
* `83280c6` / `0f90dc0` — reader aliases widened, datatype strings tightened to
  strict parity.
* `0966969` — Axon honours requested channel order; CED exposes per-channel
  streams.
* `1d26695` / `b68efcc` / `3274f5b` — Intan block sizing and SpikeGadgets stride
  corrections. These are **data-correctness** fixes on paths NDI-python already
  uses; anything read with an older NDR should be re-read.
* `aa6ac37` — NDR-python relicensed MIT (was CC-BY-NC-SA) to match NDR-matlab.

---

## 6. What this means for the open PRs

* **#61** (`catchup/ndi-python-2026-08`) pins `did`/`ndr` at the audriB fork
  hardening tips and says to flip them to VH-Lab SHAs once those PRs merge.
  They have merged. As written, #61 does **not** carry the
  `updateDIDConstants` port, so rebasing it onto a current `did` reproduces the
  57-failure/59-error state above. It needs this change (or its own copy of it)
  before its numbers mean anything.
* **#63** fixes `$NDICALCDOCUMENTPATH` by stripping any `$…PATH/` prefix inside
  NDI's own document reader. That still works and is independent of this
  change, which fixes the *other* consumer — DID's resolver, which NDI cannot
  reach by string-stripping. Once both land, the two literal
  `.replace("$NDIDOCUMENTPATH/", "")` sites in `ndi/document.py` can be
  replaced by `did.validate.resolve_definition_path`, matching how MATLAB
  resolves. Not done here to avoid conflicting with #63.
* #63's `calculator.json` copy is confirmed still missing from this repo's
  `ndi_common` (`Only in NDI-matlab: calculator.json`), as is the whole
  schema-v2 line (`simple_calc_v2_schema.json`, `tuningcurve_calc_v2_schema.json`,
  `calculator_schema.json`). NDI-python's `simple_calc.json` is still
  `class_version` 1 with `base`+`app` superclasses where NDI-matlab has moved to
  version 2 with a `calculator` superclass. That migration is deliberately
  untouched here.

---

## 7. Open asks

**DID-python**

1. `_do_remove_doc` must delete the document's `files` rows (§3). Blocking.
   Submitted as [DID-python#39](https://github.com/VH-Lab/DID-python/pull/39);
   the two strict xfails here come out when it merges.

**NDI-matlab** (shared `ndi_common`, both languages)

2. The five `apps/vhlab_voltage2firingrate/*` schemas are in the wrong format
   entirely — JSON-Schema draft-2019-09, not DID schema documents. Porting
   them is real work, not a data fix.
3. The blank-template values that violate their own schemas (§4a) — whether
   the template or the schema is wrong is the same question as `t0_t1`
   orientation and should be answered once for the whole family.
4. The three shared-JSON repairs above (`imageStackParameters`, the ingestion
   `epochid`, `"value": 0`) are on `claude/ndi-python-dependency-drift-uxa35e`
   in NDI-matlab and want a MATLAB-side run before they go further — none was
   executed against a MATLAB runtime here.
