# NDI Cloud: MATLAB vs Python Structure Audit

This document analyzes every structural difference between the MATLAB and Python
implementations of the NDI Cloud module, explains why each difference exists,
and recommends whether to change or keep it.

**Date**: 2026-02-27 (updated), originally 2025-02-15
**MATLAB source**: `VH-Lab/NDI-matlab` — `src/ndi/+ndi/+cloud/`
**Python source**: `src/ndi/cloud/`

---

## Summary

| Category | Count | Verdict |
|----------|-------|---------|
| `+implementation/` eliminated | ~60 class files | Keep (correct simplification) |
| Auth promoted to top-level | 7 functions | Keep (better ergonomics) |
| Convenience functions re-exported | 4 functions | **Implemented** (now matches MATLAB) |
| `+internal` subpackages flattened | ~20 functions | Keep (reduced nesting) |
| Crossref `+conversion/` flattened | 5 functions | Keep (single file) |
| Sync index collapsed to dataclass | 5 → 1 | Keep (Pythonic) |
| Not ported (GUI/MATLAB-specific) | 5 items | Expected |

**Bottom line**: The Python API surface mirrors MATLAB's for every function that
matters to users. The differences are all internal architecture choices that
simplify the codebase without affecting the call paths.

### Test Results (2026-02-27, verified locally)

| Suite | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| Core + MATLAB port + cloud unit tests | 1660 | 2 | 0 |

- Cloud live tests require credentials and are run separately via CI.

---

## 1. The `+implementation/` Pattern

This is the difference Steve specifically asked about.

### MATLAB Architecture (two-tier)

Every API call in MATLAB uses two files:

```
ndi.cloud.api.datasets.getDataset          → thin function wrapper
ndi.cloud.api.implementation.datasets.GetDataset  → classdef < ndi.cloud.api.call
```

The **function wrapper** (e.g. `getDataset.m`) instantiates the **implementation
class** (e.g. `GetDataset.m`) which extends the abstract base `ndi.cloud.api.call`.
The implementation class declaratively encodes the HTTP method, URL template,
body schema, etc. in class properties. Then `call.execute()` reads those
properties and makes the HTTP request.

This gives MATLAB ~60 function files + ~60 implementation class files = **120
files** for the same set of API endpoints.

### Python Architecture (single-tier)

Python has a `CloudClient` class that wraps `requests.Session` with auth
headers, URL building, and error mapping. Each API module contains plain
functions that call `client.get(...)`, `client.post(...)`, etc. directly:

```python
# ndi.cloud.api.datasets
@_auto_client
def get_dataset(dataset_id: str, *, client: CloudClient | None = None) -> dict:
    return client.get("/datasets/{datasetId}", datasetId=dataset_id)
```

This gives Python ~15 functions per module file × 5 modules = **5 files** for
the same endpoints.

### Why this is correct

The two-tier pattern exists in MATLAB because MATLAB lacks a clean HTTP client
abstraction. The `ndi.cloud.api.call` base class + implementation subclasses are
essentially a declarative HTTP framework built from scratch. Python's
`requests.Session` already provides this, so `CloudClient` replaces the entire
`call` + `implementation` hierarchy.

**User-facing call path is identical:**
- MATLAB: `ndi.cloud.api.datasets.getDataset(datasetId)`
- Python: `ndi.cloud.api.datasets.get_dataset(dataset_id)`

Adding an `implementation/` package to Python would double the code for zero
user benefit.

**Verdict: Keep the Python approach.**

---

## 1b. Keyword-Only `client` Parameter (Implemented — Issue #2)

### MATLAB

MATLAB cloud API functions don't take a client parameter at all — auth is
handled internally via `ndi.cloud.authenticate()`:

```matlab
ndi.cloud.api.datasets.getDataset(datasetId)
```

### Python (before)

Python required an explicit `CloudClient` as the first positional argument:

```python
client = CloudClient(config)
get_dataset(client, dataset_id)  # client is first positional arg
```

### Python (after, Implemented)

All `ndi.cloud.api.*` functions now have `client` as a **keyword-only**
parameter with `default=None`. The `@_auto_client` decorator injects a
client via `CloudClient.from_env()` when none is provided:

```python
# Auto-client from env vars (matches MATLAB — no client needed)
get_dataset(dataset_id)

# Explicit client via keyword (advanced usage)
get_dataset(dataset_id, client=my_client)
```

