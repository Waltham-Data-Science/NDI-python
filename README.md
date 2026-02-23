# NDI-Python

[![CI](https://github.com/Waltham-Data-Science/NDI-python/actions/workflows/ci.yml/badge.svg)](https://github.com/Waltham-Data-Science/NDI-python/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

Python implementation of the **Neuroscience Data Interface** ([NDI](https://neurodatainterface.org)) — a framework for managing, querying, and analyzing neuroscience experimental data.

NDI provides a unified interface for working with multi-modal neuroscience data (electrophysiology, imaging, stimulation) across different acquisition systems, with built-in support for time synchronization, document-based metadata, and cloud storage.

## Features

- **Document management** — JSON-schema-backed documents for experiments, subjects, probes, epochs, and more
- **Database** — SQLite-backed storage with rich querying (regex, numeric, dependency graphs)
- **Time synchronization** — Clock types, time mappings, and sync graphs for aligning data across devices
- **DAQ readers** — Built-in readers for Intan, Blackrock, CED Spike2, and SpikeGadgets formats
- **Element/Probe hierarchy** — Represent electrodes, optical fibers, and other recording devices
- **Session management** — Directory-backed sessions with epoch discovery and file navigation
- **App framework** — Extensible application framework with spike extraction, sorting, and stimulus analysis
- **Calculator framework** — Reusable computation pipelines (tuning curves, orientation selectivity)
- **Cloud API** — REST client for NDI Cloud with sync, upload/download, and DOI administration
- **Ontology providers** — 13 providers (OLS, NCBITaxon, PubChem, RRID, UniProt, and more)
- **Schema validation** — JSON Schema validation with superclass chain walking
- **OpenMINDS integration** — Convert openMINDS metadata objects to NDI documents

## Installation

```bash
git clone https://github.com/Waltham-Data-Science/NDI-python.git
cd NDI-python
python -m venv venv
source venv/bin/activate  # Linux/macOS (venv\Scripts\activate on Windows)
python ndi_install.py
```

The installer clones all dependencies, installs packages, and validates your setup. Run `python -m ndi check` at any time to verify your installation.

### Updating

```bash
python ndi_install.py --update
```

### Tutorials

```bash
python tutorials/tutorial_67f723d574f5f79c6062389d.py   # Dabrowska dataset
python tutorials/tutorial_682e7772cdf3f24938176fac.py   # Jess Haley dataset
```

See [tutorials/README.md](tutorials/README.md) for full setup and cloud credentials.

### Dependencies

NDI-Python requires these VH-Lab packages (installed automatically by `ndi_install.py`):

| Package | Repository | Purpose |
|---------|-----------|---------|
| [DID-python](https://github.com/VH-Lab/DID-python) | VH-Lab/DID-python | Document database backend (SQLite, queries) |
| [vhlab-toolbox-python](https://github.com/VH-Lab/vhlab-toolbox-python) | VH-Lab/vhlab-toolbox-python | Data utilities, file formats, signal processing |

Additional dependencies (installed automatically): `numpy`, `networkx`, `jsonschema`, `requests`, `scipy`, `pandas`, `matplotlib`.

<details>
<summary>Manual installation (advanced)</summary>

```bash
git clone https://github.com/Waltham-Data-Science/NDI-python.git
cd NDI-python
python -m venv venv
source venv/bin/activate

# Clone VH-Lab dependencies (not yet on PyPI)
git clone https://github.com/VH-Lab/DID-python.git ~/.ndi/tools/DID-python
git clone https://github.com/VH-Lab/vhlab-toolbox-python.git ~/.ndi/tools/vhlab-toolbox-python
export PYTHONPATH="$HOME/.ndi/tools/DID-python/src:$HOME/.ndi/tools/vhlab-toolbox-python:$PYTHONPATH"

# Install NDI-python (--no-deps works around DID packaging bug)
pip install -e ".[dev,tutorials]" --no-deps
pip install numpy networkx jsonschema requests pytest pytest-cov scipy pandas matplotlib opencv-python-headless portalocker openminds
```

</details>

## Quick Start

```python
from ndi import Document, Query, DirSession
from ndi.session import MockSession

# Create a document with schema validation
doc = Document('base')
print(f"Document ID: {doc.id}")

# Query documents using Pythonic operators
q = Query('base.name') == 'my_experiment'
q_type = Query('').isa('subject')
q_combined = q & q_type

# Use MockSession for quick experimentation
with MockSession('test') as session:
    session.database_add(Document('base'))
    results = session.database_search(Query.all())
    print(f"Found {len(results)} documents")

# Use DirSession for persistent, directory-backed sessions
session = DirSession('my_experiment', '/path/to/data')
session.database_add(doc)
results = session.database_search(Query('').isa('base'))
```

## Package Structure

```
src/ndi/
├── Core
│   ├── document.py            Document class with JSON schema loading
│   ├── query.py               Query builder with operator overloading (==, &, |)
│   ├── database.py            SQLite database backend
│   ├── ido.py                 Unique identifier generation (UUID-based)
│   ├── validate.py            JSON Schema validation with superclass chains
│   └── common/                PathConstants, timestamp, logging
│
├── Data Acquisition
│   ├── daq/                   DAQ system abstraction and readers
│   │   ├── reader/mfdaq/      Intan, Blackrock, CED Spike2, SpikeGadgets
│   │   └── metadatareader/    NewStim, NielsenLab metadata readers
│   ├── epoch/                 Epoch, EpochSet, EpochProbeMap
│   └── file/                  FileNavigator, EpochDirNavigator
│
├── Neural Elements
│   ├── element/               Element base class and utilities
│   ├── probe/                 Probe, ProbeTimeseries, ProbeTimeseriesMFDAQ
│   ├── element_timeseries.py  ElementTimeseries (data access)
│   ├── neuron.py              Neuron class
│   └── subject.py             Subject class
│
├── Sessions & Datasets
│   ├── session/               Session, DirSession, MockSession, SessionTable
│   ├── dataset.py             Multi-session Dataset container
│   └── cache.py               FIFO/LIFO cache implementations
│
├── Applications
│   ├── app/                   App framework, SpikeExtractor, SpikeSorter
│   │   └── stimulus/          StimulusDecoder, TuningResponse
│   ├── calc/                  Calculator framework
│   │   ├── example/           SimpleCalc
│   │   └── stimulus/          TuningCurveCalc, TuningFit
│   └── calculator.py          Calculator base class with run loop
│
├── Cloud & Sync
│   ├── cloud/                 CloudClient, CloudConfig
│   │   ├── api/               REST endpoints (datasets, documents, files, users)
│   │   ├── sync/              Sync engine (push, pull, index management)
│   │   └── admin/             DOI generation, Crossref submission
│   └── ontology/              13 ontology providers with LRU cache
│
├── Utilities
│   ├── fun/                   Utility functions (doc, epoch, file, data, stimulus)
│   ├── mock/                  Mock data generators for testing
│   ├── database_fun.py        Database search/export utilities
│   ├── database_ingestion.py  File ingestion/expulsion system
│   ├── openminds_convert.py   OpenMINDS object conversion
│   └── documentservice.py     DocumentService mixin
│
└── Shared Data (ndi_common/)
    ├── database_documents/    84 JSON document schemas
    ├── schema_documents/      JSON Schema validation files
    ├── probe/                 Probe type → class mapping
    └── ...                    Configs, ontology, vocabulary data
```

## MATLAB Migration

This package is a complete Python port of the [MATLAB NDI](https://github.com/VH-Lab/NDI-matlab) codebase. See [MATLAB_MAPPING.md](MATLAB_MAPPING.md) for the full function-by-function mapping.

### Key API Differences

| Concept | MATLAB | Python |
|---------|--------|--------|
| Query creation | `ndi.query('field', 'exact_string', 'val')` | `Query('field') == 'val'` |
| Type query | `ndi.query('', 'isa', 'subject')` | `Query('').isa('subject')` |
| Combine queries | `ndi.query(q1, '&', q2)` | `q1 & q2` |
| Method names | `camelCase` (e.g., `setSessionId`) | `snake_case` (e.g., `set_session_id`) |
| Properties | `doc.id()` (method call) | `doc.id` (property access) |
| Session ID | `session.id()` | `session.id()` (still a method) |

## Architecture

```
                    DocumentService (mixin)
                    ├── Subject
                    └── Element ← Ido + EpochSet + DocumentService
                        ├── Probe (measurement devices)
                        │   └── ProbeTimeseries
                        │       ├── ProbeTimeseriesMFDAQ
                        │       └── ProbeTimeseriesStimulator
                        ├── ElementTimeseries (data access)
                        └── Neuron

App (DocumentService)
├── MarkGarbage
├── SpikeExtractor
├── SpikeSorter
├── StimulusDecoder
├── TuningResponse
└── Calculator (App + AppDoc)
    ├── SimpleCalc
    ├── TuningCurveCalc
    └── TuningFit (abstract)

Session (abstract)
├── DirSession (directory-backed)
└── MockSession (in-memory, for testing)

Dataset (multi-session container)
```

## Development

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_document.py -v

# Run with coverage
pytest tests/ --cov=src/ndi --cov-report=term-missing
```

### Code Quality

CI enforces formatting and lint on every push/PR:

```bash
# Format code (must pass `black --check` in CI)
black src/ tests/

# Lint (must pass `ruff check` in CI)
ruff check src/ tests/

# Auto-fix lint issues
ruff check --fix src/ tests/

# Type check (optional, not yet enforced in CI)
mypy src/ndi/
```

### Building Documentation

```bash
pip install -e ".[docs]"
mkdocs build
mkdocs serve  # Local preview at http://127.0.0.1:8000
```

## Test Coverage

- **1,704 tests passing** across 30+ test files (Python 3.10, 3.11, 3.12)
- Covers all modules: core, DAQ, time, session, app, cloud, ontology, validation
- ~71% line coverage across `src/ndi/`

## License

This project is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

Contact [Brandeis University Office of Technology Licensing](https://www.brandeis.edu/innovation/what-we-do/office-of-technology-licensing.html) for commercial licensing.

## Acknowledgments

- **[VH-Lab](https://vhlab.neuroscience.brandeis.edu/)** at Brandeis University — original MATLAB NDI codebase
- **Audri Bhowmick / [Waltham Data Science](https://github.com/Waltham-Data-Science)** — Python port
- **NDI Cloud** — [ndi-cloud.com](https://www.ndi-cloud.com) for cloud storage and sharing
