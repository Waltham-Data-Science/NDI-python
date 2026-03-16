# AGENTS.md

## 1. Role & Mission

You are an AI Developer for the NDI (Neuroscience ndi_gui_Data Interface) project. Your mission is to maintain 1:1 functional and semantic parity between the mature MATLAB (Source of Truth) codebase and the Python port.

## 2. The Mandatory Knowledge Base

Before proposing, writing, or refactoring any code, you MUST read the following files in order:

1. **Porting Protocol:** `docs/developer_notes/PYTHON_PORTING_GUIDE.md`
   - Focus: Technical workflow, naming rules, Pydantic validation, and linting requirements.

2. **Universal Principles:** `docs/developer_notes/ndi_xlang_principles.md`
   - Focus: High-level logic rules (e.g., 0-vs-1 indexing, Semantic Parity for scientific counting, and NumPy usage).

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
- **Formatting:** Code must pass `black` and `ruff check --fix` before completion.

## 5. Directory Mapping Reference

- **MATLAB Source:** `VH-ndi_gui_Lab/NDI-matlab` (GitHub)
- **Python Target:** `src/ndi/[namespace]/` (Mirrors MATLAB `+namespace/`)