Function signatures follow the pattern:

```python
@_auto_client
def get_dataset(dataset_id: str, *, client: CloudClient | None = None):
    return client.get("/datasets/{datasetId}", datasetId=dataset_id)
```

The `@_auto_client` decorator is minimal — it checks `kwargs.get("client")`
and injects `CloudClient.from_env()` if None. No duck-typing or positional
detection needed since `client` is keyword-only.

**Verdict: Implemented. Now matches MATLAB's call pattern exactly.**

---

## 2. Auth Functions Promoted to Top-Level

### MATLAB

```matlab
ndi.cloud.api.auth.login(email, password)
ndi.cloud.api.auth.logout()
ndi.cloud.authenticate()
```

### Python

```python
from ndi.cloud import login, logout, authenticate  # top-level re-exports
# Also accessible at ndi.cloud.auth.login(), etc.
```

### Why

MATLAB puts auth under `ndi.cloud.api.auth` because each `.m` file must live in
a namespace directory. Python promotes auth to `ndi.cloud.auth` (one level
shallower) and re-exports from `ndi.cloud.__init__` for convenience.

Users call `from ndi.cloud import login` — the simplest possible import.

**Verdict: Keep. Strictly better ergonomics, no loss of discoverability.**

---

## 3. Top-Level Convenience Functions (Implemented)

### Before

MATLAB's top-level convenience functions (`downloadDataset`, `uploadDataset`,
`syncDataset`, `uploadSingleFile`) lived directly in `ndi.cloud.*`. Python had
these in submodules (`orchestration.py`, `upload.py`) but did **not** re-export
them from `ndi.cloud`.

This meant:
- MATLAB: `ndi.cloud.downloadDataset(...)`
- Python: `ndi.cloud.orchestration.download_dataset(...)` (deeper import)

### After (Implemented)

Python now re-exports these via lazy imports in `ndi.cloud.__init__`:

```python
from ndi.cloud import download_dataset, upload_dataset, sync_dataset, upload_single_file
```

The lazy import mechanism ensures `import ndi.cloud` never fails when `requests`
is not installed. The functions are still defined in their respective modules
(`orchestration.py`, `upload.py`) — the re-exports are just convenience aliases.

| MATLAB | Python (now) |
|--------|-------------|
| `ndi.cloud.downloadDataset` | `ndi.cloud.download_dataset` |
| `ndi.cloud.uploadDataset` | `ndi.cloud.upload_dataset` |
| `ndi.cloud.syncDataset` | `ndi.cloud.sync_dataset` |
| `ndi.cloud.uploadSingleFile` | `ndi.cloud.upload_single_file` |

**Verdict: Implemented. Now matches MATLAB's discoverability.**

### 3b. camelCase Aliases (Implemented — Issue #4)

MATLAB users expect `ndi.cloud.downloadDataset` (camelCase). Python used only
`ndi.cloud.download_dataset` (snake_case). Now the lazy-import table in
`ndi.cloud.__init__` also registers camelCase aliases:

```python
# Both work:
ndi.cloud.download_dataset(...)     # Python convention (primary)
ndi.cloud.downloadDataset(...)      # MATLAB convention (alias)
```

| MATLAB camelCase | Python alias → target |
|------------------|-----------------------|
| `downloadDataset` | → `download_dataset` |
| `uploadDataset` | → `upload_dataset` |
| `syncDataset` | → `sync_dataset` |
| `uploadSingleFile` | → `upload_single_file` |

**Verdict: Implemented. camelCase aliases resolve via `__getattr__` lazy import.**

---

## 3c. Query Subclassing and Cloud API (Implemented — Issue #3)

### Problem

MATLAB's `ndi.query` inherits from `did.query` (`classdef query < did.query`).
Python's `ndi.Query` was a standalone class that didn't subclass `did.query.Query`,
breaking `isinstance` checks and the shared `search_structure` contract.

### Solution

`ndi.Query` now subclasses `did.query.Query`:

```python
import did.query

class Query(did.query.Query):
    """NDI query — subclasses did.query.Query, adds Pythonic operators."""
```

