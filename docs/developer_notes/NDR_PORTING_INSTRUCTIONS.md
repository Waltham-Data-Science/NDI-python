# Instructions: Port NDR-matlab to NDR-python

**For:** Claude Code agent working in the new `NDR-python` repository
**Reference implementation:** [NDR-matlab](https://github.com/VH-Lab/NDR-matlab)
**Pattern to follow:** [NDI-python](https://github.com/Waltham-Data-Science/NDI-python) (this repo)

---

## 1. Overview

NDR (Neuroscience Data Reader) is a lower-level data-reading library used by NDI. NDR-matlab lives at `https://github.com/VH-Lab/NDR-matlab`. Your job is to create `NDR-python` as a faithful Python mirror, following the exact same lead-follow architecture, developer notes, bridge YAML protocol, and symmetry test framework used in NDI-python.

NDR-matlab provides:
- An abstract base reader class (`ndr.reader.base`)
- A high-level reader wrapper (`ndr.reader`)
- 10 format-specific reader subclasses (Intan RHD, Axon ABF, CED SMR, etc.)
- Format handler packages with low-level file I/O
- Time, string, data, and file utilities

---

## 2. Repository Setup

### 2.1 Create the repo structure

```
NDR-python/
├── src/
│   └── ndr/
│       ├── __init__.py
│       ├── globals.py              # from +ndr/globals.m
│       ├── known_readers.py        # from +ndr/known_readers.m
│       ├── reader_wrapper.py       # from +ndr/reader.m (the high-level wrapper)
│       ├── reader/
│       │   ├── __init__.py
│       │   ├── base.py             # from +ndr/+reader/base.m
│       │   ├── intan_rhd.py        # from +ndr/+reader/intan_rhd.m
│       │   ├── axon_abf.py         # from +ndr/+reader/axon_abf.m
│       │   ├── ced_smr.py          # from +ndr/+reader/ced_smr.m
│       │   ├── bjg.py              # from +ndr/+reader/bjg.m
│       │   ├── dabrowska.py        # from +ndr/+reader/dabrowska.m
│       │   ├── neo.py              # from +ndr/+reader/neo.m
│       │   ├── spikegadgets_rec.py # from +ndr/+reader/spikegadgets_rec.m
│       │   ├── tdt_sev.py          # from +ndr/+reader/tdt_sev.m
│       │   └── whitematter.py      # from +ndr/+reader/whitematter.m
│       ├── format/
│       │   ├── __init__.py
│       │   ├── intan/
│       │   │   ├── __init__.py
│       │   │   └── ...             # from +ndr/+format/+intan/
│       │   ├── axon/
│       │   ├── ced/
│       │   ├── bjg/
│       │   ├── dabrowska/
│       │   ├── spikegadgets/
│       │   ├── tdt/
│       │   ├── textSignal/
│       │   └── whitematter/
│       ├── data/
│       │   └── ...                 # from +ndr/+data/
│       ├── file/
│       │   └── ...                 # from +ndr/+file/
│       ├── fun/
│       │   └── ...                 # from +ndr/+fun/
│       ├── string/
│       │   └── ...                 # from +ndr/+string/
│       └── time/
│           └── ...                 # from +ndr/+time/
├── tests/
│   ├── __init__.py
│   ├── test_reader_base.py
│   ├── test_readers.py
│   └── symmetry/                   # Cross-language symmetry tests
│       ├── conftest.py
│       ├── make_artifacts/
│       │   └── reader/
│       │       └── test_read_data.py
│       └── read_artifacts/
│           └── reader/
│               └── test_read_data.py
├── docs/
│   └── developer_notes/
│       ├── PYTHON_PORTING_GUIDE.md
│       ├── ndr_xlang_principles.md
│       ├── ndr_matlab_python_bridge.yaml
│       └── symmetry_tests.md
├── example_data/                   # Copy from NDR-matlab for testing
├── pyproject.toml
├── README.md
├── LICENSE
└── AGENTS.md
```

### 2.2 Directory Parity Rule

MATLAB `+namespace` paths map directly to Python package directories:

| MATLAB | Python |
|--------|--------|
| `+ndr/globals.m` | `src/ndr/globals.py` |
| `+ndr/reader.m` | `src/ndr/reader_wrapper.py` |
| `+ndr/+reader/base.m` | `src/ndr/reader/base.py` |
| `+ndr/+reader/intan_rhd.m` | `src/ndr/reader/intan_rhd.py` |
| `+ndr/+format/+intan/` | `src/ndr/format/intan/` |
| `+ndr/+time/` | `src/ndr/time/` |

**Exception:** `+ndr/reader.m` is the high-level wrapper class. Since `ndr/reader/` is the reader subpackage, put the wrapper in `ndr/reader_wrapper.py` and re-export from `ndr/__init__.py`.

### 2.3 pyproject.toml

Model after NDI-python's pyproject.toml:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ndr"
version = "0.1.0"
description = "Neuroscience Data Reader - Python implementation"
readme = "README.md"
license = {text = "CC-BY-NC-SA-4.0"}
authors = [{name = "VH-Lab", email = "vhlab@brandeis.edu"}]
maintainers = [{name = "Waltham Data Science"}]
requires-python = ">=3.10"
dependencies = [
    "numpy>=1.20.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
    "mypy>=1.0.0",
]

[tool.hatch.metadata]
allow-direct-references = true

[tool.hatch.build.targets.wheel]
packages = ["src/ndr"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short --ignore=tests/symmetry"
markers = [
    "slow: marks tests as slow",
    "symmetry: marks cross-language symmetry tests",
]

[tool.black]
line-length = 100
target-version = ["py310", "py311", "py312"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP"]
ignore = ["E501", "B905", "E402", "B017", "B028"]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401", "UP035"]
```

Add additional dependencies as needed when porting format readers that require third-party libraries (e.g., `neo` for the Neo reader, `scipy` for certain file formats).

---

## 3. Developer Notes (Create These Files)

You must create four developer notes files in `docs/developer_notes/`. These are adapted from NDI-python's equivalents but scoped to NDR.

### 3.1 `PYTHON_PORTING_GUIDE.md`

Create this file with the following content (adapt from NDI-python's version):

```markdown
# NDR MATLAB to Python Porting Guide

## 1. The Core Philosophy: Lead-Follow Architecture

The MATLAB codebase is the **Source of Truth**. The Python version is a "faithful mirror."
When a conflict arises between "Pythonic" style and MATLAB symmetry, **symmetry wins**.

- **Lead-Follow:** MATLAB defines the logic, hierarchy, and naming.
- **The Contract:** Every package contains an `ndr_matlab_python_bridge.yaml`.
  This file is the binding contract for function names, arguments, and return types.

## 2. Naming & Discovery (The Mirror Rule)

Function and class names must match MATLAB exactly.

- **Naming Source:** Refer to the local `ndr_matlab_python_bridge.yaml`.
- **Missing Entries:** If a function is not in the bridge file, refer to the MATLAB
  source, add the entry to the bridge file, and notify the user.
- **Case Preservation:** Use `readchannels_epochsamples`, not `read_channels_epoch_samples`.
- **Directory Parity:** Python file paths must mirror MATLAB `+namespace` paths
  (e.g., `+ndr/+reader` -> `src/ndr/reader/`).

## 3. The Porting Workflow (The Bridge Protocol)

1. **Check the Bridge:** Open the `ndr_matlab_python_bridge.yaml` in the target package.
2. **Sync the Interface:** If the function is missing or outdated, update the YAML first.
3. **Record the Sync Hash:** Store the short git hash of the MATLAB `.m` file:
   `git log -1 --format="%h" -- <path-to-matlab-file>`
4. **Implement:** Write Python code to satisfy the interface defined in the YAML.
5. **Log & Notify:** Record the sync date in the YAML's `decision_log`.

## 4. Input Validation: Pydantic is Mandatory

Use `@pydantic.validate_call` on all public-facing API functions.

- MATLAB `double`/`numeric` -> Python `float | int`
- MATLAB `char`/`string` -> Python `str`
- MATLAB `{member1, member2}` -> Python `Literal["member1", "member2"]`

## 5. Multiple Returns (Outputs)

Return multiple values as a **tuple** in the exact order defined in the YAML.

## 6. Code Style & Linting

- **Black:** The sole code formatter. Line length 100.
- **Ruff:** The primary linter. Run `ruff check --fix` before committing.

## 7. Error Handling

If MATLAB throws an `error`, Python MUST raise a corresponding Exception.
```

### 3.2 `ndr_xlang_principles.md`

Create this file, adapted from NDI-python's `ndi_xlang_principles.md`:

```markdown
# NDR Cross-Language (MATLAB/Python) Principles

- **Status:** Active
- **Scope:** Universal (Applies to all NDR implementations)

## 1. Indexing & Counting (The Semantic Parity Rule)

- Python uses 0-indexing internally.
- User-facing concepts (Epochs, Channels) use 1-based numbering in both languages.
- Python code accepts `channel_number=1` from user, maps to `data[0]` internally.

## 2. Data Containers

- Prefer NumPy over lists for numerical data.
- MATLAB `double` array -> `numpy.ndarray` in Python.

## 3. Multiple Returns

- Python returns multiple values as a tuple in MATLAB signature order.

## 4. Booleans

- MATLAB `1`/`0` (logical) -> Python `True`/`False`.

## 5. Strings

- MATLAB `char` and `string` -> Python `str`.
- MATLAB cell array of strings -> Python `list[str]`.

## 6. Error Philosophy

- No silent failures. If MATLAB errors, Python raises an exception.
```

### 3.3 `ndr_matlab_python_bridge.yaml`

Create the bridge YAML spec file. This defines the contract format:

```yaml
# The NDR Bridge Protocol: YAML Specification
#
# Name:     ndr_matlab_python_bridge.yaml
# Location: One file per sub-package directory
#           (e.g., src/ndr/reader/ndr_matlab_python_bridge.yaml).
# Role:     Primary Contract. Defines how MATLAB names and types map to Python.

project_metadata:
  bridge_version: "1.1"
  naming_policy: "Strict MATLAB Mirror"
  indexing_policy: "Semantic Parity (1-based for user concepts, 0-based for internal data)"

# When porting a function:
# 1. Check:  Does the function/class exist in the YAML?
# 2. Add/Update: If missing or changed, update the YAML first.
# 3. Record Hash: git log -1 --format="%h" -- <path-to-matlab-file>
# 4. Notify: Tell the user what was added/changed.

# --- Example: Class ---
# - name: base
#   type: class
#   matlab_path: "+ndr/+reader/base.m"
#   python_path: "ndr/reader/base.py"
#   matlab_last_sync_hash: "a4c9e07"
#   methods:
#     - name: readchannels_epochsamples
#       input_arguments:
#         - name: channeltype
#           type_python: "str"
#         - name: channel
#           type_python: "int | list[int]"
#         - name: epoch
#           type_python: "str | int"
#         - name: s0
#           type_python: "int"
#         - name: s1
#           type_python: "int"
#       output_arguments:
#         - name: data
#           type_python: "numpy.ndarray"
```

Then create **one bridge YAML per sub-package** as you port it:
- `src/ndr/reader/ndr_matlab_python_bridge.yaml`
- `src/ndr/format/intan/ndr_matlab_python_bridge.yaml`
- `src/ndr/time/ndr_matlab_python_bridge.yaml`
- etc.

### 3.4 `symmetry_tests.md`

Create this file, adapted from NDI-python's version:

```markdown
# Cross-Language Symmetry Test Framework

**Status:** Active
**Scope:** NDR-python <-> NDR-matlab parity

## Purpose

Symmetry tests verify that data read by one language implementation matches
the other. This ensures the Python and MATLAB NDR stacks remain interoperable.

## Architecture

| Phase | Python location | MATLAB location |
|-------|----------------|-----------------|
| **makeArtifacts** | `tests/symmetry/make_artifacts/` | `tests/+ndr/+symmetry/+makeArtifacts/` |
| **readArtifacts** | `tests/symmetry/read_artifacts/` | `tests/+ndr/+symmetry/+readArtifacts/` |

### Artifact Directory Layout

```
<tempdir>/NDR/symmetryTest/
├── pythonArtifacts/
│   └── <namespace>/<className>/<testName>/
│       ├── readData.json           # Channel data, timestamps, etc.
│       └── metadata.json           # Channel list, sample rates, epoch info
└── matlabArtifacts/
    └── <namespace>/<className>/<testName>/
        └── ... (same structure)
```

### Workflow

1. **makeArtifacts** (Python or MATLAB) reads example data files and writes
   JSON artifacts containing: channel lists, sample rates, epoch clocks,
   t0/t1 boundaries, and actual data samples.
2. **readArtifacts** (the other language) loads the same example data files,
   reads the same channels/epochs, and compares against the stored artifacts.

Each `readArtifacts` test is parameterized over `{matlabArtifacts, pythonArtifacts}`.

## Running

```bash
# Generate artifacts
pytest tests/symmetry/make_artifacts/ -v

# Verify artifacts
pytest tests/symmetry/read_artifacts/ -v
```

## Writing a New Symmetry Test

See NDI-python's `docs/developer_notes/symmetry_tests.md` for the full template.
Adapt the pattern for NDR's reader-centric API.
```

---

## 4. AGENTS.md

Create an `AGENTS.md` at the repo root:

```markdown
# Instructions for AI Agents

## Overview

NDR-python is a faithful Python port of NDR-matlab (Neuroscience Data Reader).

## Architecture

- **Lead-Follow:** MATLAB is the source of truth. Python mirrors it exactly.
- **Bridge Contract:** Each sub-package has an `ndr_matlab_python_bridge.yaml`
  defining the function names, arguments, and return types.
- **Naming:** Preserve MATLAB names exactly. Use `readchannels_epochsamples`,
  not `read_channels_epoch_samples`.

## Key Classes

- `ndr.reader.base` — Abstract base class. All readers inherit from this.
- `ndr.reader` (wrapper) — High-level interface that delegates to a base reader.
- `ndr.reader.intan_rhd`, `ndr.reader.axon_abf`, etc. — Format-specific readers.

## Workflow

1. Check the bridge YAML in the target package.
2. If the function is missing, add it based on the MATLAB source.
3. Record the MATLAB git hash in `matlab_last_sync_hash`.
4. Implement the Python code.
5. Run `black` and `ruff check --fix` before committing.
6. Run `pytest` to verify.

## Testing

- Unit tests: `pytest tests/`
- Symmetry tests: `pytest tests/symmetry/` (excluded from default run)

## Environment

- Python 3.10+
- NumPy for all numerical data
- Pydantic for input validation (`@validate_call`)
```

---

## 5. Classes to Port

### 5.1 Priority Order

Port in this order (each builds on the previous):

1. **`ndr.reader.base`** — Abstract base class with all method signatures
2. **`ndr.reader` (wrapper)** — High-level reader interface
3. **`ndr.format.intan`** — Intan RHD format handler (most commonly used)
4. **`ndr.reader.intan_rhd`** — Intan reader subclass
5. **Utility packages** — `ndr.time`, `ndr.data`, `ndr.string`, `ndr.file`, `ndr.fun`
6. **Remaining readers** — `axon_abf`, `ced_smr`, `bjg`, `dabrowska`, `spikegadgets_rec`, `tdt_sev`, `whitematter`, `neo`
7. **`ndr.globals`** and **`ndr.known_readers`**

### 5.2 The Abstract Base: `ndr.reader.base`

This is the most important class. It defines the interface all readers must implement.

**MATLAB source:** `+ndr/+reader/base.m`

**Properties:**
- `MightHaveTimeGaps` (bool)

**Abstract methods (subclasses MUST implement):**
- `readchannels_epochsamples(channeltype, channel, epoch, s0, s1)` -> `numpy.ndarray`
- `readevents_epochsamples_native(channeltype, channel, epoch, s0, s1)` -> tuple

**Concrete methods (base provides default implementations):**
- `canbereadtogether(channels)` -> `bool`
- `daqchannels2internalchannels(channeltype, channel, epoch)` -> internal channel struct
- `epochclock(epoch)` -> list of clock types
- `getchannelsepoch(epoch)` -> list of channel descriptors
- `underlying_datatype(channeltype, channel, epoch)` -> str
- `samplerate(epoch, channeltype, channel)` -> float
- `t0_t1(epoch)` -> tuple[float, float]
- `samples2times(epoch, samples, channeltype, channel)` -> numpy.ndarray
- `times2samples(epoch, times, channeltype, channel)` -> numpy.ndarray

**Static methods:**
- `mfdaq_channeltypes()` -> list[str]
- `mfdaq_prefix(channeltype)` -> str
- `mfdaq_type(channeltype)` -> str

### 5.3 The Reader Wrapper: `ndr.reader`

**MATLAB source:** `+ndr/reader.m`

This wraps a `base` subclass and provides the high-level `read()` method plus delegation to all base methods. The constructor takes a format name string and instantiates the appropriate reader subclass.

### 5.4 Format-Specific Readers

Each reader in `+ndr/+reader/` subclasses `base` and overrides the abstract methods. Each has a corresponding format handler package in `+ndr/+format/` that does the low-level binary file I/O.

| Reader class | Format package | File format |
|-------------|---------------|-------------|
| `intan_rhd` | `+ndr/+format/+intan/` | Intan RHD2000 (.rhd) |
| `axon_abf` | `+ndr/+format/+axon/` | Axon ABF (.abf) |
| `ced_smr` | `+ndr/+format/+ced/` | CED Spike2 (.smr) |
| `bjg` | `+ndr/+format/+bjg/` | BJG format |
| `dabrowska` | `+ndr/+format/+dabrowska/` | Dabrowska format |
| `spikegadgets_rec` | `+ndr/+format/+spikegadgets/` | SpikeGadgets (.rec) |
| `tdt_sev` | `+ndr/+format/+tdt/` | TDT (.sev) |
| `whitematter` | `+ndr/+format/+whitematter/` | White Matter format |
| `neo` | `+ndr/+format/+neo/` | Neo Python bridge |

**Important:** The `intan_rhd` reader should use `vhlab-toolbox-python` for the low-level RHD file reading if available, as NDI-python does. Add `vhlab-toolbox-python` as an optional dependency:

```toml
dependencies = [
    "numpy>=1.20.0",
    "pydantic>=2.0",
    "vhlab-toolbox-python @ git+https://github.com/VH-Lab/vhlab-toolbox-python.git@main",
]
```

### 5.5 Skip the Template

`+ndr/+reader/somecompany_someformat.m` is a template for creating new readers. Do NOT port it. It's documentation, not functional code.

---

## 6. Symmetry Tests

### 6.1 conftest.py

Create `tests/symmetry/conftest.py`:

```python
"""Shared fixtures and configuration for NDR symmetry tests."""

import tempfile
from pathlib import Path

# Base directory where all symmetry artifacts live:
#   <tempdir>/NDR/symmetryTest/<sourceType>/<namespace>/<class>/<test>/
SYMMETRY_BASE = Path(tempfile.gettempdir()) / "NDR" / "symmetryTest"
PYTHON_ARTIFACTS = SYMMETRY_BASE / "pythonArtifacts"
MATLAB_ARTIFACTS = SYMMETRY_BASE / "matlabArtifacts"

SOURCE_TYPES = ["matlabArtifacts", "pythonArtifacts"]
```

Note: `NDR` not `NDI` in the path.

### 6.2 makeArtifacts Example

Create `tests/symmetry/make_artifacts/reader/test_read_data.py`:

```python
"""Generate symmetry artifacts for NDR reader tests.

Reads example data files using NDR readers and exports:
- Channel metadata (names, types, sample rates)
- Epoch clock types and t0/t1 boundaries
- Actual data samples for comparison
"""

import json
import shutil

import numpy as np
import pytest

from ndr.reader.intan_rhd import IntanRHDReader
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "reader" / "readData" / "testReadDataArtifacts"
EXAMPLE_DATA = Path(__file__).parents[4] / "example_data"


class TestReadData:
    @pytest.fixture(autouse=True)
    def _setup(self):
        rhd_file = EXAMPLE_DATA / "Intan_160317_125049_short.rhd"
        if not rhd_file.exists():
            pytest.skip("Example RHD file not available")
        self.reader = IntanRHDReader()
        self.epochfiles = [str(rhd_file)]

    def test_read_data_artifacts(self):
        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        ARTIFACT_DIR.mkdir(parents=True)

        # Export channel metadata
        channels = self.reader.getchannelsepoch(self.epochfiles)
        metadata = {
            "channels": channels,
            "samplerate": self.reader.samplerate(self.epochfiles, "ai", 1),
            "t0_t1": list(self.reader.t0_t1(self.epochfiles)),
            "epochclock": self.reader.epochclock(self.epochfiles),
        }
        (ARTIFACT_DIR / "metadata.json").write_text(
            json.dumps(metadata, indent=2, default=str), encoding="utf-8"
        )

        # Export a small data sample
        data = self.reader.readchannels_epochsamples("ai", [1], self.epochfiles, 0, 100)
        (ARTIFACT_DIR / "readData.json").write_text(
            json.dumps({"ai_channel_1_samples_0_100": data.tolist()}, indent=2),
            encoding="utf-8",
        )
```

### 6.3 readArtifacts Example

Create `tests/symmetry/read_artifacts/reader/test_read_data.py`:

```python
"""Read and verify symmetry artifacts for NDR reader tests."""

import json

import numpy as np
import pytest

from ndr.reader.intan_rhd import IntanRHDReader
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE

EXAMPLE_DATA = Path(__file__).parents[4] / "example_data"


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    return request.param


class TestReadData:
    def _artifact_dir(self, source_type):
        return SYMMETRY_BASE / source_type / "reader" / "readData" / "testReadDataArtifacts"

    def test_read_data_metadata(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(f"No artifacts from {source_type}")

        metadata = json.loads((artifact_dir / "metadata.json").read_text())

        rhd_file = EXAMPLE_DATA / "Intan_160317_125049_short.rhd"
        if not rhd_file.exists():
            pytest.skip("Example RHD file not available")

        reader = IntanRHDReader()
        epochfiles = [str(rhd_file)]

        actual_sr = reader.samplerate(epochfiles, "ai", 1)
        assert actual_sr == metadata["samplerate"], (
            f"Sample rate mismatch: {actual_sr} vs {metadata['samplerate']}"
        )

        actual_t0_t1 = reader.t0_t1(epochfiles)
        assert np.allclose(actual_t0_t1, metadata["t0_t1"], atol=1e-6)

    def test_read_data_samples(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(f"No artifacts from {source_type}")

        read_data = json.loads((artifact_dir / "readData.json").read_text())
        expected = np.array(read_data["ai_channel_1_samples_0_100"])

        rhd_file = EXAMPLE_DATA / "Intan_160317_125049_short.rhd"
        if not rhd_file.exists():
            pytest.skip("Example RHD file not available")

        reader = IntanRHDReader()
        actual = reader.readchannels_epochsamples("ai", [1], [str(rhd_file)], 0, 100)

        assert np.allclose(actual, expected, atol=1e-9), (
            f"Data mismatch for ai channel 1, samples 0-100 ({source_type})"
        )
```

### 6.4 Symmetry Test Guidelines

- Artifact paths use **camelCase** so both Python and MATLAB write to the same directories.
- `readArtifacts` tests must `pytest.skip()` if the artifact directory doesn't exist (the other language may not have been run yet).
- Symmetry tests are excluded from the default pytest run via `--ignore=tests/symmetry` in `pyproject.toml`.
- For NDR, the primary thing to test for symmetry is **data values** — both languages reading the same binary file should produce the same numerical results (within floating-point tolerance).

---

## 7. Porting Rules

### 7.1 Naming

- **Preserve MATLAB names exactly.** `readchannels_epochsamples`, not `read_channels_epoch_samples`.
- **Class names:** `base`, `intan_rhd`, `axon_abf` — match the MATLAB filenames.
- **Method names:** Match MATLAB exactly: `getchannelsepoch`, `t0_t1`, `epochclock`.

### 7.2 Method Signatures

Fetch each MATLAB `.m` file from GitHub and port the exact method signature. The MATLAB source is at:

```
https://raw.githubusercontent.com/VH-Lab/NDR-matlab/main/+ndr/+reader/<filename>.m
```

For each method, create a bridge YAML entry BEFORE writing the implementation.

### 7.3 Epoch Files Convention

In NDR-matlab, `epoch` arguments to reader methods are typically file paths (a cell array of filenames). In Python, use `list[str]` — a list of file path strings.

### 7.4 Channel Types

NDR uses standard channel type strings. The static method `mfdaq_channeltypes()` returns:
`['ai', 'ao', 'di', 'do', 'time', 'auxiliary', 'mark', 'event', 'text']`

With prefixes from `mfdaq_prefix()`:
`{'ai': 'ai', 'ao': 'ao', 'di': 'di', 'do': 'do', ...}`

### 7.5 Return Types

- Numerical data: `numpy.ndarray`
- Channel lists: `list[dict]` where each dict has keys like `name`, `type`, `samplerate`
- Time boundaries: `tuple[float, float]`
- Clock types: `list[dict]` with `type` key

### 7.6 Error Handling

- If MATLAB throws an error, Python raises `ValueError` or `TypeError`.
- Never silently return empty/None when MATLAB would error.

---

## 8. Format Handler Packages

Each format handler in `+ndr/+format/` contains low-level file I/O functions. These are the workhorses that actually read binary data from disk.

For the Intan format (`+ndr/+format/+intan/`), consider using `vhlab-toolbox-python` which already has Intan RHD reading capability, rather than porting the MATLAB binary reader from scratch.

For other formats, check if Python libraries already exist:
- **Axon ABF:** `pyabf` package
- **CED SMR:** `neo` or `sonpy` packages
- **TDT:** `tdt` package
- **SpikeGadgets:** May need native port
- **Neo:** Already wraps Python's `neo` package

If a well-maintained Python library exists for a format, use it as the backend and wrap it to match the NDR interface. Document this in the bridge YAML's `decision_log`.

---

## 9. Testing

### 9.1 Unit Tests

Write unit tests for each reader using the example data files from `example_data/`:

```python
def test_intan_rhd_getchannelsepoch():
    reader = IntanRHDReader()
    channels = reader.getchannelsepoch(["example_data/Intan_160317_125049_short.rhd"])
    assert len(channels) > 0
    assert any(ch["type"] == "ai" for ch in channels)

def test_intan_rhd_readchannels():
    reader = IntanRHDReader()
    data = reader.readchannels_epochsamples(
        "ai", [1], ["example_data/Intan_160317_125049_short.rhd"], 0, 100
    )
    assert data.shape == (100, 1)
```

### 9.2 Run Before Committing

```bash
black src/ tests/
ruff check --fix src/ tests/
pytest tests/ -v
```

---

## 10. Relationship to NDI-python

NDR-python will be a dependency of NDI-python. Once NDR-python is ready:

1. Add it to NDI-python's `pyproject.toml`:
   ```toml
   "ndr @ git+https://github.com/VH-Lab/NDR-python.git@main",
   ```

2. NDI-python's `ndi.daq.reader.mfdaq.intan` will delegate to `ndr.reader.intan_rhd` instead of implementing its own reading logic.

3. The NDI `ndi.file.navigator` will use NDR readers to access epoch data.

This mirrors the MATLAB architecture where NDI-matlab depends on NDR-matlab.

---

## 11. Quick-Start Checklist

- [ ] Create repo structure per Section 2
- [ ] Create `pyproject.toml` per Section 2.3
- [ ] Create all four developer notes files per Section 3
- [ ] Create `AGENTS.md` per Section 4
- [ ] Create `tests/symmetry/conftest.py` per Section 6.1
- [ ] Port `ndr.reader.base` (abstract base class)
- [ ] Create bridge YAML for `src/ndr/reader/`
- [ ] Port `ndr.reader` wrapper
- [ ] Port `ndr.format.intan` (or wire to vhlab-toolbox-python)
- [ ] Port `ndr.reader.intan_rhd`
- [ ] Write unit tests using example data
- [ ] Write symmetry makeArtifacts test
- [ ] Write symmetry readArtifacts test
- [ ] Port utility packages (`time`, `data`, `string`, `file`, `fun`)
- [ ] Port remaining readers
- [ ] Run `black`, `ruff`, `pytest`
- [ ] Commit and push
