# MATLAB to Python Porting Rules

## 1. The Core Philosophy: Lead-Follow Architecture

The MATLAB codebase is the **Source of Truth**. The Python version is a "faithful mirror." When a conflict arises between "Pythonic" style and MATLAB symmetry, **symmetry wins**.

## 2. Function & Variable Naming (The "Strict Mirror" Rule)

**MATLAB function names are the source of truth.** Do **not** attempt to "translate" MATLAB names into Python PEP 8 (`snake_case`).

- **Exact Match:** Every function name in Python must be an identical string match to the MATLAB function name.
- **Case Sensitivity:** If the MATLAB function is `ListAllDocuments`, the Python function must be `ListAllDocuments`. If the MATLAB function is `get_dataset_id`, the Python function must be `get_dataset_id`. If the MATLAB function is `savetofile`, the Python method must be `savetofile` (not `save_to_file`).
- **No Aliasing:** Do not create `snake_case` aliases unless explicitly requested. The user should be able to copy-paste function names between environments.
- **Verification:** When porting or reviewing code, always check the MATLAB source at [VH-Lab/NDI-matlab](https://github.com/VH-Lab/NDI-matlab) to confirm the exact function name. The MATLAB `.m` file's `function` line is the canonical reference.

## 3. Namespace and Directory Structure

MATLAB namespaces (`+` packages) must be mapped 1:1 to Python packages and modules to ensure discoverability.

- **Hierarchy:** Every MATLAB `+namespace` folder must become a Python directory containing an `__init__.py`.
- **File Mapping:** If a MATLAB function exists as `+ndi/+fun/+X/Y.m`, the Python equivalent must be located at `ndi/fun/X/Y.py`.
- **Sub-modules:** For functions inside a namespace that aren't in their own file, group them into a `.py` file named after the MATLAB namespace level.

## 4. Input Validation: Pydantic is Mandatory

To replicate the robustness of the MATLAB `arguments` block, use Pydantic for all public-facing API functions.

- **Decorator:** Use the `@pydantic.validate_call` decorator on all functions.
- **Type Mirroring:**
  - MATLAB `double` or `numeric` → Python `float` or `int`
  - MATLAB `char` or `string` → Python `str`
  - MATLAB `{member1, member2}` → Python `Literal["member1", "member2"]`
- **Coercion:** Allow Pydantic's default behavior of casting (e.g., allowing a string `"1"` or integer `1` to satisfy a `bool` type).

## 5. Error Handling

- If a MATLAB function throws an error for a specific condition, the Python version must raise a corresponding Exception (`ValueError`, `TypeError`, or a custom `NDIError`).
- The goal is to ensure that a user providing bad input gets a **"Hard Fail"** at the function entry point in both languages.

## 6. Documentation (Docstring Symmetry)

- Include the original MATLAB documentation in the Python docstring.
- Note any Python-specific requirements (like specific library dependencies) at the bottom of the docstring.

---

## Namespace Coverage Status

Verified coverage of each MATLAB namespace against the Python port. See
[MATLAB_MAPPING.md](MATLAB_MAPPING.md) for the full function-by-function mapping.

### `ndi.cloud.api` — Fully Ported

**Verified:** 2026-03-11 against `VH-Lab/NDI-matlab` branch `main`.

| Submodule | MATLAB funcs | Python funcs | Coverage | Notes |
|-----------|:------------:|:------------:|:--------:|-------|
| `+datasets` (14) | 14 | 14 + 2 | **100 %** | Python adds `listAllDatasets` (auto-paginator), `listDeletedDatasets` |
| `+documents` (15) | 15 | 15 + 1 | **100 %** | `countDocuments` subsumes MATLAB's `documentCount`; Python adds `bulkUpload` |
| `+files` (6) | 6 | 6 + 2 | **100 %** | Python adds `putFileBytes`, `getBulkUploadURL` |
| `+users` (3) | 3 | 3 | **100 %** | |
| `+compute` (6) | 6 | 6 | **100 %** | |
| `+auth` (8) | 8 | 8 | **100 %** | `loginOriginal`/`logoutOriginal` (legacy) intentionally skipped; auth funcs live in `ndi.cloud.auth` |
| `call.m` / `url.m` | 2 | — | **N/A** | Replaced by `CloudClient` + `CloudConfig` (architectural change) |
| `+implementation/*` (50 classes) | 50 | — | **N/A** | Eliminated; single `CloudClient` replaces all impl classes |

**Architectural differences from MATLAB:**

- MATLAB uses an abstract `call` base class with 50 concrete implementation classes (one per endpoint). Python replaces this with `CloudClient`, a thin `requests.Session` wrapper with `get`/`post`/`put`/`delete` methods.
- MATLAB `url.m` builds endpoint URLs from a name→template dictionary. Python uses `CloudConfig.api_url` + path templates in each function.
- All Python API functions use `@pydantic.validate_call` for input validation (matching MATLAB `arguments` blocks) and `@_auto_client` to make the `client` parameter optional.

**Not ported (intentional):**

| MATLAB | Reason |
|--------|--------|
| `ndi.cloud.uilogin` | MATLAB GUI |
| `ndi.cloud.ui.dialog.selectCloudDataset` | MATLAB GUI dialog |
| `ndi.cloud.utility.createCloudMetadataStruct` | MATLAB struct validator; `CloudConfig` replaces |
| `ndi.cloud.utility.mustBeValidMetadata` | MATLAB struct validator; type hints replace |

### `ndi.validators` — Fully Ported

**Verified:** 2026-03-11 against `VH-Lab/NDI-matlab` branch `main`.

| MATLAB | Python | Coverage |
|--------|--------|:--------:|
| 11 functions | 11 functions | **100 %** |

All 11 MATLAB `arguments`-block validators ported 1:1 with matching
function names.  Python equivalents accept Python types (``list`` for
cell array, ``dict`` for struct, ``pd.DataFrame`` for table).

### `ndi.util` — Fully Ported

**Verified:** 2026-03-11 against `VH-Lab/NDI-matlab` branch `main`.

| Category | MATLAB funcs | Python funcs | Coverage | Notes |
|----------|:------------:|:------------:|:--------:|-------|
| Data/time utilities (8) | 8 | 8 | **100 %** | |
| `+openminds` (2) | 2 | 2 | **100 %** | Ported in `ndi.openminds_convert` |
| GUI / MATLAB-specific (3) | 3 | — | **N/A** | `choosefile`, `choosefileordir`, `toolboxdir` |

**Not ported (intentional):**

| MATLAB | Reason |
|--------|--------|
| `ndi.util.choosefile` | MATLAB GUI dialog (`inputdlg`) |
| `ndi.util.choosefileordir` | MATLAB GUI dialog (`inputdlg`) |
| `ndi.util.toolboxdir` | MATLAB-specific path resolution |
