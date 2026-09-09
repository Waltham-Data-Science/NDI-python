# NDI MATLAB to Python Porting Guide

## 1. The Core Philosophy: Lead-Follow Architecture

The MATLAB codebase is the **Source of Truth**. The Python version is a "faithful mirror." When a conflict arises between "Pythonic" style and MATLAB symmetry, **symmetry wins**.

- **Lead-Follow:** MATLAB defines the logic, hierarchy, and naming.
- **The Contract:** Every package contains an `ndi_matlab_python_bridge.yaml`. This file is the binding contract for function names, arguments, and return types for that specific namespace.

## 2. Naming & Discovery (The Mirror Rule)

Function and class names must match MATLAB exactly.

- **Naming Source:** Refer to the local `ndi_matlab_python_bridge.yaml`.
- **Missing Entries:** If a function is not in the bridge file, refer to the MATLAB source to determine the name, add the entry to the bridge file, and notify the user of the addition for their review.
- **Case Preservation:** Use `ListAllDocuments`, not `list_all_documents`. Use `savetofile`, not `save_to_file`.
- **Directory Parity:** Python file paths must mirror MATLAB `+namespace` paths (e.g., `+ndi/+cloud` → `src/ndi/cloud/`).

## 3. The Porting Workflow (The Bridge Protocol)

To port or update a function, agents must follow these steps:

1. **Check the Bridge:** Open the `ndi_matlab_python_bridge.yaml` in the target package.
2. **Sync the Interface:** If the function is missing or outdated, update the YAML entry first based on the MATLAB `.m` file.
3. **Record the Sync Hash:** Store, in `matlab_last_sync_hash`, the short hash of a **COMMIT in NDI-matlab** that your examination was made against. Obtain it with:

   ```
   git log -1 --format="%h" -- <path-to-matlab-file>
   ```

   **It must be a commit, never a blob.** `git hash-object <file>` returns the hash *of the file's contents*, which looks equally plausible in the YAML and is useless here: the freshness check works by walking history (`git log <hash>..HEAD -- <path>`), and a blob is not a point in history to walk from. 35 entries carried blob hashes before this was written down, because "the hash of the MATLAB file" reads naturally as either one. A test now rejects anything that is not a commit.

   Either kind of commit is acceptable: the file'''s own last-touching commit (what the command above gives), or a repo-wide commit such as NDI-matlab `HEAD` when you examined a batch of files together. Both are points in history, so both let the check ask "has this file moved since?"
4. **Implement:** Write the Python code to satisfy the `input_arguments` and `output_arguments` defined in the YAML.

   If you are NOT porting it, the entry needs a `status` and a `decision_log` instead. The five permitted values, what each claims, and how to choose between them are defined in section 6 of `docs/developer_notes/ndi_matlab_python_bridge.yaml` — that is the normative list, and this guide deliberately does not repeat it.
5. **Log & Notify:** Record the sync date in the YAML's `decision_log` (e.g., `"Synchronized with MATLAB main as of 2026-03-12."`). ndi_document any intentional divergences. Explicitly tell the user what changes were made to the bridge file so they can review the contract.

## 4. Input Validation: Pydantic is Mandatory

To replicate the robustness of the MATLAB `arguments` block, use Pydantic for all public-facing API functions.

- **Decorator:** Use the `@pydantic.validate_call` decorator on all functions.
- **Type Mirroring:**
  - MATLAB `double`/`numeric` → Python `float | int`
  - MATLAB `char`/`string` → Python `str`
  - MATLAB `{member1, member2}` → Python `Literal["member1", "member2"]`
- **Union Types:** Implement multiple allowed types as a Type Union (e.g., `str | int`).
- **Coercion:** Allow Pydantic's default casting (e.g., allowing a string `"1"` to satisfy a `bool` type).
- **Arbitrary Types:** For types like `numpy.ndarray`, use `config=ConfigDict(arbitrary_types_allowed=True)`.

## 5. Multiple Returns (Outputs)

MATLAB allows multiple return values natively. In Python, these must be returned as a **tuple** in the exact order defined in the `output_arguments` section of the bridge YAML.

## 6. Code Style & Linting

All Python code must pass formatting and linting before being committed.

- **Black:** The sole code formatter. Use default line length (88).
- **Ruff:** The primary linter. Run `ruff check --fix` before committing.

## 7. Error Handling & Documentation

- **Hard Fails:** If a MATLAB function throws an error, the Python version must raise a corresponding Exception (`ValueError`, `TypeError`, or `NDIError`).
- **Docstring Symmetry:** Include the original MATLAB documentation in the Python docstring. Add a "Python-specific Notes" section at the bottom for library-specific details.
