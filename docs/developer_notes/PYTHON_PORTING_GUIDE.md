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
3. **Implement:** Write the Python code to satisfy the `input_arguments` and `output_arguments` defined in the YAML.
4. **Log & Notify:** Document intentional divergences in the YAML's `decision_log`. Explicitly tell the user what changes were made to the bridge file so they can review the contract.

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
