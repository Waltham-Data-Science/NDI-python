# Class Naming Convention: MATLAB-Python Mechanical Mapping

- **Status:** Active
- **Scope:** All NDI-Python and related projects (DID-Python, etc.)
- **Goal:** Eliminate lookup tables and manual mapping between MATLAB and Python class names.

## The Rule

Python class names are derived mechanically from the fully-qualified MATLAB class name using two substitutions:

1. Replace every `.` (dot) in the MATLAB name with `_` (single underscore)
2. Replace every `_` (underscore) in the MATLAB name with `__` (double underscore)

The mapping is **invertible** — given a Python class name you can always recover the MATLAB name:

1. Replace every `__` with `_`
2. Replace every (remaining) `_` with `.`

## Examples

| MATLAB class                        | Python class                              |
|-------------------------------------|-------------------------------------------|
| `ndi.session.dir`                   | `ndi_session_dir`                         |
| `ndi.probe.timeseries.mfdaq`        | `ndi_probe_timeseries_mfdaq`              |
| `ndi.daq.system`                    | `ndi_daq_system`                          |
| `ndi.epoch.epochprobemap_daqsystem` | `ndi_epoch_epochprobemap__daqsystem`      |
| `ndi.time.timereference_struct`     | `ndi_time_timereference__struct`          |
| `ndi.calc.tuning_fit`               | `ndi_calc_tuning__fit`                    |
| `ndi.element`                       | `ndi_element`                             |
| `ndi.document`                      | `ndi_document`                            |

Note how `epochprobemap_daqsystem` (which has an underscore in MATLAB) becomes
`epochprobemap__daqsystem` with a double underscore in Python. This distinguishes
it from a hypothetical `ndi.epoch.epochprobemap.daqsystem` (with a dot), which
would be `ndi_epoch_epochprobemap_daqsystem` (single underscore).

## Why This Convention

### Problem: Fragile CamelCase mapping

The previous approach used PEP 8 CamelCase names (`DirSession`, `ProbeTimeseriesMFDAQ`,
`EpochProbeMapDAQSystem`) and maintained explicit mapping tables (YAML bridge files,
per-class `matlab_class` attributes, module-level aliases). This was fragile because:

- Capitalization conventions are ambiguous (is it `MFDAQReader` or `MfdaqReader`?)
- Every new class required updating multiple mapping tables
- No mechanical way to go from a MATLAB name to the Python name or vice versa

### Solution: Mechanical underscore mapping

With this convention:

- **No lookup tables needed.** The class name IS the mapping.
- **No ambiguity.** The conversion is deterministic in both directions.
- **No fragility.** Adding a new class requires zero mapping infrastructure.
- **Cross-project safety.** The full MATLAB namespace prefix (`ndi_`, `did_`, `vhlab_`, etc.)
  is included in the name, so classes from different projects never collide.

### Trade-off: PEP 8

This convention departs from PEP 8's recommendation of CamelCase for class names.
This is a deliberate choice — MATLAB interop and mapping simplicity take priority
over Python style conventions in this project. (NumPy similarly departs from PEP 8
for consistency with mathematical conventions.)

## Scope

This convention applies to **classes that have MATLAB equivalents**. Python-only
classes (exceptions, enums, internal dataclasses, test utilities) may use standard
Python naming conventions. Examples of classes that keep standard names:

- `CacheEntry` (internal data structure, no MATLAB equivalent)
- `SQLiteDriver` (internal backend, no MATLAB equivalent)
- `DocExistsAction` (Python enum)
- `ValidationResult` (Python-specific)
- `CloudError`, `CloudAuthError` (Python exceptions)
- `ChannelType`, `ChannelInfo` (Python-specific enums/dataclasses)

## Conversion Functions

For programmatic use, the conversion can be expressed as:

```python
def matlab_to_python(matlab_name: str) -> str:
    """Convert 'ndi.session.dir' -> 'ndi_session_dir'."""
    return matlab_name.replace("_", "__").replace(".", "_")

def python_to_matlab(python_name: str) -> str:
    """Convert 'ndi_session_dir' -> 'ndi.session.dir'."""
    return python_name.replace("__", "\x00").replace("_", ".").replace("\x00", "_")
```

## Module-Level Aliases

For convenience, `__init__.py` files may provide aliases so that the Python
import path mirrors the MATLAB access path. For example:

```python
# In ndi/session/__init__.py
from .dir import ndi_session_dir

# Alias so that ndi.session.dir(...) works like MATLAB
dir = ndi_session_dir
```

These aliases are optional conveniences, not the primary naming mechanism.

## Instructions for AI Agents

1. When creating a new class that has a MATLAB equivalent, derive the Python
   class name mechanically using the rules above.
2. Do NOT invent CamelCase names or maintain separate mapping tables.
3. External library classes (e.g., `did.query.Query`, `requests.Session`) must
   NOT be renamed — only NDI-Python classes follow this convention.
4. The `ndi_matlab_python_bridge.yaml` files record the mapping for documentation
   purposes but are NOT the source of truth — the class name itself is.