Key properties:
- `search_structure` (inherited from `did.Query`) is the single source of truth
- `isinstance(q, did.query.Query)` returns `True`
- `to_search_structure()` inherited from `did.Query` — returns `search_structure` directly
- MATLAB constructor: `Query('', 'isa', 'base')` maps to DID operations
- Pythonic operators (`==`, `!=`, `>`, `<`, `contains()`, `match()`) build DID-format `search_structure`
- `__and__` / `__or__` return `ndi.Query` (not `did.Query`)

```python
# MATLAB-style
q = Query('', 'isa', 'base')
q = Query('base.name', 'exact_string', 'test')

# Pythonic (builds same search_structure)
q = Query('base.name') == 'test'

# Cloud API — auto-coerced via _coerce_search_structure()
result = ndi_query('public', q)
```

**Verdict: Implemented. Proper subclass of did.Query with full MATLAB compatibility.**

---

## 3d. APIResponse 4-Tuple Unpacking (Implemented — Issue #5)

### Problem

MATLAB cloud API functions return a 4-tuple `[b, answer, apiResponse, apiURL]`
providing response metadata alongside the data. Python's `APIResponse` wrapped
results but didn't support MATLAB-style tuple unpacking.

### Solution

`APIResponse.__iter__` now yields a 4-tuple `(success, data, status_code, url)`:

```python
# Pattern 1: single-value assignment (dict proxy — backward compatible)
result = get_dataset(dataset_id)
result.get("name")       # proxied to data dict
result.success           # True for HTTP 2xx
result.status_code       # 200

# Pattern 2: MATLAB-style 4-tuple unpacking
b, answer, status, url = get_dataset(dataset_id)
answer["name"]           # answer is the raw dict

# Pattern 3: aggregation function unpacking
b, docs, status, url = list_all_documents(dataset_id)
for doc in docs:         # docs is plain list
    print(doc.get("_id"))
```

Aggregation functions (`list_all_documents`, `list_all_datasets`, `ndi_query_all`,
`list_sessions`, `list_files`) explicitly wrap their results in `APIResponse` so
tuple unpacking works consistently. Internal callers that iterate over aggregated
results use `.data` to access the raw list.

**Verdict: Implemented. MATLAB `[b, answer, resp, url]` pattern works in Python.**

---

## 4. Internal Helpers Flattened

### MATLAB

MATLAB has two separate `+internal` namespaces:

```
ndi.cloud.internal.*            (10 functions — JWT, token, dataset linking)
ndi.cloud.sync.internal.*       (12 functions — sync plumbing)
ndi.cloud.sync.internal.index.* (5 functions — sync index CRUD)
```

### Python

Python consolidates into fewer locations:

