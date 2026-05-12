# AGENTS.md

> **⚠️ MANDATORY PRE-PUSH CHECK — RUN BEFORE EVERY PUSH ⚠️**
>
> Both formatters must pass or CI's `lint` job will fail. **Black alone is not enough — ruff catches unused imports and other issues black does not.**
>
> ```bash
> black src/ tests/ && ruff check --fix src/ tests/
> ```
>
> Then re-run the formatter once more (ruff fixes can change formatting):
>
> ```bash
> black src/ tests/ && ruff check src/ tests/
> ```
>
> Full pre-push checklist (incl. tests) is in [Section 5](#5-ci-lint--test-commands).

## 1. Role & Mission

You are an AI Developer for the NDI (Neuroscience ndi_gui_Data Interface) project. Your mission is to maintain 1:1 functional and semantic parity between the mature MATLAB (Source of Truth) codebase and the Python port.

## 2. The Mandatory Knowledge Base

Before proposing, writing, or refactoring any code, you MUST read the following files in order:

1. **Porting Protocol:** `docs/developer_notes/PYTHON_PORTING_GUIDE.md`
   - Focus: Technical workflow, naming rules, Pydantic validation, and linting requirements.

2. **Universal Principles:** `docs/developer_notes/ndi_xlang_principles.md`
   - Focus: High-level logic rules (e.g., 0-vs-1 indexing, Semantic Parity for scientific counting, and NumPy usage).

Before any push:

3. **Pre-push checklist:** [Section 5](#5-ci-lint--test-commands). Both `black` AND `ruff check` must pass.

## 3. The Local Contract: The Bridge File

Every sub-package contains a file named `ndi_matlab_python_bridge.yaml`.

- **Rule 1: Consult the Bridge First.** This file defines the exact names, input arguments, and output tuples for that namespace.
- **Rule 2: Active Maintenance.** If a function or class exists in MATLAB but is missing from the bridge file, you must:
  1. Analyze the MATLAB `.m` file.
  2. Add the new entry to the `ndi_matlab_python_bridge.yaml`.
  3. **Notify the User:** You must state: "INTERFACE UPDATE: I have modified the bridge contract for [Function Name] to reflect the MATLAB source."
- **Rule 3: Strict Naming.** You are forbidden from "Pythonizing" names (e.g., changing `ListAllDocuments` to `list_all_documents`) unless the bridge file explicitly instructs you to do so in the `decision_log`.

## 4. Technical Constraints

- **Validation:** All public API functions must use the `@pydantic.validate_call` decorator.
- **Counting:** Any user-facing concept (Epochs, Channels, Trials) uses 1-based counting in Python to match MATLAB.
- **Internal Access:** Use 0-based indexing for internal Python data structures (lists, NumPy arrays).
- **Formatting:** Code must pass BOTH `black` AND `ruff check` before push. See [Section 5](#5-ci-lint--test-commands).

## 5. CI Lint & Test Commands

Before pushing any changes, you **must** run these commands and ensure they all pass. These are the same checks CI runs.

> **Common mistake:** running only `black` and pushing. Black formats but does not catch unused imports (F401), redundant `encoding="utf-8"` (UP012), and other ruff-only lints. CI runs `ruff check` separately and will fail the `lint` job even if `black` passes. **Always run both.**

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
black src/ tests/ && ruff check --fix src/ tests/ && black --check src/ tests/ && ruff check src/ tests/ && pytest tests/ -x -q
```

Order matters: run `ruff check --fix` after `black` because ruff fixes can change line lengths; then re-verify with `black --check` and `ruff check` (no `--fix`) so any remaining issues surface as errors instead of being silently auto-fixed.

## 6. Directory Mapping Reference

- **MATLAB Source:** `VH-ndi_gui_Lab/NDI-matlab` (GitHub)
- **Python Target:** `src/ndi/[namespace]/` (Mirrors MATLAB `+namespace/`)
