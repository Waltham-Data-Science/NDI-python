# NDI-Python

**Neuroscience Data Interface** - Python implementation.

NDI provides a unified framework for managing, querying, and analyzing neuroscience experimental data across different acquisition systems.

## Overview

NDI-Python is a complete port of the [MATLAB NDI](https://github.com/VH-Lab/NDI-matlab) codebase, providing:

- **Document-based metadata** with JSON schema validation
- **SQLite database** backend for persistent storage and rich queries
- **Time synchronization** across heterogeneous recording devices
- **DAQ readers** for Intan, Blackrock, CED Spike2, and SpikeGadgets
- **Application framework** for spike sorting, stimulus analysis, and tuning curves
- **Cloud integration** with NDI Cloud for sharing and collaboration
- **13 ontology providers** for standardized scientific vocabularies

## Quick Start

```python
from ndi import Document, Query, DirSession
from ndi.session import MockSession

# Create and query documents
with MockSession('demo') as session:
    doc = Document('base')
    session.database_add(doc)
    results = session.database_search(Query.all())
    print(f"Found {len(results)} documents")
```

## Installation

```bash
git clone https://github.com/Waltham-Data-Science/NDI-python.git
cd NDI-python
pip install -e ".[dev]"
```

See the [README](https://github.com/Waltham-Data-Science/NDI-python#readme) for full installation instructions including VH-Lab dependency setup.

## MATLAB Migration

If you're migrating from MATLAB NDI, see [MATLAB_MAPPING.md](https://github.com/Waltham-Data-Science/NDI-python/blob/main/MATLAB_MAPPING.md) for a complete function-by-function reference.
