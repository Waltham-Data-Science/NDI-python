# AGENTS.md

## 1. Role & Mission

You are an AI Developer for the NDI (Neuroscience ndi_gui_Data Interface) project. Your mission is to maintain 1:1 functional and semantic parity between the mature MATLAB (Source of Truth) codebase and the Python port.

## 2. The Mandatory Knowledge Base

Before proposing, writing, or refactoring any code, you MUST read the following files in order:

1. **Porting Protocol:** `docs/developer_notes/PYTHON_PORTING_GUIDE.md`
   - Focus: Technical workflow, naming rules, Pydantic validation, and linting requirements.

2. **Universal Principles:** `docs/developer_notes/ndi_xlang_principles.md`
   - Focus: High-level logic rules (e.g., 0-vs-1 indexing, Semantic Parity for scientific counting, and NumPy usage).

3. **Bridge Field Reference:** `docs/developer_notes/ndi_matlab_python_bridge.yaml`
   - Focus: What every field in a bridge entry means, and the NORMATIVE `status` vocabulary (its section 6). This is the single source of truth for those rules; nothing else restates them.

## 3. The Local Contract: The Bridge File

Every sub-package contains a file named `ndi_matlab_python_bridge.yaml`.

- **Rule 1: Consult the Bridge First.** This file defines the exact names, input arguments, and output tuples for that namespace.
- **Rule 2: Active Maintenance.** If a function or class exists in MATLAB but is missing from the bridge file, you must:
  1. Analyze the MATLAB `.m` file.
  2. Add the new entry to the `ndi_matlab_python_bridge.yaml`.
  3. **Notify the User:** You must state: "INTERFACE UPDATE: I have modified the bridge contract for [Function Name] to reflect the MATLAB source."
- **Rule 3: Strict Naming.** You are forbidden from "Pythonizing" names (e.g., changing `ListAllDocuments` to `list_all_documents`) unless the bridge file explicitly instructs you to do so in the `decision_log`.
- **Rule 4: Say Which Kind Of "Not Ported".** An entry with no Python counterpart carries a `status` and a `decision_log`. There are exactly five values, and picking the wrong one misleads the next reader:

  | status | means |
  |---|---|
  | *(absent)* + a `python_path` | ported: a 1:1 counterpart under the mirrored name. The normal case — writing `ported` out is allowed but never required. |
  | `ported_differently` | Python CAN do it, just not 1:1 — different name, folded into a class, a library that does the job. Say how. |
  | `matlab_only` | Python needs nothing, by design: the function works around MATLAB itself (no `parfor`, no logging module, cannot read `.npy`). |
  | `porting_deferred` | portable work nobody has done yet. Say why not now, or what blocks it. |
  | `retired` | there is no MATLAB function to port — removed upstream, or never existed. A tombstone. |

  The distinction that matters most is `ported_differently` vs the rest: it is the only one that answers **yes** to "can I do this from Python?". Definitions, worked examples and a decision procedure are in section 6 of `docs/developer_notes/ndi_matlab_python_bridge.yaml`. Enforced by `tests/test_matlab_bridge_status.py`.

  Do not invent a sixth value. `not_yet_ported`, `not_applicable`, `implemented` and `does_not_exist` were retired: the first two each meant several incompatible things at once. `ported_elsewhere` was renamed to `ported_differently` (NDR-python#21) — same meaning, but it names the manner rather than a place `python_path` already gives.

## 4. Technical Constraints

- **Validation:** All public API functions must use the `@pydantic.validate_call` decorator.
- **Counting:** Any user-facing concept (Epochs, Channels, Trials) uses 1-based counting in Python to match MATLAB.
- **Internal Access:** Use 0-based indexing for internal Python data structures (lists, NumPy arrays).
- **Formatting:** Code must pass `black` and `ruff check --fix` before completion.

## 5. CI Lint & Test Commands

Before pushing any changes, you **must** run these commands and ensure they all pass. These are the same checks CI runs.

### Formatting (Black)

```bash
black --check src/ tests/
```

To auto-fix formatting issues:

```bash
black src/ tests/
```

Configuration is in `pyproject.toml`: line-length = 100, target-version = py310/py311/py312.

### Linting (Ruff)

```bash
ruff check src/ tests/
```

To auto-fix what ruff can:

```bash
ruff check --fix src/ tests/
```

Configuration is in `pyproject.toml` under `[tool.ruff]` and `[tool.ruff.lint]`.

### Tests

```bash
pytest tests/ -v --tb=short
```

Symmetry tests (cross-language MATLAB/Python parity) are excluded from the default run and are invoked separately in CI:

```bash
pytest tests/symmetry/make_artifacts/ -v --tb=short
pytest tests/symmetry/read_artifacts/ -v --tb=short
```

### Quick pre-push checklist

```bash
black src/ tests/ && ruff check src/ tests/ && pytest tests/ -x -q
```

## 6. Directory Mapping Reference

- **MATLAB Source:** `VH-ndi_gui_Lab/NDI-matlab` (GitHub)
- **Python Target:** `src/ndi/[namespace]/` (Mirrors MATLAB `+namespace/`)