- `ndi.cloud.auth` — JWT/token functions (moved from `+internal`)
- `ndi.cloud.internal` — dataset linking, file tracking (merged from both)
- `ndi.cloud.filehandler` — on-demand file fetching via `ndic://` protocol (consolidates MATLAB's `updateFileInfoForRemoteFiles.m`, `setFileInfo.m`, and the `customFileHandler` callback from `didsqlite.m`)
- `ndi.cloud.sync.SyncIndex` dataclass — replaces 5 index functions
- `ndi.cloud.sync.operations` — private helpers inline (e.g. `_delete_local_docs`)

### Why

MATLAB needs separate files per function. Python can group related functions in
one module. The sync index functions (`createSyncIndexStruct`,
`getIndexFilepath`, `readSyncIndex`, `updateSyncIndex`, `writeSyncIndex`)
naturally become methods on a `SyncIndex` dataclass.

**Verdict: Keep. Fewer files, same functionality.**

---

## 5. Crossref Conversion Subpackage Flattened

### MATLAB

```
ndi.cloud.admin.crossref.Constants
ndi.cloud.admin.crossref.conversion.convertContributors
ndi.cloud.admin.crossref.conversion.convertDatasetDate
ndi.cloud.admin.crossref.conversion.convertFunding
ndi.cloud.admin.crossref.conversion.convertLicense
ndi.cloud.admin.crossref.conversion.convertRelatedPublications
```

### Python

All in one file: `ndi.cloud.admin.crossref`

```python
CrossrefConstants       # frozen dataclass (replaces Constants.m classdef)
convert_contributors()
convert_dataset_date()
convert_funding()
convert_license()
convert_related_publications()
```

### Why

Five small conversion functions don't justify a sub-sub-package in Python. They
share the same imports and constants. One ~290-line file is more navigable than
6 separate files of 30-50 lines each.

**Verdict: Keep. All conversion functions are now ported.**

---

## 6. Not Ported (Intentional)

These MATLAB-only items were deliberately not ported:

| MATLAB | Reason |
|--------|--------|
| `ndi.cloud.uilogin` | MATLAB GUI login dialog |
| `ndi.cloud.ui.dialog.selectCloudDataset` | MATLAB GUI dataset picker |
| `ndi.cloud.utility.createCloudMetadataStruct` | MATLAB struct validation; replaced by `CloudConfig` dataclass + type hints |
| `ndi.cloud.utility.mustBeValidMetadata` | Same as above |
| `+internal/duplicateDocuments` | Duplicate detection utility — could be ported if needed |

---

## 7. Naming Convention

All function names follow the expected language conventions:

- MATLAB: `camelCase` — `getDataset`, `listDatasetDocuments`, `getBulkDownloadURL`
- Python: `snake_case` — `get_dataset`, `list_documents`, `get_bulk_download_url`

Class names stay `PascalCase` in both: `SyncOptions`, `CloudClient`,
`CrossrefConstants`.

---

## 8. Full Function Coverage Matrix

See [MATLAB_MAPPING.md](MATLAB_MAPPING.md) for the complete function-by-function
cross-reference table covering the entire `ndi.cloud` module (and all other NDI
modules).

---

## Appendix: Python-Only Additions

These functions exist in Python but have no MATLAB equivalent:

| Function | Why |
|----------|-----|
| `list_all_datasets()` | Auto-paginator convenience |
| `list_all_documents()` | Auto-paginator convenience |
| `ndi_query_all()` | Auto-paginator convenience |
| `undelete_dataset()` | Soft-delete API (new backend feature) |
| `list_deleted_datasets()` | Soft-delete API |
| `list_deleted_documents()` | Soft-delete API |
| `put_file_bytes()` | Upload raw bytes (no file on disk) |
| `get_bulk_upload_url()` (files) | Bulk file upload URL |
| `bulk_upload()` (documents) | Low-level ZIP document upload |
| `sync.sync()` | Dispatch by SyncMode enum |
| `download_full_dataset()` | All-in-one dataset + files download |
| `fetch_cloud_file()` | On-demand binary file download via `ndic://` protocol |
| `get_or_create_cloud_client()` | Auto-auth from env vars for headless on-demand fetch |

These should eventually be back-ported to MATLAB for feature parity. The
soft-delete functions (`undelete_dataset`, `list_deleted_*`) will need MATLAB
equivalents once the backend branch is merged. Note: `fetch_cloud_file` has
a MATLAB equivalent (the `customFileHandler` callback in `didsqlite.m`), but
the Python implementation is a standalone function rather than a callback,
since DID-python lacks callback support.

---

## Appendix: Packaging & Dependencies

### pyproject.toml

| Dependency | Type | Status |
|-----------|------|--------|
| `did` (DID-python) | Core | Git URL dep in pyproject.toml; installed normally via pip |
| `numpy>=1.20.0` | Core | OK |
| `networkx>=2.6` | Core | OK |
| `jsonschema>=4.0.0` | Core | OK |
| `requests>=2.28.0` | Core | OK |
| `openMINDS>=0.2.0` | Optional (`[openminds]`) | Added 2026-02-22 |
| `pandas>=1.5.0` | Optional (`[pandas]`) | OK |
| `scipy>=1.9.0` | Optional (`[scipy]`) | OK |
| `matplotlib>=3.5.0` | Optional (`[tutorials]`) | OK |
| `opencv-python-headless>=4.5.0` | Optional (`[tutorials]`) | OK |

**Note**: `vhlab-toolbox-python` is also required at runtime but is not in
`pyproject.toml` — `ndi_install.py` clones it and configures a .pth file.
DID-python's packaging bug (PR #16) was fixed upstream in Feb 2026, so it
now installs correctly via pip from the git URL in pyproject.toml.
`vhlab-toolbox-python` should eventually be published to PyPI for a clean
`pip install ndi`.

### Backend (ndi-cloud-node)

No changes required. The Python client is fully compatible with the current
backend API. Key operational note: the AWS Lambda 30-second timeout causes
HTTP 504 on large publish/unpublish operations. The Python client mitigates
this with `_retry_on_server_error()` (2 retries with exponential backoff).
