# Cross-Language Symmetry Test Framework

**Status:** Active
**Scope:** NDI-python ↔ NDI-matlab parity

## Purpose

Symmetry tests verify that NDI sessions, documents, and probes created by one
language implementation can be correctly read and interpreted by the other.
This is the primary mechanism for ensuring that the Python and MATLAB NDI stacks
remain interoperable as both codebases evolve.

## Architecture

The framework has two halves, each existing in both languages:

| Phase | Python location | MATLAB location |
|-------|----------------|-----------------|
| **makeArtifacts** | `tests/symmetry/make_artifacts/` | `tests/+ndi/+symmetry/+makeArtifacts/` |
| **readArtifacts** | `tests/symmetry/read_artifacts/` | `tests/+ndi/+symmetry/+readArtifacts/` |

### Artifact Directory Layout

All artifacts are written to the OS temporary directory under a fixed path:

```
<tempdir>/NDI/symmetryTest/
├── pythonArtifacts/
│   └── <namespace>/<className>/<testName>/
│       ├── .ndi/              # NDI session database
│       ├── jsonDocuments/     # One JSON file per document
│       │   ├── <doc_id_1>.json
│       │   └── <doc_id_2>.json
│       └── probes.json        # Array of probe descriptors
└── matlabArtifacts/
    └── <namespace>/<className>/<testName>/
        └── ... (same structure)
```

- **`<namespace>`** — the NDI domain being tested (e.g., `session`).
- **`<className>`** — the test class name, in camelCase (e.g., `buildSession`).
- **`<testName>`** — the test method name, in camelCase (e.g., `testBuildSessionArtifacts`).

### Workflow

```
┌──────────────────────────┐     ┌──────────────────────────┐
│  Python makeArtifacts    │     │  MATLAB makeArtifacts    │
│  pytest tests/symmetry/  │     │  runtests('ndi.symmetry. │
│    make_artifacts/ -v    │     │    makeArtifacts')       │
└──────────┬───────────────┘     └──────────┬───────────────┘
           │ writes                          │ writes
           ▼                                 ▼
     pythonArtifacts/                  matlabArtifacts/
           │                                 │
           └────────────┬────────────────────┘
                        │ reads
           ┌────────────┴────────────────────┐
           │                                 │
           ▼                                 ▼
┌──────────────────────────┐     ┌──────────────────────────┐
│  Python readArtifacts    │     │  MATLAB readArtifacts    │
│  pytest tests/symmetry/  │     │  runtests('ndi.symmetry. │
│    read_artifacts/ -v    │     │    readArtifacts')       │
└──────────────────────────┘     └──────────────────────────┘
```

Each `readArtifacts` test is parameterized over `{matlabArtifacts, pythonArtifacts}`
so a single test class validates both directions of compatibility.

## Running the Tests

### From Python

```bash
# Generate artifacts
pytest tests/symmetry/make_artifacts/ -v

# Verify artifacts (skips missing sources)
pytest tests/symmetry/read_artifacts/ -v

# Both phases at once
pytest tests/symmetry/ -v
```

### From MATLAB

```matlab
% Generate artifacts
results = runtests('ndi.symmetry.makeArtifacts');

% Verify artifacts
results = runtests('ndi.symmetry.readArtifacts');
```

### Why Separate from Regular Tests?

Symmetry tests are **excluded from the default `pytest` run** (via
`--ignore=tests/symmetry` in `pyproject.toml`) because:

1. **readArtifacts** tests will mostly just be skipped unless the user has
   previously run MATLAB's `makeArtifacts` suite on the same machine.
2. **makeArtifacts** tests write to the system temp directory, which is a
   side-effect that doesn't belong in routine CI.
3. The full cross-language cycle requires both runtimes and is better suited
   to integration / nightly CI pipelines.

## Writing a New Symmetry Test

### 1. Choose a namespace

Pick the NDI domain being tested (e.g., `session`, `document`, `probe`).

### 2. Create the makeArtifacts test

**Python:** `tests/symmetry/make_artifacts/<namespace>/test_<name>.py`

```python
import json, shutil
from pathlib import Path
from tests.symmetry.conftest import PYTHON_ARTIFACTS
from ndi.session.dir import ndi_session_dir

ARTIFACT_DIR = PYTHON_ARTIFACTS / "<namespace>" / "<className>" / "<testName>"

class TestMyFeature:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        # Build session in tmp_path ...
        self.session = ndi_session_dir("exp1", tmp_path / "exp1")

    def test_my_feature_artifacts(self):
        if ARTIFACT_DIR.exists():
            shutil.rmtree(ARTIFACT_DIR)
        shutil.copytree(str(self.session.path), str(ARTIFACT_DIR))
        # Write jsonDocuments/, probes.json, etc.
```

**MATLAB:** `tests/+ndi/+symmetry/+makeArtifacts/+<namespace>/<ClassName>.m`

Follow the INSTRUCTIONS.md in the MATLAB `+makeArtifacts` folder.

### 3. Create the readArtifacts test

**Python:** `tests/symmetry/read_artifacts/<namespace>/test_<name>.py`

```python
import json, pytest
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE
from ndi.session.dir import ndi_session_dir

@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    return request.param

class TestMyFeature:
    def test_my_feature_artifacts(self, source_type):
        artifact_dir = SYMMETRY_BASE / source_type / "<namespace>" / ...
        if not artifact_dir.exists():
            pytest.skip(f"No artifacts from {source_type}")
        session = ndi_session_dir("exp1", artifact_dir)
        # Assertions ...
```

**MATLAB:** `tests/+ndi/+symmetry/+readArtifacts/+<namespace>/<ClassName>.m`

Follow the INSTRUCTIONS.md in the MATLAB `+readArtifacts` folder.

### 4. Naming Conventions

| Concept | Python | MATLAB |
|---------|--------|--------|
| Test directory | `tests/symmetry/make_artifacts/session/` | `tests/+ndi/+symmetry/+makeArtifacts/+session/` |
| Test file | `test_build_session.py` | `buildSession.m` |
| Test class | `TestBuildSession` | `buildSession` (classdef) |
| Artifact className | `buildSession` (camelCase) | `buildSession` |
| Artifact testName | `testBuildSessionArtifacts` (camelCase) | `testBuildSessionArtifacts` |

Use **camelCase** for the artifact directory components (`className`, `testName`)
so that both languages write to and read from the exact same paths.
