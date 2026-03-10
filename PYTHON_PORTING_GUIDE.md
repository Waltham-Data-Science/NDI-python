# MATLAB to Python Porting Rules

## 1. The Core Philosophy: Lead-Follow Architecture

The MATLAB codebase is the **Source of Truth**. The Python version is a "faithful mirror." When a conflict arises between "Pythonic" style and MATLAB symmetry, **symmetry wins**.

## 2. Function & Variable Naming (The "Strict Mirror" Rule)

Do **not** attempt to "translate" MATLAB names into Python PEP 8 (`snake_case`).

- **Exact Match:** Every function name in Python must be an identical string match to the MATLAB function name.
- **Case Sensitivity:** If the MATLAB function is `ListAllDocuments`, the Python function must be `ListAllDocuments`. If the MATLAB function is `get_dataset_id`, the Python function must be `get_dataset_id`.
- **No Aliasing:** Do not create `snake_case` aliases unless explicitly requested. The user should be able to copy-paste function names between environments.

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
